from __future__ import annotations
import json
import time
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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
    VAULT_TERMS,
    ELIGIBILITY_RULES,
    INELIGIBLE_RULES,
    WATERFALL_DEFAULTS,
    waterfall_simulation,
    waterfall_scenarios,
    EVENT_SCENARIO_PRESETS,
    event_portfolio_scenario,
    waterfall_from_event_scenario,
    event_waterfall_scenarios,
    MEDUSDI_DEFAULTS,
    RISK_FAMILY_HEALTHCARE_BETA,
    portfolio_healthcare_beta,
    medusdi_request_hedge,
    medusdi_hedge_pnl,
    POSITION_MARKS,
    TREASURY_ASSUMPTIONS,
    position_marks,
    vault_nav,
    cash_collateral_dashboard,
    expected_loss_analytics,
    correlation_matrix_frame,
    correlated_loss_analytics,
    TOKEN_CLASS_TERMS,
    TOKEN_LIFECYCLE,
    DEFAULT_INVESTOR_REGISTRY,
    token_class_economics,
    registry_summary,
    mint_tokens,
    burn_tokens,
    whitelist_wallet,
    token_nav_distribution_sync,
)

def money(x: float) -> str:
    return "$" + f"{x:,.0f}"


PROTOCOL_CAPITAL_POOLS = [
    {
        "pool_id":"CARE-HRV-01","name":"Healthcare Event Risk Vault 2027",
        "mandate":"Diversified institutional healthcare event risk",
        "eligible_families":["Respiratory Utilization","Healthcare Inflation","Reimbursement","Pharmacy / Specialty"],
        "geographies":["Texas","National","North Carolina"],"target_capital":10_000_000.0,
        "available_capacity":2_100_000.0,"single_event_limit":0.125,
        "minimum_basis_grade":"B+","medusdi_policy":"Permitted","price_adjustment":0.000,
    },
    {
        "pool_id":"CARE-RESP-01","name":"Respiratory Utilization Sidecar",
        "mandate":"Seasonal respiratory and utilization event risk",
        "eligible_families":["Respiratory Utilization"],
        "geographies":["Texas","National","North Carolina"],"target_capital":5_000_000.0,
        "available_capacity":1_250_000.0,"single_event_limit":0.20,
        "minimum_basis_grade":"B","medusdi_policy":"Limited","price_adjustment":-0.015,
    },
    {
        "pool_id":"CARE-INF-01","name":"Healthcare Inflation Capacity Pool",
        "mandate":"Healthcare inflation, reimbursement and medical-cost factor risk",
        "eligible_families":["Healthcare Inflation","Reimbursement"],
        "geographies":["National"],"target_capital":6_000_000.0,
        "available_capacity":1_800_000.0,"single_event_limit":0.18,
        "minimum_basis_grade":"A-","medusdi_policy":"Required","price_adjustment":-0.010,
    },
]

PROTOCOL_LIFECYCLE = [
    ("Submitted","Originator"),("Validated","Oriel"),("Routed","CareFi Protocol"),
    ("Quoted","Capital Pools"),("Allocated","CareFi Protocol"),("Hedged","MEDUSDi Layer"),
    ("Executed","Venue"),("Collateralized","Vault / Clearer"),("Observing","Public Print"),
    ("Resolved","Oriel / Venue"),("Settled","Venue / Administrator"),("Distributed","Token / Investor Ledger"),
]

TRANSACTION_STEPS = [
    "Risk enters","Oriel validates","Capacity assembles","MEDUSDi hedge attaches",
    "Venue execution","Capital stack updates","Settlement & distribution",
]

_PROTOCOL_BASIS_RANK={"A":6,"A-":5,"B+":4,"B":3,"B-":2,"C+":1}
_PROTOCOL_BASIS_CHARGE={"A":0.005,"A-":0.008,"B+":0.015,"B":0.020,"B-":0.027,"C+":0.035}

def _protocol_pool_quote(pool,payload):
    family=str(payload["risk_family"])
    geography=str(payload["geography"])
    grade=str(payload["basis_grade"])
    if family not in pool["eligible_families"]:
        return {"pool_id":pool["pool_id"],"pool_name":pool["name"],"decision":"INELIGIBLE","reason":"Risk family outside mandate","eligible_capacity":0.0,"minimum_price":None,"medusdi_hedge":0.0}
    if geography not in pool["geographies"]:
        return {"pool_id":pool["pool_id"],"pool_name":pool["name"],"decision":"INELIGIBLE","reason":"Geography outside mandate","eligible_capacity":0.0,"minimum_price":None,"medusdi_hedge":0.0}
    if _PROTOCOL_BASIS_RANK.get(grade,0) < _PROTOCOL_BASIS_RANK.get(pool["minimum_basis_grade"],0):
        return {"pool_id":pool["pool_id"],"pool_name":pool["name"],"decision":"INELIGIBLE","reason":"Basis grade below pool minimum","eligible_capacity":0.0,"minimum_price":None,"medusdi_hedge":0.0}

    p=float(payload["model_probability"])
    duration=min(0.004*int(payload["tenor_months"]),0.050)
    minimum_price=min(max(p+0.020+duration+_PROTOCOL_BASIS_CHARGE.get(grade,0.020)+float(pool["price_adjustment"]),0.01),0.95)
    capital_fraction=1.0-minimum_price
    event_limit=float(pool["target_capital"])*float(pool["single_event_limit"])
    capacity_by_limit=event_limit/capital_fraction if capital_fraction>0 else 0.0
    eligible_capacity=min(float(payload["requested_notional"]),float(pool["available_capacity"]),capacity_by_limit)
    hedge_ratio={"Required":0.75,"Permitted":0.50,"Limited":0.25}.get(pool["medusdi_policy"],0.0)
    hedge=medusdi_request_hedge(eligible_capacity,family,hedge_ratio)["medusdi_hedge_notional"]
    return {
        "pool_id":pool["pool_id"],"pool_name":pool["name"],
        "decision":"APPROVED" if eligible_capacity>=float(payload["requested_notional"])-1 else "PARTIAL",
        "reason":"Eligible","eligible_capacity":eligible_capacity,"minimum_price":minimum_price,
        "medusdi_hedge":hedge,
    }

def route_capacity_request(payload):
    quotes=[_protocol_pool_quote(pool,payload) for pool in PROTOCOL_CAPITAL_POOLS]
    executable=sorted(
        [q for q in quotes if q["eligible_capacity"]>0 and q["minimum_price"] is not None],
        key=lambda q:(q["minimum_price"],-q["eligible_capacity"])
    )
    remaining=float(payload["requested_notional"])
    allocations=[]
    weighted_price=0.0
    total_hedge=0.0
    for quote in executable:
        if remaining<=0:
            break
        allocation=min(remaining,float(quote["eligible_capacity"]))
        hedge_share=allocation/quote["eligible_capacity"] if quote["eligible_capacity"] else 0.0
        allocated_hedge=float(quote["medusdi_hedge"])*hedge_share
        allocations.append({**quote,"allocated_notional":allocation,"allocated_medusdi_hedge":allocated_hedge})
        weighted_price+=allocation*float(quote["minimum_price"])
        total_hedge+=allocated_hedge
        remaining-=allocation
    assembled=float(payload["requested_notional"])-max(remaining,0.0)
    return {
        "quotes":quotes,"allocations":allocations,"requested_notional":float(payload["requested_notional"]),
        "assembled_capacity":assembled,"unfilled":max(remaining,0.0),
        "blended_price":weighted_price/assembled if assembled else 0.0,
        "blended_medusdi_hedge":total_hedge,
        "fill_ratio":assembled/float(payload["requested_notional"]) if float(payload["requested_notional"]) else 0.0,
    }

