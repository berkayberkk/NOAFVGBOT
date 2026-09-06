const fmtPctB = (v) => (v === null || v === undefined) ? "–" : (v * 100).toFixed(1) + "%";
const fmtRB = (v) => (v === null || v === undefined) ? "–" : (v >= 0 ? "+" : "") + v.toFixed(4);

let _keptSymbolsB = [];
(async () => {
  const { data } = await getJSON("/api/config");
  _keptSymbolsB = (data && data.kept_symbols) || [];
})();

// ---------- Walk-forward pencereleri ----------
function wfStatus(better) {
  if (better > 0) return ["ROBUST", "robust"];
  if (better > -0.05) return ["WEAK", "weak"];
  return ["FAILED", "failed"];
}

async function loadWalkforward() {
  const { data, error } = await getJSON("/api/diagnostics/h1_disable_walkforward_results.json");
  const container = document.getElementById("wf-container");
  if (error || !data) {
    container.innerHTML = `<div class="empty-state" style="display:block"><div class="empty-title">Walk-forward verisi yok</div><div class="empty-desc">${escapeHtml(error || "dosya bulunamadı")}</div></div>`;
    return;
  }
  container.innerHTML = "";
  let windowNo = 1;
  for (const [symbol, folds] of Object.entries(data)) {
    for (const f of folds) {
      const alone = f["M30-alone"], combined = f["M30+H1-combined"];
      const better = Math.max(alone.expectancy_r, combined.expectancy_r);
      const [statusLabel, statusClass] = wfStatus(better);
      const card = document.createElement("div");
      card.className = "wf-window-card";
      card.innerHTML = `
        <div class="wf-title">WINDOW ${String(windowNo).padStart(2, "0")} · ${escapeHtml(symbol)}</div>
        <div class="wf-flow">${escapeHtml(f.period)} · M30-ALONE → M30+H1-COMBINED</div>
        <div class="wf-metric-row"><span class="k">M30 win / exp_R</span><span class="v">${fmtPctB(alone.win_rate)} / ${fmtRB(alone.expectancy_r)}</span></div>
        <div class="wf-metric-row"><span class="k">M30 n (dolan)</span><span class="v">${alone.n_filled}</span></div>
        <div class="wf-metric-row"><span class="k">Combined win / exp_R</span><span class="v">${fmtPctB(combined.win_rate)} / ${fmtRB(combined.expectancy_r)}</span></div>
        <div class="wf-metric-row"><span class="k">Combined n (dolan)</span><span class="v">${combined.n_filled}</span></div>
        <div class="wf-metric-row"><span class="k">Daha iyi</span><span class="v">${combined.expectancy_r > alone.expectancy_r ? "COMBINED" : "ALONE"}</span></div>
        <span class="wf-status ${statusClass}">${statusLabel}</span>`;
      container.appendChild(card);
      windowNo++;
    }
  }
  if (!windowNo || windowNo === 1) {
    container.innerHTML = '<span class="hint">Veri bulunamadı.</span>';
  }
}

// ---------- Diagnostics listesi + görüntüleyici (eski app.js'ten taşındı) ----------
async function loadDiagnosticsList() {
  const { data } = await getJSON("/api/diagnostics/list");
  const container = document.getElementById("diagnostics-list");
  const currentActive = container.querySelector(".diag-chip.active")?.dataset.name;
  container.innerHTML = "";
  for (const item of (data || [])) {
    const chip = document.createElement("div");
    chip.className = "diag-chip" + (item.name === currentActive ? " active" : "");
    chip.dataset.name = item.name;
    chip.innerHTML = `<span class="name">${escapeHtml(item.name)}</span><span class="desc">${escapeHtml(item.description)}</span>`;
    chip.onclick = () => {
      container.querySelectorAll(".diag-chip").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      renderDiagnostic(item.name);
    };
    container.appendChild(chip);
  }
  if (!data || !data.length) {
    container.innerHTML = '<span class="hint">Henüz sonuç dosyası yok.</span>';
  }
}

function sortableTable(headers, rows, defaultSortIdx) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  let sortIdx = defaultSortIdx || 0;
  let sortDir = -1;

  function renderBody() {
    const sorted = [...rows].sort((a, b) => {
      const av = a.raw[sortIdx], bv = b.raw[sortIdx];
      if (av < bv) return -1 * sortDir;
      if (av > bv) return 1 * sortDir;
      return 0;
    });
    table.querySelector("tbody").innerHTML = sorted.map(r =>
      `<tr${r.isKept ? ' class="kept-row"' : ""}>${r.cells.map(c => `<td>${c}</td>`).join("")}</tr>`
    ).join("");
  }

  const thead = document.createElement("thead");
  thead.innerHTML = `<tr>${headers.map((h, i) =>
    `<th class="sortable" data-idx="${i}">${h}</th>`).join("")}</tr>`;
  thead.querySelectorAll("th").forEach(th => {
    th.onclick = () => {
      const idx = parseInt(th.dataset.idx);
      sortDir = (sortIdx === idx) ? -sortDir : -1;
      sortIdx = idx;
      renderBody();
    };
  });
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  table.appendChild(tbody);
  wrap.appendChild(table);
  renderBody();
  return wrap;
}

