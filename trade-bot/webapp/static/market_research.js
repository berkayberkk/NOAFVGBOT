const TIMEFRAMES = ["M30", "H1", "H2", "H4", "D1", "W1"];

function verdictBadge(v) {
  const map = {
    BUY: '<span class="dir-badge dir-buy">BUY</span>',
    SELL: '<span class="dir-badge dir-sell">SELL</span>',
    MIXED: '<span class="badge badge-warn">MIXED</span>',
    NEUTRAL: '<span class="badge badge-unknown">NEUTRAL</span>',
    DATA_INCOMPLETE: '<span class="badge badge-warn" title="eksik/yetersiz/bayat veri">VERİ EKSİK</span>',
    SYMBOL_UNAVAILABLE: '<span class="badge badge-unknown" title="broker Market Watch listesinde bulunamadi">YOK</span>',
    FETCH_ERROR: '<span class="badge badge-error">HATA</span>',
    NOT_SCANNED: '<span class="badge badge-unknown">—</span>',
  };
  return map[v] || `<span class="badge badge-unknown">${escapeHtml(v)}</span>`;
}

let _confluence = {};
let _candidates = [];
let _results = {};

async function loadWarningFailedCounts() {
  const { data } = await getJSON("/api/scanner/results");
  _results = data || {};
  let warnings = 0, failed = 0;
  for (const tfMap of Object.values(_results)) {
    for (const r of Object.values(tfMap)) {
      if (r.status === "DATA_INCOMPLETE") warnings++;
      else if (r.status === "SYMBOL_UNAVAILABLE" || r.status === "FETCH_ERROR") failed++;
    }
  }
  document.getElementById("s-warnings").textContent = warnings;
  document.getElementById("s-failed").textContent = failed;
}

async function loadProgress() {
  const { data, error } = await getJSON("/api/scanner/progress");
  const badge = document.getElementById("research-status-badge");
  if (error || !data) {
    badge.textContent = "HENÜZ TARANMADI";
    badge.className = "badge badge-unknown";
    document.getElementById("s-total-instruments").textContent = "–";
    document.getElementById("s-scanned").textContent = "–";
    document.getElementById("s-jobs").textContent = "–";
    return;
  }
  badge.textContent = data.status;
  badge.className = "badge " + (data.status === "COMPLETED" ? "badge-ok" : "badge-warn");
  document.getElementById("s-total-instruments").textContent = data.total_instruments;
  document.getElementById("s-scanned").textContent = `${data.scanned_instruments} / ${data.total_instruments}`;
  document.getElementById("s-jobs").textContent = `${data.completed_jobs} / ${data.total_jobs}`;

  const progressBlock = document.getElementById("scanner-progress-block");
  if (data.status === "RUNNING") {
    progressBlock.style.display = "block";
    document.getElementById("scanner-current").textContent = data.current ? `şu an: ${data.current}` : "";
    const logViewer = document.getElementById("scanner-log");
    logViewer.innerHTML = (data.log || []).map(l => `<div class="log-line"><span class="log-msg">${escapeHtml(l)}</span></div>`).join("");
    logViewer.scrollTop = logViewer.scrollHeight;
  } else {
    progressBlock.style.display = "none";
  }
}

async function loadCandidates() {
  const { data, error } = await getJSON("/api/scanner/candidates");
  _candidates = data || [];
  const tbody = document.querySelector("#candidates-table tbody");
  const empty = document.getElementById("candidates-empty");
  if (error || !_candidates.length) {
    tbody.innerHTML = "";
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";
  tbody.innerHTML = _candidates.slice(0, 20).map((c, i) => `
    <tr class="clickable" onclick="location.href='/market-research/${encodeURIComponent(c.symbol)}'">
      <td>${i + 1}</td>
      <td>${escapeHtml(c.symbol)}</td>
      <td>${escapeHtml(c.timeframe)}</td>
      <td>${verdictBadge(c.direction)}</td>
      <td class="num">${escapeHtml(c.mtf_alignment_label)}${c.conflict ? ' ⚠' : ""}</td>
      <td class="num pos">+${c.expected_r.toFixed(2)}R</td>
      <td class="num">${c.risk.toFixed(5)}</td>
      <td>${escapeHtml(c.module)}</td>
    </tr>`).join("");
}

let _matrixRows = [];

async function loadMatrix() {
  const { data: confluenceData } = await getJSON("/api/scanner/confluence");
  _confluence = confluenceData || {};
  _matrixRows = Object.keys(_confluence).sort();
  applyMatrixFilters();
}

function applyMatrixFilters() {
  const q = document.getElementById("f-symbol-search").value.trim().toLowerCase();
  const signal = document.getElementById("f-signal").value;
  const minAlign = parseInt(document.getElementById("f-min-alignment").value);
  const conflictOnly = document.getElementById("f-conflict").value === "yes";

  const rows = _matrixRows.filter(symbol => {
    const c = _confluence[symbol];
    if (q && !symbol.toLowerCase().includes(q)) return false;
    if (signal && c.dominant_direction !== signal && !(signal === "NEUTRAL" && !c.dominant_direction)) return false;
    if (c.alignment_score < minAlign) return false;
    if (conflictOnly && !c.conflict) return false;
    return true;
  });

  document.getElementById("matrix-count").textContent = `(${rows.length} / ${_matrixRows.length})`;
  const tbody = document.querySelector("#matrix-table tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--text-secondary);padding:20px;">Filtreyle eşleşen enstrüman yok.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(symbol => {
    const c = _confluence[symbol];
    const tfCells = TIMEFRAMES.map(tf => `<td>${verdictBadge(c.per_timeframe_verdict[tf] || "NOT_SCANNED")}</td>`).join("");
    return `<tr class="clickable" onclick="location.href='/market-research/${encodeURIComponent(symbol)}'">
      <td><strong>${escapeHtml(symbol)}</strong></td>
      ${tfCells}
      <td class="num">${escapeHtml(c.alignment_label)}${c.conflict ? ' <span title="' + escapeHtml(c.conflict_detail || '') + '">⚠</span>' : ""}</td>
      <td>${c.analyzable_timeframes === TIMEFRAMES.length ? '<span class="badge badge-ok">Complete</span>' : `<span class="badge badge-warn">${c.analyzable_timeframes}/${TIMEFRAMES.length}</span>`}</td>
    </tr>`;
  }).join("");
}

["f-symbol-search", "f-signal", "f-min-alignment", "f-conflict"].forEach(id => {
  const el = document.getElementById(id);
  el.addEventListener(el.tagName === "INPUT" ? "input" : "change", applyMatrixFilters);
});

function refreshAll() {
  loadProgress();
  loadCandidates();
  loadMatrix();
  loadWarningFailedCounts();
}

refreshAll();
setInterval(refreshAll, 8000);