def protocol_transaction_snapshot(payload):
    routed=route_capacity_request(payload)
    beta=medusdi_request_hedge(routed["assembled_capacity"],str(payload["risk_family"]),0.50)
    base_nav=vault_nav(SAMPLE_PORTFOLIO,CARE_HRV_01["target_capital"],MEDUSDI_DEFAULTS["portfolio_hedge_ratio"])
    risk=correlated_loss_analytics(
        SAMPLE_PORTFOLIO,CARE_HRV_01["target_capital"],
        WATERFALL_DEFAULTS["equity_pct"],WATERFALL_DEFAULTS["mezz_pct"],WATERFALL_DEFAULTS["senior_pct"],
        expense_rate=WATERFALL_DEFAULTS["expense_rate"],correlation_scale=1.0,simulations=10000
    )
    return {
        "payload":dict(payload),"routed":routed,"beta":beta,"vault_nav":base_nav["nav"],
        "posted_collateral":base_nav["posted_collateral"],
        "expected_loss":risk["expected_principal_loss"],"var95_loss":risk["var95_loss"],
    }

st.set_page_config(page_title="CareFi · Event Capacity Protocol",page_icon="CF",layout="wide",initial_sidebar_state="collapsed")

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

st.markdown("<div class='topbar'><div class='brand'>CARE<span>FI</span></div><div class='tag'>EVENT CAPACITY PROTOCOL · V1.0</div></div>",unsafe_allow_html=True)
st.markdown("<div class='hero'><h1>CareFi Event Capacity Protocol</h1><p>Standardize event risk, route it to institutional capital, attach healthcare-inflation hedges, and carry the position through settlement and investor distribution. <b>First modeled vault: CARE-HRV-01.</b></p></div>",unsafe_allow_html=True)

if "payload" not in st.session_state:
    st.session_state.payload=dict(ORIEL_TEXAS_RESPIRATORY)

metrics=portfolio_metrics(SAMPLE_PORTFOLIO,CARE_HRV_01["target_capital"])
m1,m2,m3,m4,m5=st.columns(5)
m1.metric("Committed capital",money(CARE_HRV_01["target_capital"]))
m2.metric("Capital deployed",money(metrics["deployed"]))
m3.metric("Available capacity",money(metrics["available"]))
m4.metric("Weighted event probability",f"{metrics['weighted_probability']:.1%}")
m5.metric("Indicative portfolio yield",f"{metrics['indicative_yield']:.1%}")

tabs=st.tabs(["Protocol Overview","Transaction Flow","Vault Overview","Mandate & Terms","Request Capacity","Portfolio Impact","Portfolio","NAV & Marks","Risk Analytics","Cash & Collateral","Waterfall Simulator","Tokenized Interests","Oriel Reference Layer"])

with tabs[0]:
    st.markdown("<div class='section'>CareFi Event Capacity Protocol</div>",unsafe_allow_html=True)
    st.markdown("<div class='callout'><b>Protocol layer.</b> Oriel standardizes and values event risk; the CareFi protocol validates, routes and assembles institutional capacity across eligible capital pools; MEDUSDi can hedge the common healthcare-inflation factor; venues execute and settle; the token layer records investor economics and lifecycle state.</div>",unsafe_allow_html=True)

    protocol_payload=st.session_state.get("last_payload",st.session_state.payload)
    routed=route_capacity_request(protocol_payload)

    p1,p2,p3,p4,p5=st.columns(5)
    p1.metric("Risk request",money(routed["requested_notional"]))
    p2.metric("Capacity assembled",money(routed["assembled_capacity"]))
    p3.metric("Fill ratio",f"{routed['fill_ratio']:.0%}")
    p4.metric("Blended minimum price",f"{routed['blended_price']:.1%}" if routed["assembled_capacity"] else "—")
    p5.metric("MEDUSDi overlay",money(routed["blended_medusdi_hedge"]))

    st.markdown("#### Capital registry")
    registry_rows=[]
    for pool in PROTOCOL_CAPITAL_POOLS:
        registry_rows.append([
            pool["pool_id"],pool["name"],pool["mandate"],money(pool["target_capital"]),
            money(pool["available_capacity"]),", ".join(pool["eligible_families"]),
            pool["minimum_basis_grade"],pool["medusdi_policy"],
        ])
    registry_df=pd.DataFrame(registry_rows,columns=[
        "Pool","Capital pool","Mandate","Target capital","Available capacity",
        "Eligible risk families","Min basis grade","MEDUSDi policy"
    ])
    st.dataframe(registry_df,use_container_width=True,hide_index=True)

    st.markdown("#### Routed capacity quotes")
    quote_rows=[]
    allocation_lookup={a["pool_id"]:a for a in routed["allocations"]}
    for q in routed["quotes"]:
        alloc=allocation_lookup.get(q["pool_id"])
        quote_rows.append([
            q["pool_id"],q["decision"],q["reason"],money(q["eligible_capacity"]),
            f"{q['minimum_price']:.1%}" if q["minimum_price"] is not None else "—",
            money(alloc["allocated_notional"]) if alloc else money(0),
            money(alloc["allocated_medusdi_hedge"]) if alloc else money(0),
        ])
    quotes_df=pd.DataFrame(quote_rows,columns=[
        "Pool","Decision","Reason","Quoted capacity","Minimum price","Allocated","MEDUSDi hedge"
    ])
    st.dataframe(quotes_df,use_container_width=True,hide_index=True)

    st.markdown("#### Capacity assembly")
    if routed["allocations"]:
        alloc_df=pd.DataFrame([
            {
                "Pool":a["pool_id"],
                "Allocated notional":a["allocated_notional"],
                "Minimum price":a["minimum_price"],
                "MEDUSDi hedge":a["allocated_medusdi_hedge"],
            } for a in routed["allocations"]
        ])
        fig_alloc=px.bar(
            alloc_df,x="Pool",y="Allocated notional",
            text=alloc_df["Allocated notional"].map(money),
            labels={"Allocated notional":"Allocated capacity"}
        )
        fig_alloc.update_layout(height=320,margin=dict(l=0,r=0,t=20,b=0))
        st.plotly_chart(fig_alloc,use_container_width=True,config={"displayModeBar":False})

    st.markdown("#### Protocol flow")
    node_labels=["Risk request","Oriel","CareFi Protocol"]+[p["pool_id"] for p in PROTOCOL_CAPITAL_POOLS]+["MEDUSDi","Venue","HRV-S / M / E","Investors"]
    node_index={name:i for i,name in enumerate(node_labels)}
    source=[node_index["Risk request"],node_index["Oriel"]]
    target=[node_index["Oriel"],node_index["CareFi Protocol"]]
    value=[routed["requested_notional"],routed["requested_notional"]]
    for alloc in routed["allocations"]:
        source.append(node_index["CareFi Protocol"])
        target.append(node_index[alloc["pool_id"]])
        value.append(alloc["allocated_notional"])
        source.append(node_index[alloc["pool_id"]])
        target.append(node_index["Venue"])
        value.append(alloc["allocated_notional"])
        if alloc["allocated_medusdi_hedge"]>0:
            source.append(node_index[alloc["pool_id"]])
            target.append(node_index["MEDUSDi"])
            value.append(alloc["allocated_medusdi_hedge"])
    source.extend([node_index["Venue"],node_index["HRV-S / M / E"]])
    target.extend([node_index["HRV-S / M / E"],node_index["Investors"]])
    value.extend([routed["assembled_capacity"],routed["assembled_capacity"]])
    sankey=go.Figure(data=[go.Sankey(
        node=dict(label=node_labels,pad=18,thickness=18),
        link=dict(source=source,target=target,value=value),
    )])
    sankey.update_layout(height=420,margin=dict(l=0,r=0,t=20,b=10))
    st.plotly_chart(sankey,use_container_width=True,config={"displayModeBar":False})

    lifecycle=pd.DataFrame(PROTOCOL_LIFECYCLE,columns=["State","Responsible layer"])
    st.markdown("#### Canonical lifecycle")
    st.dataframe(lifecycle,use_container_width=True,hide_index=True)
    st.caption("CARE-HRV-01 is the first modeled vault on this protocol. CARE-RESP-01 and CARE-INF-01 are illustrative prototype capacity pools used to demonstrate multi-pool routing.")

