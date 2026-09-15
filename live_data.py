from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import pandas as pd
import requests

BLS_API="https://api.bls.gov/publicAPI/v2/timeseries/data/"
CDC_BASE="https://data.cdc.gov/resource"

BLS_SERIES={
    "Medical CPI":"CUUR0000SAM",
    "Medical Care Services CPI":"CUUR0000SAM2",
    "Healthcare Services PPI":"SIHCARE3",
}

LIVE_SOURCE_REGISTRY=[
    {"source":"BLS Medical CPI","role":"Healthcare inflation reference","mode":"LIVE API","production_use":"Reference input"},
    {"source":"BLS Healthcare Services PPI","role":"Provider-cost reference","mode":"LIVE API","production_use":"Reference input"},
    {"source":"CDC NSSP / FluView","role":"Respiratory public print","mode":"LIVE API + first-print archive required","production_use":"Observation / settlement support"},
    {"source":"CMS reimbursement","role":"Reimbursement public print","mode":"NOT CONNECTED","production_use":"Fallback to modeled position"},
    {"source":"MEDUSDi","role":"Healthcare-inflation hedge asset","mode":"MANUAL REFERENCE","production_use":"No live token mark yet"},
    {"source":"Venue collateral","role":"Posted collateral / execution state","mode":"MODELED","production_use":"No live venue account connected"},
]

def parse_bls_response(payload: dict) -> dict[str,pd.DataFrame]:
    if payload.get("status")!="REQUEST_SUCCEEDED":
        raise RuntimeError("BLS API request did not succeed")
    out={}
    for series in payload.get("Results",{}).get("series",[]):
        sid=series.get("seriesID","")
        rows=[]
        for item in series.get("data",[]):
            period=str(item.get("period",""))
            if not period.startswith("M") or period=="M13":
                continue
            try:
                month=int(period[1:])
                rows.append({
                    "date":pd.Timestamp(year=int(item["year"]),month=month,day=1),
                    "value":float(item["value"]),
                    "series_id":sid,
                })
            except (ValueError,TypeError,KeyError):
                continue
        out[sid]=pd.DataFrame(rows).sort_values("date").reset_index(drop=True) if rows else pd.DataFrame(columns=["date","value","series_id"])
    return out

def fetch_bls_series(start_year: int, end_year: int, timeout: int = 10) -> dict[str,pd.DataFrame]:
    ids=list(BLS_SERIES.values())
    resp=requests.post(
        BLS_API,
        json={"seriesid":ids,"startyear":str(start_year),"endyear":str(end_year)},
        timeout=timeout,
    )
    resp.raise_for_status()
    return parse_bls_response(resp.json())

def _first_present(row: dict, keys: tuple[str,...]):
    for key in keys:
        if row.get(key) not in (None,""):
            return row.get(key)
    return None

