from __future__ import annotations
import pandas as pd

VERSION="CRG-0.1.0"

EVENT_IDS={
 "Texas respiratory utilization":"risk:tx-respiratory",
 "National influenza ED utilization":"risk:us-influenza-ed",
 "Healthcare services PPI shock":"risk:hc-services-ppi",
 "Medical CPI acceleration":"risk:medical-cpi",
 "Medicare reimbursement shortfall":"risk:medicare-reimbursement",
 "Specialty-drug utilization shock":"risk:specialty-drug",
}

def _slug(v):
    return "".join(ch if ch.isalnum() else "-" for ch in str(v).lower()).strip("-")

def _marks(feed):
    payload=(feed or {}).get("payload",feed or {})
    return {str(x.get("position")):x for x in payload.get("marks",[])}

def _basis_score(g):
    return {"A":1.0,"A-":.9,"B+":.8,"B":.7,"B-":.6,"C+":.5}.get(str(g),.5)

def _eligible(pool,family,geo,grade):
    rank={"A":6,"A-":5,"B+":4,"B":3,"B-":2,"C+":1}
    return family in pool.get("eligible_families",[]) and geo in pool.get("geographies",[]) and rank.get(str(grade),0)>=rank.get(str(pool.get("minimum_basis_grade")),0)

def build_risk_graph(portfolio,event_marks,capital_pools,family_betas,corr):
    marks=_marks(event_marks)
    nodes={}
    edges=[]
    def node(i,t,l,**a):
        nodes.setdefault(i,{"id":i,"type":t,"label":l,**a})
    def edge(a,b,r,w=1.0,**x):
        edges.append({"source":a,"target":b,"relation":r,"weight":float(w),**x})

    node("hedge:medusdi","hedge","MEDUSDi")
    event_ids=[]
    for _,row in portfolio.reset_index(drop=True).iterrows():
        pos=str(row["position"]); eid=EVENT_IDS.get(pos,"risk:"+_slug(pos)); event_ids.append(eid)
        mark=marks.get(pos,{})
        family=str(row["risk_family"]); geo=str(row["geography"]); src=str(row["source"])
        grade=str(mark.get("basis_grade") or "B+")
        beta=float(family_betas.get(family,0.0))
        fair=mark.get("fair_value",row.get("model_probability"))
        pools=[]
        for p in capital_pools:
            pid="pool:"+str(p["pool_id"])
            node(pid,"capital_pool",str(p["pool_id"]),available_capacity=float(p.get("available_capacity",0)))
            if _eligible(p,family,geo,grade):
                pools.append(str(p["pool_id"]))
                edge(eid,pid,"eligible_capacity",max(float(p.get("available_capacity",0)),1),available_capacity=float(p.get("available_capacity",0)))
        score=100*(.35*_basis_score(grade)+.25*(1 if mark.get("source_health")=="healthy" else .5)+.20*min(len(pools)/2,1)+.20*(1-min(beta,1)))
        node(eid,"event",pos,contract_id=mark.get("contract_id"),risk_family=family,geography=geo,public_print=src,basis_grade=grade,fair_value=fair,healthcare_beta=beta,eligible_pools=pools,basis_connectivity_score=round(score,1))
        sid="print:"+_slug(src); fid="family:"+_slug(family); gid="geo:"+_slug(geo)
        node(sid,"public_print",src); node(fid,"risk_family",family); node(gid,"geography",geo)
        edge(eid,sid,"settles_to",1,basis_grade=grade); edge(eid,fid,"classified_as"); edge(eid,gid,"located_in")
        if beta>0: edge(eid,"hedge:medusdi","hedge_beta",beta,beta=beta)

    if corr is not None and not corr.empty:
        n=min(len(event_ids),len(corr.index))
        for i in range(n):
            for j in range(i+1,n):
                c=float(corr.iloc[i,j])
                if abs(c)>=.25: edge(event_ids[i],event_ids[j],"correlated_with",abs(c),correlation=c)

    ev=[x for x in nodes.values() if x["type"]=="event"]
    return {"artifact":"carefi.risk_graph.v1","version":VERSION,"nodes":list(nodes.values()),"edges":edges,
      "summary":{"event_count":len(ev),"node_count":len(nodes),"edge_count":len(edges),
      "live_public_reference_pct":sum(x.get("contract_id") is not None for x in ev)/len(ev) if ev else 0,
      "capital_routable_pct":sum(bool(x.get("eligible_pools")) for x in ev)/len(ev) if ev else 0,
      "hedge_connected_pct":sum(float(x.get("healthcare_beta",0))>0 for x in ev)/len(ev) if ev else 0}}

def event_table(graph):
    rows=[]
    for n in graph.get("nodes",[]):
        if n.get("type")!="event": continue
        rows.append({"Contract":n.get("contract_id"),"Risk":n.get("label"),"Family":n.get("risk_family"),"Geography":n.get("geography"),"Public print":n.get("public_print"),"Basis":n.get("basis_grade"),"Oriel FV":n.get("fair_value"),"MEDUSDi beta":n.get("healthcare_beta"),"Eligible pools":", ".join(n.get("eligible_pools",[])) or "None","Basis connectivity":n.get("basis_connectivity_score")})
    return pd.DataFrame(rows)

def neighborhood(graph,event_id):
    m={n["id"]:n for n in graph.get("nodes",[])}
    rows=[]
    for e in graph.get("edges",[]):
        if event_id not in (e["source"],e["target"]): continue
        other=e["target"] if e["source"]==event_id else e["source"]
        detail=""
        if e["relation"]=="correlated_with": detail=f"Correlation {float(e.get('correlation',0)):+.2f}"
        elif e["relation"]=="hedge_beta": detail=f"Healthcare beta {float(e.get('beta',0)):.2f}"
        elif e["relation"]=="eligible_capacity": detail="Available capacity "+f"{float(e.get('available_capacity',0)):,.0f}"
        elif e["relation"]=="settles_to": detail="Basis "+str(e.get("basis_grade",""))
        rows.append({"Relation":e["relation"].replace("_"," "),"Connected node":m.get(other,{}).get("label",other),"Node type":m.get(other,{}).get("type",""),"Detail":detail})
    return pd.DataFrame(rows)

def layered_layout(graph):
    xmap={"public_print":0,"geography":0,"event":1,"risk_family":2,"hedge":2,"capital_pool":3}
    groups={}
    for n in graph.get("nodes",[]): groups.setdefault(xmap.get(n.get("type"),1),[]).append(n)
    out={}
    for x,items in groups.items():
        items=sorted(items,key=lambda z:(z.get("type",""),z.get("label","")))
        for i,n in enumerate(items): out[n["id"]]=(x,(len(items)-1)/2-i)
    return out
