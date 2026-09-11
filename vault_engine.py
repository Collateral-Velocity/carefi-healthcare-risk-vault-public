from __future__ import annotations
import copy
import json
import pandas as pd
import numpy as np
from statistics import NormalDist

CARE_HRV_01 = {
    "name": "CARE-HRV-01 · Healthcare Event Risk Vault 2027",
    "mandate": "Diversified institutional risk capacity for objectively settled U.S. healthcare event markets.",
    "target_capital": 10_000_000.0,
    "single_event_limit": 0.125,
    "family_limit": 0.30,
    "geography_limit": 0.25,
}

ORIEL_TEXAS_RESPIRATORY = {
    "contract_id": "ORIEL-HC-TX-FLU-2027-01",
    "source": "Oriel Healthcare Event Risk Workbench",
    "title": "Texas influenza ED-utilization seasonal touch",
    "risk_family": "Respiratory Utilization",
    "geography": "Texas",
    "public_print": "CDC NSSP / FluView",
    "trigger": "Influenza ED-visit percentage meets or exceeds the selected threshold during the defined 2027–28 respiratory-season window.",
    "window_start": "2027-10-09",
    "window_end": "2028-05-20",
    "model_probability": 0.36,
    "requested_notional": 1_000_000.0,
    "tenor_months": 8,
    "basis_grade": "B+",
    "oriel_reference_version": "HERW 0.3.0",
}

SAMPLE_PORTFOLIO = pd.DataFrame([
    {"position":"Texas respiratory utilization","risk_family":"Respiratory Utilization","geography":"Texas","source":"CDC NSSP / FluView","notional":1_000_000.0,"price":0.43,"model_probability":0.36,"capital_at_risk":570_000.0},
    {"position":"National influenza ED utilization","risk_family":"Respiratory Utilization","geography":"National","source":"CDC NSSP / FluView","notional":900_000.0,"price":0.39,"model_probability":0.33,"capital_at_risk":549_000.0},
    {"position":"Healthcare services PPI shock","risk_family":"Healthcare Inflation","geography":"National","source":"BLS","notional":1_250_000.0,"price":0.31,"model_probability":0.24,"capital_at_risk":862_500.0},
    {"position":"Medical CPI acceleration","risk_family":"Healthcare Inflation","geography":"National","source":"BLS","notional":1_000_000.0,"price":0.34,"model_probability":0.27,"capital_at_risk":660_000.0},
    {"position":"Medicare reimbursement shortfall","risk_family":"Reimbursement","geography":"National","source":"CMS","notional":900_000.0,"price":0.29,"model_probability":0.22,"capital_at_risk":639_000.0},
    {"position":"Specialty-drug utilization shock","risk_family":"Pharmacy / Specialty","geography":"National","source":"Public print TBD","notional":700_000.0,"price":0.35,"model_probability":0.28,"capital_at_risk":455_000.0},
])

REQUIRED_ORIEL_FIELDS = [
    "contract_id","title","risk_family","geography","public_print",
    "model_probability","requested_notional","tenor_months","basis_grade"
]

def portfolio_metrics(portfolio: pd.DataFrame, target_capital: float) -> dict[str,float]:
    deployed=float(portfolio["capital_at_risk"].sum())
    available=max(target_capital-deployed,0.0)
    weights=portfolio["capital_at_risk"]/deployed if deployed else 0.0
    weighted_probability=float((weights*portfolio["model_probability"]).sum()) if deployed else 0.0
    expected_pnl=float(((portfolio["price"]-portfolio["model_probability"])*portfolio["notional"]).sum())
    indicative_yield=expected_pnl/deployed if deployed else 0.0
    return {"deployed":deployed,"available":available,"weighted_probability":weighted_probability,"indicative_yield":indicative_yield,"expected_pnl":expected_pnl}

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

def validate_oriel_payload(payload: dict) -> tuple[bool,list[str]]:
    missing=[k for k in REQUIRED_ORIEL_FIELDS if k not in payload]
    if missing:
        return False, missing
    p=float(payload["model_probability"])
    n=float(payload["requested_notional"])
    t=int(payload["tenor_months"])
    if not 0 < p < 1 or n <= 0 or t <= 0:
        return False, ["invalid_numeric_values"]
    return True, []

def parse_oriel_json(raw: str) -> dict:
    payload=json.loads(raw)
    ok, errors=validate_oriel_payload(payload)
    if not ok:
        raise ValueError("Invalid Oriel payload: " + ", ".join(errors))
    return payload

