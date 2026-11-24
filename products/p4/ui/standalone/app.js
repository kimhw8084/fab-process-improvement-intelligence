"use strict";

const $ = (id) => document.getElementById(id);
const editor = $("investigation-json");
const runButton = $("run-analysis");
const cancelButton = $("cancel-analysis");
const mcpButton = $("run-mcp");
const state = {job: null, evidence: null, loaded: ""};

function showStatus(message) { $("run-status").textContent = message; }
function safeJson(value) { return JSON.stringify(value, null, 2); }
function setLoaded(data, source) {
  editor.value = safeJson(data);
  state.loaded = source;
  $("source-state").textContent = source;
  runButton.disabled = false;
  refreshPreview();
  showStatus("Ready for local analysis.");
}
function refreshPreview() {
  try {
    const data = JSON.parse(editor.value);
    if (!data || Array.isArray(data) || typeof data !== "object") throw new Error("Expected a JSON object.");
    const factors = Array.isArray(data.factors) ? data.factors.map((factor) => `${factor.name || "?"} (${factor.unit || "unit not supplied"})`).join(", ") : "not declared";
    const rows = Array.isArray(data.observations) ? data.observations.length : 0;
    const objectives = Array.isArray(data.objectives) ? data.objectives.length : (data.primary_metric ? 1 : "not declared");
    $("preview").textContent = `${data.objective || "Objective not supplied"}\n${rows.toLocaleString()} supplied observations · ${factors} · ${objectives} objective(s)\nMode: ${data.mode || "SYNTHETIC_DEMO"} · source mappings are not inferred by this preview.`;
    runButton.disabled = false;
  } catch (error) {
    $("preview").textContent = `JSON needs attention: ${error.message}`;
    runButton.disabled = true;
  }
}
function fmt(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value ?? "Not estimable");
  return new Intl.NumberFormat(undefined, {maximumSignificantDigits: 5}).format(value);
}
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function renderClaims(evidence) {
  const host = $("claims"); host.replaceChildren();
  const claims = Array.isArray(evidence.claims) ? evidence.claims : [];
  if (!claims.length) host.append(node("p", "No positive claims were emitted. Review the refusal or limitation details below.", "claim"));
  for (const claim of claims) {
    const item = node("article", undefined, "claim");
    item.append(node("strong", `${claim.category || "Evidence"} · ${claim.certainty || "Unspecified"}`));
    item.append(node("span", claim.statement || "Claim text unavailable."));
    host.append(item);
  }
}
function termTable(sensitivity) {
  const table = node("table");
  const head = node("thead");
  const row = node("tr");
  for (const title of ["Model term", "Estimate", "95% interval"]) row.append(node("th", title));
  head.append(row); table.append(head);
  const body = node("tbody");
  const terms = sensitivity && sensitivity.terms;
  for (const [name, value] of Object.entries(terms || {})) {
    if (name.startsWith("intercept")) continue;
    const tr = node("tr");
    tr.append(node("th", name));
    tr.append(node("td", fmt(value.estimate)));
    tr.append(node("td", Array.isArray(value.ci95) ? `[${fmt(value.ci95[0])}, ${fmt(value.ci95[1])}]` : "Withheld"));
    body.append(tr);
  }
  table.append(body); return table;
}
function renderFactorFigure(sensitivity) {
  const terms = Object.entries((sensitivity && sensitivity.terms) || {}).filter(([name, value]) => !name.startsWith("intercept") && Array.isArray(value.ci95) && value.ci95.length === 2 && value.ci95.every(Number.isFinite));
  if (!terms.length) return null;
  const card = node("article", undefined, "viz-card");
  card.append(node("h3", "D01 · Factor estimate intervals"));
  card.append(node("p", "Intervals use the fitted model's stated covariance and assumptions; terms have different engineering units and should not be ranked by magnitude."));
  const width = 600, left = 190, right = 24, rowHeight = 27, height = 27 + terms.length * rowHeight;
  const values = terms.flatMap(([, item]) => item.ci95);
  const span = Math.max(...values) - Math.min(...values) || 1;
  const low = Math.min(0, ...values), high = Math.max(0, ...values), plotLow = low - span * .06, plotHigh = high + span * .06;
  const x = (v) => left + (v - plotLow) / (plotHigh - plotLow) * (width - left - right);
  const parts = [`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="D01 fitted term estimates and 95 percent intervals. Exact values are in the following table.">`, `<line x1="${x(0)}" x2="${x(0)}" y1="12" y2="${height-5}" stroke="#9aadaa" stroke-dasharray="3 3"/>`];
  terms.forEach(([name, item], i) => {
    const y = 24 + i * rowHeight;
    parts.push(`<text x="${left-9}" y="${y+3}" text-anchor="end" font-size="10" fill="#526c68">${escapeXml(name)}</text>`);
    parts.push(`<line x1="${x(item.ci95[0])}" x2="${x(item.ci95[1])}" y1="${y}" y2="${y}" stroke="#16877c" stroke-width="3"/><circle cx="${x(item.estimate)}" cy="${y}" r="4" fill="#075e59"/>`);
  });
  parts.push("</svg>");
  const svg = document.createElement("div"); svg.innerHTML = parts.join(""); card.append(svg.firstElementChild);
  card.append(termTable(sensitivity));
  return card;
}
function escapeXml(text) { return String(text).replace(/[<>&"']/g, (c) => ({"<":"&lt;",">":"&gt;","&":"&amp;",'"':"&quot;","'":"&apos;"}[c])); }
function renderTradeoffFigure(tradeoffs) {
  const objectives = Array.isArray(tradeoffs && tradeoffs.objective_metrics) ? tradeoffs.objective_metrics : [];
  const values = Array.isArray(tradeoffs && tradeoffs.pareto_values) ? tradeoffs.pareto_values : [];
  if (objectives.length < 2 || values.length === 0) return null;
  const xName = objectives[0].metric, yName = objectives[1].metric;
  const points = values.filter((p) => Number.isFinite(p[xName]) && Number.isFinite(p[yName]));
  if (!points.length) return null;
  const card = node("article", undefined, "viz-card");
  card.append(node("h3", "D03 · Observed objective tradeoff"));
  card.append(node("p", `${objectives[0].direction} ${xName} (${objectives[0].unit}) vs ${objectives[1].direction} ${yName} (${objectives[1].unit}). This plots observed candidates; it is not a predicted optimum.`));
  const W=500,H=230,L=58,R=20,T=12,B=42, xs=points.map((p)=>p[xName]), ys=points.map((p)=>p[yName]);
  const dx=Math.max(...xs)-Math.min(...xs)||1,dy=Math.max(...ys)-Math.min(...ys)||1;
  const px=(v)=>L+(v-Math.min(...xs))/dx*(W-L-R), py=(v)=>T+(Math.max(...ys)-v)/dy*(H-T-B);
  const parts=[`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Observed Pareto candidate scatter plot; exact values are in the following table."><line x1="${L}" y1="${H-B}" x2="${W-R}" y2="${H-B}" stroke="#b6c8c3"/><line x1="${L}" y1="${T}" x2="${L}" y2="${H-B}" stroke="#b6c8c3"/><text x="${(L+W-R)/2}" y="${H-9}" text-anchor="middle" font-size="10" fill="#526c68">${escapeXml(xName)}</text><text x="13" y="${(T+H-B)/2}" transform="rotate(-90 13 ${(T+H-B)/2})" text-anchor="middle" font-size="10" fill="#526c68">${escapeXml(yName)}</text>`];
  for(const p of points) parts.push(`<circle cx="${px(p[xName])}" cy="${py(p[yName])}" r="5" fill="#087e79"><title>${escapeXml(p.id)}: ${escapeXml(fmt(p[xName]))}, ${escapeXml(fmt(p[yName]))}</title></circle>`);
  parts.push("</svg>"); const holder=document.createElement("div"); holder.innerHTML=parts.join(""); card.append(holder.firstElementChild);
  const table=node("table"),thead=node("thead"),tr=node("tr");
  for(const title of ["Candidate",xName,yName])tr.append(node("th",title)); thead.append(tr);table.append(thead);
  const tbody=node("tbody"); for(const p of points){const row=node("tr");row.append(node("th",p.id));row.append(node("td",fmt(p[xName])));row.append(node("td",fmt(p[yName])));tbody.append(row);} table.append(tbody);card.append(table);
  return card;
}
const capabilityNames = [
  ["D01_sensitivity", "D01 · Factor sensitivity"],
  ["D02_supported_region", "D02 · Supported process region"],
  ["D02_observed_process_window", "D02 · Observed feasible settings"],
  ["D03_tradeoffs", "D03 · Objective tradeoffs"],
  ["D04_experiment_proposal", "D04 · Next experiment"],
  ["D05_effectiveness", "D05 · Intervention evaluation"],
  ["validation_split", "Independent validation"]
];
function renderCapabilities(dossier) {
  const host=$("capability-results");host.replaceChildren();
  for(const [key,title] of capabilityNames){
    const value=dossier && dossier[key];const card=node("article",undefined,"capability-card");
    const header=node("header");header.append(node("h3",title));header.append(node("span",value && value.status ? value.status : "NOT REQUESTED"));card.append(header);
    const detail=value && (value.reason || value.interpretation || value.method || value.design || value.qualification || value.coverage_limitation);
    card.append(node("p",detail || "Inspect the evidence object for method, diagnostics, constraints, and limitations."));
    if(value){const disclosure=node("details",undefined,"capability-evidence"),summary=node("summary","Inspect capability evidence JSON"),pre=node("pre");
      disclosure.append(summary,pre);disclosure.addEventListener("toggle",()=>{if(disclosure.open&&!pre.textContent)pre.textContent=safeJson(value);});card.append(disclosure);}host.append(card);
  }
}
function renderEvidence(evidence) {
  state.evidence=evidence;
  $("results").hidden=false;
  const status=evidence.status || "ERROR";
  const banner=$("result-banner");banner.dataset.status=status;banner.replaceChildren(node("span",`${status} · ${evidence.investigation_id || "Investigation"}`),node("span",(evidence.limitations||[]).join(" ")||"Review assumptions and source scope before use."));
  renderClaims(evidence);
  const artifact=(evidence.artifacts||[]).find((item)=>item && item.type==="p4_decision_dossier")||{};
  const visuals=$("visuals");visuals.replaceChildren();
  const factor=renderFactorFigure(artifact.D01_sensitivity);if(factor)visuals.append(factor);
  const tradeoff=renderTradeoffFigure(artifact.D03_tradeoffs);if(tradeoff)visuals.append(tradeoff);
  renderCapabilities(artifact);
  const rawDetails=$("raw-json").closest("details");
  $("raw-json").textContent=rawDetails.open?safeJson(evidence):"";
  $("export-result").disabled=false;
  $("results-heading").focus?.();
  $("results").scrollIntoView({behavior:"smooth",block:"start"});
}
$("raw-json").closest("details").addEventListener("toggle",()=>{
  if($("raw-json").closest("details").open&&state.evidence&&!$("raw-json").textContent)
    $("raw-json").textContent=safeJson(state.evidence);
});
async function responseJson(response) {
  const body=await response.json();
  if(!response.ok)throw new Error(body.error||`Request failed (${response.status})`);
  return body;
}
$("load-demo").addEventListener("click",async()=>{
  showStatus("Loading the bundled synthetic example…");
  try{setLoaded(await responseJson(await fetch("/api/demo",{cache:"no-store"})),"Synthetic fixture");}
  catch(error){showStatus(`Could not load example: ${error.message}`);}
});
$("file-input").addEventListener("change",async(event)=>{
  const file=event.target.files && event.target.files[0];if(!file)return;
  if(file.size>2*1024*1024){showStatus("File exceeds the 2 MiB local input limit.");return;}
  try{const data=JSON.parse(await file.text());if(!data||Array.isArray(data)||typeof data!=="object")throw new Error("Expected a JSON object.");setLoaded(data,`Local file · ${file.name}`);}
  catch(error){showStatus(`Could not load file: ${error.message}`);}
});
editor.addEventListener("input",refreshPreview);
async function runJob(endpoint,payload,label){
  runButton.disabled=true;mcpButton.disabled=true;showStatus(`Starting ${label}…`);
  try{
    const started=await responseJson(await fetch(endpoint,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}));
    state.job=started.job_id;cancelButton.hidden=false;showStatus(`${label} running…`);
    while(state.job){await new Promise((resolve)=>setTimeout(resolve,350));const job=await responseJson(await fetch(started.poll,{cache:"no-store"}));
      if(job.status==="RUNNING")continue;
      state.job=null;cancelButton.hidden=true;runButton.disabled=!editor.value.trim();
      if(job.result)renderEvidence(job.result);else showStatus(job.error?`Analysis failed (${job.error}).`:`Analysis ${job.status.toLowerCase()}.`);
      break;
    }
  }catch(error){state.job=null;cancelButton.hidden=true;runButton.disabled=!editor.value.trim();showStatus(`${label} could not start: ${error.message}`);}
  loadMcpState();
}
runButton.addEventListener("click",async()=>{
  let payload;try{payload=JSON.parse(editor.value);}catch(error){showStatus(`Fix JSON syntax before analysis: ${error.message}`);return;}
  await runJob("/api/jobs",payload,"Local analysis");
});
mcpButton.addEventListener("click",async()=>{await runJob("/api/mcp-jobs",{},"Configured read-only acquisition and P4 analysis");});
cancelButton.addEventListener("click",async()=>{
  if(!state.job)return;showStatus("Requesting cancellation…");
  try{await responseJson(await fetch(`/api/jobs/${state.job}/cancel`,{method:"POST"}));showStatus("Cancellation requested; waiting for local analysis to stop.");}
  catch(error){showStatus(`Cancellation request failed: ${error.message}`);}
});
$("export-result").addEventListener("click",()=>{
  if(!state.evidence)return;
  const blob=new Blob([safeJson(state.evidence)+"\n"],{type:"application/json"});const url=URL.createObjectURL(blob);const a=document.createElement("a");
  a.href=url;a.download=`p4-evidence-${state.evidence.investigation_id||"result"}.json`;document.body.append(a);a.click();a.remove();URL.revokeObjectURL(url);
});
async function loadPreflight(){
  try{const report=await responseJson(await fetch("/api/preflight",{cache:"no-store"}));const host=$("preflight");
    const mcp=await responseJson(await fetch("/api/mcp/status",{cache:"no-store"}));
    const title=node("strong",`Internal source qualification · ${mcp.qualification_status || report.status || "PENDING_INTERNAL"}`);host.append(title,node("div",mcp.message || "No site configuration is loaded."));
    const ul=node("ul");for(const reason of report.reasons||[])ul.append(node("li",reason));host.append(ul);
  }catch(_){$("preflight").textContent="Qualification status is unavailable.";}
}
async function loadMcpState(){
  try{const info=await responseJson(await fetch("/api/mcp/status",{cache:"no-store"}));
    $("mcp-state").textContent=info.state||"PENDING_INTERNAL";$("mcp-message").textContent=info.message||"MCP configuration unavailable.";
    mcpButton.disabled=info.enabled!==true||Boolean(state.job);
  }catch(_){$("mcp-state").textContent="Unavailable";$("mcp-message").textContent="MCP acquisition status could not be checked.";mcpButton.disabled=true;}
}
loadMcpState();
loadPreflight();
