from __future__ import annotations
import pandas as pd

CARE_HRV_01 = {
    "name": "CARE-HRV-01 · Healthcare Event Risk Vault 2027",
    "mandate": "Diversified institutional risk capacity for objectively settled U.S. healthcare event markets.",
    "target_capital": 10_000_000.0,
    "single_event_limit": 0.125,
    "family_limit": 0.30,
    "geography_limit": 0.25,
}

SAMPLE_PORTFOLIO = pd.DataFrame([
    {"position":"Texas respiratory utilization","risk_family":"Respiratory Utilization","geography":"Texas","source":"CDC NSSP / FluView","notional":1_000_000.0,"price":0.43,"model_probability":0.36,"capital_at_risk":570_000.0},
    {"position":"National influenza ED utilization","risk_family":"Respiratory Utilization","geography":"National","source":"CDC NSSP / FluView","notional":900_000.0,"price":0.39,"model_probability":0.33,"capital_at_risk":549_000.0},
    {"position":"Healthcare services PPI shock","risk_family":"Healthcare Inflation","geography":"National","source":"BLS","notional":1_250_000.0,"price":0.31,"model_probability":0.24,"capital_at_risk":862_500.0},
    {"position":"Medical CPI acceleration","risk_family":"Healthcare Inflation","geography":"National","source":"BLS","notional":1_000_000.0,"price":0.34,"model_probability":0.27,"capital_at_risk":660_000.0},
    {"position":"Medicare reimbursement shortfall","risk_family":"Reimbursement","geography":"National","source":"CMS","notional":900_000.0,"price":0.29,"model_probability":0.22,"capital_at_risk":639_000.0},
    {"position":"Specialty-drug utilization shock","risk_family":"Pharmacy / Specialty","geography":"National","source":"Public print TBD","notional":700_000.0,"price":0.35,"model_probability":0.28,"capital_at_risk":455_000.0},
])

def portfolio_metrics(portfolio: pd.DataFrame, target_capital: float) -> dict[str,float]:
    deployed=float(portfolio["capital_at_risk"].sum())
    available=max(target_capital-deployed,0.0)
    weights=portfolio["capital_at_risk"]/deployed if deployed else 0.0
    weighted_probability=float((weights*portfolio["model_probability"]).sum()) if deployed else 0.0
    expected_pnl=float(((portfolio["price"]-portfolio["model_probability"])*portfolio["notional"]).sum())
    indicative_yield=expected_pnl/deployed if deployed else 0.0
    return {"deployed":deployed,"available":available,"weighted_probability":weighted_probability,"indicative_yield":indicative_yield}

def _basis_charge(grade:str)->float:
    return {"A":0.005,"A-":0.008,"B+":0.015,"B":0.020,"B-":0.027,"C+":0.035}.get(grade,0.020)

def capacity_quote(portfolio:pd.DataFrame,vault:dict,requested_notional:float,market_probability:float,risk_family:str,geography:str,tenor_months:int,basis_grade:str)->dict:
    nav=float(vault["target_capital"])
    deployed=float(portfolio["capital_at_risk"].sum())
    available=max(nav-deployed,0.0)
    family_cap=nav*float(vault["family_limit"])
    geo_cap=nav*float(vault["geography_limit"])
    event_cap=nav*float(vault["single_event_limit"])
    family_used=float(portfolio.loc[portfolio["risk_family"]==risk_family,"capital_at_risk"].sum())
    geo_used=float(portfolio.loc[portfolio["geography"]==geography,"capital_at_risk"].sum())
    uncertainty=0.020
    duration=min(0.004*tenor_months,0.050)
    basis=_basis_charge(basis_grade)
    family_pressure=family_used/family_cap if family_cap else 1.0
    geo_pressure=geo_used/geo_cap if geo_cap else 1.0
    concentration=0.005+0.0125*max(family_pressure,geo_pressure)
    minimum_price=min(market_probability+uncertainty+duration+basis+concentration,0.95)
    capital_fraction=1.0-minimum_price
    limits=[
        requested_notional,
        event_cap/capital_fraction,
        max(family_cap-family_used,0.0)/capital_fraction,
        max(geo_cap-geo_used,0.0)/capital_fraction,
        available/capital_fraction,
    ]
    eligible=max(0.0,min(limits))
    consumed=eligible*capital_fraction
    if eligible<=0: decision="DECLINED"
    elif eligible+1<requested_notional: decision="PARTIAL"
    else: decision="APPROVED"
    return {
        "decision":decision,"eligible_capacity":eligible,"minimum_price":minimum_price,
        "capital_consumed":consumed,
        "post_family_concentration":(family_used+consumed)/nav,
        "post_geo_concentration":(geo_used+consumed)/nav,
        "market_probability":market_probability,"uncertainty_charge":uncertainty,
        "duration_charge":duration,"basis_charge":basis,"concentration_charge":concentration,
    }