with tabs[1]:
    st.markdown("<div class='section'>Risk enters → capacity assembles → hedge attaches → capital stack updates</div>",unsafe_allow_html=True)
    st.markdown("<div class='callout'><b>One risk, end to end.</b> Run the guided demo to watch a standardized Oriel healthcare event move through the protocol into institutional capacity, a MEDUSDi factor hedge, venue collateralization, the CARE-HRV capital stack and tokenized investor distributions.</div>",unsafe_allow_html=True)

    flow_payload=st.session_state.get("last_payload",st.session_state.payload)
    tx=protocol_transaction_snapshot(flow_payload)
    if "protocol_flow_step" not in st.session_state:
        st.session_state.protocol_flow_step=0

    f1,f2,f3=st.columns([1,1,1])
    play=f1.button("▶ Play transaction",use_container_width=True)
    if f2.button("Next step →",use_container_width=True):
        st.session_state.protocol_flow_step=min(st.session_state.protocol_flow_step+1,len(TRANSACTION_STEPS)-1)
    if f3.button("↺ Reset",use_container_width=True):
        st.session_state.protocol_flow_step=0

    progress=st.progress((st.session_state.protocol_flow_step+1)/len(TRANSACTION_STEPS))
    flow_placeholder=st.empty()

    def render_protocol_step(step_index:int):
        step=TRANSACTION_STEPS[step_index]
        routed_tx=tx["routed"]
        with flow_placeholder.container():
            st.markdown("### "+str(step_index+1)+" · "+step)
            if step_index==0:
                s1,s2,s3,s4=st.columns(4)
                s1.metric("Requested protection",money(flow_payload["requested_notional"]))
                s2.metric("Oriel probability",f"{float(flow_payload['model_probability']):.1%}")
                s3.metric("Geography",str(flow_payload["geography"]))
                s4.metric("Tenor",str(flow_payload["tenor_months"])+" months")
                st.markdown("<div class='dark'><b>"+str(flow_payload["title"])+"</b><br>"+str(flow_payload["trigger"])+"<br><br>Settlement source: "+str(flow_payload["public_print"])+"</div>",unsafe_allow_html=True)
            elif step_index==1:
                s1,s2,s3,s4=st.columns(4)
                s1.metric("Contract ID",str(flow_payload["contract_id"]))
                s2.metric("Basis grade",str(flow_payload["basis_grade"]))
                s3.metric("Risk family",str(flow_payload["risk_family"]))
                s4.metric("Validation","PASSED")
                st.json(flow_payload,expanded=False)
            elif step_index==2:
                arows=[]
                for a in routed_tx["allocations"]:
                    arows.append([a["pool_id"],money(a["allocated_notional"]),f"{a['minimum_price']:.1%}",money(a["allocated_medusdi_hedge"])])
                st.dataframe(pd.DataFrame(arows,columns=["Capital pool","Allocated","Min price","MEDUSDi hedge"]),use_container_width=True,hide_index=True)
                s1,s2,s3=st.columns(3)
                s1.metric("Assembled",money(routed_tx["assembled_capacity"]))
                s2.metric("Blended minimum price",f"{routed_tx['blended_price']:.1%}")
                s3.metric("Unfilled",money(routed_tx["unfilled"]))
            elif step_index==3:
                hedge=tx["beta"]
                s1,s2,s3=st.columns(3)
                s1.metric("Gross healthcare beta",money(hedge["gross_beta_exposure"]))
                s2.metric("MEDUSDi hedge",money(routed_tx["blended_medusdi_hedge"]))
                s3.metric("Net modeled beta",money(max(hedge["gross_beta_exposure"]-routed_tx["blended_medusdi_hedge"],0.0)))
                st.markdown("<div class='dark'>The event-specific risk remains in the capacity pools while MEDUSDi offsets part of the common healthcare-inflation factor.</div>",unsafe_allow_html=True)
            elif step_index==4:
                s1,s2,s3,s4=st.columns(4)
                s1.metric("Execution state","ALLOCATED")
                s2.metric("Notional to venue",money(routed_tx["assembled_capacity"]))
                s3.metric("Modeled collateral",money(tx["posted_collateral"]))
                s4.metric("Observation state","READY")
                st.progress(routed_tx["fill_ratio"])
                st.caption("Venue execution and collateral are represented as lifecycle states in the prototype; no live venue order is submitted.")
            elif step_index==5:
                s1,s2,s3,s4=st.columns(4)
                s1.metric("Vault NAV",money(tx["vault_nav"]))
                s2.metric("Correlated expected loss",money(tx["expected_loss"]))
                s3.metric("95% loss",money(tx["var95_loss"]))
                s4.metric("Capital stack","HRV-E → HRV-M → HRV-S")
                stack=pd.DataFrame([
                    ["HRV-S","50%","Senior / last loss"],
                    ["HRV-M","30%","Mezzanine"],
                    ["HRV-E","20%","Equity / first loss"],
                ],columns=["Class","Target capital","Role"])
                st.dataframe(stack,use_container_width=True,hide_index=True)
            else:
                sync=token_nav_distribution_sync(
                    CARE_HRV_01["target_capital"],tx["vault_nav"],750000.0,
                    senior_pref=WATERFALL_DEFAULTS["senior_pref"],mezz_pref=WATERFALL_DEFAULTS["mezz_pref"]
                )
                out=sync[["class","nav_per_token","distribution","distribution_per_token","sync_state"]].copy()
                out["nav_per_token"]=out["nav_per_token"].map(lambda x:"USD "+f"{x:,.4f}")
                out["distribution"]=out["distribution"].map(money)
                out["distribution_per_token"]=out["distribution_per_token"].map(lambda x:"USD "+f"{x:,.4f}")
                out.columns=["Class","NAV / token","Distribution","Distribution / token","Ledger state"]
                st.dataframe(out,use_container_width=True,hide_index=True)
                st.success("Public print resolves → venue settles → vault NAV updates → waterfall allocates proceeds → token ledger synchronizes investor entitlements.")

    if play:
        for i in range(len(TRANSACTION_STEPS)):
            st.session_state.protocol_flow_step=i
            progress.progress((i+1)/len(TRANSACTION_STEPS))
            flow_placeholder.empty()
            render_protocol_step(i)
            time.sleep(0.55)
    else:
        render_protocol_step(st.session_state.protocol_flow_step)

    step_status=pd.DataFrame([
        [str(i+1),name,"COMPLETE" if i<st.session_state.protocol_flow_step else ("ACTIVE" if i==st.session_state.protocol_flow_step else "PENDING")]
        for i,name in enumerate(TRANSACTION_STEPS)
    ],columns=["Step","Transaction state","Status"])
    st.dataframe(step_status,use_container_width=True,hide_index=True)
    st.caption("The guided flow is a deterministic demonstration of the protocol architecture; capital pools, pricing adjustments and lifecycle outputs remain prototype assumptions.")

with tabs[2]:
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