def portfolio_impact(portfolio: pd.DataFrame, vault: dict, payload: dict, quote: dict) -> dict:
    before=portfolio_metrics(portfolio,float(vault["target_capital"]))
    added=float(quote["capital_consumed"])
    eligible=float(quote["eligible_capacity"])
    if eligible <= 0:
        return {"before":before,"after":before,"delta_expected_pnl":0.0}
    row={
        "position":str(payload["title"]),
        "risk_family":str(payload["risk_family"]),
        "geography":str(payload["geography"]),
        "source":str(payload["public_print"]),
        "notional":eligible,
        "price":float(quote["minimum_price"]),
        "model_probability":float(payload["model_probability"]),
        "capital_at_risk":added,
    }
    after_df=pd.concat([portfolio,pd.DataFrame([row])],ignore_index=True)
    after=portfolio_metrics(after_df,float(vault["target_capital"]))
    return {"before":before,"after":after,"delta_expected_pnl":after["expected_pnl"]-before["expected_pnl"]}

def oriel_payload_json() -> str:
    return json.dumps(copy.deepcopy(ORIEL_TEXAS_RESPIRATORY),indent=2)


VAULT_TERMS = {
    "vehicle": "CARE-HRV-01 · Healthcare Event Risk Vault 2027",
    "legal_wrapper": "Single-purpose commodity pool / SPV or equivalent regulated wrapper; final form TBD with counsel and CPO/administrator.",
    "investment_period": "Calendar 2027",
    "base_term": "Through final settlement of approved 2027-originated positions plus orderly wind-down.",
    "liquidity": "No ordinary redemption of capital supporting unresolved event positions; distributions from unencumbered cash at designated windows.",
    "nav_frequency": "Monthly, plus material event-driven updates.",
    "valuation_hierarchy": [
        "Executable representative two-sided venue market",
        "Oriel documented fair-value estimate",
        "Independent administrator / risk-committee fair value",
    ],
    "eligible_sources": ["CDC", "BLS", "CMS", "BEA", "Other pre-approved independent public data sources"],
    "minimum_basis_grade": "B+",
    "leverage": "None assumed in base prototype",
    "loss_waterfall": ["HRV-E", "HRV-M", "HRV-S"],
    "distribution_waterfall": [
        "Operating expenses and reserves",
        "HRV-S entitlement",
        "HRV-M entitlement",
        "Residual to HRV-E",
    ],
    "management_fee": "TBD",
    "performance_fee": "TBD",
    "governance": "Documented risk-committee approval process for live deployment; exceptions recorded and disclosed.",
    "token_role": "Programmable record of economic interest and vault accounting state; not a substitute for the regulated legal wrapper.",
}

ELIGIBILITY_RULES = [
    "Healthcare utilization, medical-cost, reimbursement, healthcare-inflation, pharmacy/specialty-drug, or closely related healthcare-economic exposure.",
    "Objective, independently published public print or rule-based observable.",
    "Unambiguous observation window, publication source, revision policy and fallback.",
    "Executable on an approved venue or through an approved regulated structure.",
    "Independently valuable by Oriel or another approved administrator/reference process.",
    "Passes CareFi underwriting for basis risk, probability, economics, duration and concentration.",
]

INELIGIBLE_RULES = [
    "Discretionary claims determinations as the settlement trigger.",
    "Non-public client data as the sole settlement source.",
    "Unresolved legal enforceability or ambiguous settlement terms.",
    "No defined source-disruption fallback.",
    "Settlement materially controlled by the protection buyer or seller.",
]


WATERFALL_DEFAULTS = {
    "equity_pct": 0.20,
    "mezz_pct": 0.30,
    "senior_pct": 0.50,
    "senior_pref": 0.06,
    "mezz_pref": 0.10,
    "gross_income_rate": 0.12,
    "expense_rate": 0.01,
    "scenarios": {
        "Mild": 0.08,
        "Moderate": 0.30,
        "Severe": 0.60,
    },
}

