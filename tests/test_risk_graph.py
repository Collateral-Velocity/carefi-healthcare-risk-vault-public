import pandas as pd
from risk_graph import build_risk_graph
from vault_engine import SAMPLE_PORTFOLIO,RISK_FAMILY_HEALTHCARE_BETA,correlation_matrix_frame

POOLS=[
 {"pool_id":"CARE-HRV-01","eligible_families":["Respiratory Utilization","Healthcare Inflation","Reimbursement","Pharmacy / Specialty"],"geographies":["Texas","National","North Carolina"],"available_capacity":2100000.0,"minimum_basis_grade":"B+"},
 {"pool_id":"CARE-RESP-01","eligible_families":["Respiratory Utilization"],"geographies":["Texas","National","North Carolina"],"available_capacity":1250000.0,"minimum_basis_grade":"B"},
 {"pool_id":"CARE-INF-01","eligible_families":["Healthcare Inflation","Reimbursement"],"geographies":["National"],"available_capacity":1800000.0,"minimum_basis_grade":"A-"},
]

def test_risk_graph_builds_expected_relationships():
    marks={"marks":[
        {"position":"Texas respiratory utilization","contract_id":"ORIEL-HC-TX-FLU-2027-01","basis_grade":"B+","fair_value":0.36,"source_health":"healthy"},
        {"position":"Healthcare services PPI shock","contract_id":"ORIEL-HC-PPI-2027-01","basis_grade":"A-","fair_value":0.31,"source_health":"healthy"},
    ]}
    graph=build_risk_graph(SAMPLE_PORTFOLIO,marks,POOLS,RISK_FAMILY_HEALTHCARE_BETA,correlation_matrix_frame(SAMPLE_PORTFOLIO,1.0))
    assert graph["artifact"]=="carefi.risk_graph.v1"
    assert graph["summary"]["event_count"]==6
    assert graph["summary"]["client_exposure_count"]==4
    for relation in ["proxied_by","basis_evidence","maps_to_contract","settles_to","eligible_capacity","hedge_beta","correlated_with"]:
        assert any(e["relation"]==relation for e in graph["edges"])
    tx=next(n for n in graph["nodes"] if n["id"]=="risk:tx-respiratory")
    assert "CARE-HRV-01" in tx["eligible_pools"]
    assert tx["basis_connectivity_score"]>0


def test_client_basis_translation_score():
    from risk_graph import CLIENT_EXPOSURE_PRESETS,client_basis_score
    result=client_basis_score(CLIENT_EXPOSURE_PRESETS[0])
    assert 0 < result["score"] <= 100
    assert result["grade"] in ["A","A-","B+","B","B-","C+"]
