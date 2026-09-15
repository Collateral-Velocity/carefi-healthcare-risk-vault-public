from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import base64
import time
from urllib.parse import urlparse
import pandas as pd
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

BLS_API="https://api.bls.gov/publicAPI/v2/timeseries/data/"
CDC_BASE="https://data.cdc.gov/resource"
BLS_PPI_SPECIAL_INDEX_URL="https://download.bls.gov/pub/time.series/wp/wp.data.18.SpecialIndexes"

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


def parse_bls_special_index_text(text: str, series_id: str = "SIHCARE3") -> pd.DataFrame:
    rows=[]
    for raw_line in text.splitlines():
        line=raw_line.strip()
        if not line or line.lower().startswith("series_id"):
            continue
        parts=[p.strip() for p in raw_line.split("\t")]
        if len(parts)<4:
            parts=line.split()
        if len(parts)<4 or parts[0]!=series_id:
            continue
        try:
            year=int(parts[1])
            period=str(parts[2])
            if not period.startswith("M") or period=="M13":
                continue
            month=int(period[1:])
            value=float(parts[3])
            rows.append({
                "date":pd.Timestamp(year=year,month=month,day=1),
                "value":value,
                "series_id":series_id,
            })
        except (ValueError,TypeError):
            continue
    if not rows:
        return pd.DataFrame(columns=["date","value","series_id"])
    return pd.DataFrame(rows).sort_values("date").drop_duplicates("date",keep="last").reset_index(drop=True)

def fetch_bls_special_index(
    series_id: str = "SIHCARE3",
    start_year: int | None = None,
    end_year: int | None = None,
    timeout: int = 20,
) -> pd.DataFrame:
    end_year=int(end_year or datetime.now(timezone.utc).year)
    start_year=int(start_year or max(end_year-10,2014))

    # First preference: isolated BLS API request. Some special indexes are
    # omitted when mixed with unrelated survey series in one payload.
    try:
        resp=requests.post(
            BLS_API,
            json={"seriesid":[series_id],"startyear":str(start_year),"endyear":str(end_year)},
            headers={"Content-Type":"application/json","User-Agent":"CareFi-Oriel/1.0 data-ingestion"},
            timeout=timeout,
        )
        resp.raise_for_status()
        parsed=parse_bls_response(resp.json())
        df=parsed.get(series_id,pd.DataFrame())
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # Official PPI Special Indexes flat file fallback.
    resp=requests.get(
        BLS_PPI_SPECIAL_INDEX_URL,
        headers={"User-Agent":"Mozilla/5.0 CareFi-Oriel/1.0 (+https://orielmarkets.com)","Accept":"text/plain,*/*"},
        timeout=timeout,
    )
    resp.raise_for_status()
    df=parse_bls_special_index_text(resp.text,series_id=series_id)
    if df.empty:
        raise RuntimeError(f"{series_id} not found via BLS API or PPI Special Indexes flat file")
    mask=(df["date"].dt.year>=start_year)&(df["date"].dt.year<=end_year)
    return df.loc[mask].reset_index(drop=True)

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

ORIEL_MEDUSDI_ARTIFACT="https://orielmarkets.com/medusd/data/usdi_med_basis_monitor.json"
ORIEL_MEDUSDI_USDC_ARTIFACT="https://orielmarkets.com/medusd/data/usdi_med_usdc_reference.json"
ORIEL_EVENT_MARKS_PATH=DATA_DIR/"oriel_event_marks.json"

def fetch_oriel_marks(timeout: int = 10) -> dict:
    custom_url=os.getenv("ORIEL_MARKS_URL")
    if custom_url:
        result=fetch_authenticated_json(custom_url,os.getenv("ORIEL_MARKS_TOKEN"),timeout=timeout)
        if result.get("status")=="live":
            result["source"]="Oriel configured event-mark endpoint"
            result["url"]=custom_url
        return result
    if not ORIEL_EVENT_MARKS_PATH.exists():
        return {"status":"not_connected","error":"Oriel event-mark artifact not yet generated"}
    try:
        payload=json.loads(ORIEL_EVENT_MARKS_PATH.read_text())
        return {
            "status":"live",
            "source":"Oriel persisted healthcare event-mark artifact",
            "payload":payload,
            "methodology_version":payload.get("methodology_version"),
            "generated_at":payload.get("generated_at"),
        }
    except Exception as exc:
        return {"status":"error","error":str(exc)}

