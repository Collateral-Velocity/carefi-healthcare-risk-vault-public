from __future__ import annotations

from dataclasses import dataclass
import math
import pandas as pd

ROUTER_VERSION="CCR-2.0.0"

BASIS_RANK={"A":6,"A-":5,"B+":4,"B":3,"B-":2,"C+":1}
BASIS_CHARGE={"A":0.005,"A-":0.008,"B+":0.015,"B":0.020,"B-":0.027,"C+":0.035}

DEFAULT_ASSUMPTIONS={
    "uncertainty_charge":0.020,
    "duration_monthly_charge":0.004,
    "duration_cap":0.050,
    "capital_hurdle_annual":0.080,
    "collateral_funding_spread_annual":0.025,
    "correlation_charge_max":0.020,
    "concentration_charge_max":0.030,
    "hedge_execution_cost":0.004,
    "hedge_risk_credit":0.006,
    "chunk_notional":50000.0,
}

FAMILY_REPRESENTATIVE={
    "Respiratory Utilization":0,
    "Healthcare Inflation":2,
    "Reimbursement":4,
    "Pharmacy / Specialty":5,
}

HEDGE_RATIO={"Required":0.75,"Permitted":0.50,"Limited":0.25,"None":0.0}

def _eligible(pool,payload):
    family=str(payload["risk_family"])
    geography=str(payload["geography"])
    grade=str(payload["basis_grade"])
    if family not in pool["eligible_families"]:
        return False,"Risk family outside mandate"
    if geography not in pool["geographies"]:
        return False,"Geography outside mandate"
    if BASIS_RANK.get(grade,0)<BASIS_RANK.get(str(pool.get("minimum_basis_grade")),0):
        return False,"Basis grade below pool minimum"
    return True,"Eligible"

def _portfolio_family_concentration(portfolio,total_capital,family):
    if portfolio is None or portfolio.empty or total_capital<=0:
        return 0.0
    x=portfolio[portfolio["risk_family"]==family]["capital_at_risk"].sum()
    return float(x)/float(total_capital)

def _portfolio_geo_concentration(portfolio,total_capital,geo):
    if portfolio is None or portfolio.empty or total_capital<=0:
        return 0.0
    x=portfolio[portfolio["geography"]==geo]["capital_at_risk"].sum()
    return float(x)/float(total_capital)

def _average_positive_correlation(payload,portfolio,corr):
    if corr is None or len(corr)==0 or portfolio is None or portfolio.empty:
        return 0.0
    family=str(payload["risk_family"])
    idx=FAMILY_REPRESENTATIVE.get(family)
    if idx is None or idx>=len(corr):
        return 0.0
    weights=portfolio["capital_at_risk"].astype(float).to_numpy()
    if weights.sum()<=0:
        return 0.0
    row=corr[idx,:len(weights)]
    positive=[max(float(x),0.0) for x in row]
    return float(sum(w*c for w,c in zip(weights,positive))/weights.sum())

