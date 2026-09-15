"""basis_underwriting.py — Oriel Basis Grade / Hedge Effectiveness Model.

This module translates a healthcare economic exposure into an objectively settled
public-print hedge candidate and emits a machine-readable underwriting payload
for downstream CareFi capacity routing.

The current version is a prototype underwriting framework. Candidate proxy priors
are explicit and must be replaced/calibrated with client-specific outcome history
when available.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
import math

METHODOLOGY_VERSION="OBH-0.1.0"

@dataclass(frozen=True)
class ExposureIntake:
    exposure_id: str
    client_type: str
    economic_metric: str
    geography: str
    horizon_months: int
    amount_at_risk: float
    loss_driver: str
    target_loss_unit: str = "USD"

@dataclass(frozen=True)
class ProxyCandidate:
    proxy_id: str
    label: str
    source: str
    dataset: str
    metric: str
    geography: str
    cadence: str
    publication_lag_days: int
    revision_risk: float
    continuity: float
    settlement_clarity: float
    geography_fit: float
    timing_fit: float
    historical_relationship: float
    relationship_evidence: str
    recommended_structure: str
    recommended_threshold: str

PROXY_LIBRARY=[
    ProxyCandidate(
        "CDC-FLU-ED-US","CDC influenza ED-visit percentage","CDC NSSP / FluView","vutn-jzwm",
        "Influenza ED visits as % of all ED visits","National","Weekly",6,0.10,0.92,0.95,0.70,0.92,0.62,
        "Illustrative prior pending client outcome calibration","Seasonal touch","≥ 5.0% in-window"
    ),
    ProxyCandidate(
        "CDC-FLU-ED-TX","Texas influenza ED-visit percentage","CDC NSSP / FluView","vutn-jzwm",
        "Influenza ED visits as % of all ED visits","Texas","Weekly",6,0.10,0.92,0.95,0.95,0.92,0.72,
        "Illustrative prior pending client outcome calibration","Seasonal touch","Threshold calibrated to client loss function"
    ),
    ProxyCandidate(
        "BLS-MCPI","Medical Care CPI","BLS","CUUR0000SAM",
        "Medical Care CPI","National","Monthly",14,0.05,0.99,0.98,0.80,0.78,0.70,
        "Illustrative prior; public history available","YoY acceleration","≥ 4.0% YoY"
    ),
    ProxyCandidate(
        "BLS-HCPPI","Healthcare Services PPI — private insurance patients","BLS","WPUSIHCARE3",
        "Health care services, private insurance patients","National","Monthly",30,0.08,0.94,0.96,0.85,0.80,0.78,
        "Illustrative prior; public history available","YoY provider-price shock","≥ 4.0% YoY"
    ),
]

PRESETS={
    "Texas MA respiratory PMPM / MLR risk": ExposureIntake(
        "EXP-TX-MA-RESP","Medicare Advantage plan","Respiratory-driven PMPM / MLR variance",
        "Texas",8,2_000_000.0,"Acute respiratory utilization and admissions"
    ),
    "Texas ACO respiratory shared-savings erosion": ExposureIntake(
        "EXP-TX-ACO-RESP","ACO / value-based care organization","Shared-savings erosion from respiratory utilization",
        "Texas",8,1_000_000.0,"Acute admissions and post-acute utilization"
    ),
    "Employer medical-inflation budget variance": ExposureIntake(
        "EXP-EMP-MEDINF","Self-insured employer","Medical-cost trend versus budget",
        "National",12,2_500_000.0,"Medical inflation above actuarial budget"
    ),
    "Commercial carrier provider-rate trend": ExposureIntake(
        "EXP-COMM-PROV","Health carrier","Provider-price trend / medical-cost margin",
        "National",12,3_000_000.0,"Commercial provider repricing"
    ),
}

def _clamp(x: float) -> float:
    return max(0.0,min(float(x),1.0))

def publication_quality(candidate: ProxyCandidate) -> float:
    lag_score=max(0.0,1.0-min(candidate.publication_lag_days/60.0,1.0))
    revision_score=1.0-_clamp(candidate.revision_risk)
    return _clamp(0.30*lag_score+0.25*revision_score+0.25*candidate.continuity+0.20*candidate.settlement_clarity)

def economic_fit(exposure: ExposureIntake, candidate: ProxyCandidate) -> float:
    geography=candidate.geography_fit
    if exposure.geography.lower()==candidate.geography.lower():
        geography=max(geography,0.95)
    elif candidate.geography=="National" and exposure.geography!="National":
        geography=min(geography,0.72)

    metric=str(exposure.economic_metric).lower()
    proxy=str(candidate.metric).lower()
    semantic=0.55
    if "respir" in metric and ("influenza" in proxy or "ed visit" in proxy):
        semantic=0.90
    elif ("provider" in metric or "price" in metric) and "private insurance" in proxy:
        semantic=0.92
    elif ("inflation" in metric or "medical-cost" in metric) and "medical care cpi" in proxy:
        semantic=0.86
    return _clamp(0.60*semantic+0.40*geography)

def proxy_score(exposure: ExposureIntake, candidate: ProxyCandidate) -> dict[str,Any]:
    pub=publication_quality(candidate)
    econ=economic_fit(exposure,candidate)
    hist=_clamp(candidate.historical_relationship)
    geo=_clamp(candidate.geography_fit if exposure.geography=="National" else (0.98 if candidate.geography==exposure.geography else candidate.geography_fit))
    timing=_clamp(candidate.timing_fit)
    clarity=_clamp(candidate.settlement_clarity)

    score=100.0*(0.30*econ+0.22*hist+0.15*geo+0.13*timing+0.12*pub+0.08*clarity)
    return {
        "proxy_id":candidate.proxy_id,
        "label":candidate.label,
        "source":candidate.source,
        "dataset":candidate.dataset,
        "score":round(score,1),
        "economic_fit":econ,
        "historical_relationship":hist,
        "geography_fit":geo,
        "timing_fit":timing,
        "publication_quality":pub,
        "settlement_clarity":clarity,
        "revision_risk":candidate.revision_risk,
        "relationship_evidence":candidate.relationship_evidence,
        "recommended_structure":candidate.recommended_structure,
        "recommended_threshold":candidate.recommended_threshold,
    }

def evaluate_proxies(exposure: ExposureIntake) -> list[dict[str,Any]]:
    rows=[proxy_score(exposure,c) for c in PROXY_LIBRARY]
    return sorted(rows,key=lambda r:r["score"],reverse=True)

def hedge_effectiveness(exposure: ExposureIntake, proxy: dict[str,Any], client_calibration: float|None=None) -> dict[str,Any]:
    relationship=_clamp(client_calibration if client_calibration is not None else proxy["historical_relationship"])
    basis_quality=_clamp(
        0.35*relationship+
        0.20*proxy["economic_fit"]+
        0.15*proxy["geography_fit"]+
        0.15*proxy["timing_fit"]+
        0.10*proxy["publication_quality"]+
        0.05*proxy["settlement_clarity"]
    )
    # Hedge effectiveness is deliberately less than raw relationship because a
    # binary/parametric payout cannot capture all severity/volume variance.
    effectiveness=_clamp(0.80*basis_quality+0.10*relationship)
    evidence_penalty=0.06 if client_calibration is None else 0.025
    low=max(effectiveness-evidence_penalty,0.0)
    high=min(effectiveness+evidence_penalty,1.0)
    residual=1.0-effectiveness
    amount=float(exposure.amount_at_risk)
    return {
        "hedge_effectiveness":effectiveness,
        "confidence_low":low,
        "confidence_high":high,
        "residual_basis_risk":residual,
        "estimated_covered_economic_risk":amount*effectiveness,
        "estimated_residual_economic_risk":amount*residual,
        "calibration_state":"client_calibrated" if client_calibration is not None else "illustrative_prior",
        "relationship_used":relationship,
    }

def basis_grade(effectiveness: dict[str,Any], proxy: dict[str,Any]) -> dict[str,Any]:
    score=100.0*(
        0.50*effectiveness["hedge_effectiveness"]+
        0.15*proxy["publication_quality"]+
        0.15*proxy["geography_fit"]+
        0.10*proxy["timing_fit"]+
        0.10*proxy["settlement_clarity"]
    )
    grade="A" if score>=90 else "A-" if score>=85 else "B+" if score>=78 else "B" if score>=70 else "B-" if score>=62 else "C+"
    return {"basis_score":round(score,1),"basis_grade":grade}

def key_basis_risks(exposure: ExposureIntake, proxy: dict[str,Any], effectiveness: dict[str,Any]) -> list[str]:
    risks=[]
    if proxy["geography_fit"]<0.85:
        risks.append("Geographic basis: public print is broader than the client exposure.")
    if proxy["timing_fit"]<0.85:
        risks.append("Timing basis: publication/observation cadence may not align with realized economic loss.")
    if proxy["historical_relationship"]<0.75:
        risks.append("Economic basis: historical relationship is not yet strong enough to assume one-for-one loss offset.")
    if proxy["revision_risk"]>0.10:
        risks.append("Publication basis: source revisions require a frozen first-print methodology.")
    if effectiveness["calibration_state"]!="client_calibrated":
        risks.append("Calibration basis: hedge effectiveness currently uses an underwriting prior rather than client-specific outcome history.")
    return risks or ["No material basis exception identified under current prototype assumptions."]

def underwriting_output(
    exposure: ExposureIntake,
    selected_proxy_id: str|None=None,
    client_calibration: float|None=None,
) -> dict[str,Any]:
    ranked=evaluate_proxies(exposure)
    selected=next((x for x in ranked if x["proxy_id"]==selected_proxy_id),ranked[0])
    eff=hedge_effectiveness(exposure,selected,client_calibration)
    grade=basis_grade(eff,selected)
    return {
        "schema_version":"oriel.basis-underwriting.v1",
        "methodology_version":METHODOLOGY_VERSION,
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "exposure":asdict(exposure),
        "recommended_proxy":selected,
        "hedge_effectiveness":eff,
        "basis_underwriting":{**grade,"key_basis_risks":key_basis_risks(exposure,selected,eff)},
        "recommended_contract":{
            "structure":selected["recommended_structure"],
            "threshold":selected["recommended_threshold"],
            "public_print":selected["source"],
            "dataset":selected["dataset"],
            "geography":exposure.geography,
            "horizon_months":exposure.horizon_months,
        },
        "carefi_payload":{
            "risk_family":"Respiratory Utilization" if "CDC-" in selected["proxy_id"] else "Healthcare Inflation",
            "geography":exposure.geography,
            "requested_notional":exposure.amount_at_risk,
            "basis_grade":grade["basis_grade"],
            "basis_score":grade["basis_score"],
            "hedge_effectiveness":eff["hedge_effectiveness"],
            "public_print":selected["source"],
            "source_dataset":selected["dataset"],
            "tenor_months":exposure.horizon_months,
        },
        "disclosure":"Prototype underwriting output. Hedge effectiveness is indicative until calibrated to client-specific realized loss/outcome data.",
    }
