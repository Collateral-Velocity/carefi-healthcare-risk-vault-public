from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from live_data import fetch_oriel_marks
from risk_graph import build_risk_graph,event_table,neighborhood,layered_layout,CLIENT_EXPOSURE_PRESETS,client_basis_score
from vault_engine import SAMPLE_PORTFOLIO,RISK_FAMILY_HEALTHCARE_BETA,correlation_matrix_frame

POOLS=[
 {"pool_id":"CARE-HRV-01","eligible_families":["Respiratory Utilization","Healthcare Inflation","Reimbursement","Pharmacy / Specialty"],"geographies":["Texas","National","North Carolina"],"available_capacity":2100000.0,"minimum_basis_grade":"B+"},
 {"pool_id":"CARE-RESP-01","eligible_families":["Respiratory Utilization"],"geographies":["Texas","National","North Carolina"],"available_capacity":1250000.0,"minimum_basis_grade":"B"},
 {"pool_id":"CARE-INF-01","eligible_families":["Healthcare Inflation","Reimbursement"],"geographies":["National"],"available_capacity":1800000.0,"minimum_basis_grade":"A-"},
]

@st.cache_data(ttl=900,show_spinner=False)
def _state():
    return build_risk_graph(SAMPLE_PORTFOLIO,fetch_oriel_marks(),POOLS,RISK_FAMILY_HEALTHCARE_BETA,correlation_matrix_frame(SAMPLE_PORTFOLIO,1.0),client_exposures=CLIENT_EXPOSURE_PRESETS)

