"""Standalone Streamlit workbench for Oriel / CareFi healthcare event risk."""
from __future__ import annotations

import base64
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from healthcare_event_risk_engine import (
    beta_binomial_mean,
    history_for_geography,
    load_strike_ladder,
    load_weekly_history,
    probability_views,
    simulation_summary,
    trade_economics,
)
from basis_underwriting_ui import render_basis_underwriting_workbench

from healthcare_event_risk_advanced import (
    build_scenario_payload,
    contract_window_history,
    historical_window_metrics,
    product_comparison_table,
    rolling_window_season_summary,
    rolling_window_series,
    scenario_json,
    simulate_correlated_weekly_paths,
)

PROJECT_ROOT = Path(__file__).resolve().parent
MODEL_VERSION = "HERW 0.3.1"
METHODOLOGY_STATUS = "Research / actuarial review pending"


def _logo_data_uri() -> str:
    p = PROJECT_ROOT / "assets" / "oriel_logo.svg"
    if p.exists():
        return f"data:image/svg+xml;base64,{base64.b64encode(p.read_bytes()).decode()}"
    return ""


@st.cache_data(ttl=3600, show_spinner=False)
def _weekly_history() -> pd.DataFrame:
    return load_weekly_history()


@st.cache_data(show_spinner=False)
def _path_simulation(
    geography: str,
    touch_strike: float,
    rolling_strike: float,
    notional: float,
    evergreen_cap_weeks: int,
    start_mmdd: str,
    end_mmdd: str,
    n_paths: int,
    severity_shift: float,
    dispersion: float,
    persistence: float,
    data_signature: str,
):
    # data_signature invalidates this cache when the CDC as-of date changes.
    del data_signature
    weekly = _weekly_history()
    return simulate_correlated_weekly_paths(
        geography=geography,
        weekly_df=weekly,
        touch_strike_pct=touch_strike,
        rolling_strike_pct=rolling_strike,
        notional=notional,
        evergreen_cap_weeks=evergreen_cap_weeks,
        start_mmdd=start_mmdd,
        end_mmdd=end_mmdd,
        n_paths=n_paths,
        severity_shift_pct=severity_shift,
        dispersion_multiplier=dispersion,
        persistence_multiplier=persistence,
    )


