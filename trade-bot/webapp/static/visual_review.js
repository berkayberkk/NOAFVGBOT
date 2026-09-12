/* FAZ A -- Gorsel Inceleme Paneli. Kart cizimi icin chart_common.js'deki
 * paintChart/createInteractiveChart/outcomeBadge PAYLASILAN fonksiyonlarini
 * kullanir (module.js ile AYNI motor). */

let _page = { symbol: null, timeframe: null, module: null, outcome: null, offset: 0, limit: 50 };

function invalidReasonBadge(reason) {
  if (!reason) return "";
  return `<span class="reason-badge" style="color:var(--warning);">geçersiz: ${escapeHtml(reason)}</span>`;
}

function consistencyBanner(c) {
  if (!c) return "";
  let cls = "badge-warn", text = c.message;
  if (c.checked && c.match === true) cls = "badge-ok";
  else if (c.checked && c.match === false) cls = "badge-error";
  const detail = c.checked
    ? ` (resmi: n=${c.official.n}, exp=${c.official.expectancy_r} | panel: n=${c.computed.n}, exp=${c.computed.expectancy_r})`
    : "";
  return `<div class="section-block-head" style="margin-top:10px;">
    <span class="${cls}" style="padding:4px 10px;border-radius:6px;font-size:12px;font-weight:600;display:inline-block;max-width:100%;white-space:normal;">
      ${escapeHtml(text)}${escapeHtml(detail)}
    </span>
  </div>`;
}

function exampleId(ex) {
  return `${ex.module}-${ex.symbol}-${ex.signal_time}-${ex.signal_index}`;
}

function renderExample(ex) {
  const card = document.createElement("div");
  card.className = "example-card";
  const id = exampleId(ex);
  const dirClass = ex.direction === "BUY" ? "buy" : "sell";
  card.innerHTML = `
    <div class="example-header">
      <div>
        <strong>${escapeHtml(ex.symbol)}</strong>
        <span class="dir-badge dir-${dirClass}">${ex.direction}</span>
        ${outcomeBadge(ex.outcome)}
        ${ex.valid ? `<span class="r-badge">${fmtTradeR(ex.r_multiple)}</span>` : ""}
        ${ex.valid ? `<span class="reason-badge">${escapeHtml(ex.reason || "")}</span>` : invalidReasonBadge(ex.invalid_reason)}
      </div>
      <div class="example-meta">
        Sinyal: ${fmtTime(ex.signal_time)} &nbsp;|&nbsp; bar #${ex.signal_index}
        ${ex.valid ? ` &nbsp;|&nbsp; Giriş: ${ex.entry_fill_time ? fmtTime(ex.entry_fill_time) : "–"} &nbsp;|&nbsp; Çıkış: ${ex.exit_time ? fmtTime(ex.exit_time) : "–"}` : ""}
        ${ex.bars_held ? ` &nbsp;|&nbsp; ${ex.bars_held} bar açık kaldı` : ""}
      </div>
    </div>
    ${ex.chart_truncated ? `<div class="truncated-note">grafik ilk ${ex.candles.length} barla sınırlandı (performans için)${ex.bars_held ? ` — gerçek çıkış ${ex.bars_held} bar sonra` : ""}</div>` : ""}
    <div class="chart-toolbar">
      <span class="chart-hint">tekerlek: yakınlaştır &middot; sürükle: kaydır &middot; çift-tık: sıfırla</span>
      <button type="button" class="chart-reset-btn">Sıfırla</button>
    </div>
    <div class="chart-scroll"><canvas></canvas></div>
    <details class="example-feedback">
      <summary>Bu sinyal hakkında not bırak</summary>
      <textarea placeholder="Bu spesifik sinyalle ilgili gözlemin..." rows="2"></textarea>
      <button type="button">Kaydet</button>
      <span class="feedback-sent-note"></span>
    </details>`;

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
    btn.textContent = "Kaydediliyor…";
    try {
      const { error } = await getJSON("/api/visual_review/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: ex.symbol, module: ex.module, timeframe: _page.timeframe,
          signal_index: ex.signal_index, signal_time: ex.signal_time, text,
        }),
      });
      if (error) {
        note.textContent = "hata: " + error;
      } else {
        textarea.value = "";
        note.textContent = "kaydedildi ✓";
        setTimeout(() => { note.textContent = ""; }, 3000);
      }
    } finally {
      btn.disabled = false;
      btn.textContent = "Kaydet";
    }
  });

  return card;
}