def render_risk_graph_page():
    st.set_page_config(page_title="CareFi · Risk Graph",page_icon="◈",layout="wide")
    st.title("CareFi Risk Graph")
    st.caption("Client economic exposure → public proxy → basis assessment → event contract → hedge factors → eligible capacity")
    g=_state(); s=g["summary"]
    a,b,c,d,e=st.columns(5)
    a.metric("Client exposures",s["client_exposure_count"]); b.metric("Healthcare risks",s["event_count"]); c.metric("Relationships",s["edge_count"])
    d.metric("Capital routable",f"{s['capital_routable_pct']:.0%}"); e.metric("Hedge connected",f"{s['hedge_connected_pct']:.0%}")

    pos=layered_layout(g); ex=[];ey=[];cx=[];cy=[]
    for edge in g["edges"]:
        if edge["source"] not in pos or edge["target"] not in pos: continue
        x0,y0=pos[edge["source"]]; x1,y1=pos[edge["target"]]
        if edge["relation"]=="correlated_with": cx += [x0,x1,None]; cy += [y0,y1,None]
        else: ex += [x0,x1,None]; ey += [y0,y1,None]
    fig=go.Figure()
    fig.add_trace(go.Scatter(x=ex,y=ey,mode="lines",hoverinfo="skip",line=dict(width=1),showlegend=False))
    if cx: fig.add_trace(go.Scatter(x=cx,y=cy,mode="lines",hoverinfo="skip",line=dict(width=2,dash="dot"),name="Correlation"))
    names={"economic_exposure":"Client exposure","public_print":"Public proxy","geography":"Geography","basis_assessment":"Basis assessment","event":"Event contract","risk_family":"Risk family","hedge":"Hedge factor","capital_pool":"Capital pool"}
    for kind in names:
        ns=[n for n in g["nodes"] if n["type"]==kind and n["id"] in pos]
        if not ns: continue
        hover=[]
        for n in ns:
            if kind=="event":
                fv=n.get("fair_value")
                hover.append("<b>"+str(n["label"])+"</b><br>Basis "+str(n.get("basis_grade","—"))+"<br>Oriel FV "+(f"{float(fv):.1%}" if fv is not None else "—")+"<br>Connectivity "+f"{float(n.get('basis_connectivity_score',0)):.0f}/100")
            else: hover.append("<b>"+str(n["label"])+"</b><br>"+names[kind])
        fig.add_trace(go.Scatter(x=[pos[n["id"]][0] for n in ns],y=[pos[n["id"]][1] for n in ns],mode="markers+text",text=[n["label"] for n in ns],textposition="top center",hovertext=hover,hoverinfo="text",marker=dict(size=[22 if kind=="event" else 16 for _ in ns],line=dict(width=1)),name=names[kind]))
    fig.update_xaxes(tickmode="array",tickvals=[0,1,2,3,4,5],ticktext=["Client exposure","Public proxy","Basis","Event contract","Risk factors","Capital pools"],showgrid=False,zeroline=False)
    fig.update_yaxes(showticklabels=False,showgrid=False,zeroline=False)
    fig.update_layout(height=650,margin=dict(l=20,r=20,t=30,b=20),legend_orientation="h",legend_y=-0.12)
    st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})

    st.subheader("Parametric exposure translator")
    preset_lookup={x["label"]:x for x in CLIENT_EXPOSURE_PRESETS}
    selected=st.selectbox("Illustrative client exposure",list(preset_lookup.keys()),key="parametric_client_exposure")
    base=dict(preset_lookup[selected])
    p1,p2=st.columns([1,1])
    with p1:
        amount=st.number_input("Economic amount at risk",min_value=100000.0,max_value=25000000.0,value=float(base["amount_at_risk"]),step=100000.0,format="%.0f")
        effectiveness=st.slider("Estimated hedge effectiveness",0.0,1.0,float(base["hedge_effectiveness"]),0.01)
    with p2:
        st.markdown("**Economic metric**")
        st.write(base["economic_metric"])
        st.markdown("**Mapped public proxy**")
        st.write(base["public_proxy"])
        st.markdown("**Target event contract**")
        st.write(base["target_event"])
    with st.expander("Basis model inputs"):
        q1,q2,q3=st.columns(3)
        publication=q1.slider("Publication quality",0.0,1.0,float(base["publication_quality"]),0.01)
        geography=q2.slider("Geography fit",0.0,1.0,float(base["geography_fit"]),0.01)
        timing=q3.slider("Timing fit",0.0,1.0,float(base["timing_fit"]),0.01)
    translated={**base,"amount_at_risk":float(amount),"hedge_effectiveness":float(effectiveness),"publication_quality":float(publication),"geography_fit":float(geography),"timing_fit":float(timing)}
    basis=client_basis_score(translated)
    m1,m2,m3,m4=st.columns(4)
    m1.metric("Basis Translation Score",f"{basis['score']:.0f}/100",basis["grade"])
    m2.metric("Hedge effectiveness",f"{basis['hedge_effectiveness']:.0%}")
    m3.metric("Amount at risk",f"${float(translated['amount_at_risk']):,.0f}")
    m4.metric("Client type",str(translated["client_type"]))
    path_rows=[
        ["1 · Client exposure",translated["label"],translated["economic_metric"]],
        ["2 · Public proxy",translated["public_proxy"],"Objective independently published reference"],
        ["3 · Basis assessment",basis["grade"]+" · "+f"{basis['score']:.0f}/100","Estimated hedge effectiveness "+f"{basis['hedge_effectiveness']:.0%}"],
        ["4 · Event contract",translated["target_event"],"Standardized Oriel/CareFi event risk"],
        ["5 · Hedge factor","MEDUSDi","Common healthcare-inflation factor where applicable"],
        ["6 · Capacity","CareFi eligible pools","Mandate, basis and concentration constraints"],
    ]
    st.dataframe(pd.DataFrame(path_rows,columns=["Stage","Mapped element","CareFi interpretation"]),use_container_width=True,hide_index=True)
    st.caption("Illustrative underwriting inputs. Production basis scores would be calibrated against client outcomes and realized hedge performance.")

    st.subheader("Risk graph register")
    df=event_table(g)
    if not df.empty:
        df["Oriel FV"]=df["Oriel FV"].map(lambda x:"—" if pd.isna(x) else f"{float(x):.1%}")
        df["MEDUSDi beta"]=df["MEDUSDi beta"].map(lambda x:f"{float(x):.2f}")
        df["Basis connectivity"]=df["Basis connectivity"].map(lambda x:f"{float(x):.0f}/100")
        st.dataframe(df,use_container_width=True,hide_index=True)

    events=[n for n in g["nodes"] if n["type"]=="event"]; lookup={n["label"]:n["id"] for n in events}
    st.subheader("Relationship drill-down")
    label=st.selectbox("Healthcare exposure",list(lookup.keys()))
    nid=lookup[label]; n=next(x for x in events if x["id"]==nid)
    x1,x2,x3,x4=st.columns(4)
    x1.metric("Basis grade",n.get("basis_grade","—")); x2.metric("Connectivity",f"{float(n.get('basis_connectivity_score',0)):.0f}/100")
    x3.metric("MEDUSDi beta",f"{float(n.get('healthcare_beta',0)):.2f}"); x4.metric("Eligible pools",len(n.get("eligible_pools",[])))
    st.dataframe(neighborhood(g,nid),use_container_width=True,hide_index=True)
    st.info("The Risk Graph now starts with the client economic exposure. CareFi maps that exposure to an objective public proxy, scores the basis, standardizes the event contract, and then connects it to hedge factors and eligible institutional capacity.")
