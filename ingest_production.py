from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from live_data import BLS_SERIES, fetch_bls_series, fetch_cdc_rows

DATA_DIR=Path("data")
DATA_DIR.mkdir(exist_ok=True)
SNAPSHOT_PATH=DATA_DIR/"public_snapshot.json"
BLS_PATH=DATA_DIR/"bls_history.csv"
CDC_LEDGER_PATH=DATA_DIR/"cdc_first_print.json"

DATE_KEYS=("week_end","week_ending","weekendingdate","week_ending_date","week_end_date","date")
VALUE_KEYS=("percent_of_ed_visits","percent_visits","visit_percentage","percentage","percent","value","data_value")
DISEASE_KEYS=("pathogen","disease","diagnosis","indicator","virus","category")
STATE_KEYS=("state","jurisdiction","location","geography")
COUNTY_KEYS=("county","county_name")

def first(row,keys):
    for key in keys:
        value=row.get(key)
        if value not in (None,""):
            return value
    return None

def normalize_cdc_row(row):
    period=first(row,DATE_KEYS)
    value=first(row,VALUE_KEYS)
    if period is None or value is None:
        return None
    disease=str(first(row,DISEASE_KEYS) or "")
    state=str(first(row,STATE_KEYS) or "")
    county=str(first(row,COUNTY_KEYS) or "")
    geography=", ".join([x for x in (county,state) if x]) or "United States"
    try:
        numeric=float(str(value).replace("%","").replace(",","").strip())
    except ValueError:
        return None
    period=str(period)[:10]
    key="|".join([period,geography.lower(),disease.lower()])
    return {
        "key":key,"period_end":period,"geography":geography,"disease":disease,
        "value":numeric,
    }

def load_ledger():
    if CDC_LEDGER_PATH.exists():
        return json.loads(CDC_LEDGER_PATH.read_text())
    return {"dataset_id":"rdmq-nq56","methodology":"first seen by scheduled ingestion; revisions ignored","records":{}}

def main():
    now=datetime.now(timezone.utc).isoformat()
    year=datetime.now(timezone.utc).year
    errors=[]

    # BLS durable history
    bls_latest={}
    try:
        raw=fetch_bls_series(max(year-10,2015),year)
        frames=[]
        reverse={sid:name for name,sid in BLS_SERIES.items()}
        for sid,df in raw.items():
            if df.empty:
                continue
            tmp=df.copy()
            tmp["series"]=reverse.get(sid,sid)
            frames.append(tmp)
            tmp2=tmp.sort_values("date").copy()
            tmp2["yoy_pct"]=tmp2["value"].pct_change(12)*100.0
            last=tmp2.iloc[-1]
            bls_latest[reverse.get(sid,sid)]={
                "series_id":sid,
                "date":str(last["date"].date()),
                "value":float(last["value"]),
                "yoy_pct":float(last["yoy_pct"]) if pd.notna(last["yoy_pct"]) else None,
            }
        if frames:
            hist=pd.concat(frames,ignore_index=True)
            hist["date"]=pd.to_datetime(hist["date"]).dt.strftime("%Y-%m-%d")
            hist.to_csv(BLS_PATH,index=False)
    except Exception as exc:
        errors.append("BLS: "+str(exc))

    # CDC persistent first-print ledger
    cdc_summary={"rows_fetched":0,"new_first_prints":0,"latest_period":None}
    try:
        rows=fetch_cdc_rows(limit=5000)
        cdc_summary["rows_fetched"]=len(rows)
        ledger=load_ledger()
        records=ledger.setdefault("records",{})
        new_count=0
        latest=None
        for row in rows:
            normalized=normalize_cdc_row(row)
            if not normalized:
                continue
            if normalized["key"] not in records:
                records[normalized["key"]]={
                    **normalized,
                    "first_seen_at":now,
                    "source_dataset":"rdmq-nq56",
                }
                new_count+=1
            p=normalized["period_end"]
            if latest is None or p>latest:
                latest=p
        ledger["last_ingested_at"]=now
        ledger["record_count"]=len(records)
        CDC_LEDGER_PATH.write_text(json.dumps(ledger,indent=2,sort_keys=True))
        cdc_summary.update({"new_first_prints":new_count,"latest_period":latest,"ledger_records":len(records)})
    except Exception as exc:
        errors.append("CDC: "+str(exc))

    snapshot={
        "generated_at":now,
        "status":"healthy" if not errors else "degraded",
        "errors":errors,
        "bls_latest":bls_latest,
        "cdc":cdc_summary,
        "medusdi":{
            "spot_status":"not_connected",
            "reference_status":"live_medical_cpi" if "Medical CPI" in bls_latest else "unavailable",
            "reference_series":"CUUR0000SAM",
            "note":"MEDUSDi spot requires an explicit token/pool address; Medical CPI is the live fair-value reference input only.",
        },
        "venue":{
            "status":"not_connected",
            "note":"Venue collateral/account feed requires authorized API credentials.",
        },
    }
    SNAPSHOT_PATH.write_text(json.dumps(snapshot,indent=2,sort_keys=True))
    print(json.dumps(snapshot,indent=2))

if __name__=="__main__":
    main()