def fetch_oriel_medusdi_reference(timeout: int = 10) -> dict:
    result=fetch_authenticated_json(ORIEL_MEDUSDI_ARTIFACT,timeout=timeout)
    if result.get("status")=="live":
        result["source"]="Oriel live MEDUSDi artifact"
        result["url"]=ORIEL_MEDUSDI_ARTIFACT
    return result

MEDUSDI_UNISWAP_PAIR=os.getenv("MEDUSDI_UNISWAP_PAIR","0xee1a8ace9099257c794a23d2ee2ff6e382e4d72b")
DEXSCREENER_PAIR_URL="https://api.dexscreener.com/latest/dex/pairs/ethereum/{pair}"

def fetch_medusdi_spot(timeout: int = 10) -> dict:
    custom_url=os.getenv("MEDUSDI_SPOT_URL")
    if custom_url:
        return fetch_authenticated_json(custom_url,os.getenv("MEDUSDI_SPOT_TOKEN"),timeout=timeout)

    # Primary source: Oriel's own on-chain/BLS monitor artifact.
    oriel=fetch_authenticated_json(ORIEL_MEDUSDI_ARTIFACT,timeout=timeout)
    if oriel.get("status")=="live":
        payload=oriel.get("payload") or {}
        spot=payload.get("spot") or {}
        ref=payload.get("reference") or {}
        basis=payload.get("basis") or {}
        quality=payload.get("quality") or {}
        if spot.get("price") is not None:
            return {
                "status":"live",
                "source":"Oriel live MEDUSDi artifact",
                "pair_address":spot.get("pool_address") or MEDUSDI_UNISWAP_PAIR,
                "price_native":spot.get("price"),
                "quote":spot.get("quote","USDi"),
                "reference_value":ref.get("value"),
                "reference_source":ref.get("source"),
                "basis_pct":basis.get("pct"),
                "quality_status":quality.get("status"),
                "quality_flags":quality.get("flags") or [],
                "as_of":spot.get("as_of") or ref.get("as_of"),
                "contracts":payload.get("contracts") or {},
            }

    # Fallback: public market-data API for the known Uniswap v3 pool.
    try:
        resp=requests.get(DEXSCREENER_PAIR_URL.format(pair=MEDUSDI_UNISWAP_PAIR),timeout=timeout)
        resp.raise_for_status()
        payload=resp.json()
        pairs=payload.get("pairs") or []
        if not pairs:
            return {"status":"error","error":"No MEDUSDi Uniswap pair returned","pair":MEDUSDI_UNISWAP_PAIR}
        pair=pairs[0]
        return {
            "status":"live",
            "source":"DexScreener / Uniswap v3",
            "pair_address":pair.get("pairAddress",MEDUSDI_UNISWAP_PAIR),
            "dex_id":pair.get("dexId"),
            "base_token":pair.get("baseToken"),
            "quote_token":pair.get("quoteToken"),
            "price_native":pair.get("priceNative"),
            "price_usd":pair.get("priceUsd"),
            "liquidity_usd":(pair.get("liquidity") or {}).get("usd"),
            "volume":pair.get("volume") or {},
            "txns":pair.get("txns") or {},
            "url":pair.get("url"),
        }
    except Exception as exc:
        return {"status":"error","error":str(exc),"pair":MEDUSDI_UNISWAP_PAIR}

KALSHI_PROD_BASE="https://external-api.kalshi.com/trade-api/v2"
KALSHI_DEMO_BASE="https://external-api.demo.kalshi.co/trade-api/v2"