with tabs[3]:
    st.markdown("<div class='section'>Vault mandate and economic wrapper</div>",unsafe_allow_html=True)
    st.markdown("<div class='callout'><b>Prototype term sheet.</b> CARE-HRV-01 is modeled as a regulated CPO/SPV-style capital vehicle with tokenized economic interests layered on top. The token does not replace the legal wrapper, venue, clearing or custody infrastructure.</div>",unsafe_allow_html=True)
    left_terms,right_terms=st.columns(2,gap="large")
    with left_terms:
        st.markdown("#### Core terms")
        core=pd.DataFrame([
            ["Legal wrapper",VAULT_TERMS["legal_wrapper"]],
            ["Investment period",VAULT_TERMS["investment_period"]],
            ["Base term",VAULT_TERMS["base_term"]],
            ["Liquidity",VAULT_TERMS["liquidity"]],
            ["NAV frequency",VAULT_TERMS["nav_frequency"]],
            ["Minimum basis grade",VAULT_TERMS["minimum_basis_grade"]],
            ["Leverage",VAULT_TERMS["leverage"]],
            ["Management fee",VAULT_TERMS["management_fee"]],
            ["Performance fee",VAULT_TERMS["performance_fee"]],
        ],columns=["Term","Prototype policy"])
        st.dataframe(core,use_container_width=True,hide_index=True)
        st.markdown("#### Eligibility")
        for rule in ELIGIBILITY_RULES:
            st.markdown("✓ "+rule)
        st.markdown("#### Normally ineligible without exception")
        for rule in INELIGIBLE_RULES:
            st.markdown("— "+rule)
    with right_terms:
        st.markdown("#### Valuation hierarchy")
        for i,item in enumerate(VAULT_TERMS["valuation_hierarchy"],1):
            st.markdown(f"**{i}.** {item}")
        st.markdown("#### Loss waterfall")
        st.markdown(" → ".join(VAULT_TERMS["loss_waterfall"]) + "  \\n*First-loss to last-loss*")
        st.markdown("#### Distribution waterfall")
        for i,item in enumerate(VAULT_TERMS["distribution_waterfall"],1):
            st.markdown(f"**{i}.** {item}")
        st.markdown("#### Governance")
        st.write(VAULT_TERMS["governance"])
        st.markdown("#### Token role")
        st.write(VAULT_TERMS["token_role"])
        st.markdown("#### Breach / disruption policy")
        st.write("Passive breaches caused by NAV movement do not automatically force liquidation. New allocations to the affected bucket stop; CareFi may reduce, hedge, run off or seek a documented temporary exception. Every contract must define a public-print fallback before execution.")
    st.caption("Prototype terms only. Final legal, tax, securities, commodities, custody and offering terms require counsel and service-provider review.")

with tabs[4]:
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
        st.markdown("#### MEDUSDi hedge layer")
        medusdi_enabled=st.toggle("Hedge common healthcare-inflation factor with MEDUSDi",value=True)
        default_beta=RISK_FAMILY_HEALTHCARE_BETA.get(risk_family,0.25)
        healthcare_beta=st.slider("Illustrative healthcare-inflation beta",0,100,int(default_beta*100),5)/100
        request_hedge_ratio=st.slider("MEDUSDi hedge ratio",0,100,int(MEDUSDI_DEFAULTS["request_hedge_ratio"]*100),5,disabled=not medusdi_enabled)/100

    quote=capacity_quote(SAMPLE_PORTFOLIO,CARE_HRV_01,requested,market_probability,risk_family,geography,tenor_months,basis_grade)
    active_payload={**p,"title":title,"risk_family":risk_family,"geography":geography,"public_print":public_print,"requested_notional":requested,"model_probability":market_probability,"tenor_months":tenor_months,"basis_grade":basis_grade}
    impact=portfolio_impact(SAMPLE_PORTFOLIO,CARE_HRV_01,active_payload,quote)
    medusdi_request=medusdi_request_hedge(
        quote["eligible_capacity"],risk_family,request_hedge_ratio if medusdi_enabled else 0.0,healthcare_beta
    )
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
        st.markdown("<div class='section'>MEDUSDi hedge overlay</div>",unsafe_allow_html=True)
        h1,h2,h3=st.columns(3)
        h1.metric("Gross healthcare-beta exposure",money(medusdi_request["gross_beta_exposure"]))
        h2.metric("Suggested MEDUSDi hedge",money(medusdi_request["medusdi_hedge_notional"]))
        h3.metric("Net healthcare-beta exposure",money(medusdi_request["net_beta_exposure"]))
        st.caption("Illustrative factor hedge only. The prototype does not yet give hard collateral or concentration-limit credit for MEDUSDi; it shows how the common healthcare-inflation component could be offset alongside the event position.")

with tabs[5]:
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

with tabs[6]:
    st.markdown("<div class='section'>MEDUSDi healthcare-beta dashboard</div>",unsafe_allow_html=True)
    portfolio_hedge_ratio=st.slider("Portfolio MEDUSDi hedge ratio",0,100,int(MEDUSDI_DEFAULTS["portfolio_hedge_ratio"]*100),5,key="portfolio_medusdi_ratio")/100
    beta_view=portfolio_healthcare_beta(SAMPLE_PORTFOLIO,portfolio_hedge_ratio)
    b1,b2,b3=st.columns(3)
    b1.metric("Gross healthcare-beta exposure",money(beta_view["gross_beta_exposure"]))
    b2.metric("MEDUSDi hedge",money(beta_view["medusdi_hedge_notional"]))
    b3.metric("Net healthcare-beta exposure",money(beta_view["net_beta_exposure"]))
    beta_detail=pd.DataFrame(beta_view["detail"])
    beta_detail["notional"]=beta_detail["notional"].map(money)
    beta_detail["healthcare_beta"]=beta_detail["healthcare_beta"].map(lambda x:f"{x:.0%}")
    beta_detail["gross_beta_exposure"]=beta_detail["gross_beta_exposure"].map(money)
    beta_detail.columns=["Position","Risk family","Notional","Illustrative healthcare beta","Gross beta exposure"]
    st.dataframe(beta_detail,use_container_width=True,hide_index=True)
    st.caption("Healthcare betas are illustrative prototype assumptions, not empirically calibrated hedge ratios.")

    st.markdown("<div class='section'>Current modeled portfolio</div>",unsafe_allow_html=True)
    display=SAMPLE_PORTFOLIO.copy()
    display["notional"]=display["notional"].map(money)
    display["capital_at_risk"]=display["capital_at_risk"].map(money)
    display["model_probability"]=display["model_probability"].map(lambda x:f"{x:.1%}")
    display["price"]=display["price"].map(lambda x:f"{x:.1%}")
    st.dataframe(display,use_container_width=True,hide_index=True)

with tabs[7]:
    st.markdown("<div class='section'>Real NAV + live position marks</div>",unsafe_allow_html=True)
    st.markdown("<div class='callout'><b>Modeled live marks.</b> Until venue feeds are connected, current marks below are Oriel prototype fair values. NAV reconciles committed capital, event-contract MTM, MEDUSDi MTM and accrued fees.</div>",unsafe_allow_html=True)
    nav_hedge_ratio=st.slider("MEDUSDi hedge ratio used in NAV",0,100,int(MEDUSDI_DEFAULTS["portfolio_hedge_ratio"]*100),5,key="nav_medusdi_ratio")/100
    nav_view=vault_nav(SAMPLE_PORTFOLIO,CARE_HRV_01["target_capital"],nav_hedge_ratio)
    n1,n2,n3,n4,n5=st.columns(5)
    n1.metric("Current NAV",money(nav_view["nav"]),money(nav_view["nav_change"]))
    n2.metric("Event MTM",money(nav_view["event_unrealized_pnl"]))
    n3.metric("MEDUSDi MTM",money(nav_view["medusdi_unrealized_pnl"]))
    n4.metric("Posted collateral",money(nav_view["posted_collateral"]))
    n5.metric("Unencumbered cash",money(nav_view["unencumbered_cash"]))
    marks=nav_view["marks"].copy()
    marks["entry_price"]=marks["entry_price"].map(lambda x:f"{x:.1%}")
    marks["oriel_fair_value"]=marks["oriel_fair_value"].map(lambda x:f"{x:.1%}")
    for col in ["unrealized_pnl","notional","collateral_posted"]:
        marks[col]=marks[col].map(money)
    marks.columns=["Position","Risk family","Geography","Entry price","Current Oriel mark","Unrealized P&L","Notional","Collateral posted","Settlement date","Status","Mark source"]
    st.dataframe(marks,use_container_width=True,hide_index=True)
    st.caption("Short-YES mark convention: unrealized P&L = (entry price − current fair value) × notional. These are modeled marks, not live venue quotes.")