function renderUniverseOrFullScan(data, isUniverse) {
  const wrap = document.createElement("div");
  if (isUniverse) {
    const note = document.createElement("p");
    note.className = "hint";
    note.innerHTML = `<strong>Bilgi amaçlı:</strong> bu 101 sembollük tarama araştırma/teşhis içindir. ` +
      `Bot şu an SADECE <strong>${_keptSymbolsB.join(" / ") || "GOLD / BTCUSD / EURGBP"}</strong>'de gerçek işlem açıyor ` +
      `(vurgulu satırlar) — diğer semboller canlıda işlem görmüyor.`;
    wrap.appendChild(note);
  }

  const rows = [];
  for (const [symbol, info] of Object.entries(data)) {
    const isKept = _keptSymbolsB.includes(symbol);
    if (info.error) {
      rows.push({ cells: [symbol, "HATA: " + info.error, "", "", "", "", ""], raw: [symbol, -999, 0, 0, 0, 0, 0], isKept });
      continue;
    }
    const pl = info.portfolio_level || {};
    const taken = pl.taken_by_module || {};
    const takenStr = Object.entries(taken).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k}:${v}`).join(" ");
    rows.push({
      cells: [
        (isKept ? "★ " : "") + symbol, info.n_signals ?? "–",
        pl.n_taken_into_portfolio ?? "–",
        fmtPctB(pl.portfolio_win_rate),
        fmtRB(pl.portfolio_expectancy_r),
        pl.portfolio_profit_factor ?? "–",
        takenStr,
      ],
      raw: [symbol, info.n_signals || 0, pl.n_taken_into_portfolio || 0,
            pl.portfolio_win_rate || 0, pl.portfolio_expectancy_r || 0, pl.portfolio_profit_factor || 0, takenStr],
      isKept,
    });
  }
  wrap.appendChild(sortableTable(
    ["Sembol", "Sinyal", "Alınan", "Win%", "Exp_R", "PF", "Modül dağılımı (alınan)"],
    rows, 4
  ));
  return wrap;
}

function renderModuleLevelDeepDive(data) {
  const container = document.createElement("div");
  for (const [symbol, info] of Object.entries(data)) {
    const h3 = document.createElement("h3");
    h3.textContent = symbol;
    h3.style.marginTop = "16px";
    container.appendChild(h3);
    const rows = [];
    for (const [mod, m] of Object.entries(info.module_level || {})) {
      rows.push({
        cells: [mod, m.n_signals, m.n_filled, fmtPctB(m.win_rate), fmtPctB(m.breakeven_wr_required),
                fmtRB(m.expectancy_r), m.profit_factor ?? "–",
                fmtPctB(m.true_sl_loss_rate_of_filled), fmtPctB(m.breakeven_rate_of_filled),
                m.avg_bars_to_sl_hit ?? "–"],
        raw: [mod, m.n_signals, m.n_filled, m.win_rate, m.breakeven_wr_required,
              m.expectancy_r, m.profit_factor || 0, m.true_sl_loss_rate_of_filled || 0,
              m.breakeven_rate_of_filled || 0, m.avg_bars_to_sl_hit || 0],
      });
    }
    container.appendChild(sortableTable(
      ["Modül", "Sinyal", "Dolan", "Win%", "Gereken%", "Exp_R", "PF", "SL%", "BE%", "SL'e bar"], rows, 5
    ));
  }
  return container;
}

async function renderDiagnostic(name) {
  const viewer = document.getElementById("diagnostics-viewer");
  viewer.innerHTML = '<span class="placeholder">yükleniyor…</span>';
  const { data, error } = await getJSON(`/api/diagnostics/${name}`);
  if (error) { viewer.innerHTML = `<span class="placeholder">${error}</span>`; return; }
  viewer.innerHTML = "";

  if (name.includes("universe") || name.includes("full_scan")) {
    if (name.includes("full_scan") && Object.values(data)[0] && Object.values(data)[0].module_level) {
      viewer.appendChild(renderModuleLevelDeepDive(data));
    } else {
      viewer.appendChild(renderUniverseOrFullScan(data, name.includes("universe")));
    }
  } else {
    const pre = document.createElement("pre");
    pre.style.whiteSpace = "pre-wrap";
    pre.style.fontSize = "12px";
    pre.textContent = JSON.stringify(data, null, 2).slice(0, 20000);
    viewer.appendChild(pre);
  }
}

loadWalkforward();
loadDiagnosticsList();