function renderSummary(data) {
  const a = data.aggregate;
  const el = document.getElementById("vr-summary");
  el.innerHTML = `
    <div class="section-block-head">
      <div class="hint" style="margin:0;">
        <strong>${escapeHtml(data.symbol)}</strong> / ${escapeHtml(data.timeframe)} / ${escapeHtml(data.module.toUpperCase())} --
        train+val: ${data.trainval_candles} mum (toplam ${data.total_candles} mumun holdout hariç kısmı) --
        işleme dönüşen sinyal: ${data.total_traded} -- geçersiz/filtrelenmiş: ${data.total_invalid} --
        panel ort. expectancy: <strong>${a.expectancy_r !== null ? a.expectancy_r : "–"}R</strong>
        (n=${a.n}, win_rate=${a.win_rate !== null ? (a.win_rate * 100).toFixed(1) + "%" : "–"})
      </div>
    </div>`;
}

function renderPagination(data) {
  const el = document.getElementById("vr-pagination");
  const shownFrom = data.total_filtered === 0 ? 0 : data.offset + 1;
  const shownTo = data.offset + data.shown;
  el.innerHTML = `
    <button type="button" id="vr-prev" ${data.offset <= 0 ? "disabled" : ""}>&laquo; Önceki</button>
    <span class="hint" style="margin:0;">${shownFrom}-${shownTo} / ${data.total_filtered}</span>
    <button type="button" id="vr-next" ${shownTo >= data.total_filtered ? "disabled" : ""}>Sonraki &raquo;</button>`;
  const prev = document.getElementById("vr-prev");
  const next = document.getElementById("vr-next");
  if (prev) prev.addEventListener("click", () => { _page.offset = Math.max(0, _page.offset - _page.limit); load(); });
  if (next) next.addEventListener("click", () => { _page.offset = _page.offset + _page.limit; load(); });
}

async function load() {
  const symbol = document.getElementById("vr-symbol").value;
  const timeframe = document.getElementById("vr-timeframe").value;
  const module = document.getElementById("vr-module").value;
  const outcome = document.getElementById("vr-outcome").value;
  const statusEl = document.getElementById("vr-status");
  const container = document.getElementById("vr-examples-container");
  const consistencyEl = document.getElementById("vr-consistency");
  const summaryEl = document.getElementById("vr-summary");
  const paginationEl = document.getElementById("vr-pagination");

  if (!symbol || !module) {
    statusEl.textContent = "Sembol ve modül seçip Yükle'ye basın.";
    return;
  }

  // Filtre degistiginde sayfayi basa sar (offset sadece prev/next'ten degisir)
  if (symbol !== _page.symbol || timeframe !== _page.timeframe || module !== _page.module || outcome !== _page.outcome) {
    _page.offset = 0;
  }
  _page = { ..._page, symbol, timeframe, module, outcome };

  statusEl.textContent = "Hesaplanıyor (sinyal üretimi + backtest çalışıyor)… büyük sembollerde biraz sürebilir.";
  container.innerHTML = "";
  consistencyEl.innerHTML = "";
  summaryEl.innerHTML = "";
  paginationEl.innerHTML = "";

  const params = new URLSearchParams({ symbol, timeframe, module, offset: _page.offset, limit: _page.limit });
  if (outcome) params.set("outcome", outcome);
  const { data, error } = await getJSON(`/api/visual_review/signals?${params.toString()}`);

  if (error || !data) {
    statusEl.textContent = "";
    container.innerHTML = `<div class="empty-state" style="display:block">${escapeHtml(error || "bilinmeyen hata")}</div>`;
    return;
  }

  statusEl.textContent = "";
  consistencyEl.innerHTML = consistencyBanner(data.consistency);
  renderSummary(data);
  renderPagination(data);

  if (!data.examples.length) {
    container.innerHTML = '<div class="empty-state" style="display:block">Bu filtreyle sinyal yok.</div>';
    return;
  }
  for (const ex of data.examples) container.appendChild(renderExample(ex));
}

async function init() {
  const { data, error } = await getJSON("/api/visual_review/options");
  if (error || !data) {
    document.getElementById("vr-status").textContent = "seçenekler yüklenemedi: " + (error || "");
    return;
  }
  const symbolSelect = document.getElementById("vr-symbol");
  for (const s of data.symbols) {
    const opt = document.createElement("option");
    opt.value = s; opt.textContent = s;
    symbolSelect.appendChild(opt);
  }
  const tfSelect = document.getElementById("vr-timeframe");
  for (const tf of data.timeframes) {
    const opt = document.createElement("option");
    opt.value = tf; opt.textContent = tf === data.official_timeframe ? `${tf} (resmi)` : tf;
    if (tf === data.official_timeframe) opt.selected = true;
    tfSelect.appendChild(opt);
  }
  const modSelect = document.getElementById("vr-module");
  for (const [key, name] of Object.entries(data.modules)) {
    const opt = document.createElement("option");
    opt.value = key; opt.textContent = name;
    modSelect.appendChild(opt);
  }

  document.getElementById("vr-load-btn").addEventListener("click", load);
}

init();
