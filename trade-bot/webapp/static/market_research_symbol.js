const TIMEFRAMES = ["M30", "H1", "H2", "H4", "D1", "W1"];
const STATUS_LABELS = {
  DATA_INCOMPLETE: "DATA INCOMPLETE", SYMBOL_UNAVAILABLE: "SYMBOL UNAVAILABLE",
  FETCH_ERROR: "FETCH ERROR", OK: "ANALYZED",
};

function dirBadge(dir) {
  if (dir === "BUY") return '<span class="dir-badge dir-buy">BUY</span>';
  if (dir === "SELL") return '<span class="dir-badge dir-sell">SELL</span>';
  if (dir === "MIXED") return '<span class="badge badge-warn">MIXED</span>';
  return '<span class="badge badge-unknown">NEUTRAL</span>';
}

function renderCandidate(c) {
  return `
    <div class="wf-window-card" style="margin-bottom:10px;">
      <div class="wf-title">${escapeHtml(c.module)} · ${dirBadge(c.direction)}</div>
      <div class="wf-metric-row"><span class="k">Entry</span><span class="v">${c.entry}</span></div>
      <div class="wf-metric-row"><span class="k">SL</span><span class="v neg">${c.sl}</span></div>
      <div class="wf-metric-row"><span class="k">TP</span><span class="v pos">${c.tp}</span></div>
      <div class="wf-metric-row"><span class="k">Risk</span><span class="v">${c.risk.toFixed(5)}</span></div>
      <div class="wf-metric-row"><span class="k">Expected R</span><span class="v pos">+${c.expected_r.toFixed(2)}R</span></div>
      <div class="wf-metric-row"><span class="k">Sinyal Zamanı</span><span class="v" style="font-size:11px;">${fmtTime(c.signal_time)}</span></div>
    </div>`;
}

function renderTimeframeCard(tf, r) {
  const card = document.createElement("div");
  card.className = "section-block";
  card.id = `tf-card-${tf}`;

  if (!r || r.status !== "OK") {
    const status = r ? r.status : "NOT_SCANNED";
    card.innerHTML = `
      <div class="section-block-head">
        <h2 style="margin:0;">${tf}</h2>
        <span class="badge ${status === 'FETCH_ERROR' ? 'badge-error' : 'badge-warn'}">${STATUS_LABELS[status] || status}</span>
      </div>
      <p class="hint">${escapeHtml((r && r.reason) || "Bu zaman dilimi için henüz analiz yok.")}</p>
      <button type="button" class="btn-ghost retry-btn" data-tf="${tf}">Retry</button>
      <span class="retry-note" style="margin-left:8px;"></span>`;
    card.querySelector(".retry-btn").addEventListener("click", (e) => retryTimeframe(tf, e.target));
    return card;
  }

  const modBadges = Object.entries(r.module_verdicts || {}).map(([m, v]) =>
    `<span class="badge ${v === 'PASS' ? 'badge-ok' : 'badge-unknown'}" style="margin-right:6px;">${m.toUpperCase()}: ${v}</span>`
  ).join("");

  card.innerHTML = `
    <div class="section-block-head">
      <h2 style="margin:0;">${tf}</h2>
      ${dirBadge(r.verdict)}
    </div>
    <div style="display:flex; gap:24px; flex-wrap:wrap; margin-bottom:14px; font-size:12.5px; color:var(--text-secondary);">
      <span>Current Price: <b class="mono" style="color:var(--text-primary);">${r.current_price ?? "–"}</b></span>
      <span>Analyzed At: <b class="mono" style="color:var(--text-primary);">${fmtTime(r.analyzed_at)}</b></span>
      <span>Data Through: <b class="mono" style="color:var(--text-primary);">${fmtTime(r.data_through)}</b></span>
      <span>Mum sayısı: <b class="mono" style="color:var(--text-primary);">${r.n_candles}</b></span>
    </div>
    <div style="margin-bottom:14px;">${modBadges}</div>
    <div id="candidates-${tf}">
      ${(r.candidates && r.candidates.length) ? r.candidates.map(renderCandidate).join("") : '<p class="hint">Şu an bekleyen (henüz fiyata dokunmamış) bir sinyal yok.</p>'}
    </div>`;
  return card;
}

async function retryTimeframe(tf, btn) {
  btn.disabled = true;
  btn.textContent = "Yenileniyor…";
  const note = btn.parentElement.querySelector(".retry-note");
  const { data, error } = await getJSON(`/api/scanner/rescan/${encodeURIComponent(SYMBOL)}/${tf}`, { method: "POST" });
  if (error) {
    note.textContent = "hata: " + error;
    btn.disabled = false;
    btn.textContent = "Retry";
    return;
  }
  await loadAll();
}

async function loadAll() {
  const { data: resultsData } = await getJSON(`/api/scanner/results/${encodeURIComponent(SYMBOL)}`);
  const { data: confluenceData } = await getJSON("/api/scanner/confluence");
  const conf = (confluenceData || {})[SYMBOL];

  const confluenceBody = document.getElementById("confluence-body");
  if (conf) {
    document.getElementById("symbol-price").textContent =
      resultsData && resultsData.M30 && resultsData.M30.current_price ? resultsData.M30.current_price : "–";
    confluenceBody.innerHTML = `
      <div style="display:flex; gap:28px; flex-wrap:wrap; align-items:center;">
        <div><div class="kpi-label">Uyum</div><div class="kpi-value">${escapeHtml(conf.alignment_label)}</div></div>
        <div><div class="kpi-label">Dominant Yön</div><div class="kpi-value" style="font-size:16px;">${dirBadge(conf.dominant_direction || "NEUTRAL")}</div></div>
        <div><div class="kpi-label">BUY / SELL / NEUTRAL</div><div class="kpi-value" style="font-size:16px;">${conf.buy_count} / ${conf.sell_count} / ${conf.neutral_count}</div></div>
      </div>`;
    const banner = document.getElementById("conflict-banner");
    if (conf.conflict) {
      banner.style.display = "block";
      document.getElementById("conflict-detail-text").textContent = conf.conflict_detail || "";
    } else {
      banner.style.display = "none";
    }
  } else {
    confluenceBody.innerHTML = '<p class="hint">Bu sembol için henüz tarama sonucu yok.</p>';
  }

  const container = document.getElementById("timeframe-cards");
  container.innerHTML = "";
  for (const tf of TIMEFRAMES) {
    container.appendChild(renderTimeframeCard(tf, resultsData ? resultsData[tf] : null));
  }
}

loadAll();
