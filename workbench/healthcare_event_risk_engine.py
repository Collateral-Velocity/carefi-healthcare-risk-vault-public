"""Healthcare Event Risk underwriting helpers.

The workbench supports three related influenza ED-utilization structures:
1) seasonal single-week touch,
2) 13-week rolling-average touch, and
3) weekly evergreen contracts.

The model is intentionally transparent and scenario-oriented; it does not claim
to produce an executable market price or certified actuarial fair value.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, log
from pathlib import Path
import random
import statistics
from typing import Iterable

import pandas as pd

DATA_ROOT = Path(__file__).resolve().parent / "data" / "healthcare_event_risk"
WEEKLY_SOURCE_URL = (
    "https://raw.githubusercontent.com/cdcepi/FluSight-forecast-hub/"
    "main/target-data/target-ed-visits-prop.csv"
)
SUPPORTED_GEOGRAPHIES = ("Texas", "North Carolina")


@dataclass(frozen=True)
class ProbabilityView:
    historical: float
    credibility_adjusted: float
    simulated: float
    n_seasons: int
    historical_hits: int


@dataclass(frozen=True)
class TradeEconomics:
    notional: float
    yes_price: float
    model_probability: float
    client_premium: float
    client_gross_payout_if_trigger: float
    client_net_protection_if_trigger: float
    client_expected_cash_value: float
    lp_collateral: float
    lp_profit_if_no_trigger: float
    lp_loss_if_trigger: float
    lp_expected_pnl: float
    lp_expected_return_on_collateral: float


def load_history() -> pd.DataFrame:
    df = pd.read_csv(DATA_ROOT / "seasonal_peaks.csv")
    df["peak_week"] = pd.to_datetime(df["peak_week"])
    return df


def load_strike_ladder() -> pd.DataFrame:
    return pd.read_csv(DATA_ROOT / "strike_ladder.csv")


def history_for_geography(geography: str) -> pd.DataFrame:
    df = load_history()
    return df[df["geography"] == geography].copy().reset_index(drop=True)


def load_weekly_history(source_url: str = WEEKLY_SOURCE_URL) -> pd.DataFrame:
    """Load observed state-level influenza ED-visit proportions from CDC FluSight.

    The source publishes decimal proportions. This function converts them to
    percentage points so 0.10 becomes 10.0%. Only supported workbench states are
    retained. The live source is intentionally used for research analytics; a
    settlement oracle should continue to pin a specific publication/commit.
    """
    df = pd.read_csv(source_url)
    required = {"date", "location_name", "value"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Weekly source missing required columns: {sorted(missing)}")

    out = df[df["location_name"].isin(SUPPORTED_GEOGRAPHIES)].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out = out.dropna(subset=["date", "value"])
    out = out.rename(columns={"location_name": "geography", "value": "proportion"})
    out["ed_visits_pct"] = out["proportion"] * 100.0
    out = out.drop_duplicates(subset=["date", "geography"], keep="first")
    return out[["date", "geography", "proportion", "ed_visits_pct"]].sort_values(
        ["geography", "date"]
    ).reset_index(drop=True)


def respiratory_season(date: pd.Timestamp, start_month: int = 10, end_month: int = 5) -> str | None:
    """Return season label for dates inside the Oct-May analysis window by default."""
    d = pd.Timestamp(date)
    if start_month <= d.month <= 12:
        return f"{d.year}-{str(d.year + 1)[-2:]}"
    if 1 <= d.month <= end_month:
        return f"{d.year - 1}-{str(d.year)[-2:]}"
    return None


def seasonal_weekly_history(
    geography: str,
    weekly_df: pd.DataFrame | None = None,
    start_month: int = 10,
    end_month: int = 5,
) -> pd.DataFrame:
    """Return weekly observations inside each respiratory-season analysis window."""
    if weekly_df is None:
        weekly_df = load_weekly_history()
    df = weekly_df[weekly_df["geography"] == geography].copy()
    if df.empty:
        raise ValueError(f"No weekly history available for {geography}")
    df["season"] = df["date"].map(lambda d: respiratory_season(d, start_month, end_month))
    df = df[df["season"].notna()].sort_values("date").reset_index(drop=True)
    df["week_of_season"] = df.groupby("season").cumcount() + 1
    return df


def rolling_average_series(
    geography: str,
    window: int = 13,
    weekly_df: pd.DataFrame | None = None,
    start_month: int = 10,
    end_month: int = 5,
) -> pd.DataFrame:
    """Compute within-season rolling averages; windows never cross season boundaries."""
    if window < 2:
        raise ValueError("window must be at least 2 weeks")
    df = seasonal_weekly_history(geography, weekly_df, start_month, end_month)
    df[f"rolling_{window}w_pct"] = (
        df.groupby("season")["ed_visits_pct"]
        .transform(lambda s: s.rolling(window=window, min_periods=window).mean())
    )
    return df


def rolling_season_summary(
    geography: str,
    window: int = 13,
    weekly_df: pd.DataFrame | None = None,
    start_month: int = 10,
    end_month: int = 5,
) -> pd.DataFrame:
    """Return each season's maximum completed rolling average and its end week."""
    df = rolling_average_series(geography, window, weekly_df, start_month, end_month)
    col = f"rolling_{window}w_pct"
    valid = df.dropna(subset=[col]).copy()
    if valid.empty:
        return pd.DataFrame(columns=["season", "max_rolling_pct", "peak_window_end"])
    idx = valid.groupby("season")[col].idxmax()
    out = valid.loc[idx, ["season", "date", col]].copy()
    out = out.rename(columns={"date": "peak_window_end", col: "max_rolling_pct"})
    return out.sort_values("season").reset_index(drop=True)