LOGO_DATA_URI = _logo_data_uri()
st.set_page_config(
    page_title="Oriel · Healthcare Event Risk Workbench",
    page_icon="OR",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Instrument+Serif:ital@0;1&family=DM+Sans:wght@300;400;500;600;700&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;color:#1a1a2e;}
.stApp{background:#e8e5df;}.block-container{padding:0 2rem 4rem!important;max-width:100%!important;}#MainMenu,footer,header{visibility:hidden;}
.oriel-nav{background:#12151e;padding:0 2rem;display:flex;align-items:center;justify-content:space-between;height:48px;margin:0 -2rem 18px;border-bottom:1px solid rgba(255,255,255,.05);}.nav-left{display:flex;align-items:center;gap:16px;}.oriel-logo{display:block;height:26px;width:auto;max-width:112px;object-fit:contain;}.nav-wordmark{font-family:'Instrument Serif',serif;font-size:1.25rem;color:#f0ece4}.nav-wordmark em{font-style:italic;color:#d4a853}.nav-pipe{width:1px;height:14px;background:rgba(255,255,255,.08);}.nav-label{font-size:.7rem;color:#8892a4;font-weight:700;letter-spacing:.08em;text-transform:uppercase;}
.page-title{font-size:1.35rem;font-weight:650;color:#151827;margin-bottom:2px}.page-sub{font-size:.78rem;color:#4b5563;margin-bottom:14px}.shdr{font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;color:#374151;font-weight:800;padding-bottom:7px;margin:12px 0;border-bottom:2px solid rgba(0,0,0,.12)}.note{background:#fffbf2;border:1px solid #e8d5a3;border-left:3px solid #d4a853;border-radius:6px;padding:11px 13px;font-size:.72rem;line-height:1.55;color:#1f2937}.dark{background:#151827;color:#d7dde8;border-radius:8px;padding:12px 14px;font-size:.72rem;line-height:1.55}.dark b{color:#f0c060}.note-box{background:#f7f4ed;border:1px solid rgba(0,0,0,.12);border-left:3px solid #d4a853;border-radius:6px;padding:11px 13px;font-size:.75rem;line-height:1.55;color:#1f2937;margin:.35rem 0 .75rem}[data-testid="stMetricValue"]{font-family:'DM Mono',monospace;font-size:1.25rem!important}
</style>
""",
    unsafe_allow_html=True,
)
logo_html = f"<img src='{LOGO_DATA_URI}' class='oriel-logo' alt='Oriel'>" if LOGO_DATA_URI else "<span class='nav-wordmark'>Or<em>i</em>el</span>"
st.markdown(
    f"""<div class='oriel-nav'><div class='nav-left'>{logo_html}<div class='nav-pipe'></div><span class='nav-label'>Healthcare Event Risk Workbench</span></div><div style='color:#d4a853;font-size:.65rem;font-weight:700;letter-spacing:.08em'>DECISION SUPPORT · {MODEL_VERSION}</div></div>""",
    unsafe_allow_html=True,
)
st.markdown("<div class='page-title'>Underwriting & Scenario Analysis</div>", unsafe_allow_html=True)
st.markdown("<div class='page-sub'>Contract-window backtesting, correlated weekly path simulation and trade economics for healthcare event risk. Research decision support — not executable fair value.</div>", unsafe_allow_html=True)

st.markdown("<div class='shdr'>Oriel Underwriting / Basis Translation</div>", unsafe_allow_html=True)
render_basis_underwriting_workbench()
st.markdown("<div style='height:10px'></div><hr style='border:none;border-top:1px solid rgba(0,0,0,.12);margin:8px 0 18px'>", unsafe_allow_html=True)

try:
    weekly_all = _weekly_history()
    data_asof = pd.Timestamp(weekly_all["date"].max())
    weekly_error = None
except Exception as exc:
    weekly_all = None
    data_asof = None
    weekly_error = str(exc)

ladder = load_strike_ladder()
left, right = st.columns([1.05, 2.55], gap="large")

with left:
    st.markdown("<div class='shdr'>Contract Builder</div>", unsafe_allow_html=True)
    geography = st.selectbox("Geography", ["Texas", "North Carolina"])
    geo_ladder = ladder[(ladder["geography"] == geography) & (ladder["recommended_for_quote"] == "YES")]
    strikes = [float(x) for x in geo_ladder["strike_pct"].tolist()]
    default_touch = 10.5 if geography == "Texas" else 15.0
    default_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - default_touch))
    strike = st.selectbox("Seasonal / weekly touch strike", strikes, index=default_idx, format_func=lambda x: f"{x:.1f}%")
    notional = float(st.number_input("Payout notional per contract", min_value=10000, max_value=5000000, value=100000, step=10000))

    st.markdown("<div class='shdr'>Exact Contract Window</div>", unsafe_allow_html=True)
    start_date = st.date_input("First qualifying week ending", value=date(2027, 10, 9))
    end_date = st.date_input("Last qualifying week ending", value=date(2028, 5, 20))
    if end_date <= start_date:
        st.error("Last qualifying week must be after the first qualifying week.")
        st.stop()
    start_mmdd = start_date.strftime("%m-%d")
    end_mmdd = end_date.strftime("%m-%d")
    st.caption(f"Historical backtest maps {start_mmdd} → {end_mmdd} onto each observed respiratory season.")

    suggested_roll = 5.0
    if weekly_all is not None:
        try:
            tmp_roll = rolling_window_season_summary(geography, weekly_all, start_mmdd, end_mmdd, 13)
            if not tmp_roll.empty:
                suggested_roll = max(0.5, round(float(tmp_roll["max_rolling_pct"].quantile(0.75)) * 2) / 2)
        except Exception:
            pass
    rolling_strike = float(st.number_input("13-week average strike", min_value=0.1, max_value=25.0, value=float(suggested_roll), step=0.5, format="%.1f"))

    st.markdown("<div class='shdr'>Indicative Pricing</div>", unsafe_allow_html=True)
    seasonal_price = st.slider("Seasonal touch YES price", 1, 99, 20, 1, format="%d¢") / 100.0
    rolling_price = st.slider("13-week YES price", 1, 99, 20, 1, format="%d¢") / 100.0
    evergreen_price = st.slider("Weekly evergreen YES price", 1, 50, 5, 1, format="%d¢") / 100.0
    evergreen_cap_weeks = int(st.slider("Evergreen aggregate payout cap", 1, 20, 4, 1, format="%d trigger weeks"))

    st.markdown("<div class='shdr'>Actuarial Assumptions</div>", unsafe_allow_html=True)
    prior_mean = st.slider("Prior exceedance probability", 0.05, 0.60, 0.25, 0.01)
    prior_strength = st.slider("Prior credibility (equivalent seasons)", 0.5, 8.0, 2.0, 0.5)
    severity_shift = st.slider("Weekly-path severity shift (pct points)", -2.0, 3.0, 0.0, 0.1)
    dispersion = st.slider("Weekly-path dispersion multiplier", 0.5, 2.0, 1.0, 0.05)
    persistence = st.slider("Weekly persistence multiplier", 0.5, 1.5, 1.0, 0.05)
    n_paths = int(st.select_slider("Correlated simulation paths", options=[1000, 2500, 5000, 10000], value=5000))

hist = history_for_geography(geography)
views, peak_sims = probability_views(
    geography=geography,
    strike_pct=strike,
    prior_mean=prior_mean,
    prior_strength=prior_strength,
    severity_shift_pct=severity_shift,
    dispersion_multiplier=dispersion,
)
peak_stats = simulation_summary(peak_sims)

if weekly_all is None:
    with right:
        st.error(f"Weekly CDC history could not be loaded: {weekly_error}")
        st.info("The original seasonal peak analysis remains available, but the requested weekly-path features require the CDC weekly series.")
    st.stop()

window_hist = contract_window_history(geography, weekly_all, start_mmdd, end_mmdd)
roll_summary = rolling_window_season_summary(geography, weekly_all, start_mmdd, end_mmdd, 13)
historical = historical_window_metrics(
    geography, weekly_all, strike, rolling_strike, start_mmdd, end_mmdd
)
path_summary, sample_paths = _path_simulation(
    geography, strike, rolling_strike, notional, evergreen_cap_weeks,
    start_mmdd, end_mmdd, n_paths, severity_shift, dispersion, persistence,
    data_asof.isoformat(),
)

seasonal_cred = beta_binomial_mean(
    int(historical["seasonal_touch_hits"]), int(historical["seasons"]), prior_mean, prior_strength
)
rolling_cred = beta_binomial_mean(
    int(historical["rolling_13w_hits"]), max(int(historical["rolling_13w_seasons"]), 1), prior_mean, prior_strength
)
seasonal_econ = trade_economics(notional, seasonal_price, path_summary.seasonal_touch_probability)
rolling_econ = trade_economics(notional, rolling_price, path_summary.rolling_13w_touch_probability)
weeks = path_summary.n_weeks
evergreen_total_premium = notional * evergreen_price * weeks
evergreen_expected_payout = path_summary.expected_cumulative_payout
evergreen_expected_client_cash = evergreen_expected_payout - evergreen_total_premium
evergreen_lp_expected_pnl = evergreen_total_premium - evergreen_expected_payout

with right:
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Exact-window touch · hist", f"{float(historical['seasonal_touch_probability']):.1%}")
    k2.metric("Exact-window touch · sim", f"{path_summary.seasonal_touch_probability:.1%}")
    k3.metric("13-week touch · sim", f"{path_summary.rolling_13w_touch_probability:.1%}")
    k4.metric("Weekly exceedance · sim", f"{path_summary.weekly_exceedance_probability:.1%}")
    k5.metric("Expected hit weeks", f"{path_summary.expected_trigger_weeks:.2f}")
    st.markdown("<div class='note'><b>Model boundary.</b> Weekly paths preserve observed serial persistence using an AR(1) residual process around the historical within-window seasonal profile. This is a transparent scenario model for underwriting discussion; actuarial review remains pending.</div>", unsafe_allow_html=True)

    tabs = st.tabs(["Seasonal Touch", "13-Week Average", "Weekly Evergreen", "Product Comparison"])

    with tabs[0]:
        a, b = st.columns([1.35, 1], gap="large")
        with a:
            st.markdown("<div class='shdr'>Historical Exact-Window Weekly Path</div>", unsafe_allow_html=True)
            fig = go.Figure()
            for season, sdf in window_hist.groupby("season"):
                fig.add_trace(go.Scatter(x=sdf["week_of_window"], y=sdf["ed_visits_pct"], mode="lines", name=season))
            fig.add_hline(y=strike, line_dash="dash", annotation_text=f"Strike {strike:.1f}%")
            fig.update_layout(height=330, margin=dict(l=0,r=0,t=10,b=0), plot_bgcolor="#fff", paper_bgcolor="rgba(0,0,0,0)", xaxis_title="Week in mapped contract window", yaxis_title="Influenza ED visits (%)")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        with b:
            st.markdown("<div class='shdr'>Probability Views</div>", unsafe_allow_html=True)
            st.metric("Historical exact-window touch", f"{float(historical['seasonal_touch_probability']):.1%}", f"{int(historical['seasonal_touch_hits'])} of {int(historical['seasons'])} seasons")
            st.metric("Credibility-adjusted", f"{seasonal_cred:.1%}")
            st.metric("Correlated weekly-path simulation", f"{path_summary.seasonal_touch_probability:.1%}")
            st.caption(f"Legacy peak-only simulation: {views.simulated:.1%}; simulated peak P90 {peak_stats['p90']:.2f}%.")

        st.markdown("<div class='shdr'>Seasonal Touch Economics</div>", unsafe_allow_html=True)
        x1,x2,x3,x4 = st.columns(4)
        x1.metric("Client premium", f"${seasonal_econ.client_premium:,.0f}")
        x2.metric("Net protection if trigger", f"${seasonal_econ.client_net_protection_if_trigger:,.0f}")
        x3.metric("LP collateral at risk", f"${seasonal_econ.lp_collateral:,.0f}")
        x4.metric("LP expected P&L", f"${seasonal_econ.lp_expected_pnl:,.0f}")

    with tabs[1]:
        st.markdown("<div class='shdr'>13-Week Sustained-Burden Structure</div>", unsafe_allow_html=True)
        r1, r2 = st.columns([1.4, 1], gap="large")
        with r1:
            rfig = go.Figure(go.Bar(x=roll_summary["season"], y=roll_summary["max_rolling_pct"], customdata=roll_summary["peak_window_end"].dt.strftime("%Y-%m-%d"), hovertemplate="%{x}<br>Max 13-week avg: %{y:.2f}%<br>Window end: %{customdata}<extra></extra>"))
            rfig.add_hline(y=rolling_strike, line_dash="dash", annotation_text=f"Strike {rolling_strike:.1f}%")
            rfig.update_layout(height=320, margin=dict(l=0,r=0,t=10,b=0), plot_bgcolor="#fff", paper_bgcolor="rgba(0,0,0,0)", yaxis_title="Max 13-week average (%)")
            st.plotly_chart(rfig, use_container_width=True, config={"displayModeBar": False})
        with r2:
            st.metric("Historical seasonal touch", f"{float(historical['rolling_13w_probability']):.1%}", f"{int(historical['rolling_13w_hits'])} of {int(historical['rolling_13w_seasons'])} seasons")
            st.metric("Credibility-adjusted", f"{rolling_cred:.1%}")
            st.metric("Correlated-path simulation", f"{path_summary.rolling_13w_touch_probability:.1%}")
            st.caption("Trigger is based on the maximum completed 13-week arithmetic average inside the exact mapped contract window.")

        st.markdown("<div class='shdr'>13-Week Contract Economics</div>", unsafe_allow_html=True)
        x1,x2,x3,x4,x5 = st.columns(5)
        x1.metric("Client premium", f"${rolling_econ.client_premium:,.0f}")
        x2.metric("Gross payout", f"${rolling_econ.client_gross_payout_if_trigger:,.0f}")
        x3.metric("Net protection", f"${rolling_econ.client_net_protection_if_trigger:,.0f}")
        x4.metric("LP collateral", f"${rolling_econ.lp_collateral:,.0f}")
        x5.metric("LP expected P&L", f"${rolling_econ.lp_expected_pnl:,.0f}")
        st.caption(f"Expected client cash value using the correlated-path trigger probability: ${rolling_econ.client_expected_cash_value:,.0f}. Avoided medical/operating loss is not included.")

        roll_series = rolling_window_series(geography, weekly_all, start_mmdd, end_mmdd, 13).dropna(subset=["rolling_13w_pct"])
        line = go.Figure()
        for season, sdf in roll_series.groupby("season"):
            line.add_trace(go.Scatter(x=sdf["week_of_window"], y=sdf["rolling_13w_pct"], mode="lines", name=season))
        line.add_hline(y=rolling_strike, line_dash="dash", annotation_text=f"Strike {rolling_strike:.1f}%")
        line.update_layout(height=300, margin=dict(l=0,r=0,t=10,b=0), plot_bgcolor="#fff", paper_bgcolor="rgba(0,0,0,0)", xaxis_title="Week in mapped contract window", yaxis_title="13-week average (%)")
        st.plotly_chart(line, use_container_width=True, config={"displayModeBar": False})

    with tabs[2]:
        st.markdown("<div class='shdr'>Correlated Weekly Path Simulation</div>", unsafe_allow_html=True)
        e1,e2,e3,e4,e5 = st.columns(5)
        e1.metric("P(≥1 trigger week)", f"{path_summary.evergreen_any_trigger_probability:.1%}")
        e2.metric("Expected trigger weeks", f"{path_summary.expected_trigger_weeks:.2f}")
        e3.metric("Expected longest run", f"{path_summary.expected_longest_run:.2f} wks")
        e4.metric("Expected cumulative payout", f"${path_summary.expected_cumulative_payout:,.0f}")
        e5.metric("P95 cumulative payout", f"${path_summary.p95_cumulative_payout:,.0f}")

        pfig = go.Figure()
        for path_id, pdf in sample_paths[sample_paths["path"] <= 12].groupby("path"):
            pfig.add_trace(go.Scatter(x=pdf["week"], y=pdf["ed_visits_pct"], mode="lines", line=dict(width=1), opacity=.45, showlegend=False, hovertemplate=f"Path {path_id}<br>Week %{{x}}<br>%{{y:.2f}}%<extra></extra>"))
        pfig.add_hline(y=strike, line_dash="dash", annotation_text=f"Weekly strike {strike:.1f}%")
        pfig.update_layout(height=330, margin=dict(l=0,r=0,t=10,b=0), plot_bgcolor="#fff", paper_bgcolor="rgba(0,0,0,0)", xaxis_title="Week in contract window", yaxis_title="Simulated influenza ED visits (%)")
        st.plotly_chart(pfig, use_container_width=True, config={"displayModeBar": False})

        st.markdown("<div class='shdr'>Evergreen Program Economics</div>", unsafe_allow_html=True)
        y1,y2,y3,y4,y5 = st.columns(5)
        y1.metric("Weekly premium", f"${notional * evergreen_price:,.0f}")
        y2.metric("Full-window premiums", f"${evergreen_total_premium:,.0f}")
        y3.metric("Expected gross payout", f"${evergreen_expected_payout:,.0f}")
        y4.metric("Client expected cash value", f"${evergreen_expected_client_cash:,.0f}")
        y5.metric("LP expected program P&L", f"${evergreen_lp_expected_pnl:,.0f}")
        st.caption(f"Assumes renewal for all {weeks} qualifying weeks, notional resets weekly, and aggregate payouts are capped at {evergreen_cap_weeks} trigger weeks (${path_summary.max_cumulative_payout:,.0f}). Per-active-contract LP collateral is ${notional * (1-evergreen_price):,.0f}.")

        g1,g2,g3,g4 = st.columns(4)
        g1.metric("Fitted weekly persistence φ", f"{path_summary.fitted_phi:.2f}")
        g2.metric("Stressed persistence φ", f"{path_summary.simulated_phi:.2f}")
        g3.metric("Innovation σ", f"{path_summary.innovation_sigma:.3f}")
        g4.metric("Season effect σ", f"{path_summary.season_effect_sigma:.3f}")

    with tabs[3]:
        comparison = product_comparison_table(
            notional, seasonal_price, rolling_price, evergreen_price,
            historical, path_summary, evergreen_cap_weeks,
        )
        display = comparison.copy()
        display["Historical trigger probability"] = display["Historical trigger probability"].map(lambda x: f"{x:.1%}")
        display["Simulated trigger probability"] = display["Simulated trigger probability"].map(lambda x: f"{x:.1%}")
        display["Indicative premium"] = display["Indicative premium"].map(lambda x: f"${x:,.0f}")
        display["LP capital at risk"] = display["LP capital at risk"].map(lambda x: f"${x:,.0f}")
        display["Expected payout frequency"] = [f"{path_summary.seasonal_touch_probability:.1%} / season", f"{path_summary.rolling_13w_touch_probability:.1%} / season", f"{path_summary.expected_trigger_weeks:.2f} weeks / season"]
        display["Maximum payout"] = display["Maximum payout"].map(lambda x: f"${x:,.0f}")
        st.markdown("<div class='shdr'>Structure Comparison</div>", unsafe_allow_html=True)
        st.dataframe(display, use_container_width=True, hide_index=True)
        st.caption("Weekly Evergreen premium is the full-window premium if renewed every qualifying week. Its LP capital-at-risk figure is per active weekly contract; its maximum payout reflects the selected aggregate trigger-week cap.")

st.markdown("<div class='shdr'>Scenario Save / Export</div>", unsafe_allow_html=True)
comparison = product_comparison_table(
    notional, seasonal_price, rolling_price, evergreen_price,
    historical, path_summary, evergreen_cap_weeks,
)
scenario = build_scenario_payload({
    "model_version": MODEL_VERSION,
    "methodology_status": METHODOLOGY_STATUS,
    "geography": geography,
    "first_qualifying_week": start_date,
    "last_qualifying_week": end_date,
    "weekly_touch_strike_pct": strike,
    "rolling_13w_strike_pct": rolling_strike,
    "notional_per_contract": notional,
    "seasonal_yes_price": seasonal_price,
    "rolling_13w_yes_price": rolling_price,
    "evergreen_weekly_yes_price": evergreen_price,
    "evergreen_payout_cap_weeks": evergreen_cap_weeks,
    "severity_shift_pct": severity_shift,
    "dispersion_multiplier": dispersion,
    "persistence_multiplier": persistence,
    "simulation_paths": n_paths,
    "fitted_phi": path_summary.fitted_phi,
    "simulated_phi": path_summary.simulated_phi,
    "historical_seasonal_touch_probability": float(historical["seasonal_touch_probability"]),
    "simulated_seasonal_touch_probability": path_summary.seasonal_touch_probability,
    "historical_13w_touch_probability": float(historical["rolling_13w_probability"]),
    "simulated_13w_touch_probability": path_summary.rolling_13w_touch_probability,
    "simulated_weekly_exceedance_probability": path_summary.weekly_exceedance_probability,
    "expected_trigger_weeks": path_summary.expected_trigger_weeks,
    "expected_cumulative_evergreen_payout": path_summary.expected_cumulative_payout,
    "cdc_data_asof": data_asof,
})

if "saved_scenarios" not in st.session_state:
    st.session_state.saved_scenarios = []

s1,s2,s3 = st.columns([1,1,1])
with s1:
    if st.button("Save current scenario", use_container_width=True):
        st.session_state.saved_scenarios.append(scenario)
        st.success(f"Saved scenario {scenario['scenario_id']} in this session.")
with s2:
    st.download_button(
        "Export current scenario · JSON",
        data=scenario_json(scenario),
        file_name=f"carefi_event_risk_{scenario['scenario_id']}.json",
        mime="application/json",
        use_container_width=True,
    )
with s3:
    st.download_button(
        "Export product comparison · CSV",
        data=comparison.to_csv(index=False),
        file_name=f"carefi_product_comparison_{scenario['scenario_id']}.csv",
        mime="text/csv",
        use_container_width=True,
    )

if st.session_state.saved_scenarios:
    saved_df = pd.DataFrame(st.session_state.saved_scenarios)
    cols = [c for c in ["scenario_id", "saved_at_utc", "geography", "first_qualifying_week", "last_qualifying_week", "weekly_touch_strike_pct", "rolling_13w_strike_pct", "notional_per_contract"] if c in saved_df.columns]
    st.dataframe(saved_df[cols], use_container_width=True, hide_index=True)
    st.download_button("Export saved scenario register · CSV", saved_df.to_csv(index=False), "carefi_saved_scenarios.csv", "text/csv")

st.markdown("<div class='shdr'>Model Governance</div>", unsafe_allow_html=True)
g1,g2,g3,g4 = st.columns(4)
with g1:
    st.markdown(f"<div class='dark'><b>Model</b><br>{MODEL_VERSION}<br>Research owner: Oriel Labs<br>Commercial user: CareFi</div>", unsafe_allow_html=True)
with g2:
    st.markdown(f"<div class='dark'><b>Status</b><br>{METHODOLOGY_STATUS}<br>Actuarial approval: not yet recorded<br>Executable fair value: no</div>", unsafe_allow_html=True)
with g3:
    st.markdown(f"<div class='dark'><b>Data</b><br>CDC FluSight / NSSP<br>Research data as of {data_asof:%Y-%m-%d}<br>Runtime cache: 1 hour</div>", unsafe_allow_html=True)
with g4:
    st.markdown(f"<div class='dark'><b>Contract / Oracle</b><br>Backtest window: {start_mmdd} → {end_mmdd}<br>Settlement version pin: required<br>Revision / fallback: contract-defined</div>", unsafe_allow_html=True)

st.markdown("<div class='shdr'>Methodology / Actuarial Review</div>", unsafe_allow_html=True)
m1,m2,m3 = st.columns(3, gap="large")
with m1:
    st.markdown("<div class='dark'><b>Exact-window history</b><br>Each selected month/day boundary is mapped onto every observed respiratory season. No interpolation is used for contract backtesting.</div>", unsafe_allow_html=True)
with m2:
    st.markdown("<div class='dark'><b>Correlated weekly paths</b><br>Ordinal-week log-profile plus AR(1) residual persistence and a season-level severity effect. Severity, dispersion and persistence stresses remain visible user inputs.</div>", unsafe_allow_html=True)
with m3:
    st.markdown("<div class='dark'><b>Review priorities</b><br>Validate persistence specification, between-season effect, 13-week arithmetic averaging, evergreen payout cap, stress ranges and basis-risk treatment before external reliance.</div>", unsafe_allow_html=True)

st.markdown("---")
st.caption("Research decision support only. Weekly source is the live CDC FluSight/NSSP research feed. Final traded contracts should pin the exact publication/commit, observation convention, revision treatment and fallback process.")