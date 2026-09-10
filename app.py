from __future__ import annotations
import json
import pandas as pd
import plotly.express as px
import streamlit as st

from vault_engine import (
    CARE_HRV_01,
    SAMPLE_PORTFOLIO,
    ORIEL_TEXAS_RESPIRATORY,
    capacity_quote,
    portfolio_metrics,
    parse_oriel_json,
    portfolio_impact,
    oriel_payload_json,
)

def money(x: float) -> str:
    return "$" + f"{x:,.0f}"

st.set_page_config(page_title="CareFi · Healthcare Risk Vault",page_icon="CF",layout="wide",initial_sidebar_state="collapsed")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600;700&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;color:#172033}
.stApp{background:#f4f2ed}.block-container{padding:0 2rem 4rem!important;max-width:100%!important}
#MainMenu,footer,header{visibility:hidden}
.topbar{background:#101827;color:white;margin:0 -2rem 1.2rem;padding:.85rem 2rem;display:flex;justify-content:space-between;align-items:center}
.brand{font-weight:800;letter-spacing:.08em}.brand span{color:#8ed7bd}.tag{font-size:.72rem;color:#aeb8c7;letter-spacing:.08em}
.hero{background:white;border:1px solid #ddd8cf;border-radius:12px;padding:1.25rem 1.35rem;margin-bottom:1rem}
.hero h1{margin:0;font-size:1.65rem}.hero p{margin:.35rem 0 0;color:#5c6678;font-size:.9rem}
.section{font-size:.72rem;font-weight:800;letter-spacing:.11em;text-transform:uppercase;color:#596273;margin:1.1rem 0 .5rem}
.callout{background:#eaf6f1;border-left:4px solid #2d8f6f;padding:.8rem 1rem;border-radius:7px;font-size:.82rem}
.dark{background:#101827;color:#dce4ee;border-radius:9px;padding:1rem;font-size:.82rem}
[data-testid="stMetricValue"]{font-family:'DM Mono',monospace;font-size:1.35rem!important}
</style>
""",unsafe_allow_html=True)

st.markdown("<div class='topbar'><div class='brand'>CARE<span>FI</span></div><div class='tag'>EVENT CAPACITY PROTOCOL · V0.2</div></div>",unsafe_allow_html=True)
st.markdown("<div class='hero'><h1>"+CARE_HRV_01["name"]+"</h1><p>"+CARE_HRV_01["mandate"]+"</p></div>",unsafe_allow_html=True)

metrics=portfolio_metrics(SAMPLE_PORTFOLIO,CARE_HRV_01["target_capital"])
m1,m2,m3,m4,m5=st.columns(5)
m1.metric("Committed capital",money(CARE_HRV_01["target_capital"]))
m2.metric("Capital deployed",money(metrics["deployed"]))
m3.metric("Available capacity",money(metrics["available"]))
m4.metric("Weighted event probability",f"{metrics['weighted_probability']:.1%}")
m5.metric("Indicative portfolio yield",f"{metrics['indicative_yield']:.1%}")

tabs=st.tabs(["Vault Overview","Request Capacity","Portfolio Impact","Portfolio","Tokenized Interests","Oriel Reference Layer"])

with tabs[0]:
    st.markdown("<div class='section'>Mandate & controls</div>",unsafe_allow_html=True)
    c1,c2=st.columns([1.15,1],gap="large")
    with c1:
        st.markdown("<div class='callout'><b>Purpose.</b> Supply diversified, fully collateralized risk capacity to objectively settled U.S. healthcare event markets. CareFi underwrites capacity; Oriel supplies the reference layer.</div>",unsafe_allow_html=True)
        st.write("")
        controls=pd.DataFrame([
            ["Target capital",money(CARE_HRV_01["target_capital"])],
            ["Investment period","2027"],
            ["Single-event limit",f"{CARE_HRV_01['single_event_limit']:.0%} NAV"],
            ["Risk-family limit",f"{CARE_HRV_01['family_limit']:.0%} NAV"],
            ["Geographic limit",f"{CARE_HRV_01['geography_limit']:.0%} NAV"],
            ["Approved public prints","CDC · BLS · CMS · BEA"],
            ["Valuation / reference layer","Oriel"],
        ],columns=["Control","CARE-HRV-01"])
        st.dataframe(controls,use_container_width=True,hide_index=True)
    with c2:
        by_family=SAMPLE_PORTFOLIO.groupby("risk_family",as_index=False)["capital_at_risk"].sum()
        fig=px.pie(by_family,values="capital_at_risk",names="risk_family",hole=.58)
        fig.update_layout(height=330,margin=dict(l=0,r=0,t=15,b=0),legend_title_text="")
        st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})

if "payload" not in st.session_state:
    st.session_state.payload=dict(ORIEL_TEXAS_RESPIRATORY)

with tabs[1]:
    st.markdown("<div class='section'>Oriel → CareFi capacity request</div>",unsafe_allow_html=True)
    st.markdown("<div class='callout'><b>Preloaded example:</b> Texas respiratory utilization from the Oriel Healthcare Event Risk Workbench. Edit any field below or import a standardized Oriel JSON payload.</div>",unsafe_allow_html=True)
    with st.expander("Import from Oriel JSON"):
        raw=st.text_area("Oriel contract payload",value=oriel_payload_json(),height=260)
        if st.button("Load Oriel payload"):
            try:
                st.session_state.payload=parse_oriel_json(raw)
                st.success("Oriel contract loaded into CARE-HRV-01.")
            except Exception as exc:
                st.error(str(exc))

    p=st.session_state.payload
    left,right=st.columns([1,1.2],gap="large")
    with left:
        title=st.text_input("Exposure",str(p["title"]))
        family_options=["Respiratory Utilization","Healthcare Inflation","Reimbursement","Pharmacy / Specialty"]
        family_index=family_options.index(p["risk_family"]) if p["risk_family"] in family_options else 0
        risk_family=st.selectbox("Risk family",family_options,index=family_index)
        geo_options=["Texas","National","North Carolina"]
        geo_index=geo_options.index(p["geography"]) if p["geography"] in geo_options else 0
        geography=st.selectbox("Geography",geo_options,index=geo_index)
        public_print=st.text_input("Settlement source",str(p["public_print"]))
        requested=float(st.number_input("Protection requested",min_value=100000,max_value=5000000,value=int(p["requested_notional"]),step=50000))
        market_probability=st.slider("Oriel reference probability",1,99,int(round(float(p["model_probability"])*100)),1)/100
        tenor_months=st.slider("Tenor (months)",1,24,int(p["tenor_months"]),1)
        grades=["A","A-","B+","B","B-","C+"]
        grade_index=grades.index(p["basis_grade"]) if p["basis_grade"] in grades else 2
        basis_grade=st.selectbox("Basis-risk grade",grades,index=grade_index)

    quote=capacity_quote(SAMPLE_PORTFOLIO,CARE_HRV_01,requested,market_probability,risk_family,geography,tenor_months,basis_grade)
    active_payload={**p,"title":title,"risk_family":risk_family,"geography":geography,"public_print":public_print,"requested_notional":requested,"model_probability":market_probability,"tenor_months":tenor_months,"basis_grade":basis_grade}
    impact=portfolio_impact(SAMPLE_PORTFOLIO,CARE_HRV_01,active_payload,quote)
    st.session_state.last_quote=quote
    st.session_state.last_payload=active_payload
    st.session_state.last_impact=impact

    with right:
        st.markdown("<div class='section'>CARE-HRV-01 decision</div>",unsafe_allow_html=True)
        q1,q2,q3=st.columns(3)
        q1.metric("Decision",quote["decision"])
        q2.metric("Eligible capacity",money(quote["eligible_capacity"]))
        q3.metric("Minimum YES price",f"{quote['minimum_price']:.1%}")
        q4,q5,q6=st.columns(3)
        q4.metric("Capital consumed",money(quote["capital_consumed"]))
        q5.metric("Post-trade family concentration",f"{quote['post_family_concentration']:.1%}")
        q6.metric("Post-trade geography concentration",f"{quote['post_geo_concentration']:.1%}")
        st.markdown("<div class='section'>Why this price?</div>",unsafe_allow_html=True)
        bridge=pd.DataFrame([
            ["Oriel reference probability",quote["market_probability"]],
            ["Model uncertainty",quote["uncertainty_charge"]],
            ["Duration / collateral",quote["duration_charge"]],
            ["Concentration",quote["concentration_charge"]],
            ["Basis risk",quote["basis_charge"]],
            ["Vault minimum price",quote["minimum_price"]],
        ],columns=["Component","Price contribution"])
        bridge["Price contribution"]=bridge["Price contribution"].map(lambda x:f"{x:.1%}")
        st.dataframe(bridge,use_container_width=True,hide_index=True)

with tabs[2]:
    quote=st.session_state.get("last_quote",capacity_quote(SAMPLE_PORTFOLIO,CARE_HRV_01,ORIEL_TEXAS_RESPIRATORY["requested_notional"],ORIEL_TEXAS_RESPIRATORY["model_probability"],ORIEL_TEXAS_RESPIRATORY["risk_family"],ORIEL_TEXAS_RESPIRATORY["geography"],ORIEL_TEXAS_RESPIRATORY["tenor_months"],ORIEL_TEXAS_RESPIRATORY["basis_grade"]))
    payload=st.session_state.get("last_payload",ORIEL_TEXAS_RESPIRATORY)
    impact=st.session_state.get("last_impact",portfolio_impact(SAMPLE_PORTFOLIO,CARE_HRV_01,payload,quote))
    before,after=impact["before"],impact["after"]
    st.markdown("<div class='section'>Portfolio effect of proposed allocation</div>",unsafe_allow_html=True)
    a1,a2,a3,a4=st.columns(4)
    a1.metric("Available capacity",money(after["available"]),money(after["available"]-before["available"]))
    a2.metric("Portfolio yield",f"{after['indicative_yield']:.1%}",f"{after['indicative_yield']-before['indicative_yield']:+.1%}")
    a3.metric("Weighted probability",f"{after['weighted_probability']:.1%}",f"{after['weighted_probability']-before['weighted_probability']:+.1%}")
    a4.metric("Incremental expected P&L",money(impact["delta_expected_pnl"]))
    st.markdown("<div class='dark'><b>Capital allocation logic:</b> CARE-HRV-01 does not simply accept every positive-edge event. Capacity is capped by single-event, risk-family, geography and total available-capital constraints. The same Oriel contract can therefore clear at different capacity levels as the vault portfolio changes.</div>",unsafe_allow_html=True)

with tabs[3]:
    st.markdown("<div class='section'>Current modeled portfolio</div>",unsafe_allow_html=True)
    display=SAMPLE_PORTFOLIO.copy()
    display["notional"]=display["notional"].map(money)
    display["capital_at_risk"]=display["capital_at_risk"].map(money)
    display["model_probability"]=display["model_probability"].map(lambda x:f"{x:.1%}")
    display["price"]=display["price"].map(lambda x:f"{x:.1%}")
    st.dataframe(display,use_container_width=True,hide_index=True)

with tabs[4]:
    st.markdown("<div class='section'>Illustrative digital interests</div>",unsafe_allow_html=True)
    st.markdown("""
The blockchain layer records vault ownership, subscriptions, NAV, deployed collateral, loss allocation and distributions. The prototype does **not** assume unrestricted secondary trading.

| Class | Role | Illustrative economics |
|---|---|---|
| **HRV-S** | Senior participation | First priority in distributions; lower loss absorption |
| **HRV-M** | Mezzanine participation | Intermediate return / loss layer |
| **HRV-E** | Equity / first-loss | Highest risk; residual economics and first-loss protection |

A regulated CPO/SPV or equivalent institutional wrapper would remain the legal capital vehicle. The token is the programmable accounting and ownership layer—not a substitute for regulated execution, clearing or fund governance.
""")

with tabs[5]:
    st.markdown("<div class='section'>Oriel reference architecture</div>",unsafe_allow_html=True)
    st.markdown("""
**Oriel Workbench → standardized contract payload → CARE-HRV-01 capacity engine → venue execution → vault portfolio.**

The common schema carries contract ID, exposure, risk family, geography, public settlement print, model probability, requested notional, tenor and basis-risk grade. This keeps the Oriel reference function distinct from CareFi's underwriting and capital-allocation function.
""")
    st.code(oriel_payload_json(),language="json")

st.markdown("---")
st.caption("CARE-HRV-01 is a research prototype for institutional discussion. It is not an offering, investment product, executable quote or legal structure.")