def rolling_touch_probability(
    geography: str,
    strike_pct: float,
    window: int = 13,
    weekly_df: pd.DataFrame | None = None,
) -> tuple[float, int, int]:
    summary = rolling_season_summary(geography, window, weekly_df)
    vals = summary["max_rolling_pct"].tolist()
    return historical_touch_probability(vals, strike_pct)


def weekly_evergreen_summary(
    geography: str,
    strike_pct: float,
    weekly_df: pd.DataFrame | None = None,
) -> dict[str, float | int]:
    """Describe one-week exceedances for a recurring/evergreen weekly contract.

    The hit rate is a descriptive frequency across observed seasonal weeks. Weekly
    observations are serially correlated, so this is not an independent-trial
    probability and should not be annualized as such.
    """
    df = seasonal_weekly_history(geography, weekly_df)
    hit = df["ed_visits_pct"] >= strike_pct
    n = int(len(df))
    hits = int(hit.sum())
    seasons = int(df["season"].nunique())

    longest_run = 0
    current_run = 0
    for value in hit.tolist():
        if bool(value):
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0

    seasons_with_hit = int(df.assign(hit=hit).groupby("season")["hit"].any().sum())
    return {
        "weekly_hit_rate": hits / n if n else 0.0,
        "hit_weeks": hits,
        "observed_weeks": n,
        "seasons": seasons,
        "seasons_with_hit": seasons_with_hit,
        "longest_hit_run": longest_run,
    }