with tabs[8]:
    st.markdown("<div class='section'>Expected loss / tranche-risk analytics</div>",unsafe_allow_html=True)
    st.markdown("<div class='callout'><b>Joint-loss model.</b> CARE-HRV-01 now compares the exact independent 64-state baseline with a correlated Gaussian-copula model. The correlated model preserves each event's modeled probability while allowing respiratory, inflation, reimbursement and specialty-drug risks to cluster.</div>",unsafe_allow_html=True)

    r1,r2,r3=st.columns(3)
    with r1:
        risk_equity=st.slider("Risk analytics HRV-E",5,50,20,1)/100
    with r2:
        risk_mezz=st.slider("Risk analytics HRV-M",5,60,30,1)/100
    risk_senior=1.0-risk_equity-risk_mezz
    with r3:
        st.metric("Risk analytics HRV-S",f"{max(risk_senior,0):.0%}")

    if risk_senior >= 0.05:
        baseline=expected_loss_analytics(
            SAMPLE_PORTFOLIO,CARE_HRV_01["target_capital"],risk_equity,risk_mezz,risk_senior,
            expense_rate=WATERFALL_DEFAULTS["expense_rate"]
        )

        st.markdown("#### Correlation assumptions")
        jc1,jc2=st.columns([1,1])
        with jc1:
            corr_scale=st.slider("Correlation strength",0,150,100,5)/100
            sims=st.select_slider("Joint-loss simulations",options=[10000,20000,30000,50000],value=30000)
            correlated=correlated_loss_analytics(
                SAMPLE_PORTFOLIO,CARE_HRV_01["target_capital"],risk_equity,risk_mezz,risk_senior,
                expense_rate=WATERFALL_DEFAULTS["expense_rate"],correlation_scale=corr_scale,
                simulations=sims
            )
            cmetrics=pd.DataFrame([
                ["Respiratory ↔ respiratory","High","TX and national flu can cluster"],
                ["Healthcare PPI ↔ Medical CPI","High","Common medical-inflation factor"],
                ["Inflation ↔ reimbursement","Moderate","Reimbursement adequacy vs cost trend"],
                ["Inflation ↔ specialty drug","Moderate","Shared medical-cost factor"],
                ["Respiratory ↔ inflation","Low","Different primary drivers"],
            ],columns=["Dependency","Prototype level","Rationale"])
            st.dataframe(cmetrics,use_container_width=True,hide_index=True)
        with jc2:
            corr_df=correlation_matrix_frame(SAMPLE_PORTFOLIO,corr_scale)
            corr_display=corr_df.applymap(lambda x:f"{x:.2f}")
            st.caption("Latent Gaussian correlation matrix")
            st.dataframe(corr_display,use_container_width=True)

        st.markdown("#### Independent vs. correlated portfolio risk")
        comparison=pd.DataFrame([
            ["Expected portfolio P&L",baseline["expected_portfolio_pnl"],correlated["expected_portfolio_pnl"]],
            ["Expected principal loss",baseline["expected_principal_loss"],correlated["expected_principal_loss"]],
            ["95% loss quantile",baseline["var95_loss"],correlated["var95_loss"]],
            ["99% loss quantile",baseline["var99_loss"],correlated["var99_loss"]],
        ],columns=["Metric","Independent","Correlated"])
        comparison["Change"]=comparison["Correlated"]-comparison["Independent"]
        for col in ["Independent","Correlated","Change"]:
            comparison[col]=comparison[col].map(money)
        st.dataframe(comparison,use_container_width=True,hide_index=True)

        e1,e2,e3,e4=st.columns(4)
        e1.metric("Correlated expected loss",money(correlated["expected_principal_loss"]),f"{correlated['expected_principal_loss_pct']:.1%} NAV")
        e2.metric("Correlated 95% loss",money(correlated["var95_loss"]),f"{correlated['var95_pct']:.1%} NAV")
        e3.metric("Correlated 99% loss",money(correlated["var99_loss"]),f"{correlated['var99_pct']:.1%} NAV")
        e4.metric("95% expected shortfall",money(correlated["expected_shortfall95"]))

        st.markdown("#### Joint-trigger risk")
        j1,j2,j3,j4=st.columns(4)
        j1.metric("P(2+ events trigger)",f"{correlated['prob_2plus_triggers']:.1%}")
        j2.metric("P(3+ events trigger)",f"{correlated['prob_3plus_triggers']:.1%}")
        j3.metric("P(4+ events trigger)",f"{correlated['prob_4plus_triggers']:.1%}")
        j4.metric("Expected trigger count",f"{correlated['expected_trigger_count']:.2f}")

        st.markdown("#### Tranche risk: independent vs correlated")
        rows=[]
        for cls in ["HRV-E","HRV-M","HRV-S"]:
            b=baseline["tranches"][cls]
            c=correlated["tranches"][cls]
            rows.append([
                cls,
                b["expected_loss"],c["expected_loss"],
                b["impairment_probability"],c["impairment_probability"],
                b["wipeout_probability"],c["wipeout_probability"],
            ])
        tr_df=pd.DataFrame(rows,columns=[
            "Class","Independent EL","Correlated EL",
            "Independent impairment","Correlated impairment",
            "Independent wipeout","Correlated wipeout"
        ])
        for col in ["Independent EL","Correlated EL"]:
            tr_df[col]=tr_df[col].map(money)
        for col in ["Independent impairment","Correlated impairment","Independent wipeout","Correlated wipeout"]:
            tr_df[col]=tr_df[col].map(lambda x:f"{x:.2%}")
        st.dataframe(tr_df,use_container_width=True,hide_index=True)

        st.markdown("<div class='dark'><b>Why this matters:</b> correlation does not materially change each contract's standalone probability; it changes the likelihood that several contracts lose at the same time. That clustering is what threatens junior tranches and eventually Senior protection. The current matrix is an explicit prototype assumption and should be replaced with empirically calibrated dependence as CareFi accumulates history and Oriel/Tynbill data.</div>",unsafe_allow_html=True)
        st.caption(correlated["assumption"])
    else:
        st.error("Equity + Mezzanine leaves less than 5% for Senior.")

