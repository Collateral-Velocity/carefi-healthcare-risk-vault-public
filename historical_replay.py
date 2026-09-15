from __future__ import annotations

import pandas as pd
import numpy as np

CDC_FLU_2025_26 = [
    ("2025-11-01",0.3),("2025-11-08",0.4),("2025-11-15",0.6),("2025-11-22",0.9),
    ("2025-11-29",1.4),("2025-12-06",1.6),("2025-12-13",2.8),("2025-12-20",5.4),
    ("2025-12-27",8.3),("2026-01-03",6.3),("2026-01-10",4.0),("2026-01-17",3.1),
    ("2026-01-24",3.4),("2026-01-31",3.3),("2026-02-07",3.2),("2026-02-14",3.5),
    ("2026-02-21",3.2),("2026-02-28",2.5),
]

REPLAY_THRESHOLDS = {
    "National influenza ED utilization": 5.0,
    "Texas respiratory utilization": 5.0,
    "Healthcare services PPI shock": 4.0,
    "Medical CPI acceleration": 4.0,
}

def cdc_flu_replay_frame() -> pd.DataFrame:
    df=pd.DataFrame(CDC_FLU_2025_26,columns=["date","influenza_ed_pct"])
    df["date"]=pd.to_datetime(df["date"])
    return df

def add_yoy(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out=df.sort_values("date").copy()
    out["yoy_pct"]=out["value"].pct_change(12)*100.0
    return out

def annual_series_stats(df: pd.DataFrame, label: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["year","series","max_yoy_pct","end_yoy_pct","observations"])
    work=add_yoy(df).dropna(subset=["yoy_pct"]).copy()
    work["year"]=work["date"].dt.year
    rows=[]
    for year,g in work.groupby("year"):
        rows.append({
            "year":int(year),"series":label,
            "max_yoy_pct":float(g["yoy_pct"].max()),
            "end_yoy_pct":float(g.sort_values("date").iloc[-1]["yoy_pct"]),
            "observations":int(len(g)),
        })
    return pd.DataFrame(rows)

def cpi_ppi_correlation(cpi_df: pd.DataFrame, ppi_df: pd.DataFrame) -> dict:
    if cpi_df.empty or ppi_df.empty:
        return {"correlation":None,"observations":0}
    c=add_yoy(cpi_df)[["date","yoy_pct"]].rename(columns={"yoy_pct":"cpi_yoy"})
    p=add_yoy(ppi_df)[["date","yoy_pct"]].rename(columns={"yoy_pct":"ppi_yoy"})
    merged=c.merge(p,on="date",how="inner").dropna()
    if len(merged)<3:
        return {"correlation":None,"observations":int(len(merged))}
    return {"correlation":float(merged["cpi_yoy"].corr(merged["ppi_yoy"])),"observations":int(len(merged))}

def replay_years(cpi_df: pd.DataFrame, ppi_df: pd.DataFrame) -> pd.DataFrame:
    cstats=annual_series_stats(cpi_df,"Medical CPI")
    pstats=annual_series_stats(ppi_df,"Healthcare Services PPI")
    years=sorted(set(cstats["year"].tolist()+pstats["year"].tolist()))
    cdc=cdc_flu_replay_frame()
    cdc_peak=float(cdc["influenza_ed_pct"].max())
    rows=[]
    for year in years:
        c=cstats[cstats["year"]==year]
        p=pstats[pstats["year"]==year]
        cmax=float(c.iloc[0]["max_yoy_pct"]) if len(c) else None
        cend=float(c.iloc[0]["end_yoy_pct"]) if len(c) else None
        pmax=float(p.iloc[0]["max_yoy_pct"]) if len(p) else None
        pend=float(p.iloc[0]["end_yoy_pct"]) if len(p) else None
        respiratory_available=(year==2025)
        rows.append({
            "year":year,
            "medical_cpi_max_yoy":cmax,
            "hc_ppi_max_yoy":pmax,
            "medical_cpi_trigger":bool(cmax is not None and cmax>=REPLAY_THRESHOLDS["Medical CPI acceleration"]),
            "hc_ppi_trigger":bool(pmax is not None and pmax>=REPLAY_THRESHOLDS["Healthcare services PPI shock"]),
            "national_flu_peak":cdc_peak if respiratory_available else None,
            "national_flu_trigger":bool(respiratory_available and cdc_peak>=REPLAY_THRESHOLDS["National influenza ED utilization"]),
            "texas_resp_proxy_trigger":bool(respiratory_available and cdc_peak>=REPLAY_THRESHOLDS["Texas respiratory utilization"]),
            "medusdi_proxy_return":(cend/100.0) if cend is not None else None,
            "data_coverage":"BLS + verified CDC first-print" if respiratory_available else "BLS observed; respiratory not replayed",
        })
    return pd.DataFrame(rows)

def covered_portfolio_replay(
    portfolio: pd.DataFrame,
    annual: pd.DataFrame,
    medusdi_hedge_notional: float = 0.0,
) -> pd.DataFrame:
    rows=[]
    pos={str(r["position"]):r for _,r in portfolio.iterrows()}
    mapping={
        "Medical CPI acceleration":"medical_cpi_trigger",
        "Healthcare services PPI shock":"hc_ppi_trigger",
        "National influenza ED utilization":"national_flu_trigger",
        "Texas respiratory utilization":"texas_resp_proxy_trigger",
    }
    for _,yr in annual.iterrows():
        pnl=0.0
        covered=0
        triggered=0
        details=[]
        for name,flag in mapping.items():
            row=pos.get(name)
            if row is None:
                continue
            if name in ("National influenza ED utilization","Texas respiratory utilization") and pd.isna(yr["national_flu_peak"]):
                continue
            hit=bool(yr[flag])
            covered+=1
            triggered+=int(hit)
            pos_pnl=-(1.0-float(row["price"]))*float(row["notional"]) if hit else float(row["price"])*float(row["notional"])
            pnl+=pos_pnl
            details.append(name+(" ✓" if hit else " —"))
        proxy_ret=yr["medusdi_proxy_return"]
        hedge_pnl=float(medusdi_hedge_notional)*(float(proxy_ret) if pd.notna(proxy_ret) else 0.0)
        rows.append({
            "year":int(yr["year"]),
            "covered_positions":covered,
            "triggered_positions":triggered,
            "covered_book_pnl":pnl,
            "medusdi_proxy_hedge_pnl":hedge_pnl,
            "hedged_covered_pnl":pnl+hedge_pnl,
            "coverage_note":yr["data_coverage"],
            "mapped_outcomes":"; ".join(details),
        })
    return pd.DataFrame(rows)
