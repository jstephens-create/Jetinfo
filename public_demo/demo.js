"use strict";
const byId = id => document.getElementById(id);
const { metrics, columns, rows } = JSON.parse(byId("snapshot").textContent);
const incidents = rows.map(row => Object.fromEntries(columns.map((field, i) => [field, row[i]])));
let matches = incidents, page = 0, selected;
const pageSize = 6;
const percent = value => (100 * value).toFixed(1) + "%";
function element(tag, text) {
  const node = document.createElement(tag);
  node.textContent = text;
  return node;
}
byId("total").textContent = metrics.total_incidents;
byId("attainment").textContent = metrics.sla_compliance_pct + "%";
byId("open").textContent = metrics.open_incidents;
for (const priority of ["Critical", "High", "Medium", "Low"]) byId("priority").add(new Option(priority, priority));
function showEvidence(incident) {
  selected = incident;
  const evidence = byId("evidence");
  evidence.replaceChildren();
  byId("download").disabled = !incident;
  for (const row of byId("rows").children) row.setAttribute("aria-pressed", String(row.dataset.id === incident?.incident_id));
  if (!incident) { evidence.append(element("p", "No incidents match these filters.")); return; }
  const facts = document.createElement("dl");
  const outcome = incident.sla_breached === null ? "Pending" : incident.sla_breached ? "Missed" : "Met";
  for (const [key, value] of Object.entries({
    "Priority": incident.priority, "Status": incident.status, "Category": incident.category,
    "Assignment group": incident.assignment_group, "Opened": incident.created_at,
    "SLA target": incident.sla_target_minutes + " min", "Resolution": incident.resolution_time_minutes === null ? "Pending" : incident.resolution_time_minutes + " min",
    "SLA outcome": outcome, "Model score": percent(incident.breach_probability) + " · " + incident.risk_level
  })) facts.append(element("dt", key), element("dd", value));
  evidence.append(element("h3", incident.incident_id), element("p", incident.affected_service), facts,
    element("p", "The model ranks relative breach risk using information available when the incident opened. The recorded SLA outcome comes from the synthetic incident log."));
}
function render() {
  const visible = matches.slice(page * pageSize, (page + 1) * pageSize);
  byId("rows").replaceChildren(...visible.map(incident => {
    const row = document.createElement("button");
    row.dataset.id = incident.incident_id;
    row.append(element("strong", incident.incident_id), element("span", incident.affected_service), element("small", incident.priority));
    row.onclick = () => showEvidence(incident);
    return row;
  }));
  byId("count").textContent = matches.length ? `${page * pageSize + 1}–${page * pageSize + visible.length} of ${matches.length} · Highest model score first` : "0 incidents";
  byId("prev").disabled = page === 0;
  byId("next").disabled = (page + 1) * pageSize >= matches.length;
  showEvidence(visible[0]);
}
function filter() {
  const term = byId("search").value.trim().toLowerCase();
  matches = incidents.filter(i => (!byId("priority").value || i.priority === byId("priority").value)
    && (i.incident_id + " " + i.affected_service).toLowerCase().includes(term));
  page = 0;
  render();
}
byId("search").oninput = byId("priority").onchange = filter;
byId("prev").onclick = () => { page--; render(); };
byId("next").onclick = () => { page++; render(); };
byId("download").onclick = () => {
  const json = JSON.stringify({source: "OKai synthetic incident demo", incident: selected}, null, 2);
  const url = URL.createObjectURL(new Blob([json], {type: "application/json"}));
  const link = document.createElement("a");
  link.href = url; link.download = selected.incident_id + "-evidence.json"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
render();
