/* Modul-basi kazanan/kaybeden/breakeven ornekleri sayfasi. Grafik cizim
 * motoru (paintChart/createInteractiveChart/outcomeBadge) artik PAYLASILAN
 * chart_common.js'de -- bu dosya SADECE ornek kartlarinin render/filtre
 * mantigini icerir (bkz. templates/module.html: chart_common.js bu
 * script'ten ONCE yukleniyor). */

let _allExamples = [];

function exampleId(ex) {
  return `${ex.module}-${ex.symbol}-${ex.signal_time}`;
}

function renderExample(ex) {
  const card = document.createElement("div");
  card.className = "example-card";
  const id = exampleId(ex);
  card.innerHTML = `
    <div class="example-header">
      <div>
        <strong>${escapeHtml(ex.symbol)}</strong>
        <span class="dir-badge dir-${ex.direction.toLowerCase()}">${ex.direction}</span>
        ${outcomeBadge(ex.outcome)}
        <span class="r-badge">${fmtTradeR(ex.r_multiple)}</span>
        <span class="reason-badge">${escapeHtml(ex.reason || "")}</span>
      </div>
      <div class="example-meta">
        Sinyal: ${fmtTime(ex.signal_time)} &nbsp;|&nbsp;
        Giriş: ${ex.entry_fill_time ? fmtTime(ex.entry_fill_time) : "–"} &nbsp;|&nbsp;
        Çıkış: ${ex.exit_time ? fmtTime(ex.exit_time) : "–"}
        ${ex.bars_held ? ` &nbsp;|&nbsp; ${ex.bars_held} bar açık kaldı` : ""}
      </div>
    </div>
    ${ex.chart_truncated ? `<div class="truncated-note">grafik ilk ${ex.candles.length} barla sınırlandı (performans için) — gerçek çıkış yukarıdaki zamanda, ${ex.bars_held} bar sonra</div>` : ""}
    <div class="chart-toolbar">
      <span class="chart-hint">tekerlek: yakınlaştır &middot; sürükle: kaydır &middot; çift-tık: sıfırla</span>
      <button type="button" class="chart-reset-btn">Sıfırla</button>
    </div>
    <div class="chart-scroll"><canvas></canvas></div>
    <details class="example-feedback">
      <summary>Bu örnek hakkında not bırak</summary>
      <textarea placeholder="Bu spesifik örnekle ilgili gözlemin..." rows="2"></textarea>
      <button type="button">Gönder</button>
      <span class="feedback-sent-note"></span>
    </details>`;

  // Performans: grafik sadece kullanicinin gorus alanina girince cizilir/etkinlesir.
  const canvas = card.querySelector("canvas");
  let chartApi = null;
  const observer = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) {
      chartApi = createInteractiveChart(canvas, ex);
      observer.disconnect();
    }
  }, { rootMargin: "200px" });
  observer.observe(canvas);

  card.querySelector(".chart-reset-btn").addEventListener("click", () => chartApi && chartApi.resetView());

  const btn = card.querySelector(".example-feedback button");
  const textarea = card.querySelector("textarea");
  const note = card.querySelector(".feedback-sent-note");
  btn.addEventListener("click", async () => {
    const text = textarea.value.trim();
    if (!text || btn.disabled) return;
    btn.disabled = true;
    btn.textContent = "Gönderiliyor…";
    try {
      await getJSON("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: `[${ex.module.toUpperCase()} örneği — ${ex.symbol}, ${ex.direction}, ${ex.outcome}, ${fmtTradeR(ex.r_multiple)}] ${text}`,
          context: { module: ex.module, symbol: ex.symbol, signal_time: ex.signal_time, example_id: id },
        }),
      });
      textarea.value = "";
      note.textContent = "kaydedildi ✓";
      setTimeout(() => { note.textContent = ""; }, 3000);
    } finally {
      btn.disabled = false;
      btn.textContent = "Gönder";
    }
  });

  return card;
}

function applyFilters() {
  const symbol = document.getElementById("filter-symbol").value;
  const outcome = document.getElementById("filter-outcome").value;
  const container = document.getElementById("examples-container");
  container.innerHTML = "";
  const filtered = _allExamples.filter(ex =>
    (!symbol || ex.symbol === symbol) && (!outcome || ex.outcome === outcome)
  );
  if (!filtered.length) {
    container.innerHTML = '<div class="empty-state" style="display:block">Bu filtreyle örnek yok.</div>';
    return;
  }
  for (const ex of filtered) container.appendChild(renderExample(ex));
}

async function init() {
  const { data, error } = await getJSON(`/api/examples/${MODULE_KEY}`);
  const container = document.getElementById("examples-container");
  if (error && (!data || !data.length)) {
    container.innerHTML = `<div class="empty-state" style="display:block">${escapeHtml(error)}</div>`;
    return;
  }
  _allExamples = data || [];

  const symbolSelect = document.getElementById("filter-symbol");
  const symbols = [...new Set(_allExamples.map(e => e.symbol))].sort();
  for (const s of symbols) {
    const opt = document.createElement("option");
    opt.value = s; opt.textContent = s;
    symbolSelect.appendChild(opt);
  }
  document.getElementById("filter-symbol").addEventListener("change", applyFilters);
  document.getElementById("filter-outcome").addEventListener("change", applyFilters);

  applyFilters();
}

init();
