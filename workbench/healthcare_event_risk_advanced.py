"""Advanced weekly-path analytics for the Healthcare Event Risk Workbench.

This module adds exact contract-window backtesting, correlated weekly path
simulation, 13-week rolling economics inputs, evergreen aggregate payout
analytics, product comparison helpers, and scenario export utilities.

The simulation is a transparent research model, not a certified actuarial fair
value model. It preserves week-to-week persistence by fitting an AR(1) process
to log-scale residuals around the observed within-window seasonal profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from math import exp, log
import random
import statistics
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class CorrelatedPathSummary:
    n_paths: int
    n_weeks: int
    fitted_phi: float
    simulated_phi: float
    innovation_sigma: float
    season_effect_sigma: float
    seasonal_touch_probability: float
    rolling_13w_touch_probability: float
    weekly_exceedance_probability: float
    evergreen_any_trigger_probability: float
    expected_trigger_weeks: float
    expected_longest_run: float
    expected_cumulative_payout: float
    p95_cumulative_payout: float
    max_cumulative_payout: float


def _parse_mmdd(value: str) -> tuple[int, int]:
    try:
        month, day = (int(x) for x in value.split("-", 1))
        date(2000, month, day)
    except Exception as exc:
        raise ValueError("Contract-window anchors must use MM-DD format") from exc
    return month, day


def _season_year_for_date(d: pd.Timestamp, start_month: int) -> int:
    return int(d.year if d.month >= start_month else d.year - 1)


def contract_window_history(
    geography: str,
    weekly_df: pd.DataFrame,
    start_mmdd: str = "10-09",
    end_mmdd: str = "05-20",
) -> pd.DataFrame:
    """Map exact month/day contract anchors onto every observed respiratory season.

    Example: 10-09 through 05-20 creates 2022-10-09 through 2023-05-20,
    2023-10-09 through 2024-05-20, etc. Observations are the weekly dates
    published in the source; no interpolation is used for contract backtesting.
    """
    sm, sd = _parse_mmdd(start_mmdd)
    em, ed = _parse_mmdd(end_mmdd)
    if sm < 7:
        raise ValueError("Start anchor should fall in the second half of the calendar year")
    if em > 6:
        raise ValueError("End anchor should fall in the first half of the following year")

    df = weekly_df[weekly_df["geography"] == geography].copy()
    if df.empty:
        raise ValueError(f"No weekly history available for {geography}")
    df["date"] = pd.to_datetime(df["date"])
    df["season_start_year"] = df["date"].map(lambda d: _season_year_for_date(d, sm))

    def inside(row: pd.Series) -> bool:
        y = int(row["season_start_year"])
        start = pd.Timestamp(date(y, sm, sd))
        end = pd.Timestamp(date(y + 1, em, ed))
        return start <= row["date"] <= end

    out = df[df.apply(inside, axis=1)].sort_values("date").copy()
    out["season"] = out["season_start_year"].map(lambda y: f"{int(y)}-{str(int(y)+1)[-2:]}")
    out["week_of_window"] = out.groupby("season").cumcount() + 1
    return out.reset_index(drop=True)


def rolling_window_series(
    geography: str,
    weekly_df: pd.DataFrame,
    start_mmdd: str,
    end_mmdd: str,
    window: int = 13,
) -> pd.DataFrame:
    if window < 2:
        raise ValueError("window must be at least 2")
    df = contract_window_history(geography, weekly_df, start_mmdd, end_mmdd)
    col = f"rolling_{window}w_pct"
    df[col] = df.groupby("season")["ed_visits_pct"].transform(
        lambda s: s.rolling(window=window, min_periods=window).mean()
    )
    return df


def rolling_window_season_summary(
    geography: str,
    weekly_df: pd.DataFrame,
    start_mmdd: str,
    end_mmdd: str,
    window: int = 13,
) -> pd.DataFrame:
    df = rolling_window_series(geography, weekly_df, start_mmdd, end_mmdd, window)
    col = f"rolling_{window}w_pct"
    valid = df.dropna(subset=[col])
    if valid.empty:
        return pd.DataFrame(columns=["season", "max_rolling_pct", "peak_window_end"])
    idx = valid.groupby("season")[col].idxmax()
    out = valid.loc[idx, ["season", "date", col]].copy()
    out.columns = ["season", "peak_window_end", "max_rolling_pct"]
    return out.sort_values("season").reset_index(drop=True)


def _historical_probability(values: list[float], strike: float) -> tuple[float, int, int]:
    if not values:
        return 0.0, 0, 0
    hits = sum(float(x) >= strike for x in values)
    return hits / len(values), hits, len(values)


def historical_window_metrics(
    geography: str,
    weekly_df: pd.DataFrame,
    touch_strike_pct: float,
    rolling_strike_pct: float,
    start_mmdd: str,
    end_mmdd: str,
) -> dict[str, float | int]:
    df = contract_window_history(geography, weekly_df, start_mmdd, end_mmdd)
    peak_values = df.groupby("season")["ed_visits_pct"].max().tolist()
    touch_p, touch_hits, seasons = _historical_probability(peak_values, touch_strike_pct)

    roll = rolling_window_season_summary(geography, weekly_df, start_mmdd, end_mmdd, 13)
    roll_p, roll_hits, roll_seasons = _historical_probability(
        roll["max_rolling_pct"].tolist(), rolling_strike_pct
    )

    hit = df["ed_visits_pct"] >= touch_strike_pct
    return {
        "seasonal_touch_probability": touch_p,
        "seasonal_touch_hits": touch_hits,
        "seasons": seasons,
        "rolling_13w_probability": roll_p,
        "rolling_13w_hits": roll_hits,
        "rolling_13w_seasons": roll_seasons,
        "weekly_exceedance_probability": float(hit.mean()) if len(hit) else 0.0,
        "weekly_hit_weeks": int(hit.sum()),
        "weekly_observed_weeks": int(len(hit)),
    }


def _longest_run(flags: list[bool]) -> int:
    best = 0
    run = 0
    for flag in flags:
        if flag:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def _fit_weekly_profile(window_df: pd.DataFrame) -> dict[str, Any]:
    """Fit an ordinal-week mean curve plus AR(1) residual persistence on log scale."""
    floor = 0.03
    work = window_df.copy()
    work["log_y"] = work["ed_visits_pct"].map(lambda x: log(max(float(x), 0.0) + floor))
    profile = work.groupby("week_of_window")["log_y"].mean().sort_index()
    if len(profile) < 2:
        raise ValueError("Not enough weekly history to fit a path model")

    work["profile"] = work["week_of_window"].map(profile)
    work["resid"] = work["log_y"] - work["profile"]

    x: list[float] = []
    y: list[float] = []
    for _, season in work.groupby("season"):
        r = season.sort_values("week_of_window")["resid"].tolist()
        for a, b in zip(r[:-1], r[1:]):
            x.append(float(a))
            y.append(float(b))

    if x and sum(v * v for v in x) > 1e-12:
        phi = sum(a * b for a, b in zip(x, y)) / sum(a * a for a in x)
    else:
        phi = 0.0
    phi = max(0.0, min(0.95, float(phi)))

    innovations = [b - phi * a for a, b in zip(x, y)]
    innovation_sigma = statistics.stdev(innovations) if len(innovations) > 1 else 0.20
    innovation_sigma = max(float(innovation_sigma), 0.02)

    season_means = work.groupby("season")["resid"].mean().tolist()
    season_sigma = statistics.stdev(season_means) if len(season_means) > 1 else 0.0

    max_week = int(work["week_of_window"].max())
    full_profile: list[float] = []
    for week in range(1, max_week + 1):
        if week in profile.index:
            full_profile.append(float(profile.loc[week]))
        else:
            prior = profile[profile.index < week]
            later = profile[profile.index > week]
            if len(prior) and len(later):
                full_profile.append((float(prior.iloc[-1]) + float(later.iloc[0])) / 2)
            elif len(prior):
                full_profile.append(float(prior.iloc[-1]))
            else:
                full_profile.append(float(later.iloc[0]))

    return {
        "floor": floor,
        "profile": full_profile,
        "phi": phi,
        "innovation_sigma": innovation_sigma,
        "season_sigma": max(float(season_sigma), 0.0),
    }


def simulate_correlated_weekly_paths(
    geography: str,
    weekly_df: pd.DataFrame,
    touch_strike_pct: float,
    rolling_strike_pct: float,
    notional: float,
    evergreen_cap_weeks: int,
    start_mmdd: str,
    end_mmdd: str,
    n_paths: int = 5000,
    severity_shift_pct: float = 0.0,
    dispersion_multiplier: float = 1.0,
    persistence_multiplier: float = 1.0,
    seed: int = 20260910,
) -> tuple[CorrelatedPathSummary, pd.DataFrame]:
    """Simulate complete weekly influenza paths with observed serial persistence.

    Residuals are AR(1) around the observed ordinal-week log-profile. A season-level
    random effect preserves between-season severity variation. The severity stress
    is an additive percentage-point shift applied after back-transforming.
    """
    if n_paths < 250:
        raise ValueError("n_paths must be at least 250")
    if evergreen_cap_weeks < 1:
        raise ValueError("evergreen_cap_weeks must be at least 1")
    if dispersion_multiplier <= 0 or persistence_multiplier <= 0:
        raise ValueError("dispersion and persistence multipliers must be positive")

    hist = contract_window_history(geography, weekly_df, start_mmdd, end_mmdd)
    fit = _fit_weekly_profile(hist)
    fitted_phi = fit["phi"]
    phi = max(0.0, min(0.98, fitted_phi * persistence_multiplier))
    innov_sigma = fit["innovation_sigma"] * dispersion_multiplier
    season_sigma = fit["season_sigma"] * dispersion_multiplier
    profile = fit["profile"]
    floor = fit["floor"]
    rng = random.Random(seed)

    any_touch = 0
    rolling_touch = 0
    total_hits = 0
    paths_with_hit = 0
    hit_counts: list[int] = []
    longest_runs: list[int] = []
    payouts: list[float] = []
    sample_rows: list[dict[str, float | int]] = []

    for path_id in range(n_paths):
        season_effect = rng.gauss(0.0, season_sigma)
        resid = rng.gauss(0.0, innov_sigma / max((1.0 - phi * phi) ** 0.5, 0.25))
        vals: list[float] = []
        for week_idx, mean_log in enumerate(profile, start=1):
            if week_idx > 1:
                resid = phi * resid + rng.gauss(0.0, innov_sigma)
            value = max(exp(mean_log + season_effect + resid) - floor + severity_shift_pct, 0.0)
            vals.append(value)
            if path_id < 40:
                sample_rows.append({"path": path_id + 1, "week": week_idx, "ed_visits_pct": value})

        flags = [v >= touch_strike_pct for v in vals]
        hits = sum(flags)
        total_hits += hits
        hit_counts.append(hits)
        longest_runs.append(_longest_run(flags))
        if hits:
            any_touch += 1
            paths_with_hit += 1

        if len(vals) >= 13:
            rolling = [statistics.mean(vals[i - 12:i + 1]) for i in range(12, len(vals))]
            if max(rolling) >= rolling_strike_pct:
                rolling_touch += 1

        paid_weeks = min(hits, evergreen_cap_weeks)
        payouts.append(float(notional) * paid_weeks)

    payouts_sorted = sorted(payouts)
    p95_idx = min(int(round(0.95 * (len(payouts_sorted) - 1))), len(payouts_sorted) - 1)
    n_weeks = len(profile)
    summary = CorrelatedPathSummary(
        n_paths=n_paths,
        n_weeks=n_weeks,
        fitted_phi=fitted_phi,
        simulated_phi=phi,
        innovation_sigma=innov_sigma,
        season_effect_sigma=season_sigma,
        seasonal_touch_probability=any_touch / n_paths,
        rolling_13w_touch_probability=rolling_touch / n_paths,
        weekly_exceedance_probability=total_hits / (n_paths * n_weeks),
        evergreen_any_trigger_probability=paths_with_hit / n_paths,
        expected_trigger_weeks=statistics.mean(hit_counts),
        expected_longest_run=statistics.mean(longest_runs),
        expected_cumulative_payout=statistics.mean(payouts),
        p95_cumulative_payout=payouts_sorted[p95_idx],
        max_cumulative_payout=float(notional) * evergreen_cap_weeks,
    )
    return summary, pd.DataFrame(sample_rows)


def product_comparison_table(
    notional: float,
    seasonal_price: float,
    rolling_price: float,
    evergreen_weekly_price: float,
    historical: dict[str, float | int],
    path_summary: CorrelatedPathSummary,
    evergreen_cap_weeks: int,
) -> pd.DataFrame:
    """Create an institutional comparison across the three structures."""
    weeks = path_summary.n_weeks
    rows = [
        {
            "Structure": "Seasonal Touch",
            "Historical trigger probability": float(historical["seasonal_touch_probability"]),
            "Simulated trigger probability": path_summary.seasonal_touch_probability,
            "Indicative premium": notional * seasonal_price,
            "LP capital at risk": notional * (1.0 - seasonal_price),
            "Expected payout frequency": path_summary.seasonal_touch_probability,
            "Maximum payout": notional,
        },
        {
            "Structure": "13-Week Average",
            "Historical trigger probability": float(historical["rolling_13w_probability"]),
            "Simulated trigger probability": path_summary.rolling_13w_touch_probability,
            "Indicative premium": notional * rolling_price,
            "LP capital at risk": notional * (1.0 - rolling_price),
            "Expected payout frequency": path_summary.rolling_13w_touch_probability,
            "Maximum payout": notional,
        },
        {
            "Structure": "Weekly Evergreen",
            "Historical trigger probability": float(historical["weekly_exceedance_probability"]),
            "Simulated trigger probability": path_summary.weekly_exceedance_probability,
            "Indicative premium": notional * evergreen_weekly_price * weeks,
            "LP capital at risk": notional * (1.0 - evergreen_weekly_price),
            "Expected payout frequency": path_summary.expected_trigger_weeks,
            "Maximum payout": notional * evergreen_cap_weeks,
        },
    ]
    return pd.DataFrame(rows)


def build_scenario_payload(values: dict[str, Any]) -> dict[str, Any]:
    """Create a stable, timestamped scenario record suitable for export/review."""
    clean: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, (pd.Timestamp, datetime, date)):
            clean[key] = value.isoformat()
        elif isinstance(value, (float, int, str, bool)) or value is None:
            clean[key] = value
        else:
            clean[key] = str(value)
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":"))
    scenario_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10].upper()
    return {
        "scenario_id": scenario_id,
        "saved_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        **clean,
    }


def scenario_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)