with tabs[9]:
    st.markdown("<div class='section'>Cash & collateral dashboard</div>",unsafe_allow_html=True)
    c1,c2,c3=st.columns(3)
    with c1:
        collateral_hedge_ratio=st.slider("MEDUSDi funded hedge ratio",0,100,int(MEDUSDI_DEFAULTS["portfolio_hedge_ratio"]*100),5,key="cash_medusdi_ratio")/100
    with c2:
        reserve_pct=st.slider("Liquidity reserve",0,20,int(TREASURY_ASSUMPTIONS["liquidity_reserve_pct"]*100),1)/100
    with c3:
        cash_yield=st.slider("Annual cash / T-bill yield",0.0,8.0,TREASURY_ASSUMPTIONS["annual_cash_yield"]*100,0.25)/100
    cash_view=cash_collateral_dashboard(
        SAMPLE_PORTFOLIO,CARE_HRV_01["target_capital"],collateral_hedge_ratio,reserve_pct,cash_yield
    )
    c4,c5,c6,c7=st.columns(4)
    c4.metric("Posted event collateral",money(cash_view["posted_collateral"]))
    c5.metric("Funded MEDUSDi hedge",money(cash_view["medusdi_hedge_notional"]))
    c6.metric("Liquidity reserve",money(cash_view["liquidity_reserve"]))
    c7.metric("Free cash",money(cash_view["unencumbered_cash"]))
    y1,y2,y3=st.columns(3)
    y1.metric("Modeled annual cash yield",money(cash_view["annual_cash_yield"]),f"{cash_yield:.2%}")
    y2.metric("Collateral utilization",f"{cash_view['posted_collateral']/CARE_HRV_01['target_capital']:.1%}")
    y3.metric("Free-liquidity ratio",f"{cash_view['unencumbered_cash']/CARE_HRV_01['target_capital']:.1%}")
    release=cash_view["collateral_release"].copy()
    release["collateral_expected_to_release"]=release["collateral_expected_to_release"].map(money)
    release.columns=["Position","Expected settlement / release","Collateral expected to release","Status"]
    st.markdown("#### Collateral release ladder")
    st.dataframe(release,use_container_width=True,hide_index=True)
    st.caption("Prototype assumes fully funded MEDUSDi spot hedges and event collateral equal to modeled capital at risk. Venue-specific collateral and treasury rules would replace these assumptions in production.")

with tabs[10]:
    st.markdown("<div class='section'>Event-driven loss waterfall / investor-return simulator</div>",unsafe_allow_html=True)
    st.markdown("<div class='callout'><b>Actual modeled portfolio.</b> The waterfall is now driven by the six healthcare positions in CARE-HRV-01. Select which events trigger; triggered positions realize their modeled maximum loss, while non-triggered positions realize the modeled contract premium. Net portfolio P&L then flows through HRV-E → HRV-M → HRV-S.</div>",unsafe_allow_html=True)

    cfg1,cfg2=st.columns([1,1],gap="large")
    with cfg1:
        st.markdown("#### Capital structure")
        equity_pct=st.slider("HRV-E · Equity / first-loss",5,50,int(WATERFALL_DEFAULTS["equity_pct"]*100),1)/100
        mezz_pct=st.slider("HRV-M · Mezzanine",5,60,int(WATERFALL_DEFAULTS["mezz_pct"]*100),1)/100
        senior_pct=1.0-equity_pct-mezz_pct
        if senior_pct < 0.05:
            st.error("Equity + Mezzanine leaves less than 5% for Senior. Reduce one of the junior tranches.")
            senior_pct=max(senior_pct,0.0)
        st.metric("HRV-S · Senior",f"{senior_pct:.0%}")
        structure=pd.DataFrame([
            ["HRV-E",equity_pct*CARE_HRV_01["target_capital"],equity_pct],
            ["HRV-M",mezz_pct*CARE_HRV_01["target_capital"],mezz_pct],
            ["HRV-S",senior_pct*CARE_HRV_01["target_capital"],senior_pct],
        ],columns=["Class","Capital","% of vault"])
        structure["Capital"]=structure["Capital"].map(money)
        structure["% of vault"]=structure["% of vault"].map(lambda x:f"{x:.0%}")
        st.dataframe(structure,use_container_width=True,hide_index=True)

    with cfg2:
        st.markdown("#### Distribution assumptions")
        senior_pref=st.slider("HRV-S preferred return",0.0,15.0,WATERFALL_DEFAULTS["senior_pref"]*100,0.5)/100
        mezz_pref=st.slider("HRV-M preferred return",0.0,25.0,WATERFALL_DEFAULTS["mezz_pref"]*100,0.5)/100
        expense_rate=st.slider("Operating expenses / fees",0.0,5.0,WATERFALL_DEFAULTS["expense_rate"]*100,0.25)/100
        st.caption("Portfolio gains/losses come from the six modeled event contracts. The preferred-return assumptions only control distribution of positive net portfolio P&L.")

    valid_structure=abs(equity_pct+mezz_pct+senior_pct-1.0)<1e-6 and senior_pct>=0.05
    if valid_structure:
        st.markdown("#### Preset event combinations")
        event_scenarios=event_waterfall_scenarios(
            SAMPLE_PORTFOLIO,CARE_HRV_01["target_capital"],equity_pct,mezz_pct,senior_pct,
            senior_pref,mezz_pref,expense_rate
        )
        scenario_summary=event_scenarios.groupby("scenario",as_index=False).agg(
            trigger_count=("trigger_count","first"),
            gross_trigger_losses=("gross_trigger_losses","first"),
            nontrigger_gains=("nontrigger_gains","first"),
            portfolio_net_pnl=("portfolio_net_pnl","first"),
            principal_loss_pct=("principal_loss_pct","first"),
        )
        order={"Mild":0,"Moderate":1,"Severe":2}
        scenario_summary["_order"]=scenario_summary["scenario"].map(order)
        scenario_summary=scenario_summary.sort_values("_order").drop(columns="_order")
        for col in ["gross_trigger_losses","nontrigger_gains","portfolio_net_pnl"]:
            scenario_summary[col]=scenario_summary[col].map(money)
        scenario_summary["principal_loss_pct"]=scenario_summary["principal_loss_pct"].map(lambda x:f"{x:.1%}")
        scenario_summary.columns=["Scenario","Events triggered","Triggered-event losses","Non-trigger gains","Net portfolio P&L","Vault principal loss"]
        st.dataframe(scenario_summary,use_container_width=True,hide_index=True)

        returns=event_scenarios.copy()
        fig=px.bar(
            returns,
            x="scenario",
            y="net_return",
            color="tranche",
            barmode="group",
            category_orders={"scenario":["Mild","Moderate","Severe"],"tranche":["HRV-E","HRV-M","HRV-S"]},
            labels={"net_return":"Investor net return","scenario":"Event scenario","tranche":"Class"},
        )
        fig.update_yaxes(tickformat=".0%")
        fig.update_layout(height=360,margin=dict(l=0,r=0,t=20,b=0),legend_title_text="")
        st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})

        st.markdown("#### Build / inspect a trigger combination")
        scenario_name=st.selectbox("Trigger set",["Mild","Moderate","Severe","Custom combination"])
        position_names=list(SAMPLE_PORTFOLIO["position"])
        if scenario_name=="Custom combination":
            triggered=st.multiselect("Events that trigger",position_names,default=EVENT_SCENARIO_PRESETS["Moderate"])
        else:
            triggered=EVENT_SCENARIO_PRESETS[scenario_name]
            st.write("**Triggered:** "+("; ".join(triggered) if triggered else "None"))

        event_result=event_portfolio_scenario(SAMPLE_PORTFOLIO,triggered)
        portfolio_beta=portfolio_healthcare_beta(SAMPLE_PORTFOLIO,MEDUSDI_DEFAULTS["portfolio_hedge_ratio"])
        medusdi_return_default=MEDUSDI_DEFAULTS["scenario_returns"].get(scenario_name,0.08)
        st.markdown("#### MEDUSDi scenario hedge")
        w1,w2=st.columns(2)
        with w1:
            wf_hedge_ratio=st.slider("MEDUSDi hedge ratio for waterfall",0,100,int(MEDUSDI_DEFAULTS["portfolio_hedge_ratio"]*100),5,key="waterfall_medusdi_ratio")/100
        with w2:
            medusdi_return=st.slider("MEDUSDi return in selected scenario",-20,30,int(medusdi_return_default*100),1)/100
        hedge_base=portfolio_healthcare_beta(SAMPLE_PORTFOLIO,wf_hedge_ratio)
        hedge_pnl=medusdi_hedge_pnl(hedge_base["medusdi_hedge_notional"],medusdi_return)

        wf=waterfall_from_event_scenario(
            CARE_HRV_01["target_capital"],event_result,equity_pct,mezz_pct,senior_pct,
            senior_pref,mezz_pref,expense_rate,hedge_pnl=0.0
        )
        wf_hedged=waterfall_from_event_scenario(
            CARE_HRV_01["target_capital"],event_result,equity_pct,mezz_pct,senior_pct,
            senior_pref,mezz_pref,expense_rate,hedge_pnl=hedge_pnl
        )

        k1,k2,k3,k4=st.columns(4)
        k1.metric("Triggered-event losses",money(event_result["gross_trigger_losses"]))
        k2.metric("Non-trigger gains",money(event_result["gross_nontrigger_gains"]))
        k3.metric("Net portfolio P&L",money(event_result["net_pnl"]))
        k4.metric("Vault principal loss",f"{wf['principal_loss_pct']:.1%}",money(wf["principal_loss"]))
        h1,h2,h3=st.columns(3)
        h1.metric("MEDUSDi hedge notional",money(hedge_base["medusdi_hedge_notional"]))
        h2.metric("Scenario MEDUSDi return",f"{medusdi_return:+.1%}")
        h3.metric("MEDUSDi hedge P&L",money(hedge_pnl))

        outcome=pd.DataFrame(event_result["rows"])
        outcome["Outcome"]=outcome["triggered"].map({True:"TRIGGERED",False:"No trigger"})
        outcome["Notional"]=outcome["notional"].map(money)
        outcome["Price"]=outcome["price"].map(lambda x:f"{x:.1%}")
        outcome["Capital at risk"]=outcome["capital_at_risk"].map(money)
        outcome["Realized P&L"]=outcome["realized_pnl"].map(money)
        outcome=outcome[["position","risk_family","Outcome","Notional","Price","Capital at risk","Realized P&L"]]
        outcome.columns=["Position","Risk family","Outcome","Notional","Entry price","Max loss / capital at risk","Realized P&L"]
        st.dataframe(outcome,use_container_width=True,hide_index=True)

        st.markdown("#### Investor waterfall")
        compare=[]
        base_rows={row["tranche"]:row for row in wf["rows"]}
        hedged_rows={row["tranche"]:row for row in wf_hedged["rows"]}
        for tranche in ["HRV-E","HRV-M","HRV-S"]:
            base=base_rows[tranche]
            hedged=hedged_rows[tranche]
            compare.append({
                "Class":tranche,
                "Unhedged principal loss":base["principal_loss"],
                "Hedged principal loss":hedged["principal_loss"],
                "Unhedged investor return":base["net_return"],
                "MEDUSDi-hedged return":hedged["net_return"],
                "Return improvement":hedged["net_return"]-base["net_return"],
            })
        compare_df=pd.DataFrame(compare)
        for col in ["Unhedged principal loss","Hedged principal loss"]:
            compare_df[col]=compare_df[col].map(money)
        for col in ["Unhedged investor return","MEDUSDi-hedged return","Return improvement"]:
            compare_df[col]=compare_df[col].map(lambda x:f"{x:+.1%}")
        st.dataframe(compare_df,use_container_width=True,hide_index=True)

        chart_rows=[]
        for tranche in ["HRV-E","HRV-M","HRV-S"]:
            chart_rows.append({"Class":tranche,"Structure":"Unhedged","Investor return":base_rows[tranche]["net_return"]})
            chart_rows.append({"Class":tranche,"Structure":"MEDUSDi hedged","Investor return":hedged_rows[tranche]["net_return"]})
        compare_chart=px.bar(pd.DataFrame(chart_rows),x="Class",y="Investor return",color="Structure",barmode="group")
        compare_chart.update_yaxes(tickformat=".0%")
        compare_chart.update_layout(height=340,margin=dict(l=0,r=0,t=20,b=0),legend_title_text="")
        st.plotly_chart(compare_chart,use_container_width=True,config={"displayModeBar":False})

        st.markdown("#### Unhedged waterfall detail")
        detail_df=pd.DataFrame(wf["rows"])
        detail_df=detail_df[[
            "tranche","beginning_capital","principal_loss","ending_principal",
            "cash_distribution","net_pnl","net_return"
        ]]
        for col in ["beginning_capital","principal_loss","ending_principal","cash_distribution","net_pnl"]:
            detail_df[col]=detail_df[col].map(money)
        detail_df["net_return"]=detail_df["net_return"].map(lambda x:f"{x:+.1%}")
        detail_df.columns=["Class","Beginning capital","Principal loss","Ending principal","Cash distribution","Net P&L","Investor return"]
        st.dataframe(detail_df,use_container_width=True,hide_index=True)

        st.markdown("<div class='dark'><b>MEDUSDi interpretation:</b> the hedge is modeled as a long healthcare-inflation factor overlay. When MEDUSDi rises in an adverse healthcare-cost scenario, its gain offsets part of the event-book loss before the HRV-E → HRV-M → HRV-S waterfall is applied. This demonstrates the architecture; the beta and scenario-return assumptions still require empirical calibration.<br><br><b>What the severe case now means:</b> Severe is not an arbitrary 60% loss. It assumes all six modeled healthcare events trigger. With the current $10M vault and modeled positions, maximum triggered-event loss is limited to the capital actually at risk in those six positions. That may impair Equity and Mezzanine without reaching Senior—which is precisely the diversification/capital-stack result the prototype should reveal rather than assume.</div>",unsafe_allow_html=True)

        with st.expander("Secondary arbitrary stress override"):
            custom_loss=st.slider("Hypothetical vault principal loss",0,100,40,1,key="secondary_custom_loss")/100
            custom_detail=waterfall_simulation(
                CARE_HRV_01["target_capital"],custom_loss,equity_pct,mezz_pct,senior_pct,
                senior_pref,mezz_pref,0.0,expense_rate
            )
            stress=pd.DataFrame(custom_detail["rows"])[["tranche","principal_loss_pct","net_return"]]
            stress["principal_loss_pct"]=stress["principal_loss_pct"].map(lambda x:f"{x:.1%}")
            stress["net_return"]=stress["net_return"].map(lambda x:f"{x:+.1%}")
            stress.columns=["Class","Principal loss","Investor return"]
            st.dataframe(stress,use_container_width=True,hide_index=True)
            st.caption("This override is retained only for capital-structure stress testing beyond the current six-position portfolio.")

