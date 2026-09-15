from capacity_router_v2 import optimize_capacity,marginal_quote,DEFAULT_ASSUMPTIONS
from vault_engine import SAMPLE_PORTFOLIO,RISK_FAMILY_HEALTHCARE_BETA,correlation_matrix_frame

POOLS=[
    {"pool_id":"CARE-HRV-01","name":"Healthcare Event Risk Vault","eligible_families":["Respiratory Utilization","Healthcare Inflation","Reimbursement","Pharmacy / Specialty"],"geographies":["Texas","National","North Carolina"],"target_capital":10000000.0,"available_capacity":2100000.0,"single_event_limit":0.125,"minimum_basis_grade":"B+","medusdi_policy":"Permitted","price_adjustment":0.0},
    {"pool_id":"CARE-RESP-01","name":"Respiratory Sidecar","eligible_families":["Respiratory Utilization"],"geographies":["Texas","National","North Carolina"],"target_capital":5000000.0,"available_capacity":1250000.0,"single_event_limit":0.20,"minimum_basis_grade":"B","medusdi_policy":"Limited","price_adjustment":-0.015},
    {"pool_id":"CARE-INF-01","name":"Inflation Pool","eligible_families":["Healthcare Inflation","Reimbursement"],"geographies":["National"],"target_capital":6000000.0,"available_capacity":1800000.0,"single_event_limit":0.18,"minimum_basis_grade":"A-","medusdi_policy":"Required","price_adjustment":-0.010},
]

def payload():
    return {
        "risk_family":"Respiratory Utilization",
        "geography":"Texas",
        "basis_grade":"B+",
        "model_probability":0.36,
        "tenor_months":8,
        "requested_notional":1000000.0,
        "healthcare_beta":RISK_FAMILY_HEALTHCARE_BETA["Respiratory Utilization"],
    }

def test_router_v2_has_full_cost_stack():
    result=optimize_capacity(payload(),POOLS,SAMPLE_PORTFOLIO,correlation_matrix_frame(SAMPLE_PORTFOLIO,1.0).to_numpy())
    assert result["router_version"]=="CCR-2.0.0"
    assert result["assembled_capacity"]>0
    assert result["allocations"]
    keys=set(result["allocations"][0]["cost_stack"])
    required={"base_probability","basis","duration","marginal_capital","correlation","concentration","collateral_funding","hedge_execution","hedge_credit"}
    assert required.issubset(keys)

def test_marginal_cost_changes_as_pool_fills():
    p=payload()
    corr=correlation_matrix_frame(SAMPLE_PORTFOLIO,1.0).to_numpy()
    pool=POOLS[0]
    q0=marginal_quote(pool,p,0.0,SAMPLE_PORTFOLIO,corr)
    q1=marginal_quote(pool,p,500000.0,SAMPLE_PORTFOLIO,corr)
    assert q1["minimum_price"]>=q0["minimum_price"]
    assert q1["diagnostics"]["pool_utilization"]>q0["diagnostics"]["pool_utilization"]

def test_investor_mandate_remains_hard_constraint():
    p=payload()
    p["risk_family"]="Pharmacy / Specialty"
    p["geography"]="Texas"
    q=marginal_quote(POOLS[1],p,0.0,SAMPLE_PORTFOLIO,correlation_matrix_frame(SAMPLE_PORTFOLIO,1.0).to_numpy())
    assert q["eligible"] is False
    assert "mandate" in q["reason"].lower()
