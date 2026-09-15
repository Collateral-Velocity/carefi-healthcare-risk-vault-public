from __future__ import annotations

from datetime import datetime, timezone
import math
import pandas as pd

METHODOLOGY_VERSION="OER-HC-1.0.0"

CONTRACT_REGISTRY=[
    {
        "contract_id":"ORIEL-HC-TX-FLU-2027-01",
        "position":"Texas respiratory utilization",
        "risk_family":"Respiratory Utilization",
        "geography":"Texas",
        "source":"CDC NSSP / FluView",
        "source_dataset":"vutn-jzwm",
        "threshold":5.0,
        "threshold_unit":"influenza ED visits %",
        "window_start":"2027-10-09",
        "window_end":"2028-05-20",
        "prior_probability":0.36,
        "basis_grade":"B+",
        "mark_method":"respiratory_touch_prior_then_observation",
    },
    {
        "contract_id":"ORIEL-HC-US-FLU-2027-01",
        "position":"National influenza ED utilization",
        "risk_family":"Respiratory Utilization",
        "geography":"United States",
        "source":"CDC NSSP / FluView",
        "source_dataset":"vutn-jzwm",
        "threshold":5.0,
        "threshold_unit":"influenza ED visits %",
        "window_start":"2027-10-09",
        "window_end":"2028-05-20",
        "prior_probability":0.33,
        "basis_grade":"A-",
        "mark_method":"respiratory_touch_prior_then_observation",
    },
    {
        "contract_id":"ORIEL-HC-PPI-2027-01",
        "position":"Healthcare services PPI shock",
        "risk_family":"Healthcare Inflation",
        "geography":"National",
        "source":"BLS PPI",
        "source_dataset":"SIHCARE3",
        "threshold":4.0,
        "threshold_unit":"YoY %",
        "window_start":"2027-01-01",
        "window_end":"2027-12-31",
        "prior_probability":0.24,
        "basis_grade":"A-",
        "mark_method":"blended_prior_empirical_exceedance",
    },
    {
        "contract_id":"ORIEL-HC-MCPI-2027-01",
        "position":"Medical CPI acceleration",
        "risk_family":"Healthcare Inflation",
        "geography":"National",
        "source":"BLS CPI",
        "source_dataset":"CUUR0000SAM",
        "threshold":4.0,
        "threshold_unit":"YoY %",
        "window_start":"2027-01-01",
        "window_end":"2027-12-31",
        "prior_probability":0.27,
        "basis_grade":"A",
        "mark_method":"blended_prior_empirical_exceedance",
    },
    {
        "contract_id":"ORIEL-HC-CMS-2027-01",
        "position":"Medicare reimbursement shortfall",
        "risk_family":"Reimbursement",
        "geography":"National",
        "source":"CMS",
        "source_dataset":None,
        "prior_probability":0.22,
        "basis_grade":"B",
        "mark_method":"not_live",
    },
    {
        "contract_id":"ORIEL-HC-RX-2027-01",
        "position":"Specialty-drug utilization shock",
        "risk_family":"Pharmacy / Specialty",
        "geography":"National",
        "source":"Public print TBD",
        "source_dataset":None,
        "prior_probability":0.28,
        "basis_grade":"C+",
        "mark_method":"not_live",
    },
]

def _annual_exceedance_probability(df: pd.DataFrame, threshold: float, min_years: int = 3) -> dict:
    if df is None or df.empty:
        return {"probability":None,"years":0,"latest_yoy":None,"latest_period":None}
    work=df[["date","value"]].copy().dropna()
    work["date"]=pd.to_datetime(work["date"])
    work=work.sort_values("date")
    work["yoy_pct"]=work["value"].pct_change(12)*100.0
    clean=work.dropna(subset=["yoy_pct"]).copy()
    if clean.empty:
        return {"probability":None,"years":0,"latest_yoy":None,"latest_period":None}
    clean["year"]=clean["date"].dt.year
    annual=clean.groupby("year")["yoy_pct"].max()
    if len(annual)<min_years:
        probability=None
    else:
        # Jeffreys-style smoothing prevents 0/1 marks from sparse history.
        hits=float((annual>=threshold).sum())
        probability=(hits+0.5)/(len(annual)+1.0)
    last=clean.iloc[-1]
    return {
        "probability":float(probability) if probability is not None else None,
        "years":int(len(annual)),
        "latest_yoy":float(last["yoy_pct"]),
        "latest_period":str(last["date"].date()),
        "annual_max_yoy":{str(int(y)):float(v) for y,v in annual.items()},
    }

def _blend_prior(prior: float, empirical: float | None, empirical_weight: float = 0.40) -> float:
    if empirical is None:
        return float(prior)
    return min(max((1.0-empirical_weight)*float(prior)+empirical_weight*float(empirical),0.01),0.99)

def _cdc_values(ledger: dict, geography: str) -> pd.DataFrame:
    rows=[]
    geo_target=geography.lower()
    for record in (ledger.get("records") or {}).values():
        if str(record.get("disease","")).lower()!="influenza":
            continue
        geo=str(record.get("geography",""))
        if geography=="United States":
            if geo.lower() not in ("united states","national","us","u.s."):
                continue
        elif geo_target not in geo.lower():
            continue
        rows.append({"date":record.get("period_end"),"value":record.get("value")})
    if not rows:
        return pd.DataFrame(columns=["date","value"])
    df=pd.DataFrame(rows)
    df["date"]=pd.to_datetime(df["date"])
    df["value"]=pd.to_numeric(df["value"],errors="coerce")
    return df.dropna().sort_values("date")

