from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from live_data import fetch_oriel_marks
from risk_graph import build_risk_graph,event_table,neighborhood,layered_layout
from vault_engine import SAMPLE_PORTFOLIO,RISK_FAMILY_HEALTHCARE_BETA,correlation_matrix_frame

POOLS=[
 {"pool_id":"CARE-HRV-01","eligible_families":["Respiratory Utilization","Healthcare Inflation","Reimbursement","Pharmacy / Specialty"],"geographies":["Texas","National","North Carolina"],"available_capacity":2100000.0,"minimum_basis_grade":"B+"},
 {"pool_id":"CARE-RESP-01","eligible_families":["Respiratory Utilization"],"geographies":["Texas","National","North Carolina"],"available_capacity":1250000.0,"minimum_basis_grade":"B"},
 {"pool_id":"CARE-INF-01","eligible_families":["Healthcare Inflation","Reimbursement"],"geographies":["National"],"available_capacity":1800000.0,"minimum_basis_grade":"A-"},
]

@st.cache_data(ttl=900,show_spinner=False)
def _state():
    return build_risk_graph(SAMPLE_PORTFOLIO,fetch_oriel_marks(),POOLS,RISK_FAMILY_HEALTHCARE_BETA,correlation_matrix_frame(SAMPLE_PORTFOLIO,1.0))

def render_risk_graph_page():
    st.set_page_config(page_title="CareFi · Risk Graph",page_icon="◈",layout="wide")
    st.title("CareFi Risk Graph")
    st.caption("Healthcare exposure → public print → basis → related risks → hedge factors → eligible capacity")
    g=_state(); s=g["summary"]
    a,b,c,d,e=st.columns(5)
    a.metric("Healthcare risks",s["event_count"]); b.metric("Graph nodes",s["node_count"]); c.metric("Relationships",s["edge_count"])
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
    names={"public_print":"Public print","geography":"Geography","event":"Healthcare risk","risk_family":"Risk family","hedge":"Hedge factor","capital_pool":"Capital pool"}
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
    fig.update_xaxes(tickmode="array",tickvals=[0,1,2,3],ticktext=["Public data / geography","Healthcare risks","Risk factors","Capital pools"],showgrid=False,zeroline=False)
    fig.update_yaxes(showticklabels=False,showgrid=False,zeroline=False)
    fig.update_layout(height=650,margin=dict(l=20,r=20,t=30,b=20),legend_orientation="h",legend_y=-0.12)
    st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})

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
    st.info("The Risk Graph is the protocol relationship layer linking settlement evidence, basis quality, related exposures, hedge sensitivity and capacity eligibility.")
