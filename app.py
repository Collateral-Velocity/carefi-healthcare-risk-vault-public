from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from vault_engine import CARE_HRV_01, SAMPLE_PORTFOLIO, capacity_quote, portfolio_metrics

def money(x: float) -> str:
    return "$" + f"{x:,.0f}"

st.set_page_config(page_title="CareFi · Healthcare Risk Vault", page_icon="CF", layout="wide", initial_sidebar_state="collapsed")

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
[data-testid="stMetricValue"]{font-family:'DM Mono',monospace;font-size:1.35rem!important}
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='topbar'><div class='brand'>CARE<span>FI</span></div><div class='tag'>EVENT CAPACITY PROTOCOL · PROTOTYPE</div></div>", unsafe_allow_html=True)
st.markdown("<div class='hero'><h1>" + CARE_HRV_01["name"] + "</h1><p>" + CARE_HRV_01["mandate"] + "</p></div>", unsafe_allow_html=True)

metrics=portfolio_metrics(SAMPLE_PORTFOLIO,CARE_HRV_01["target_capital"])
m1,m2,m3,m4,m5=st.columns(5)
m1.metric("Committed capital",money(CARE_HRV_01["target_capital"]))
m2.metric("Capital deployed",money(metrics["deployed"]))
m3.metric("Available capacity",money(metrics["available"]))
m4.metric("Weighted event probability",f"{metrics['weighted_probability']:.1%}")
m5.metric("Indicative portfolio yield",f"{metrics['indicative_yield']:.1%}")

tabs=st.tabs(["Vault Overview","Request Capacity","Portfolio","Tokenized Interests","Oriel Reference Layer"])

with tabs[0]:
    st.markdown("<div class='section'>Mandate & controls</div>",unsafe_allow_html=True)
    c1,c2=st.columns([1.15,1],gap="large")
    with c1:
        st.markdown("<div class='callout'><b>Purpose.</b> Supply diversified, fully collateralized risk capacity to objectively settled U.S. healthcare event markets. The vault is designed as an institutional capital layer beneath prediction/event-market execution venues.</div>",unsafe_allow_html=True)
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

with tabs[1]:
    st.markdown("<div class='section'>Capacity request</div>",unsafe_allow_html=True)
    left,right=st.columns([1,1.2],gap="large")
    with left:
        exposure_name=st.text_input("Exposure","Texas influenza ED-utilization seasonal touch")
        risk_family=st.selectbox("Risk family",["Respiratory Utilization","Healthcare Inflation","Reimbursement","Pharmacy / Specialty"])
        geography=st.selectbox("Geography",["Texas","National","North Carolina"])
        public_print=st.selectbox("Settlement source",["CDC NSSP / FluView","BLS","CMS","BEA"])
        requested=float(st.number_input("Protection requested",min_value=100000,max_value=5000000,value=1000000,step=50000))
        market_probability=st.slider("Reference / market probability",1,99,36,1)/100
        tenor_months=st.slider("Tenor (months)",1,24,8,1)
        basis_grade=st.selectbox("Basis-risk grade",["A","A-","B+","B","B-","C+"],index=2)

    quote=capacity_quote(SAMPLE_PORTFOLIO,CARE_HRV_01,requested,market_probability,risk_family,geography,tenor_months,basis_grade)

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
            ["Reference probability",quote["market_probability"]],
            ["Model uncertainty",quote["uncertainty_charge"]],
            ["Duration / collateral",quote["duration_charge"]],
            ["Concentration",quote["concentration_charge"]],
            ["Basis risk",quote["basis_charge"]],
            ["Vault minimum price",quote["minimum_price"]],
        ],columns=["Component","Price contribution"])
        bridge["Price contribution"]=bridge["Price contribution"].map(lambda x:f"{x:.1%}")
        st.dataframe(bridge,use_container_width=True,hide_index=True)
        st.caption("Prototype only. Settlement source: "+public_print+". Exposure: "+exposure_name+".")

with tabs[2]:
    st.markdown("<div class='section'>Current modeled portfolio</div>",unsafe_allow_html=True)
    display=SAMPLE_PORTFOLIO.copy()
    display["notional"]=display["notional"].map(money)
    display["capital_at_risk"]=display["capital_at_risk"].map(money)
    display["model_probability"]=display["model_probability"].map(lambda x:f"{x:.1%}")
    display["price"]=display["price"].map(lambda x:f"{x:.1%}")
    st.dataframe(display,use_container_width=True,hide_index=True)

with tabs[3]:
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

with tabs[4]:
    st.markdown("<div class='section'>Reference architecture</div>",unsafe_allow_html=True)
    st.markdown("""
**Oriel → standardizes the event, public print and reference probability.**  
**CareFi → originates demand, underwrites capacity and constructs the portfolio.**  
**Execution venue → lists / executes / settles the event contract.**  
**CARE-HRV-01 → warehouses diversified healthcare event risk.**  
**Blockchain → records interests, capital allocation, waterfalls and settlement state.**

The next integration step is a common contract JSON schema so an Oriel Healthcare Event Risk Workbench contract can be passed directly into this vault's **Request Capacity** engine.
""")

st.markdown("---")
st.caption("CARE-HRV-01 is a research prototype for institutional discussion. It is not an offering, investment product, executable quote or legal structure.")