def weekly_exceedance_by_season_week(
    geography: str,
    strike_pct: float,
    weekly_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Observed hit rate by ordinal week of the Oct-May season."""
    df = seasonal_weekly_history(geography, weekly_df)
    df["hit"] = df["ed_visits_pct"] >= strike_pct
    out = df.groupby("week_of_season").agg(
        observations=("hit", "size"),
        hits=("hit", "sum"),
        mean_ed_visits_pct=("ed_visits_pct", "mean"),
    ).reset_index()
    out["hit_rate"] = out["hits"] / out["observations"]
    return out


def historical_touch_probability(peaks_pct: Iterable[float], strike_pct: float) -> tuple[float, int, int]:
    peaks = [float(x) for x in peaks_pct]
    if not peaks:
        raise ValueError("At least one historical season is required")
    hits = sum(x >= strike_pct for x in peaks)
    return hits / len(peaks), hits, len(peaks)


def beta_binomial_mean(hits: int, n: int, prior_mean: float = 0.25, prior_strength: float = 2.0) -> float:
    """Posterior mean using a transparent Beta prior expressed as mean + equivalent seasons."""
    if not 0 < prior_mean < 1:
        raise ValueError("prior_mean must be between 0 and 1")
    if prior_strength <= 0:
        raise ValueError("prior_strength must be positive")
    alpha = prior_mean * prior_strength
    beta = (1.0 - prior_mean) * prior_strength
    return (hits + alpha) / (n + alpha + beta)


def fit_log_peak_distribution(peaks_pct: Iterable[float]) -> tuple[float, float]:
    peaks = [float(x) for x in peaks_pct if float(x) > 0]
    if len(peaks) < 2:
        raise ValueError("At least two positive observations are required")
    logs = [log(x) for x in peaks]
    return statistics.mean(logs), statistics.stdev(logs)


def simulate_peak_distribution(
    peaks_pct: Iterable[float],
    n_simulations: int = 20000,
    severity_shift_pct: float = 0.0,
    dispersion_multiplier: float = 1.0,
    seed: int = 20260910,
) -> list[float]:
    """Simulate seasonal peaks with a fitted lognormal distribution."""
    if n_simulations < 100:
        raise ValueError("n_simulations must be at least 100")
    if dispersion_multiplier <= 0:
        raise ValueError("dispersion_multiplier must be positive")
    peaks = [float(x) for x in peaks_pct]
    mu, sigma = fit_log_peak_distribution(peaks)
    base_median = exp(mu)
    shifted_median = max(base_median + severity_shift_pct, 0.01)
    shifted_mu = log(shifted_median)
    shifted_sigma = sigma * dispersion_multiplier
    rng = random.Random(seed)
    return [rng.lognormvariate(shifted_mu, shifted_sigma) for _ in range(n_simulations)]


def simulated_touch_probability(simulated_peaks_pct: Iterable[float], strike_pct: float) -> float:
    vals = [float(x) for x in simulated_peaks_pct]
    if not vals:
        raise ValueError("simulated_peaks_pct cannot be empty")
    return sum(x >= strike_pct for x in vals) / len(vals)


def probability_views(
    geography: str,
    strike_pct: float,
    prior_mean: float = 0.25,
    prior_strength: float = 2.0,
    n_simulations: int = 20000,
    severity_shift_pct: float = 0.0,
    dispersion_multiplier: float = 1.0,
    seed: int = 20260910,
) -> tuple[ProbabilityView, list[float]]:
    hist = history_for_geography(geography)
    peaks = hist["peak_pct"].tolist()
    raw, hits, n = historical_touch_probability(peaks, strike_pct)
    cred = beta_binomial_mean(hits, n, prior_mean, prior_strength)
    sims = simulate_peak_distribution(
        peaks,
        n_simulations=n_simulations,
        severity_shift_pct=severity_shift_pct,
        dispersion_multiplier=dispersion_multiplier,
        seed=seed,
    )
    sim_p = simulated_touch_probability(sims, strike_pct)
    return ProbabilityView(raw, cred, sim_p, n, hits), sims


def trade_economics(notional: float, yes_price: float, model_probability: float) -> TradeEconomics:
    """Economics for a client long YES and liquidity provider short YES / long NO."""
    if notional <= 0:
        raise ValueError("notional must be positive")
    if not 0 < yes_price < 1:
        raise ValueError("yes_price must be between 0 and 1")
    if not 0 <= model_probability <= 1:
        raise ValueError("model_probability must be between 0 and 1")

    client_premium = notional * yes_price
    net_if_trigger = notional - client_premium
    expected_client_cash = model_probability * notional - client_premium
    lp_collateral = notional * (1.0 - yes_price)
    lp_profit_no_trigger = notional * yes_price
    lp_loss_trigger = lp_collateral
    lp_expected_pnl = (yes_price - model_probability) * notional
    lp_roc = lp_expected_pnl / lp_collateral if lp_collateral else 0.0

    return TradeEconomics(
        notional=notional,
        yes_price=yes_price,
        model_probability=model_probability,
        client_premium=client_premium,
        client_gross_payout_if_trigger=notional,
        client_net_protection_if_trigger=net_if_trigger,
        client_expected_cash_value=expected_client_cash,
        lp_collateral=lp_collateral,
        lp_profit_if_no_trigger=lp_profit_no_trigger,
        lp_loss_if_trigger=lp_loss_trigger,
        lp_expected_pnl=lp_expected_pnl,
        lp_expected_return_on_collateral=lp_roc,
    )


def percentile(values: Iterable[float], q: float) -> float:
    vals = sorted(float(x) for x in values)
    if not vals:
        raise ValueError("values cannot be empty")
    if q <= 0:
        return vals[0]
    if q >= 1:
        return vals[-1]
    pos = (len(vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(vals) - 1)
    frac = pos - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


def simulation_summary(values: Iterable[float]) -> dict[str, float]:
    vals = [float(x) for x in values]
    return {
        "mean": statistics.mean(vals),
        "median": statistics.median(vals),
        "p10": percentile(vals, 0.10),
        "p25": percentile(vals, 0.25),
        "p75": percentile(vals, 0.75),
        "p90": percentile(vals, 0.90),
        "p95": percentile(vals, 0.95),
    }
