/* ReproLens frontend. Every diagnosis shown comes from a real /investigate
   call. Example cases travel through the real S3 -> Lambda -> Bedrock
   pipeline; picking one only pre-fills the upload slots with real fixture
   files. No mocked responses, no fabricated stats -- confidence stats and
   evidence coverage are computed from the actual API response. */

const ARTIFACT_NAMES = [
  "config.yaml",
  "requirements.txt",
  "train.log",
  "dataset_metadata.json",
  "traceback.txt",
];

const STATUS_LABELS = {
  failed: "FAILED",
  degraded: "DEGRADED",
  suspicious: "SUSPICIOUS",
  healthy: "HEALTHY",
  insufficient_evidence: "INSUFFICIENT EVIDENCE",
};

const CONFIDENCE_PCT = { high: 90, medium: 55, low: 25 };

const PREFLIGHT_TITLES = {
  class_count_consistency: "Class count consistency",
  cuda_compatibility: "CUDA compatibility",
};

const state = {
  selectedFiles: {},
  investigationId: null,
  experimentName: "",
  lastDiagnosis: null,
  historyItems: [],
};

/* ---------- Theme ---------- */

function initTheme() {
  const saved = localStorage.getItem("reprolens-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("reprolens-theme", next);
    requestAnimationFrame(() => { drawHeroConnectors(); if (state.lastDiagnosis) drawEvidenceConnectors(); });
  });
}

/* ---------- API ---------- */

function apiBase() {
  const base = window.REPROLENS_API_BASE;
  if (!base || base.startsWith("REPLACE_WITH")) {
    throw { error: "Not configured", detail: "REPROLENS_API_BASE is not set. Edit frontend/config.js after deploying the backend." };
  }
  return base.replace(/\/$/, "");
}

function setConnection(active) {
  const badge = document.getElementById("connection-badge");
  badge.textContent = active ? "● Connected" : "● Idle";
  badge.className = "conn-badge " + (active ? "conn-active" : "conn-idle");
}

/* ---------- Navigation ---------- */

function showPage(id) {
  document.querySelectorAll(".page").forEach((el) => el.classList.remove("active"));
  document.getElementById(id).classList.add("active");
  document.querySelectorAll(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.page === id));
  if (id === "page-home") requestAnimationFrame(drawHeroConnectors);
  if (id === "page-progress") requestAnimationFrame(drawPflowConnectors);
}

function cssId(name) { return name.replace(/[^a-zA-Z0-9]/g, "-"); }

/* ---------- Connector drawing (shared by hero diagram + evidence graph) ---------- */