def marginal_quote(pool,payload,allocated_so_far,portfolio=None,corr=None,assumptions=None):
    a={**DEFAULT_ASSUMPTIONS,**(assumptions or {})}
    ok,reason=_eligible(pool,payload)
    if not ok:
        return {"eligible":False,"reason":reason,"pool_id":pool["pool_id"]}

    p=float(payload["model_probability"])
    tenor=float(payload["tenor_months"])
    grade=str(payload["basis_grade"])
    family=str(payload["risk_family"])
    geo=str(payload["geography"])
    target=float(pool["target_capital"])
    available=float(pool["available_capacity"])
    event_limit=target*float(pool["single_event_limit"])
    remaining_capacity=max(available-float(allocated_so_far),0.0)

    base_probability=p
    uncertainty=float(a["uncertainty_charge"])
    basis=float(BASIS_CHARGE.get(grade,0.020))
    duration=min(float(a["duration_monthly_charge"])*tenor,float(a["duration_cap"]))

    pre_price=min(max(base_probability+uncertainty+basis+duration+float(pool.get("price_adjustment",0.0)),0.01),0.95)
    collateral_fraction=max(1.0-pre_price,0.0)

    capital_charge=collateral_fraction*float(a["capital_hurdle_annual"])*(tenor/12.0)

    corr_level=_average_positive_correlation(payload,portfolio,corr)
    utilization=(float(allocated_so_far)/target) if target else 0.0
    correlation_charge=float(a["correlation_charge_max"])*corr_level*(0.50+0.50*min(utilization/0.20,1.0))

    if pool["pool_id"]=="CARE-HRV-01":
        family_pre=_portfolio_family_concentration(portfolio,target,family)
        geo_pre=_portfolio_geo_concentration(portfolio,target,geo)
    else:
        family_pre=float(pool.get("existing_family_concentration",0.0))
        geo_pre=float(pool.get("existing_geo_concentration",0.0))

    marginal_capital=collateral_fraction*float(a["chunk_notional"])
    post_family=family_pre+(marginal_capital/target if target else 0.0)+(float(allocated_so_far)*collateral_fraction/target if target else 0.0)
    post_geo=geo_pre+(marginal_capital/target if target else 0.0)+(float(allocated_so_far)*collateral_fraction/target if target else 0.0)

    family_limit=float(pool.get("family_limit",0.30))
    geo_limit=float(pool.get("geography_limit",0.25))
    family_pressure=max(post_family-family_limit*0.70,0.0)/max(family_limit*0.30,1e-9)
    geo_pressure=max(post_geo-geo_limit*0.70,0.0)/max(geo_limit*0.30,1e-9)
    concentration_pressure=min(max(family_pressure,geo_pressure),1.0)
    concentration_charge=float(a["concentration_charge_max"])*concentration_pressure

    collateral_cost=collateral_fraction*float(a["collateral_funding_spread_annual"])*(tenor/12.0)

    hedge_ratio=HEDGE_RATIO.get(str(pool.get("medusdi_policy","None")),0.0)
    healthcare_beta=float(payload.get("healthcare_beta",0.0))
    hedge_cost=healthcare_beta*hedge_ratio*float(a["hedge_execution_cost"])
    hedge_credit=healthcare_beta*hedge_ratio*float(a["hedge_risk_credit"])
    hedge_net=hedge_cost-hedge_credit

    minimum_price=base_probability+uncertainty+basis+duration+float(pool.get("price_adjustment",0.0))+capital_charge+correlation_charge+concentration_charge+collateral_cost+hedge_net
    minimum_price=min(max(minimum_price,0.01),0.95)
    collateral_fraction=max(1.0-minimum_price,0.0)
    capacity_by_event_limit=event_limit/collateral_fraction if collateral_fraction>0 else 0.0
    max_notional=max(min(remaining_capacity,capacity_by_event_limit-float(allocated_so_far)),0.0)

    hard_concentration_breach=post_family>family_limit*1.05 or post_geo>geo_limit*1.05
    if hard_concentration_breach:
        max_notional=0.0
        reason="Concentration hard limit"

    return {
        "eligible":max_notional>0,
        "reason":reason,
        "pool_id":pool["pool_id"],
        "pool_name":pool["name"],
        "minimum_price":minimum_price,
        "max_notional":max_notional,
        "collateral_fraction":collateral_fraction,
        "healthcare_beta":healthcare_beta,
        "hedge_ratio":hedge_ratio,
        "cost_stack":{
            "base_probability":base_probability,
            "uncertainty":uncertainty,
            "basis":basis,
            "duration":duration,
            "pool_adjustment":float(pool.get("price_adjustment",0.0)),
            "marginal_capital":capital_charge,
            "correlation":correlation_charge,
            "concentration":concentration_charge,
            "collateral_funding":collateral_cost,
            "hedge_execution":hedge_cost,
            "hedge_credit":-hedge_credit,
        },
        "diagnostics":{
            "average_positive_correlation":corr_level,
            "family_concentration":post_family,
            "geography_concentration":post_geo,
            "pool_utilization":(float(allocated_so_far)/target) if target else 0.0,
        },
    }

