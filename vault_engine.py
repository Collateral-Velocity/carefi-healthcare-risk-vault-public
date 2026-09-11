from __future__ import annotations
import copy
import json
import pandas as pd

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