with tabs[11]:
    st.markdown("<div class='section'>Tokenization / Investor Registry</div>",unsafe_allow_html=True)
    st.markdown("<div class='callout'><b>State-machine prototype.</b> HRV-S, HRV-M and HRV-E are modeled as permissioned digital records of economic interests in the regulated vault wrapper. The ledger demonstrates ownership, mint/burn lifecycle, wallet eligibility, NAV synchronization and distributions. It is not yet a deployed smart contract or official transfer-agent record.</div>",unsafe_allow_html=True)

    if "token_registry" not in st.session_state:
        st.session_state.token_registry=[dict(x) for x in DEFAULT_INVESTOR_REGISTRY]
    if "token_events" not in st.session_state:
        st.session_state.token_events=[]
    if "token_nav_hedge_ratio" not in st.session_state:
        st.session_state.token_nav_hedge_ratio=MEDUSDI_DEFAULTS["portfolio_hedge_ratio"]

    token_nav=vault_nav(SAMPLE_PORTFOLIO,CARE_HRV_01["target_capital"],st.session_state.token_nav_hedge_ratio)
    class_econ=token_class_economics(CARE_HRV_01["target_capital"],token_nav["nav"])

    st.markdown("### 1 · HRV-S / HRV-M / HRV-E token economics")
    te=class_econ.copy()
    for col in ["issued_capital","token_supply","class_nav"]:
        te[col]=te[col].map(money)
    te["target_pct"]=te["target_pct"].map(lambda x:f"{x:.0%}")
    te["nav_per_token"]=te["nav_per_token"].map(lambda x:"USD "+f"{x:,.4f}")
    te.columns=["Class","Role","Target %","Issued capital","Token supply","Class NAV","NAV / token","Transfer policy","Lock-up days","Distribution priority","Loss priority"]
    st.dataframe(te,use_container_width=True,hide_index=True)
    st.caption("Prototype convention: initial issue price is USD 1.00 per token. Current NAV/token is synchronized from modeled vault NAV. Legal form, denomination and final class rights remain subject to counsel.")

    st.markdown("### 2 · Mint / burn subscription lifecycle")
    st.markdown("<div class='dark'><b>Lifecycle:</b> "+" → ".join(TOKEN_LIFECYCLE)+"</div>",unsafe_allow_html=True)

    registry=st.session_state.token_registry
    approved=[r["wallet"] for r in registry if r.get("whitelisted")]
    holders=[r["wallet"] for r in registry if float(r.get("tokens",0))>0]
    class_nav_lookup={r["class"]:r["nav_per_token"] for r in class_econ.to_dict("records")}

    l1,l2=st.columns(2,gap="large")
    with l1:
        st.markdown("#### Mint on subscription")
        mint_wallet=st.selectbox("Approved wallet",approved,key="mint_wallet")
        mint_class=st.selectbox("Token class",["HRV-S","HRV-M","HRV-E"],key="mint_class")
        mint_nav=class_nav_lookup[mint_class]
        mint_cash=st.number_input("Subscription cash",min_value=10000.0,max_value=5000000.0,value=250000.0,step=10000.0,key="mint_cash")
        st.metric("Current mint NAV / token","USD "+f"{mint_nav:,.4f}")
        if st.button("Accept subscription & mint",key="mint_btn"):
            try:
                updated,event=mint_tokens(registry,mint_wallet,mint_class,mint_cash,mint_nav)
                st.session_state.token_registry=updated
                st.session_state.token_events.insert(0,event)
                st.success(f"Minted {event['tokens']:,.2f} {mint_class} tokens to {mint_wallet}.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with l2:
        st.markdown("#### Burn on approved redemption")
        burn_wallet=st.selectbox("Holder wallet",holders,key="burn_wallet")
        selected=next(r for r in registry if r["wallet"]==burn_wallet)
        burn_class=selected["class"]
        burn_nav=class_nav_lookup.get(burn_class,1.0)
        max_tokens=float(selected["tokens"])
        burn_amount=st.number_input("Tokens to burn",min_value=0.0,max_value=max_tokens,value=min(100000.0,max_tokens),step=10000.0,key="burn_amount")
        st.metric("Redemption NAV / token","USD "+f"{burn_nav:,.4f}")
        if st.button("Approve redemption & burn",key="burn_btn"):
            try:
                updated,event=burn_tokens(registry,burn_wallet,burn_amount,burn_nav)
                st.session_state.token_registry=updated
                st.session_state.token_events.insert(0,event)
                st.success("Burned "+f"{event['tokens']:,.2f}"+" tokens; modeled proceeds "+money(event["redemption_proceeds"])+".")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.markdown("### 3 · Permissioned wallet registry")
    summary=registry_summary(st.session_state.token_registry)
    rg1,rg2,rg3,rg4=st.columns(4)
    rg1.metric("Registry wallets",summary["wallets"])
    rg2.metric("Whitelisted",summary["approved_wallets"])
    rg3.metric("Active holders",summary["active_holders"])
    rg4.metric("Pending approval",summary["pending_wallets"])

    pending=[r["wallet"] for r in st.session_state.token_registry if not r.get("whitelisted")]
    if pending:
        wl1,wl2=st.columns([1,2])
        with wl1:
            pending_wallet=st.selectbox("Pending wallet",pending,key="pending_wallet")
        with wl2:
            st.write("")
            st.write("")
            if st.button("Approve / whitelist wallet",key="whitelist_btn"):
                try:
                    updated,event=whitelist_wallet(st.session_state.token_registry,pending_wallet)
                    st.session_state.token_registry=updated
                    st.session_state.token_events.insert(0,event)
                    st.success(pending_wallet+" approved and whitelisted.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    reg_df=pd.DataFrame(st.session_state.token_registry)
    reg_df["tokens"]=reg_df["tokens"].map(lambda x:f"{float(x):,.2f}")
    reg_df.columns=["Wallet","Investor / account","Jurisdiction","Eligibility","Whitelisted","Lock-up","Class","Tokens","State"]
    st.dataframe(reg_df,use_container_width=True,hide_index=True)
    st.caption("Transfers are modeled as whitelist-only. KYC/AML, investor eligibility, jurisdiction checks, the official investor register and transfer-agent functions remain regulated off-chain processes.")

    st.markdown("### 4 · NAV + distribution synchronization")
    sync1,sync2,sync3=st.columns(3)
    with sync1:
        token_hedge_ratio=st.slider("NAV MEDUSDi hedge ratio",0,100,int(st.session_state.token_nav_hedge_ratio*100),5,key="token_sync_hedge")/100
        st.session_state.token_nav_hedge_ratio=token_hedge_ratio
    with sync2:
        distributable_cash=st.number_input("Modeled distributable cash",min_value=0.0,max_value=5000000.0,value=750000.0,step=50000.0,key="dist_cash")
    with sync3:
        st.metric("Synchronized vault NAV",money(token_nav["nav"]))

    synced=token_nav_distribution_sync(
        CARE_HRV_01["target_capital"],token_nav["nav"],distributable_cash,
        senior_pref=WATERFALL_DEFAULTS["senior_pref"],mezz_pref=WATERFALL_DEFAULTS["mezz_pref"]
    )
    sync_view=synced.copy()
    for col in ["token_supply","class_nav","distribution"]:
        sync_view[col]=sync_view[col].map(money)
    for col in ["nav_per_token","distribution_per_token","post_distribution_reference_value"]:
        sync_view[col]=sync_view[col].map(lambda x:"USD "+f"{x:,.4f}")
    sync_view.columns=["Class","Token supply","Class NAV","NAV / token","Distribution","Distribution / token","NAV + distribution reference","Sync state"]
    st.dataframe(sync_view,use_container_width=True,hide_index=True)

    st.markdown("#### Token ledger event log")
    if st.session_state.token_events:
        st.dataframe(pd.DataFrame(st.session_state.token_events),use_container_width=True,hide_index=True)
    else:
        st.info("No session events yet. Approve a wallet, mint a subscription or burn a redemption to create ledger events.")

    st.markdown("<div class='dark'><b>On-chain boundary:</b> ownership record, class, token supply, NAV reference, mint/burn state, distribution entitlement and settlement-state references can be represented on-chain. Cash custody, event contracts, KYC/AML, tax records, official NAV approval and the legal investor register remain with regulated service providers.</div>",unsafe_allow_html=True)
    st.caption("Session-state prototype only: actions reset when the Streamlit session resets. No blockchain transaction is submitted and no legal ownership changes occur.")

with tabs[12]:
    st.markdown("<div class='section'>Oriel reference architecture</div>",unsafe_allow_html=True)
    st.markdown("""
**Oriel Workbench → standardized contract payload → CARE-HRV-01 capacity engine → venue execution → vault portfolio.**

The common schema carries contract ID, exposure, risk family, geography, public settlement print, model probability, requested notional, tenor and basis-risk grade. This keeps the Oriel reference function distinct from CareFi's underwriting and capital-allocation function.
""")
    st.code(oriel_payload_json(),language="json")

st.markdown("---")
st.caption("CARE-HRV-01 is a research prototype for institutional discussion. It is not an offering, investment product, executable quote or legal structure.")