def fetch_cdc_rows(dataset_id: str = "rdmq-nq56", limit: int = 500, timeout: int = 10, where: str | None = None, order: str | None = None) -> list[dict]:
    url=f"{CDC_BASE}/{dataset_id}.json"
    params={"$limit":limit}
    if where:
        params["$where"]=where
    if order:
        params["$order"]=order
    resp=requests.get(url,params=params,timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def fetch_cdc_snapshot(dataset_id: str = "rdmq-nq56", limit: int = 500, timeout: int = 10) -> dict:
    rows=fetch_cdc_rows(dataset_id=dataset_id,limit=limit,timeout=timeout)
    latest_date=None
    latest_value=None
    for row in rows:
        date_raw=_first_present(row,("week_end","week_ending","weekendingdate","week_ending_date","week_end_date","date"))
        value_raw=_first_present(row,("percent_of_ed_visits","percent_visits","visit_percentage","percentage","percent","value","data_value"))
        if date_raw:
            try:
                d=pd.to_datetime(str(date_raw)[:10])
                if latest_date is None or d>latest_date:
                    latest_date=d
                    latest_value=value_raw
            except Exception:
                pass
    return {
        "dataset_id":dataset_id,
        "rows":len(rows),
        "latest_date":latest_date,
        "latest_value":latest_value,
        "sample_keys":sorted(list(rows[0].keys()))[:12] if rows else [],
    }

def latest_with_yoy(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"date":None,"value":None,"yoy_pct":None}
    work=df.sort_values("date").copy()
    work["yoy_pct"]=work["value"].pct_change(12)*100.0
    row=work.iloc[-1]
    return {
        "date":row["date"],
        "value":float(row["value"]),
        "yoy_pct":float(row["yoy_pct"]) if pd.notna(row["yoy_pct"]) else None,
    }

def fetch_public_sources(start_year: int, end_year: int) -> dict:
    now=datetime.now(timezone.utc).isoformat()
    result={"fetched_at":now,"bls":{},"cdc":None,"errors":[]}
    try:
        raw=fetch_bls_series(start_year,end_year)
        reverse={sid:name for name,sid in BLS_SERIES.items()}
        for sid,df in raw.items():
            result["bls"][reverse.get(sid,sid)]={"series_id":sid,"data":df,"latest":latest_with_yoy(df)}
    except Exception as exc:
        result["errors"].append("BLS: "+str(exc))
    try:
        result["cdc"]=fetch_cdc_snapshot()
    except Exception as exc:
        result["errors"].append("CDC: "+str(exc))
    return result


DATA_DIR=Path(__file__).resolve().parent/"data"
PRODUCTION_SNAPSHOT_PATH=DATA_DIR/"public_snapshot.json"
CDC_FIRST_PRINT_PATH=DATA_DIR/"cdc_first_print.json"
BLS_HISTORY_PATH=DATA_DIR/"bls_history.csv"

def load_production_snapshot() -> dict:
    if not PRODUCTION_SNAPSHOT_PATH.exists():
        return {"status":"missing","generated_at":None,"errors":["Persistent production snapshot not found."]}
    try:
        return json.loads(PRODUCTION_SNAPSHOT_PATH.read_text())
    except Exception as exc:
        return {"status":"invalid","generated_at":None,"errors":[str(exc)]}

def load_cdc_first_print_ledger() -> dict:
    if not CDC_FIRST_PRINT_PATH.exists():
        return {"dataset_id":"rdmq-nq56","records":{},"record_count":0}
    try:
        ledger=json.loads(CDC_FIRST_PRINT_PATH.read_text())
        ledger["record_count"]=len(ledger.get("records",{}))
        return ledger
    except Exception as exc:
        return {"dataset_id":"rdmq-nq56","records":{},"record_count":0,"error":str(exc)}

def load_persisted_bls_history() -> pd.DataFrame:
    if not BLS_HISTORY_PATH.exists():
        return pd.DataFrame(columns=["date","value","series_id","series"])
    try:
        df=pd.read_csv(BLS_HISTORY_PATH)
        if "date" in df.columns:
            df["date"]=pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame(columns=["date","value","series_id","series"])

def fetch_authenticated_json(url: str | None, token: str | None = None, timeout: int = 10) -> dict:
    if not url:
        return {"status":"not_connected","error":"endpoint not configured"}
    headers={}
    if token:
        headers["Authorization"]="Bearer "+token
    try:
        resp=requests.get(url,headers=headers,timeout=timeout)
        resp.raise_for_status()
        payload=resp.json()
        return {"status":"live","payload":payload,"http_status":resp.status_code}
    except Exception as exc:
        return {"status":"error","error":str(exc)}

def fetch_oriel_marks() -> dict:
    return fetch_authenticated_json(
        os.getenv("ORIEL_MARKS_URL"),
        os.getenv("ORIEL_MARKS_TOKEN"),
    )

def fetch_medusdi_spot() -> dict:
    return fetch_authenticated_json(
        os.getenv("MEDUSDI_SPOT_URL"),
        os.getenv("MEDUSDI_SPOT_TOKEN"),
    )

def fetch_venue_collateral() -> dict:
    return fetch_authenticated_json(
        os.getenv("VENUE_COLLATERAL_URL"),
        os.getenv("VENUE_COLLATERAL_TOKEN"),
    )
