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

st.markdown("<div class='topbar'><div class='brand'>CARE<span>FI</span></div><div class='tag'>HEALTHCARE EVENT RISK VAULT · V0.6</div></div>",unsafe_allow_html=True)
st.markdown("<div class='hero'><h1>"+CARE_HRV_01["name"]+"</h1><p>"+CARE_HRV_01["mandate"]+"</p></div>",unsafe_allow_html=True)

metrics=portfolio_metrics(SAMPLE_PORTFOLIO,CARE_HRV_01["target_capital"])
m1,m2,m3,m4,m5=st.columns(5)
m1.metric("Committed capital",money(CARE_HRV_01["target_capital"]))
m2.metric("Capital deployed",money(metrics["deployed"]))
m3.metric("Available capacity",money(metrics["available"]))
m4.metric("Weighted event probability",f"{metrics['weighted_probability']:.1%}")
m5.metric("Indicative portfolio yield",f"{metrics['indicative_yield']:.1%}")

tabs=st.tabs(["Vault Overview","Mandate & Terms","Request Capacity","Portfolio Impact","Portfolio","Waterfall Simulator","Tokenized Interests","Oriel Reference Layer"])

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

with tabs[2]:
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

with tabs[3]:
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

with tabs[4]:
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

with tabs[5]:
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

with tabs[6]:
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

with tabs[7]:
    st.markdown("<div class='section'>Oriel reference architecture</div>",unsafe_allow_html=True)
    st.markdown("""
**Oriel Workbench → standardized contract payload → CARE-HRV-01 capacity engine → venue execution → vault portfolio.**

The common schema carries contract ID, exposure, risk family, geography, public settlement print, model probability, requested notional, tenor and basis-risk grade. This keeps the Oriel reference function distinct from CareFi's underwriting and capital-allocation function.
""")
    st.code(oriel_payload_json(),language="json")

st.markdown("---")
st.caption("CARE-HRV-01 is a research prototype for institutional discussion. It is not an offering, investment product, executable quote or legal structure.")