def _respiratory_mark(contract: dict, ledger: dict, as_of: pd.Timestamp) -> dict:
    prior=float(contract["prior_probability"])
    window_start=pd.Timestamp(contract["window_start"])
    window_end=pd.Timestamp(contract["window_end"])
    obs=_cdc_values(ledger,contract["geography"])
    in_window=obs[(obs["date"]>=window_start)&(obs["date"]<=min(as_of,window_end))] if not obs.empty else obs
    current_max=float(in_window["value"].max()) if not in_window.empty else None
    latest=float(in_window.iloc[-1]["value"]) if not in_window.empty else None
    latest_period=str(in_window.iloc[-1]["date"].date()) if not in_window.empty else None

    if as_of < window_start:
        fair=prior
        state="pre_window_prior"
    elif current_max is not None and current_max>=float(contract["threshold"]):
        fair=1.0
        state="trigger_observed"
    elif as_of>window_end:
        fair=0.0
        state="window_closed_no_trigger"
    else:
        # During the active window, retain the calibrated prior but reduce it
        # as elapsed season share increases without a trigger. This is a
        # transparent survival update, not a claim of a structural flu model.
        elapsed=max((as_of-window_start).days,0)
        total=max((window_end-window_start).days,1)
        survival_share=max(1.0-min(elapsed/total,1.0),0.0)
        fair=max(min(prior*(0.35+0.65*survival_share),0.99),0.01)
        state="active_no_trigger"

    return {
        "fair_value":float(fair),
        "reference_value":current_max if current_max is not None else latest,
        "reference_state":state,
        "latest_observation":latest,
        "latest_observation_period":latest_period,
        "observations_in_window":int(len(in_window)),
        "source_health":"healthy" if (as_of<window_start or not obs.empty) else "no_observations",
    }

def generate_event_marks(bls_history: pd.DataFrame, cdc_ledger: dict, generated_at: datetime | None = None) -> dict:
    generated_at=generated_at or datetime.now(timezone.utc)
    as_of=pd.Timestamp(generated_at.date())
    marks=[]

    def series_frame(name: str) -> pd.DataFrame:
        if bls_history is None or bls_history.empty or "series" not in bls_history.columns:
            return pd.DataFrame(columns=["date","value"])
        return bls_history[bls_history["series"]==name][["date","value"]].copy()

    for contract in CONTRACT_REGISTRY:
        row=dict(contract)
        prior=float(contract["prior_probability"])
        method=contract["mark_method"]
        if method=="respiratory_touch_prior_then_observation":
            calc=_respiratory_mark(contract,cdc_ledger,as_of)
            row.update(calc)
            row["empirical_probability"]=None
            row["calibration_years"]=None
        elif contract["source_dataset"]=="SIHCARE3":
            stats=_annual_exceedance_probability(series_frame("Healthcare Services PPI"),float(contract["threshold"]))
            row.update({
                "fair_value":_blend_prior(prior,stats["probability"]),
                "empirical_probability":stats["probability"],
                "calibration_years":stats["years"],
                "reference_value":stats["latest_yoy"],
                "reference_state":"live_yoy_calibration" if stats["latest_yoy"] is not None else "source_unavailable",
                "latest_observation":stats["latest_yoy"],
                "latest_observation_period":stats["latest_period"],
                "source_health":"healthy" if stats["latest_yoy"] is not None else "unavailable",
            })
        elif contract["source_dataset"]=="CUUR0000SAM":
            stats=_annual_exceedance_probability(series_frame("Medical CPI"),float(contract["threshold"]))
            row.update({
                "fair_value":_blend_prior(prior,stats["probability"]),
                "empirical_probability":stats["probability"],
                "calibration_years":stats["years"],
                "reference_value":stats["latest_yoy"],
                "reference_state":"live_yoy_calibration" if stats["latest_yoy"] is not None else "source_unavailable",
                "latest_observation":stats["latest_yoy"],
                "latest_observation_period":stats["latest_period"],
                "source_health":"healthy" if stats["latest_yoy"] is not None else "unavailable",
            })
        else:
            row.update({
                "fair_value":prior,
                "empirical_probability":None,
                "calibration_years":None,
                "reference_value":None,
                "reference_state":"not_live",
                "latest_observation":None,
                "latest_observation_period":None,
                "source_health":"not_connected",
            })

        row["methodology_version"]=METHODOLOGY_VERSION
        row["generated_at"]=generated_at.isoformat()
        row["mark_type"]="Oriel documented fair value"
        row["executable"]=False
        marks.append(row)

    return {
        "artifact":"oriel.healthcare.event_marks.v1",
        "methodology_version":METHODOLOGY_VERSION,
        "generated_at":generated_at.isoformat(),
        "mark_count":len(marks),
        "live_mark_count":sum(1 for m in marks if m["source_health"]=="healthy"),
        "marks":marks,
        "methodology_notes":[
            "Respiratory contracts use the documented prior before the observation window and deterministic first-print settlement state once active.",
            "Medical CPI and SIHCARE3 fair values blend the documented model prior (60%) with smoothed historical annual-threshold exceedance frequency (40%).",
            "These are Oriel reference fair values, not executable venue quotes.",
            "CMS reimbursement and specialty-drug positions remain non-live until an approved public settlement series is connected.",
        ],
    }