def _allocate_loss(amount: float, balances: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    """Allocate portfolio losses first to Equity, then Mezzanine, then Senior."""
    remaining=max(float(amount),0.0)
    losses={"HRV-E":0.0,"HRV-M":0.0,"HRV-S":0.0}
    ending=balances.copy()
    for tranche in ["HRV-E","HRV-M","HRV-S"]:
        hit=min(ending[tranche],remaining)
        losses[tranche]=hit
        ending[tranche]-=hit
        remaining-=hit
    return losses, ending

def waterfall_simulation(
    total_capital: float,
    portfolio_loss_pct: float,
    equity_pct: float,
    mezz_pct: float,
    senior_pct: float,
    senior_pref: float,
    mezz_pref: float,
    gross_income_rate: float,
    expense_rate: float,
) -> dict:
    """Illustrative annual waterfall: principal losses E→M→S; distributable income expenses→S pref→M pref→E residual."""
    weights=[float(equity_pct),float(mezz_pct),float(senior_pct)]
    if any(x < 0 for x in weights) or abs(sum(weights)-1.0) > 1e-6:
        raise ValueError("Tranche percentages must sum to 100%.")
    total=float(total_capital)
    balances={
        "HRV-E": total*equity_pct,
        "HRV-M": total*mezz_pct,
        "HRV-S": total*senior_pct,
    }
    portfolio_loss=total*max(float(portfolio_loss_pct),0.0)
    principal_losses, ending_principal=_allocate_loss(portfolio_loss,balances)

    gross_income=total*max(float(gross_income_rate),0.0)
    expenses=total*max(float(expense_rate),0.0)
    distributable=max(gross_income-expenses,0.0)

    senior_pref_due=balances["HRV-S"]*max(float(senior_pref),0.0)
    mezz_pref_due=balances["HRV-M"]*max(float(mezz_pref),0.0)
    distributions={"HRV-S":0.0,"HRV-M":0.0,"HRV-E":0.0}

    distributions["HRV-S"]=min(distributable,senior_pref_due)
    distributable-=distributions["HRV-S"]
    distributions["HRV-M"]=min(distributable,mezz_pref_due)
    distributable-=distributions["HRV-M"]
    distributions["HRV-E"]=max(distributable,0.0)

    rows=[]
    for tranche in ["HRV-E","HRV-M","HRV-S"]:
        begin=balances[tranche]
        loss=principal_losses[tranche]
        end=ending_principal[tranche]
        dist=distributions[tranche]
        total_value=end+dist
        net_pnl=total_value-begin
        net_return=(net_pnl/begin) if begin else 0.0
        principal_loss_pct=(loss/begin) if begin else 0.0
        rows.append({
            "tranche":tranche,
            "beginning_capital":begin,
            "principal_loss":loss,
            "principal_loss_pct":principal_loss_pct,
            "ending_principal":end,
            "cash_distribution":dist,
            "ending_value_plus_distribution":total_value,
            "net_pnl":net_pnl,
            "net_return":net_return,
        })

    return {
        "total_capital":total,
        "portfolio_loss":portfolio_loss,
        "portfolio_loss_pct":portfolio_loss_pct,
        "gross_income":gross_income,
        "expenses":expenses,
        "net_income_before_waterfall":max(gross_income-expenses,0.0),
        "unallocated_loss":max(portfolio_loss-total,0.0),
        "rows":rows,
    }

def waterfall_scenarios(
    total_capital: float,
    equity_pct: float,
    mezz_pct: float,
    senior_pct: float,
    senior_pref: float,
    mezz_pref: float,
    gross_income_rate: float,
    expense_rate: float,
    scenarios: dict[str,float] | None = None,
) -> pd.DataFrame:
    scenarios=scenarios or WATERFALL_DEFAULTS["scenarios"]
    records=[]
    for name,loss_pct in scenarios.items():
        result=waterfall_simulation(
            total_capital,loss_pct,equity_pct,mezz_pct,senior_pct,
            senior_pref,mezz_pref,gross_income_rate,expense_rate
        )
        for row in result["rows"]:
            records.append({
                "scenario":name,
                "portfolio_loss_pct":loss_pct,
                **row,
            })
    return pd.DataFrame(records)


EVENT_SCENARIO_PRESETS = {
    "Mild": ["Texas respiratory utilization"],
    "Moderate": [
        "Texas respiratory utilization",
        "National influenza ED utilization",
        "Healthcare services PPI shock",
        "Medical CPI acceleration",
    ],
    "Severe": list(SAMPLE_PORTFOLIO["position"]),
}

def event_portfolio_scenario(portfolio: pd.DataFrame, triggered_positions: list[str]) -> dict:
    """Resolve the six-position short-event portfolio for a selected set of triggered events.

    If an event triggers, the modeled loss is capital_at_risk = (1-price) * notional.
    If it does not trigger, the modeled gain is price * notional.
    """
    triggered=set(triggered_positions)
    rows=[]
    gross_trigger_losses=0.0
    gross_nontrigger_gains=0.0
    for _, row in portfolio.iterrows():
        name=str(row["position"])
        is_triggered=name in triggered
        if is_triggered:
            pnl=-float(row["capital_at_risk"])
            gross_trigger_losses+=float(row["capital_at_risk"])
        else:
            pnl=float(row["price"])*float(row["notional"])
            gross_nontrigger_gains+=pnl
        rows.append({
            "position":name,
            "risk_family":str(row["risk_family"]),
            "geography":str(row["geography"]),
            "triggered":is_triggered,
            "notional":float(row["notional"]),
            "price":float(row["price"]),
            "capital_at_risk":float(row["capital_at_risk"]),
            "realized_pnl":pnl,
        })
    net_pnl=gross_nontrigger_gains-gross_trigger_losses
    return {
        "triggered_positions":list(triggered_positions),
        "trigger_count":len(triggered),
        "gross_trigger_losses":gross_trigger_losses,
        "gross_nontrigger_gains":gross_nontrigger_gains,
        "net_pnl":net_pnl,
        "rows":rows,
    }

def waterfall_from_event_scenario(
    total_capital: float,
    event_result: dict,
    equity_pct: float,
    mezz_pct: float,
    senior_pct: float,
    senior_pref: float,
    mezz_pref: float,
    expense_rate: float,
    hedge_pnl: float = 0.0,
) -> dict:
    """Allocate realized six-position portfolio P&L through the CARE-HRV-01 capital stack, optionally including MEDUSDi hedge P&L."""
    weights=[float(equity_pct),float(mezz_pct),float(senior_pct)]
    if any(x < 0 for x in weights) or abs(sum(weights)-1.0) > 1e-6:
        raise ValueError("Tranche percentages must sum to 100%.")
    total=float(total_capital)
    balances={
        "HRV-E":total*equity_pct,
        "HRV-M":total*mezz_pct,
        "HRV-S":total*senior_pct,
    }
    expenses=total*max(float(expense_rate),0.0)
    net_after_expenses=float(event_result["net_pnl"])+float(hedge_pnl)-expenses
    principal_loss=max(-net_after_expenses,0.0)
    distributable=max(net_after_expenses,0.0)

    principal_losses, ending_principal=_allocate_loss(principal_loss,balances)
    senior_pref_due=balances["HRV-S"]*max(float(senior_pref),0.0)
    mezz_pref_due=balances["HRV-M"]*max(float(mezz_pref),0.0)
    distributions={"HRV-S":0.0,"HRV-M":0.0,"HRV-E":0.0}

    distributions["HRV-S"]=min(distributable,senior_pref_due)
    distributable-=distributions["HRV-S"]
    distributions["HRV-M"]=min(distributable,mezz_pref_due)
    distributable-=distributions["HRV-M"]
    distributions["HRV-E"]=max(distributable,0.0)

    rows=[]
    for tranche in ["HRV-E","HRV-M","HRV-S"]:
        begin=balances[tranche]
        loss=principal_losses[tranche]
        end=ending_principal[tranche]
        dist=distributions[tranche]
        total_value=end+dist
        net_pnl=total_value-begin
        rows.append({
            "tranche":tranche,
            "beginning_capital":begin,
            "principal_loss":loss,
            "principal_loss_pct":loss/begin if begin else 0.0,
            "ending_principal":end,
            "cash_distribution":dist,
            "ending_value_plus_distribution":total_value,
            "net_pnl":net_pnl,
            "net_return":net_pnl/begin if begin else 0.0,
        })

    return {
        "total_capital":total,
        "gross_trigger_losses":float(event_result["gross_trigger_losses"]),
        "gross_nontrigger_gains":float(event_result["gross_nontrigger_gains"]),
        "portfolio_net_pnl_before_expenses":float(event_result["net_pnl"]),
        "expenses":expenses,
        "medusdi_hedge_pnl":float(hedge_pnl),
        "net_after_expenses":net_after_expenses,
        "principal_loss":principal_loss,
        "principal_loss_pct":principal_loss/total if total else 0.0,
        "rows":rows,
    }

def event_waterfall_scenarios(
    portfolio: pd.DataFrame,
    total_capital: float,
    equity_pct: float,
    mezz_pct: float,
    senior_pct: float,
    senior_pref: float,
    mezz_pref: float,
    expense_rate: float,
) -> pd.DataFrame:
    records=[]
    for scenario,triggered in EVENT_SCENARIO_PRESETS.items():
        event_result=event_portfolio_scenario(portfolio,triggered)
        waterfall=waterfall_from_event_scenario(
            total_capital,event_result,equity_pct,mezz_pct,senior_pct,
            senior_pref,mezz_pref,expense_rate
        )
        for row in waterfall["rows"]:
            records.append({
                "scenario":scenario,
                "trigger_count":event_result["trigger_count"],
                "gross_trigger_losses":event_result["gross_trigger_losses"],
                "nontrigger_gains":event_result["gross_nontrigger_gains"],
                "portfolio_net_pnl":event_result["net_pnl"],
                "principal_loss_pct":waterfall["principal_loss_pct"],
                **row,
            })
    return pd.DataFrame(records)


MEDUSDI_DEFAULTS = {
    "portfolio_hedge_ratio": 0.50,
    "request_hedge_ratio": 0.70,
    "scenario_returns": {"Mild": 0.03, "Moderate": 0.08, "Severe": 0.15},
}

POSITION_HEALTHCARE_BETA = {
    "Texas respiratory utilization": 0.15,
    "National influenza ED utilization": 0.15,
    "Healthcare services PPI shock": 0.75,
    "Medical CPI acceleration": 0.95,
    "Medicare reimbursement shortfall": 0.45,
    "Specialty-drug utilization shock": 0.65,
}

RISK_FAMILY_HEALTHCARE_BETA = {
    "Respiratory Utilization": 0.15,
    "Healthcare Inflation": 0.85,
    "Reimbursement": 0.45,
    "Pharmacy / Specialty": 0.65,
}

def portfolio_healthcare_beta(portfolio: pd.DataFrame, hedge_ratio: float = 0.0) -> dict:
    """Illustrative healthcare-inflation factor exposure expressed in beta-adjusted dollars."""
    detail=[]
    gross=0.0
    for _, row in portfolio.iterrows():
        beta=float(POSITION_HEALTHCARE_BETA.get(str(row["position"]),0.25))
        exposure=float(row["notional"])*beta
        gross+=exposure
        detail.append({
            "position":str(row["position"]),
            "risk_family":str(row["risk_family"]),
            "notional":float(row["notional"]),
            "healthcare_beta":beta,
            "gross_beta_exposure":exposure,
        })
    ratio=min(max(float(hedge_ratio),0.0),1.0)
    hedge_notional=gross*ratio
    net=max(gross-hedge_notional,0.0)
    return {
        "gross_beta_exposure":gross,
        "medusdi_hedge_notional":hedge_notional,
        "net_beta_exposure":net,
        "hedge_ratio":ratio,
        "detail":detail,
    }

def medusdi_request_hedge(
    eligible_notional: float,
    risk_family: str,
    hedge_ratio: float,
    beta_override: float | None = None,
) -> dict:
    beta=float(beta_override) if beta_override is not None else float(RISK_FAMILY_HEALTHCARE_BETA.get(risk_family,0.25))
    ratio=min(max(float(hedge_ratio),0.0),1.0)
    gross=max(float(eligible_notional),0.0)*beta
    hedge=gross*ratio
    return {
        "healthcare_beta":beta,
        "gross_beta_exposure":gross,
        "medusdi_hedge_notional":hedge,
        "net_beta_exposure":max(gross-hedge,0.0),
        "hedge_ratio":ratio,
    }

def medusdi_hedge_pnl(hedge_notional: float, medusdi_return: float) -> float:
    """Illustrative P&L from a long MEDUSDi hedge."""
    return float(hedge_notional)*float(medusdi_return)


POSITION_MARKS = {
    "Texas respiratory utilization": {"current_mark": 0.39, "settlement_date": "2028-06-30", "status": "Observing", "mark_source": "Oriel modeled fair value"},
    "National influenza ED utilization": {"current_mark": 0.36, "settlement_date": "2028-06-30", "status": "Observing", "mark_source": "Oriel modeled fair value"},
    "Healthcare services PPI shock": {"current_mark": 0.28, "settlement_date": "2028-03-31", "status": "Open", "mark_source": "Oriel modeled fair value"},
    "Medical CPI acceleration": {"current_mark": 0.30, "settlement_date": "2028-02-15", "status": "Open", "mark_source": "Oriel modeled fair value"},
    "Medicare reimbursement shortfall": {"current_mark": 0.25, "settlement_date": "2028-10-01", "status": "Open", "mark_source": "Oriel modeled fair value"},
    "Specialty-drug utilization shock": {"current_mark": 0.32, "settlement_date": "2028-09-30", "status": "Structuring", "mark_source": "Oriel modeled fair value"},
}

TREASURY_ASSUMPTIONS = {
    "liquidity_reserve_pct": 0.05,
    "annual_cash_yield": 0.045,
    "accrued_fee_pct": 0.005,
    "medusdi_cost_basis": 1.0000,
    "medusdi_current_mark": 1.0150,
}

def position_marks(portfolio: pd.DataFrame) -> pd.DataFrame:
    """Modeled live-mark table. Short-YES MTM P&L = (entry price - current mark) * notional."""
    rows=[]
    for _, row in portfolio.iterrows():
        name=str(row["position"])
        meta=POSITION_MARKS.get(name,{})
        current_mark=float(meta.get("current_mark",row["model_probability"]))
        notional=float(row["notional"])
        entry=float(row["price"])
        mtm_pnl=(entry-current_mark)*notional
        rows.append({
            "position":name,
            "risk_family":str(row["risk_family"]),
            "geography":str(row["geography"]),
            "entry_price":entry,
            "oriel_fair_value":current_mark,
            "unrealized_pnl":mtm_pnl,
            "notional":notional,
            "collateral_posted":float(row["capital_at_risk"]),
            "settlement_date":str(meta.get("settlement_date","TBD")),
            "status":str(meta.get("status","Open")),
            "mark_source":str(meta.get("mark_source","Oriel modeled fair value")),
        })
    return pd.DataFrame(rows)

def vault_nav(
    portfolio: pd.DataFrame,
    target_capital: float,
    medusdi_hedge_ratio: float = 0.0,
    liquidity_reserve_pct: float | None = None,
    accrued_fee_pct: float | None = None,
    medusdi_current_mark: float | None = None,
    medusdi_cost_basis: float | None = None,
) -> dict:
    marks=position_marks(portfolio)
    target=float(target_capital)
    posted=float(marks["collateral_posted"].sum())
    event_mtm=float(marks["unrealized_pnl"].sum())
    beta=portfolio_healthcare_beta(portfolio,medusdi_hedge_ratio)
    medusdi_notional=float(beta["medusdi_hedge_notional"])
    cost=float(medusdi_cost_basis if medusdi_cost_basis is not None else TREASURY_ASSUMPTIONS["medusdi_cost_basis"])
    mark=float(medusdi_current_mark if medusdi_current_mark is not None else TREASURY_ASSUMPTIONS["medusdi_current_mark"])
    medusdi_units=medusdi_notional/cost if cost else 0.0
    medusdi_value=medusdi_units*mark
    medusdi_mtm=medusdi_value-medusdi_notional
    reserve_pct=float(liquidity_reserve_pct if liquidity_reserve_pct is not None else TREASURY_ASSUMPTIONS["liquidity_reserve_pct"])
    fee_pct=float(accrued_fee_pct if accrued_fee_pct is not None else TREASURY_ASSUMPTIONS["accrued_fee_pct"])
    reserve=target*reserve_pct
    accrued_fees=target*fee_pct
    unencumbered=max(target-posted-medusdi_notional-reserve,0.0)
    nav=target+event_mtm+medusdi_mtm-accrued_fees
    return {
        "nav":nav,
        "nav_change":nav-target,
        "target_capital":target,
        "event_unrealized_pnl":event_mtm,
        "medusdi_hedge_notional":medusdi_notional,
        "medusdi_value":medusdi_value,
        "medusdi_unrealized_pnl":medusdi_mtm,
        "posted_collateral":posted,
        "liquidity_reserve":reserve,
        "unencumbered_cash":unencumbered,
        "accrued_fees":accrued_fees,
        "marks":marks,
    }

def cash_collateral_dashboard(
    portfolio: pd.DataFrame,
    target_capital: float,
    medusdi_hedge_ratio: float,
    liquidity_reserve_pct: float,
    annual_cash_yield: float,
) -> dict:
    nav=vault_nav(
        portfolio,target_capital,medusdi_hedge_ratio,
        liquidity_reserve_pct=liquidity_reserve_pct,
    )
    cash=nav["unencumbered_cash"]
    annual_yield=cash*max(float(annual_cash_yield),0.0)
    collateral_release=[]
    marks=nav["marks"]
    for _, row in marks.iterrows():
        collateral_release.append({
            "position":row["position"],
            "settlement_date":row["settlement_date"],
            "collateral_expected_to_release":row["collateral_posted"],
            "status":row["status"],
        })
    return {
        **nav,
        "annual_cash_yield_rate":annual_cash_yield,
        "annual_cash_yield":annual_yield,
        "collateral_release":pd.DataFrame(collateral_release),
    }

def _all_event_states(portfolio: pd.DataFrame) -> list[dict]:
    """Exact 2^N independent-event state distribution for the current small portfolio."""
    positions=list(portfolio["position"])
    n=len(positions)
    states=[]
    for mask in range(1 << n):
        triggered=[]
        probability=1.0
        for i,(_,row) in enumerate(portfolio.iterrows()):
            p=float(row["model_probability"])
            hit=bool(mask & (1 << i))
            probability*=p if hit else (1.0-p)
            if hit:
                triggered.append(str(row["position"]))
        result=event_portfolio_scenario(portfolio,triggered)
        states.append({
            "probability":probability,
            "triggered":triggered,
            "trigger_count":len(triggered),
            "net_pnl":float(result["net_pnl"]),
            "gross_trigger_losses":float(result["gross_trigger_losses"]),
            "nontrigger_gains":float(result["gross_nontrigger_gains"]),
        })
    return states

def expected_loss_analytics(
    portfolio: pd.DataFrame,
    total_capital: float,
    equity_pct: float = 0.20,
    mezz_pct: float = 0.30,
    senior_pct: float = 0.50,
    expense_rate: float = 0.01,
) -> dict:
    """Exact independent-event expected loss and tranche impairment analytics across all 64 states."""
    states=_all_event_states(portfolio)
    total=float(total_capital)
    expected_portfolio_pnl=sum(s["probability"]*s["net_pnl"] for s in states)
    loss_states=[]
    tranche_stats={t:{"expected_loss":0.0,"impairment_probability":0.0,"wipeout_probability":0.0} for t in ["HRV-E","HRV-M","HRV-S"]}
    for s in states:
        result=waterfall_from_event_scenario(
            total,s,equity_pct,mezz_pct,senior_pct,0.0,0.0,expense_rate,hedge_pnl=0.0
        )
        loss=float(result["principal_loss"])
        loss_states.append((loss,s["probability"]))
        for row in result["rows"]:
            t=row["tranche"]
            pl=float(row["principal_loss"])
            begin=float(row["beginning_capital"])
            tranche_stats[t]["expected_loss"]+=s["probability"]*pl
            if pl > 0:
                tranche_stats[t]["impairment_probability"]+=s["probability"]
            if begin > 0 and pl >= begin-1e-9:
                tranche_stats[t]["wipeout_probability"]+=s["probability"]
    loss_states=sorted(loss_states,key=lambda x:x[0])
    def quantile(q: float) -> float:
        c=0.0
        for loss,p in loss_states:
            c+=p
            if c>=q:
                return loss
        return loss_states[-1][0] if loss_states else 0.0
    expected_principal_loss=sum(loss*p for loss,p in loss_states)
    for t,stats in tranche_stats.items():
        denom={"HRV-E":total*equity_pct,"HRV-M":total*mezz_pct,"HRV-S":total*senior_pct}[t]
        stats["expected_loss_pct"]=stats["expected_loss"]/denom if denom else 0.0
    return {
        "expected_portfolio_pnl":expected_portfolio_pnl,
        "expected_principal_loss":expected_principal_loss,
        "expected_principal_loss_pct":expected_principal_loss/total if total else 0.0,
        "var95_loss":quantile(0.95),
        "var99_loss":quantile(0.99),
        "var95_pct":quantile(0.95)/total if total else 0.0,
        "var99_pct":quantile(0.99)/total if total else 0.0,
        "tranches":tranche_stats,
        "state_count":len(states),
        "assumption":"Independent Bernoulli events using current modeled probabilities; no correlation adjustment.",
    }


CORRELATION_BASE = np.array([
    [1.00, 0.75, 0.15, 0.15, 0.10, 0.10],
    [0.75, 1.00, 0.15, 0.15, 0.10, 0.10],
    [0.15, 0.15, 1.00, 0.70, 0.35, 0.30],
    [0.15, 0.15, 0.70, 1.00, 0.40, 0.40],
    [0.10, 0.10, 0.35, 0.40, 1.00, 0.30],
    [0.10, 0.10, 0.30, 0.40, 0.30, 1.00],
], dtype=float)

def _nearest_correlation(matrix: np.ndarray) -> np.ndarray:
    """Project a symmetric matrix to a stable positive-semidefinite correlation matrix."""
    a=(matrix+matrix.T)/2.0
    vals,vecs=np.linalg.eigh(a)
    vals=np.clip(vals,1e-6,None)
    psd=vecs @ np.diag(vals) @ vecs.T
    d=np.sqrt(np.clip(np.diag(psd),1e-12,None))
    corr=psd/np.outer(d,d)
    np.fill_diagonal(corr,1.0)
    return np.clip(corr,-0.95,1.0)

def joint_loss_correlation_matrix(scale: float = 1.0) -> np.ndarray:
    """Latent Gaussian-factor correlation matrix. Scale changes off-diagonal dependence."""
    s=max(float(scale),0.0)
    m=CORRELATION_BASE.copy()
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            if i != j:
                m[i,j]=np.clip(m[i,j]*s,-0.95,0.95)
    np.fill_diagonal(m,1.0)
    return _nearest_correlation(m)

def correlation_matrix_frame(portfolio: pd.DataFrame, scale: float = 1.0) -> pd.DataFrame:
    corr=joint_loss_correlation_matrix(scale)
    labels=[
        "TX Respiratory",
        "National Flu",
        "HC Services PPI",
        "Medical CPI",
        "Medicare Reimb.",
        "Specialty Drug",
    ]
    if len(portfolio) != len(labels):
        labels=[str(x)[:18] for x in portfolio["position"]]
    return pd.DataFrame(corr,index=labels,columns=labels)

def correlated_loss_analytics(
    portfolio: pd.DataFrame,
    total_capital: float,
    equity_pct: float = 0.20,
    mezz_pct: float = 0.30,
    senior_pct: float = 0.50,
    expense_rate: float = 0.01,
    correlation_scale: float = 1.0,
    simulations: int = 30000,
    seed: int = 202709,
) -> dict:
    """Gaussian-copula joint trigger simulation preserving each modeled marginal probability."""
    weights=[float(equity_pct),float(mezz_pct),float(senior_pct)]
    if any(x < 0 for x in weights) or abs(sum(weights)-1.0) > 1e-6:
        raise ValueError("Tranche percentages must sum to 100%.")
    n=len(portfolio)
    corr=joint_loss_correlation_matrix(correlation_scale)
    if corr.shape != (n,n):
        raise ValueError("Correlation matrix dimension does not match portfolio.")

    probabilities=np.asarray(portfolio["model_probability"],dtype=float)
    thresholds=np.array([NormalDist().inv_cdf(float(np.clip(p,1e-6,1-1e-6))) for p in probabilities])
    rng=np.random.default_rng(int(seed))
    z=rng.multivariate_normal(np.zeros(n),corr,size=int(simulations))
    hits=z <= thresholds
    gains=np.asarray(portfolio["price"],dtype=float)*np.asarray(portfolio["notional"],dtype=float)
    hit_losses=-np.asarray(portfolio["capital_at_risk"],dtype=float)
    pnl_matrix=np.where(hits,hit_losses,gains)
    portfolio_pnl=pnl_matrix.sum(axis=1)

    total=float(total_capital)
    expenses=total*max(float(expense_rate),0.0)
    net_after_expenses=portfolio_pnl-expenses
    principal_loss=np.maximum(-net_after_expenses,0.0)

    e_cap=total*equity_pct
    m_cap=total*mezz_pct
    s_cap=total*senior_pct
    e_loss=np.minimum(principal_loss,e_cap)
    rem=np.maximum(principal_loss-e_loss,0.0)
    m_loss=np.minimum(rem,m_cap)
    rem=np.maximum(rem-m_loss,0.0)
    s_loss=np.minimum(rem,s_cap)

    tranche_losses={"HRV-E":e_loss,"HRV-M":m_loss,"HRV-S":s_loss}
    tranche_caps={"HRV-E":e_cap,"HRV-M":m_cap,"HRV-S":s_cap}
    tranche_stats={}
    for t,losses in tranche_losses.items():
        cap=tranche_caps[t]
        tranche_stats[t]={
            "expected_loss":float(losses.mean()),
            "expected_loss_pct":float(losses.mean()/cap) if cap else 0.0,
            "impairment_probability":float(np.mean(losses>1e-9)),
            "wipeout_probability":float(np.mean(losses>=cap-1e-9)) if cap else 0.0,
        }

    var95=float(np.quantile(principal_loss,0.95))
    var99=float(np.quantile(principal_loss,0.99))
    tail95=principal_loss[principal_loss>=var95-1e-9]
    tail99=principal_loss[principal_loss>=var99-1e-9]
    trigger_count=hits.sum(axis=1)

    empirical_trigger_corr=np.corrcoef(hits.astype(float),rowvar=False)
    empirical_trigger_corr=np.nan_to_num(empirical_trigger_corr,nan=0.0)
    np.fill_diagonal(empirical_trigger_corr,1.0)

    return {
        "expected_portfolio_pnl":float(portfolio_pnl.mean()),
        "expected_principal_loss":float(principal_loss.mean()),
        "expected_principal_loss_pct":float(principal_loss.mean()/total) if total else 0.0,
        "var95_loss":var95,
        "var99_loss":var99,
        "var95_pct":var95/total if total else 0.0,
        "var99_pct":var99/total if total else 0.0,
        "expected_shortfall95":float(tail95.mean()) if len(tail95) else 0.0,
        "expected_shortfall99":float(tail99.mean()) if len(tail99) else 0.0,
        "tranches":tranche_stats,
        "simulations":int(simulations),
        "correlation_scale":float(correlation_scale),
        "latent_correlation":corr,
        "empirical_trigger_correlation":empirical_trigger_corr,
        "prob_2plus_triggers":float(np.mean(trigger_count>=2)),
        "prob_3plus_triggers":float(np.mean(trigger_count>=3)),
        "prob_4plus_triggers":float(np.mean(trigger_count>=4)),
        "prob_all_triggers":float(np.mean(trigger_count==n)),
        "expected_trigger_count":float(trigger_count.mean()),
        "assumption":"Gaussian-copula joint-trigger model preserving modeled marginal event probabilities; correlation inputs are prototype assumptions, not yet empirically calibrated.",
    }