def _normalize_pem(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("\\n","\n").strip()

def kalshi_sign(private_key_pem: str, timestamp: str, method: str, full_path: str) -> str:
    private_key=serialization.load_pem_private_key(
        _normalize_pem(private_key_pem).encode("utf-8"),
        password=None,
    )
    path_without_query=full_path.split("?")[0]
    message=f"{timestamp}{method.upper()}{path_without_query}".encode("utf-8")
    signature=private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")

def _kalshi_get(path: str, api_key_id: str, private_key_pem: str, base_url: str, params: dict | None = None, timeout: int = 10) -> dict:
    timestamp=str(int(time.time()*1000))
    sign_path=urlparse(base_url+path).path
    signature=kalshi_sign(private_key_pem,timestamp,"GET",sign_path)
    headers={
        "KALSHI-ACCESS-KEY":api_key_id,
        "KALSHI-ACCESS-SIGNATURE":signature,
        "KALSHI-ACCESS-TIMESTAMP":timestamp,
    }
    resp=requests.get(base_url+path,headers=headers,params=params or {},timeout=timeout)
    if resp.status_code>=400:
        detail=resp.text[:500]
        raise RuntimeError(f"Kalshi HTTP {resp.status_code}: {detail}")
    return resp.json()

def fetch_kalshi_clearer_state(
    api_key_id: str | None = None,
    private_key_pem: str | None = None,
    environment: str | None = None,
    subaccount: int | None = None,
    timeout: int = 10,
) -> dict:
    api_key_id=api_key_id or os.getenv("KALSHI_API_KEY_ID")
    private_key_pem=private_key_pem or os.getenv("KALSHI_PRIVATE_KEY")
    environment=(environment or os.getenv("KALSHI_ENV","production")).lower()
    subaccount=int(subaccount if subaccount is not None else os.getenv("KALSHI_SUBACCOUNT","0"))
    if not api_key_id or not private_key_pem:
        return {
            "status":"not_connected",
            "provider":"Kalshi",
            "environment":environment,
            "subaccount":subaccount,
            "error":"KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY are not configured",
        }
    base_url=KALSHI_DEMO_BASE if environment=="demo" else KALSHI_PROD_BASE
    try:
        balance=_kalshi_get(
            "/portfolio/balance",api_key_id,private_key_pem,base_url,
            params={"subaccount":subaccount},timeout=timeout,
        )
        positions=_kalshi_get(
            "/portfolio/positions",api_key_id,private_key_pem,base_url,
            params={"subaccount":subaccount,"limit":1000,"count_filter":"position"},timeout=timeout,
        )
        market_positions=positions.get("market_positions") or []
        gross_exposure=sum(float(p.get("market_exposure_dollars") or 0) for p in market_positions)
        realized_pnl=sum(float(p.get("realized_pnl_dollars") or 0) for p in market_positions)
        fees_paid=sum(float(p.get("fees_paid_dollars") or 0) for p in market_positions)
        return {
            "status":"live",
            "provider":"Kalshi",
            "environment":environment,
            "subaccount":subaccount,
            "available_balance_dollars":float(balance.get("balance_dollars") or (float(balance.get("balance",0))/100.0)),
            "portfolio_value_dollars":float(balance.get("portfolio_value",0))/100.0,
            "updated_ts":balance.get("updated_ts"),
            "balance_breakdown":balance.get("balance_breakdown") or [],
            "market_positions":market_positions,
            "event_positions":positions.get("event_positions") or [],
            "gross_market_exposure_dollars":gross_exposure,
            "realized_pnl_dollars":realized_pnl,
            "fees_paid_dollars":fees_paid,
        }
    except Exception as exc:
        return {
            "status":"error",
            "provider":"Kalshi",
            "environment":environment,
            "subaccount":subaccount,
            "error":str(exc),
        }

def fetch_venue_collateral() -> dict:
    return fetch_kalshi_clearer_state()
