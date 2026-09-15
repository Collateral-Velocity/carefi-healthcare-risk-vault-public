"""basis_underwriting_ui.py — Streamlit surface for the Oriel Basis Underwriting Model."""
from __future__ import annotations

from dataclasses import replace
import json
import pandas as pd
import streamlit as st

from basis_underwriting import (
    PRESETS,
    ExposureIntake,
    evaluate_proxies,
    hedge_effectiveness,
    basis_grade,
    underwriting_output,
)


def _money(x: float) -> str:
    return "$"+f"{float(x):,.0f}"


def render_basis_underwriting_workbench():
    st.markdown("<div class='shdr'>Basis Underwriting / Hedge Effectiveness Workbench</div>",unsafe_allow_html=True)
    st.caption("Translate a client economic exposure into an objective public-print hedge, score the basis, estimate hedge effectiveness, and emit the standardized Oriel → CareFi underwriting payload.")

    if "obh_preset" not in st.session_state:
        st.session_state.obh_preset=list(PRESETS.keys())[0]
    preset_name=st.selectbox("Exposure template",list(PRESETS.keys()),key="obh_preset")
    base=PRESETS[preset_name]

    t1,t2,t3,t4=st.tabs(["1 · Exposure Intake","2 · Proxy Evaluation","3 · Hedge Effectiveness","4 · Basis Underwriting Output"])

    with t1:
        c1,c2=st.columns(2,gap="large")
        with c1:
            client_type=st.text_input("Client / risk-holder type",base.client_type,key="obh_client_type")
            economic_metric=st.text_input("Economic metric at risk",base.economic_metric,key="obh_metric")
            loss_driver=st.text_area("Actual loss driver",base.loss_driver,key="obh_loss_driver",height=90)
        with c2:
            geo_opts=["Texas","National","North Carolina"]
            geo_index=geo_opts.index(base.geography) if base.geography in geo_opts else 1
            geography=st.selectbox("Geography",geo_opts,index=geo_index,key="obh_geo")
            horizon=st.slider("Risk horizon (months)",1,24,int(base.horizon_months),1,key="obh_horizon")
            amount=st.number_input("Economic amount at risk",min_value=100000.0,max_value=100000000.0,value=float(base.amount_at_risk),step=100000.0,format="%.0f",key="obh_amount")

        exposure=ExposureIntake(
            exposure_id=base.exposure_id,
            client_type=client_type,
            economic_metric=economic_metric,
            geography=geography,
            horizon_months=int(horizon),
            amount_at_risk=float(amount),
            loss_driver=loss_driver,
        )
        st.session_state.obh_exposure=exposure
        st.markdown("<div class='note-box'><b>Underwriting question:</b> Which independently published public measure best explains the client's economic loss driver, and how much of that exposure can a parametric/event payout reasonably offset?</div>",unsafe_allow_html=True)

    exposure=st.session_state.get("obh_exposure",base)
    ranked=evaluate_proxies(exposure)

    with t2:
        st.markdown("**Candidate public-print proxies**")
        rows=[]
        for x in ranked:
            rows.append({
                "Proxy":x["label"],
                "Source":x["source"],
                "Dataset":x["dataset"],
                "Proxy score":x["score"],
                "Economic fit":x["economic_fit"],
                "Historical relationship":x["historical_relationship"],
                "Geography fit":x["geography_fit"],
                "Timing fit":x["timing_fit"],
                "Publication quality":x["publication_quality"],
                "Settlement clarity":x["settlement_clarity"],
                "Evidence":x["relationship_evidence"],
            })
        df=pd.DataFrame(rows)
        for col in ["Economic fit","Historical relationship","Geography fit","Timing fit","Publication quality","Settlement clarity"]:
            df[col]=df[col].map(lambda x:f"{float(x):.0%}")
        df["Proxy score"]=df["Proxy score"].map(lambda x:f"{float(x):.1f}/100")
        st.dataframe(df,width="stretch",hide_index=True)

        proxy_labels={x["label"]:x["proxy_id"] for x in ranked}
        chosen_label=st.selectbox("Selected underwriting proxy",list(proxy_labels.keys()),key="obh_proxy_label")
        selected_id=proxy_labels[chosen_label]
        selected=next(x for x in ranked if x["proxy_id"]==selected_id)
        st.session_state.obh_proxy_id=selected_id

        p1,p2,p3,p4=st.columns(4)
        p1.metric("Proxy score",f"{selected['score']:.1f}/100")
        p2.metric("Historical relationship",f"{selected['historical_relationship']:.0%}")
        p3.metric("Publication quality",f"{selected['publication_quality']:.0%}")
        p4.metric("Settlement clarity",f"{selected['settlement_clarity']:.0%}")
        st.caption(selected["relationship_evidence"])

    selected_id=st.session_state.get("obh_proxy_id",ranked[0]["proxy_id"])
    selected=next((x for x in ranked if x["proxy_id"]==selected_id),ranked[0])

    with t3:
        st.markdown("**Hedge effectiveness estimate**")
        calibrated=st.toggle("Use client-specific historical calibration",value=False,key="obh_use_client_cal")
        client_rel=None
        if calibrated:
            client_rel=st.slider("Observed client loss ↔ public proxy relationship",0.0,1.0,float(selected["historical_relationship"]),0.01,key="obh_client_rel")
        eff=hedge_effectiveness(exposure,selected,client_rel)
        grade=basis_grade(eff,selected)

        h1,h2,h3,h4=st.columns(4)
        h1.metric("Hedge effectiveness",f"{eff['hedge_effectiveness']:.0%}")
        h2.metric("Confidence range",f"{eff['confidence_low']:.0%}–{eff['confidence_high']:.0%}")
        h3.metric("Residual basis risk",f"{eff['residual_basis_risk']:.0%}")
        h4.metric("Basis grade",grade["basis_grade"],f"{grade['basis_score']:.1f}/100")

        covered=_money(eff["estimated_covered_economic_risk"])
        residual=_money(eff["estimated_residual_economic_risk"])
        st.markdown(f"<div class='note-box'><b>Economic interpretation:</b> approximately {covered} of the {_money(exposure.amount_at_risk)} modeled exposure is associated with the selected parametric hedge; approximately {residual} remains as residual basis risk under the current assumptions.</div>",unsafe_allow_html=True)
        st.caption("Client-specific calibration should replace underwriting priors when sufficient claims, utilization, PMPM, MLR, shared-savings or other realized outcome history is available.")
        st.session_state.obh_client_cal=client_rel

    with t4:
        output=underwriting_output(
            exposure,
            selected_proxy_id=selected_id,
            client_calibration=st.session_state.get("obh_client_cal"),
        )
        bu=output["basis_underwriting"]
        he=output["hedge_effectiveness"]
        rc=output["recommended_contract"]

        o1,o2,o3,o4=st.columns(4)
        o1.metric("Basis Grade",bu["basis_grade"])
        o2.metric("Basis Score",f"{bu['basis_score']:.1f}/100")
        o3.metric("Hedge Effectiveness",f"{he['hedge_effectiveness']:.0%}")
        o4.metric("Calibration",he["calibration_state"].replace("_"," ").title())

        st.markdown("**Recommended parametric structure**")
        contract_rows=pd.DataFrame([
            ["Public print",rc["public_print"]],
            ["Dataset",rc["dataset"]],
            ["Structure",rc["structure"]],
            ["Threshold",rc["threshold"]],
            ["Geography",rc["geography"]],
            ["Horizon",f"{rc['horizon_months']} months"],
        ],columns=["Field","Recommendation"])
        st.dataframe(contract_rows,width="stretch",hide_index=True)

        st.markdown("**Key basis risks**")
        for risk in bu["key_basis_risks"]:
            st.markdown("— "+risk)

        st.markdown("**Oriel → CareFi machine-readable output**")
        st.json(output,expanded=False)
        st.download_button(
            "⬇  Download basis underwriting JSON",
            data=json.dumps(output,indent=2).encode("utf-8"),
            file_name=f"{exposure.exposure_id.lower()}_basis_underwriting.json",
            mime="application/json",
            key="obh_download",
        )
        st.caption("The CareFi payload contains the basis grade, basis score, hedge effectiveness, public print, dataset, geography, notional and tenor for downstream capacity routing.")