def optimize_capacity(payload,pools,portfolio=None,corr=None,assumptions=None):
    a={**DEFAULT_ASSUMPTIONS,**(assumptions or {})}
    requested=float(payload["requested_notional"])
    chunk=max(min(float(a["chunk_notional"]),requested),10000.0)
    allocated={p["pool_id"]:0.0 for p in pools}
    steps=[]
    remaining=requested

    while remaining>1:
        candidates=[]
        for pool in pools:
            q=marginal_quote(pool,payload,allocated[pool["pool_id"]],portfolio,corr,a)
            if q.get("eligible") and q.get("max_notional",0)>0:
                candidates.append(q)
        if not candidates:
            break
        winner=min(candidates,key=lambda x:(x["minimum_price"],-x["max_notional"]))
        amount=min(chunk,remaining,float(winner["max_notional"]))
        if amount<=0:
            break
        steps.append({**winner,"allocated_notional":amount})
        allocated[winner["pool_id"]]+=amount
        remaining-=amount

    allocations=[]
    for pool in pools:
        pid=pool["pool_id"]
        pool_steps=[s for s in steps if s["pool_id"]==pid]
        amount=sum(s["allocated_notional"] for s in pool_steps)
        if amount<=0:
            continue
        weighted_price=sum(s["allocated_notional"]*s["minimum_price"] for s in pool_steps)/amount
        keys=list(pool_steps[0]["cost_stack"].keys())
        stack={k:sum(s["allocated_notional"]*s["cost_stack"][k] for s in pool_steps)/amount for k in keys}
        last=pool_steps[-1]
        hedge_notional=amount*float(payload.get("healthcare_beta",0.0))*float(last["hedge_ratio"])
        allocations.append({
            "pool_id":pid,
            "pool_name":pool["name"],
            "allocated_notional":amount,
            "minimum_price":weighted_price,
            "marginal_last_price":last["minimum_price"],
            "allocated_medusdi_hedge":hedge_notional,
            "cost_stack":stack,
            "diagnostics":last["diagnostics"],
            "decision":"APPROVED" if amount>=requested-1 else "PARTIAL",
            "reason":"Optimized marginal allocation",
        })

    assembled=requested-max(remaining,0.0)
    blended=sum(a1["allocated_notional"]*a1["minimum_price"] for a1 in allocations)/assembled if assembled else 0.0
    quotes=[]
    for pool in pools:
        q=marginal_quote(pool,payload,0.0,portfolio,corr,a)
        quotes.append({
            "pool_id":pool["pool_id"],"pool_name":pool["name"],
            "decision":"APPROVED" if q.get("eligible") else "INELIGIBLE",
            "reason":q.get("reason"),
            "eligible_capacity":q.get("max_notional",0.0),
            "minimum_price":q.get("minimum_price"),
            "medusdi_hedge":q.get("max_notional",0.0)*float(payload.get("healthcare_beta",0.0))*float(q.get("hedge_ratio",0.0)),
            "cost_stack":q.get("cost_stack",{}),
        })

    return {
        "router_version":ROUTER_VERSION,
        "objective":"Minimize marginal all-in capacity cost subject to mandate, basis, geography, event, concentration and available-capacity constraints.",
        "quotes":quotes,
        "allocations":allocations,
        "steps":steps,
        "requested_notional":requested,
        "assembled_capacity":assembled,
        "unfilled":max(remaining,0.0),
        "blended_price":blended,
        "blended_medusdi_hedge":sum(x["allocated_medusdi_hedge"] for x in allocations),
        "fill_ratio":assembled/requested if requested else 0.0,
        "assumptions":a,
    }