function drawConnectors(container, svg, pairs, dataAttrs) {
  const containerRect = container.getBoundingClientRect();
  svg.setAttribute("width", containerRect.width);
  svg.setAttribute("height", containerRect.height);
  svg.innerHTML = "";
  pairs.forEach(([fromEl, toEl], i) => {
    if (!fromEl || !toEl) return;
    const f = fromEl.getBoundingClientRect();
    const t = toEl.getBoundingClientRect();
    const x1 = f.left + f.width / 2 - containerRect.left;
    const y1 = f.top + f.height / 2 - containerRect.top;
    const x2 = t.left + t.width / 2 - containerRect.left;
    const y2 = t.top + t.height / 2 - containerRect.top;
    const dx = (x2 - x1) * 0.5;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`);
    path.setAttribute("class", "connector-line");
    if (dataAttrs && dataAttrs[i] && dataAttrs[i].index != null) path.setAttribute("data-index", dataAttrs[i].index);
    svg.appendChild(path);
    const len = path.getTotalLength();
    path.style.strokeDasharray = `${len}`;
    path.style.strokeDashoffset = `${len}`;
    requestAnimationFrame(() => {
      path.style.transition = "stroke-dashoffset 0.9s cubic-bezier(.16,.8,.24,1), opacity 0.4s ease";
      path.style.strokeDashoffset = "0";
      path.style.opacity = "0.55";
    });
  });
}

function drawHeroConnectors() {
  const container = document.getElementById("hero-diagram");
  const svg = document.getElementById("hero-connectors");
  if (!container || !svg || !container.offsetParent) return;
  const orb = container.querySelector('[data-node="hero-orb"]');
  const output = container.querySelector('[data-node="hero-output"]');
  const chips = ["hc1", "hc2", "hc3", "hc4", "hc5"].map((n) => container.querySelector(`[data-node="${n}"]`));
  drawConnectors(container, svg, [...chips.map((c) => [c, orb]), [orb, output]]);
}

function drawEvidenceConnectors() {
  const container = document.getElementById("evidence-graph");
  const svg = document.getElementById("evidence-connectors");
  if (!container || !svg) return;
  const claim = container.querySelector(".eg-claim");
  const nodes = Array.from(container.querySelectorAll(".eg-node"));
  const signal = container.querySelector(".eg-signal");
  const pairs = [];
  const dataAttrs = [];
  nodes.forEach((n, i) => { pairs.push([claim, n]); dataAttrs.push({ index: i }); });
  if (signal) nodes.forEach((n, i) => { pairs.push([n, signal]); dataAttrs.push({ index: i }); });
  drawConnectors(container, svg, pairs, dataAttrs);
}

function renderPflowArtifacts() {
  const wrap = document.getElementById("pflow-artifacts");
  if (!wrap || wrap.childElementCount) return;
  const icons = { "config.yaml": "i-file", "requirements.txt": "i-cpu", "train.log": "i-chart", "dataset_metadata.json": "i-db", "traceback.txt": "i-warn" };
  ARTIFACT_NAMES.forEach((name, i) => {
    const chip = document.createElement("div");
    chip.className = "pflow-chip";
    chip.dataset.node = `pf-art-${i}`;
    chip.dataset.artifact = name;
    chip.innerHTML = `<svg class="icon"><use href="#${icons[name] || "i-file"}"/></svg>${name}`;
    wrap.appendChild(chip);
  });
}

function drawPflowConnectors() {
  const container = document.getElementById("pflow");
  const svg = document.getElementById("pflow-connectors");
  if (!container || !svg || !container.offsetParent) return;
  const chips = Array.from(container.querySelectorAll(".pflow-chip")).filter((c) => state.selectedFiles[c.dataset.artifact]);
  const bundle = container.querySelector('[data-node="pf-bundle"]');
  const preflight = container.querySelector('[data-node="pf-preflight"]');
  const bedrock = container.querySelector('[data-node="pf-bedrock"]');
  drawConnectors(container, svg, [...chips.map((c) => [c, bundle]), [bundle, preflight], [preflight, bedrock]]);
}

function setFlowStage(stage) {
  const container = document.getElementById("pflow");
  if (!container) return;
  const order = ["chips", "bundle", "preflight", "bedrock"];
  const idx = order.indexOf(stage);
  container.querySelectorAll(".pflow-chip").forEach((c) => c.classList.toggle("is-lit", idx >= 0));
  container.querySelector('[data-flow="bundle"]').classList.toggle("is-lit", idx >= 1);
  container.querySelector('[data-flow="preflight"]').classList.toggle("is-lit", idx >= 2);
  container.querySelector('[data-flow="bedrock"]').classList.toggle("is-lit", idx >= 3);
  requestAnimationFrame(drawPflowConnectors);
}

window.addEventListener("resize", () => {
  drawHeroConnectors();
  if (document.getElementById("page-result").classList.contains("active")) drawEvidenceConnectors();
  if (document.getElementById("page-progress").classList.contains("active")) drawPflowConnectors();
});

/* ---------- Upload grid ---------- */

function renderUploadGrid() {
  const grid = document.getElementById("upload-grid");
  grid.innerHTML = "";
  ARTIFACT_NAMES.forEach((name) => {
    const card = document.createElement("div");
    card.className = "upload-card";
    card.id = `card-${cssId(name)}`;
    card.innerHTML = `
      <div class="upload-card-name">${name}</div>
      <div class="upload-card-status" id="status-${cssId(name)}">Not uploaded</div>
      <input type="file" id="input-${cssId(name)}" />
    `;
    grid.appendChild(card);
    card.querySelector("input").addEventListener("change", (e) => { if (e.target.files[0]) setSelectedFile(name, e.target.files[0]); });
    card.addEventListener("dragover", (e) => e.preventDefault());
    card.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files[0]) setSelectedFile(name, e.dataTransfer.files[0]); });
  });
}

function setSelectedFile(name, file) {
  state.selectedFiles[name] = file;
  document.getElementById(`status-${cssId(name)}`).textContent = `✓ ${file.name}`;
  document.getElementById(`card-${cssId(name)}`).classList.add("filled");
  updateInvestigateButton();
}

function updateInvestigateButton() {
  const count = Object.keys(state.selectedFiles).length;
  document.getElementById("investigate-btn").disabled = count === 0;
  document.getElementById("upload-count").textContent = `${count} of ${ARTIFACT_NAMES.length} uploaded`;
}

async function loadExampleFixture(fixtureName) {
  state.selectedFiles = {};
  renderUploadGrid();
  showPage("page-new");
  for (const artifactName of ARTIFACT_NAMES) {
    try {
      const resp = await fetch(`assets/fixtures/${fixtureName}/${artifactName}`);
      if (!resp.ok) continue;
      const blob = await resp.blob();
      setSelectedFile(artifactName, new File([blob], artifactName, { type: "text/plain" }));
    } catch (e) { /* fixture genuinely doesn't include this artifact */ }
  }
  document.getElementById("experiment-name").value = fixtureName.replace(/_/g, " ").replace(/^\d+\s*/, "");
}

/* ---------- Investigation run ---------- */

function setStage(id, s) { document.getElementById(id).dataset.state = s; }

async function runInvestigation() {
  const experimentName = document.getElementById("experiment-name").value || "unnamed_experiment";
  showPage("page-progress");
  setConnection(true);
  document.getElementById("progress-title").textContent = `Investigating — ${experimentName}`;
  ["pstage-1", "pstage-2", "pstage-3"].forEach((id) => setStage(id, "pending"));
  setStage("pstage-1", "active");
  renderPflowArtifacts();
  requestAnimationFrame(() => setFlowStage("bundle"));

  try {
    const createResp = await fetch(`${apiBase()}/investigations`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ experiment_name: experimentName }),
    });
    if (!createResp.ok) throw await toApiError(createResp);
    const { investigation_id, upload_urls } = await createResp.json();
    state.investigationId = investigation_id;
    state.experimentName = experimentName;
    document.getElementById("investigation-id-badge").textContent = investigation_id;

    for (const [artifactName, file] of Object.entries(state.selectedFiles)) {
      const putResp = await fetch(upload_urls[artifactName], { method: "PUT", body: file });
      if (!putResp.ok) throw { error: "Upload failed", detail: `Could not upload ${artifactName} to S3.`, investigation_id };
    }
    document.getElementById("pmeta-1").textContent = `${Object.keys(state.selectedFiles).length} artifacts received`;
    setStage("pstage-1", "done");
    setStage("pstage-2", "active");
    setFlowStage("preflight");

    const investigateResp = await fetch(`${apiBase()}/investigations/${investigation_id}/investigate`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ experiment_name: experimentName }),
    });
    if (!investigateResp.ok) throw await toApiError(investigateResp);
    const diagnosis = await investigateResp.json();

    setStage("pstage-2", "done");
    setStage("pstage-3", "done");
    setFlowStage("bedrock");

    state.lastDiagnosis = diagnosis;
    renderDiagnosis(diagnosis);
    showPage("page-result");
    refreshHistory();
  } catch (err) {
    showError(err);
  } finally {
    setConnection(false);
  }
}

async function toApiError(resp) {
  try { return await resp.json(); }
  catch { return { error: "Request failed", detail: `HTTP ${resp.status}`, investigation_id: state.investigationId }; }
}

function showError(err) {
  document.getElementById("error-message").textContent = err.error || "Investigation failed";
  document.getElementById("error-detail").textContent = err.detail || err.message || "";
  document.getElementById("error-investigation-id").textContent = err.investigation_id || state.investigationId || "unknown";
  showPage("page-error");
}

/* ---------- Diagnosis rendering ---------- */

function renderDiagnosis(diagnosis) {
  const badge = document.getElementById("status-badge");
  badge.textContent = STATUS_LABELS[diagnosis.experiment_status] || diagnosis.experiment_status;
  badge.className = "status-badge status-" + diagnosis.experiment_status;

  document.getElementById("primary-diagnosis-text").textContent = diagnosis.primary_diagnosis;
  const evidence = diagnosis.evidence || [];
  const uniqueArtifacts = new Set(evidence.map((e) => e.artifact));
  const topEvidence = evidence[0];
  document.getElementById("diagnosis-summary").textContent = topEvidence ? topEvidence.significance : "";

  const preflight = diagnosis._preflight || [];
  const contradictions = preflight.filter((f) => f.result === "contradiction").length;

  document.getElementById("coverage-fraction").textContent =
    `${ARTIFACT_NAMES.filter((n) => state.selectedFiles[n] || uniqueArtifacts.has(n)).length}/${ARTIFACT_NAMES.length} artifacts`;
  document.getElementById("finding-stats").textContent =
    `${evidence.length} observation${evidence.length === 1 ? "" : "s"} · ${uniqueArtifacts.size} artifact${uniqueArtifacts.size === 1 ? "" : "s"} · ${contradictions} critical contradiction${contradictions === 1 ? "" : "s"}`;

  document.getElementById("confidence-level-text").textContent = diagnosis.confidence.toUpperCase();
  document.getElementById("confidence-fill").style.width = `${CONFIDENCE_PCT[diagnosis.confidence] || 40}%`;
  const missingCount = (diagnosis.missing_information || []).length;
  document.getElementById("confidence-stats").innerHTML = `
    <div><span class="confidence-stat-value">${evidence.length}</span><span class="confidence-stat-label">Supporting evidence</span></div>
    <div><span class="confidence-stat-value">${uniqueArtifacts.size}</span><span class="confidence-stat-label">Artifacts involved</span></div>
    <div><span class="confidence-stat-value">${contradictions}</span><span class="confidence-stat-label">Contradictions</span></div>
    <div><span class="confidence-stat-value">${missingCount}</span><span class="confidence-stat-label">Missing evidence</span></div>
  `;

  const missingBlock = document.getElementById("missing-info-banner");
  const missingList = document.getElementById("missing-info-list");
  missingList.innerHTML = "";
  if (missingCount > 0) {
    document.getElementById("missing-info-title").textContent = missingCount === 1 ? "1 piece of information is missing" : `${missingCount} pieces of information are missing`;
    (diagnosis.missing_information || []).forEach((m) => { const li = document.createElement("li"); li.textContent = m; missingList.appendChild(li); });
    missingBlock.style.display = "flex";
  } else {
    missingBlock.style.display = "none";
  }

  renderPreflight(preflight);
  renderEvidenceGraph(diagnosis);

  const hyps = document.getElementById("hypotheses-list");
  hyps.innerHTML = "";
  (diagnosis.competing_hypotheses || []).forEach((h) => {
    const card = document.createElement("div");
    card.className = "hypothesis-card";
    card.innerHTML = `<div><div class="hypothesis-name">${h.hypothesis}</div><div class="hypothesis-reason">${h.reason}</div></div><div class="hypothesis-confidence conf-${h.confidence}">${h.confidence.toUpperCase()}</div>`;
    hyps.appendChild(card);
  });

  const checks = document.getElementById("checks-list");
  checks.innerHTML = "";
  (diagnosis.recommended_checks || []).forEach((c) => { const li = document.createElement("li"); li.textContent = c; checks.appendChild(li); });

  document.getElementById("explanation-block").style.display = "none";
  closeInspector();
}

function renderPreflight(findings) {
  const list = document.getElementById("preflight-list");
  list.innerHTML = "";
  if (!findings.length) {
    list.innerHTML = `<p class="hint">No deterministic checks applied to this experiment.</p>`;
    return;
  }
  findings.forEach((f) => {
    const item = document.createElement("div");
    item.className = `preflight-item ${f.result}`;
    const icon = f.result === "contradiction" ? "i-warn" : f.result === "consistent" ? "i-check" : "i-info";
    let inner = `<svg class="icon"><use href="#${icon}"/></svg><div>
      <div class="preflight-title">${PREFLIGHT_TITLES[f.check] || f.check}</div>
      <div class="preflight-detail">${f.detail || f.reason || (f.result === "contradiction" ? "Contradiction detected between two artifacts." : "")}</div>`;
    if (f.result === "contradiction" && f.evidence && f.evidence.length === 2) {
      inner += `<div class="preflight-evidence-pair">
        <div>${f.evidence[0].artifact}<br/>${f.evidence[0].observed_value}</div>
        <div class="preflight-vs">≠</div>
        <div>${f.evidence[1].artifact}<br/>${f.evidence[1].observed_value}</div>
      </div>`;
    }
    inner += `</div>`;
    item.innerHTML = inner;
    list.appendChild(item);
  });
}

function renderEvidenceGraph(diagnosis) {
  const graph = document.getElementById("evidence-graph");
  graph.querySelectorAll(".eg-claim, .eg-row, .eg-signal").forEach((el) => el.remove());

  const claim = document.createElement("div");
  claim.className = "eg-claim";
  claim.innerHTML = `<span class="eg-claim-eyebrow">Diagnosis</span>${diagnosis.primary_diagnosis}`;
  graph.appendChild(claim);

  const row = document.createElement("div");
  row.className = "eg-row";
  (diagnosis.evidence || []).forEach((ev, i) => {
    const node = document.createElement("div");
    node.className = "eg-node";
    node.dataset.index = i;
    node.innerHTML = `<div class="eg-artifact">${ev.artifact}</div><div class="eg-location">${ev.field_or_location}</div><div class="eg-value">${ev.observed_value}</div>`;
    node.addEventListener("click", () => { openInspector(ev); highlightEvidencePath(i); });
    row.appendChild(node);
  });
  graph.appendChild(row);

  if ((diagnosis.evidence || []).length > 0) {
    const signal = document.createElement("div");
    signal.className = "eg-signal";
    signal.textContent = `${diagnosis.evidence.length} observation${diagnosis.evidence.length === 1 ? "" : "s"} supporting this diagnosis`;
    graph.appendChild(signal);
  }

  requestAnimationFrame(drawEvidenceConnectors);
}

function highlightEvidencePath(idx) {
  const graph = document.getElementById("evidence-graph");
  if (!graph) return;
  graph.querySelectorAll(".connector-line").forEach((p) => p.classList.remove("active-path"));
  graph.querySelectorAll(`.connector-line[data-index="${idx}"]`).forEach((p) => p.classList.add("active-path"));
  graph.querySelectorAll(".eg-node").forEach((n) => n.classList.toggle("is-active", Number(n.dataset.index) === idx));
  const claim = graph.querySelector(".eg-claim");
  if (claim) claim.classList.add("is-lit");
}

/* ---------- Evidence inspector ---------- */

function parseLineNumber(loc) { const m = /line\s+(\d+)/i.exec(loc || ""); return m ? parseInt(m[1], 10) : null; }

async function openInspector(evidenceItem) {
  const inspector = document.getElementById("evidence-inspector");
  document.getElementById("inspector-artifact").textContent = evidenceItem.artifact;
  document.getElementById("inspector-location").textContent = evidenceItem.field_or_location;
  document.getElementById("inspector-significance").textContent = evidenceItem.significance;

  const sourceEl = document.getElementById("inspector-source");
  const file = state.selectedFiles[evidenceItem.artifact];
  const lineNum = parseLineNumber(evidenceItem.field_or_location);

  if (file && lineNum) {
    const text = await file.text();
    const lines = text.split("\n");
    const start = Math.max(0, lineNum - 4);
    const end = Math.min(lines.length, lineNum + 3);
    sourceEl.innerHTML = "";
    for (let i = start; i < end; i++) {
      const div = document.createElement("div");
      div.className = i === lineNum - 1 ? "hl" : "";
      div.textContent = `${i + 1}  ${lines[i]}`;
      sourceEl.appendChild(div);
    }
  } else if (file) {
    sourceEl.textContent = `${evidenceItem.field_or_location}\n${evidenceItem.observed_value}`;
  } else {
    sourceEl.textContent = `${evidenceItem.observed_value}\n\n(Original file not available in this session — showing the cited value only.)`;
  }
  inspector.dataset.open = "true";
}

function closeInspector() { document.getElementById("evidence-inspector").dataset.open = "false"; }

/* ---------- Why this diagnosis ---------- */

async function askWhy() {
  const btn = document.getElementById("why-btn");
  btn.disabled = true;
  btn.textContent = "Asking ReproLens…";
  try {
    const resp = await fetch(`${apiBase()}/investigations/${state.investigationId}/explain`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ diagnosis: state.lastDiagnosis, question: "" }),
    });
    if (!resp.ok) throw await toApiError(resp);
    const result = await resp.json();
    document.getElementById("explanation-text").textContent = result.explanation;
    document.getElementById("explanation-block").style.display = "block";
  } catch (err) {
    document.getElementById("explanation-text").textContent = "Could not generate an explanation: " + (err.detail || err.error || "unknown error");
    document.getElementById("explanation-block").style.display = "block";
  } finally {
    btn.disabled = false;
    btn.textContent = "Why this diagnosis?";
  }
}

/* ---------- History ---------- */

function investigationCardHTML(item) {
  const status = item.experiment_status || "insufficient_evidence";
  const icon = status === "healthy" ? "i-check" : status === "failed" ? "i-warn" : status === "insufficient_evidence" ? "i-info" : "i-warn";
  let artifactCount = "?";
  try { artifactCount = new Set((JSON.parse(item.diagnosis_json).evidence || []).map((e) => e.artifact)).size; } catch (e) {}
  const date = item.created_at ? new Date(parseInt(item.created_at, 10) * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
  return `
    <div class="investigation-card" data-id="${item.investigation_id}">
      <div class="investigation-card-top">
        <div class="status-dot status-${status}"><svg class="icon"><use href="#${icon}"/></svg></div>
      </div>
      <div class="investigation-card-title">${item.experiment_name || "Unnamed experiment"}</div>
      <div class="investigation-card-diag">${item.primary_diagnosis || ""}</div>
      <div class="investigation-card-meta">
        <span>${date} · ${artifactCount} artifacts</span>
        <span class="chip-status status-${status}">${STATUS_LABELS[status] || status}</span>
      </div>
    </div>`;
}

async function refreshHistory() {
  try {
    const resp = await fetch(`${apiBase()}/investigations`);
    if (!resp.ok) return;
    const { investigations } = await resp.json();
    state.historyItems = (investigations || []).sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));

    const recent = document.getElementById("recent-investigations");
    const all = document.getElementById("all-investigations");
    recent.innerHTML = state.historyItems.slice(0, 4).map(investigationCardHTML).join("") || `<p class="hint">No investigations yet — start one, or try an example case.</p>`;
    all.innerHTML = state.historyItems.map(investigationCardHTML).join("");
    document.getElementById("no-investigations-msg").style.display = state.historyItems.length ? "none" : "block";

    document.querySelectorAll(".investigation-card").forEach((card) => {
      card.addEventListener("click", () => {
        const item = state.historyItems.find((i) => i.investigation_id === card.dataset.id);
        if (item) openFromHistory(item);
      });
    });
  } catch (e) { /* history is a convenience, not critical path */ }
}

function openFromHistory(item) {
  state.investigationId = item.investigation_id;
  state.selectedFiles = {};
  document.getElementById("investigation-id-badge").textContent = item.investigation_id;
  try {
    const diagnosis = JSON.parse(item.diagnosis_json);
    state.lastDiagnosis = diagnosis;
    renderDiagnosis(diagnosis);
    showPage("page-result");
  } catch (e) {
    showError({ error: "Could not load history item", detail: String(e), investigation_id: item.investigation_id });
  }
}

/* ---------- Search ---------- */

function applySearchFilter(query) {
  const q = query.trim().toLowerCase();
  document.querySelectorAll(".investigation-card, .example-card").forEach((card) => {
    card.style.display = !q || card.textContent.toLowerCase().includes(q) ? "" : "none";
  });
}

/* ---------- Reset / init ---------- */

function resetForm() {
  state.selectedFiles = {};
  state.investigationId = null;
  state.lastDiagnosis = null;
  document.getElementById("experiment-name").value = "";
  document.getElementById("investigation-id-badge").textContent = "";
  renderUploadGrid();
  updateInvestigateButton();
  closeInspector();
}

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  renderUploadGrid();
  updateInvestigateButton();
  refreshHistory();
  requestAnimationFrame(drawHeroConnectors);

  document.querySelectorAll(".nav-item").forEach((el) => {
    el.addEventListener("click", () => {
      if (el.dataset.page === "page-new") resetForm();
      showPage(el.dataset.page);
    });
  });
  document.querySelectorAll("[data-nav]").forEach((el) => {
    el.addEventListener("click", () => {
      if (el.dataset.nav === "page-new") resetForm();
      showPage(el.dataset.nav);
    });
  });

  document.getElementById("investigate-btn").addEventListener("click", runInvestigation);
  document.getElementById("why-btn").addEventListener("click", askWhy);
  document.getElementById("retry-btn").addEventListener("click", () => { resetForm(); showPage("page-new"); });
  document.getElementById("inspector-close").addEventListener("click", closeInspector);
  document.getElementById("global-search").addEventListener("input", (e) => applySearchFilter(e.target.value));

  document.querySelectorAll(".example-card").forEach((card) => {
    card.addEventListener("click", () => loadExampleFixture(card.dataset.fixture));
  });
});
