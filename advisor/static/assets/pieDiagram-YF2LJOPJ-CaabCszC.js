import{p as N}from"./chunk-TMUBEWPD-C2gkicZ3.js";import{g as B,s as U,a as K,b as V,n as Z,o as j,_ as i,l as C,c as q,C as H,G as J,I as Q,K as z,e as X,v as Y,L as ee,D as te}from"./mermaid.core-C1Q4jY2B.js";import{p as ae}from"./gitGraph-YCYPL57B-CEbOJcov.js";import{o as re}from"./d3-scale-35hnzshu.js";import"./index-CujIHyOL.js";import"./min-BLKH_CxR.js";import"./_baseUniq-Fp2NxPG1.js";var ie=te.pie,D={sections:new Map,showData:!1},h=D.sections,w=D.showData,se=structuredClone(ie),oe=i(()=>structuredClone(se),"getConfig"),ne=i(()=>{h=new Map,w=D.showData,Y()},"clear"),le=i(({label:e,value:a})=>{h.has(e)||(h.set(e,a),C.debug(`added new section: ${e}, with value: ${a}`))},"addSection"),ce=i(()=>h,"getSections"),pe=i(e=>{w=e},"setShowData"),de=i(()=>w,"getShowData"),G={getConfig:oe,clear:ne,setDiagramTitle:j,getDiagramTitle:Z,setAccTitle:V,getAccTitle:K,setAccDescription:U,getAccDescription:B,addSection:le,getSections:ce,setShowData:pe,getShowData:de},ge=i((e,a)=>{N(e,a),a.setShowData(e.showData),e.sections.map(a.addSection)},"populateDb"),ue={parse:i(async e=>{const a=await ae("pie",e);C.debug(a),ge(a,G)},"parse")},fe=i(e=>`
  .pieCircle{
    stroke: ${e.pieStrokeColor};
    stroke-width : ${e.pieStrokeWidth};
    opacity : ${e.pieOpacity};
  }
  .pieOuterCircle{
    stroke: ${e.pieOuterStrokeColor};
    stroke-width: ${e.pieOuterStrokeWidth};
    fill: none;
  }
  .pieTitleText {
    text-anchor: middle;
    font-size: ${e.pieTitleTextSize};
    fill: ${e.pieTitleTextColor};
    font-family: ${e.fontFamily};
  }
  .slice {
    font-family: ${e.fontFamily};
    fill: ${e.pieSectionTextColor};
    font-size:${e.pieSectionTextSize};
    // fill: white;
  }
  .legend text {
    fill: ${e.pieLegendTextColor};
    font-family: ${e.fontFamily};
    font-size: ${e.pieLegendTextSize};
  }
`,"getStyles"),he=fe,me=i(e=>{const a=[...e.entries()].map(s=>({label:s[0],value:s[1]})).sort((s,n)=>n.value-s.value);return ee().value(s=>s.value)(a)},"createPieArcs"),ve=i((e,a,F,s)=>{C.debug(`rendering pie chart
`+e);const n=s.db,$=q(),y=H(n.getConfig(),$.pie),T=40,o=18,d=4,c=450,m=c,v=J(a),l=v.append("g");l.attr("transform","translate("+m/2+","+c/2+")");const{themeVariables:r}=$;let[A]=Q(r.pieOuterStrokeWidth);A??(A=2);const _=y.textPosition,g=Math.min(m,c)/2-T,W=z().innerRadius(0).outerRadius(g),I=z().innerRadius(g*_).outerRadius(g*_);l.append("circle").attr("cx",0).attr("cy",0).attr("r",g+A/2).attr("class","pieOuterCircle");const b=n.getSections(),S=me(b),L=[r.pie1,r.pie2,r.pie3,r.pie4,r.pie5,r.pie6,r.pie7,r.pie8,r.pie9,r.pie10,r.pie11,r.pie12],p=re(L);l.selectAll("mySlices").data(S).enter().append("path").attr("d",W).attr("fill",t=>p(t.data.label)).attr("class","pieCircle");let E=0;b.forEach(t=>{E+=t}),l.selectAll("mySlices").data(S).enter().append("text").text(t=>(t.data.value/E*100).toFixed(0)+"%").attr("transform",t=>"translate("+I.centroid(t)+")").style("text-anchor","middle").attr("class","slice"),l.append("text").text(n.getDiagramTitle()).attr("x",0).attr("y",-400/2).attr("class","pieTitleText");const x=l.selectAll(".legend").data(p.domain()).enter().append("g").attr("class","legend").attr("transform",(t,u)=>{const f=o+d,O=f*p.domain().length/2,P=12*o,R=u*f-O;return"translate("+P+","+R+")"});x.append("rect").attr("width",o).attr("height",o).style("fill",p).style("stroke",p),x.data(S).append("text").attr("x",o+d).attr("y",o-d).text(t=>{const{label:u,value:f}=t.data;return n.getShowData()?`${u} [${f}]`:u});const M=Math.max(...x.selectAll("text").nodes().map(t=>(t==null?void 0:t.getBoundingClientRect().width)??0)),k=m+T+o+d+M;v.attr("viewBox",`0 0 ${k} ${c}`),X(v,c,k,y.useMaxWidth)},"draw"),Se={draw:ve},Ae={parser:ue,db:G,renderer:Se,styles:he};export{Ae as diagram};
