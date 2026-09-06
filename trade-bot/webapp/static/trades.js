const fmtMoneyT = (v) => (v === null || v === undefined) ? "–" : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

let _allTrades = [];
let _sortKey = "time";
let _sortDir = -1;

function eaBadgeT(row) {
  if (row.is_ea_trade) return `<span class="src-badge src-ea" title="${escapeHtml(row.ea_name)}">BOT</span>`;
  return `<span class="src-badge src-foreign" title="magic=${row.magic}">HARİCİ</span>`;
}

function populateSymbolFilter(rows) {
  const sel = document.getElementById("f-symbol");
  const current = sel.value;
  const symbols = [...new Set(rows.map(r => r.symbol))].sort();
  sel.innerHTML = '<option value="">Hepsi</option>' + symbols.map(s => `<option value="${s}">${s}</option>`).join("");
  sel.value = current;
}

function applyFiltersAndRender() {
  const days = document.getElementById("f-days").value;
  const symbol = document.getElementById("f-symbol").value;
  const result = document.getElementById("f-result").value;
  const source = document.getElementById("f-source").value;
  const q = document.getElementById("f-search").value.trim().toLowerCase();

  let rows = _allTrades.filter(r => {
    if (symbol && r.symbol !== symbol) return false;
    if (result === "win" && !(r.profit >= 0)) return false;
    if (result === "loss" && !(r.profit < 0)) return false;
    if (source === "bot" && !r.is_ea_trade) return false;
    if (source === "foreign" && r.is_ea_trade) return false;
    if (q && !(r.symbol.toLowerCase().includes(q) || (r.comment || "").toLowerCase().includes(q))) return false;
    return true;
  });

  rows = [...rows].sort((a, b) => {
    const av = a[_sortKey], bv = b[_sortKey];
    if (av < bv) return -1 * _sortDir;
    if (av > bv) return 1 * _sortDir;
    return 0;
  });

  document.getElementById("trades-count").textContent = `(${rows.length})`;
  const tbody = document.querySelector("#trades-table tbody");
  const empty = document.getElementById("trades-empty");
  tbody.innerHTML = "";
  if (!rows.length) { empty.style.display = "block"; return; }
  empty.style.display = "none";

  for (const t of rows) {
    const tr = document.createElement("tr");
    tr.className = "clickable" + (t.is_ea_trade ? "" : " foreign-row");
    tr.innerHTML = `
      <td>${fmtTime(t.time)}</td>
      <td>${escapeHtml(t.symbol)}</td>
      <td>${eaBadgeT(t)}</td>
      <td><span class="dir-badge dir-${t.type === 'BUY' ? 'buy' : 'sell'}">${escapeHtml(t.type)}</span></td>
      <td class="num">${t.volume}</td>
      <td class="num">${t.price}</td>
      <td class="num ${t.profit >= 0 ? 'pos' : 'neg'}">${fmtMoneyT(t.profit)}</td>
      <td><span class="outcome-badge outcome-${t.profit >= 0 ? 'win' : 'loss'}">${t.profit >= 0 ? 'WIN' : 'LOSS'}</span></td>
      <td>${escapeHtml(t.comment) || "–"}</td>`;
    tr.addEventListener("click", () => openTradeDrawer(t));
    tbody.appendChild(tr);
  }
}

function openTradeDrawer(t) {
  document.getElementById("td-title").textContent = `${t.symbol} ${t.type}`;
  const body = document.getElementById("td-body");
  body.innerHTML = `
    <div class="drawer-field"><div class="df-label">Kaynak</div><div class="df-value" style="font-size:13px;">${eaBadgeT(t)} ${t.ea_name ? escapeHtml(t.ea_name) : `magic=${t.magic}`}</div></div>
    <div class="drawer-field"><div class="df-label">Yön</div><div class="df-value"><span class="dir-badge dir-${t.type === 'BUY' ? 'buy' : 'sell'}">${escapeHtml(t.type)}</span></div></div>
    <div class="drawer-field"><div class="df-label">Fiyat (kapanış)</div><div class="df-value">${t.price}</div></div>
    <div class="drawer-field"><div class="df-label">Lot</div><div class="df-value">${t.volume}</div></div>
    <div class="drawer-field"><div class="df-label">P&amp;L</div><div class="df-value ${t.profit >= 0 ? 'pos' : 'neg'}">${t.profit >= 0 ? '+' : ''}${fmtMoneyT(t.profit)}</div></div>
    <div class="drawer-field"><div class="df-label">Zaman</div><div class="df-value" style="font-size:13px;">${fmtTime(t.time)}</div></div>
    <div class="drawer-field"><div class="df-label">Yorum / Sinyal Etiketi</div><div class="df-value" style="font-size:13px;">${escapeHtml(t.comment) || "–"}</div></div>
    <div class="drawer-field"><div class="df-label">Ticket</div><div class="df-value" style="font-size:13px;">#${t.ticket}</div></div>
    <p class="hint" style="margin-top:8px;">Not: MT5 işlem geçmişi entry/SL/TP/R-multiple'ı ayrı saklamıyor — bu alanlar sadece backtest tarafında (Strategy/Backtest sayfaları) mevcut.</p>`;
  openDrawer(document.getElementById("trade-drawer"));
}

document.getElementById("td-close").addEventListener("click", () => closeDrawer(document.getElementById("trade-drawer")));

async function loadTrades() {
  const days = document.getElementById("f-days").value;
  const { data, error } = await getJSON(`/api/mt5/history?days=${days}`);
  if (error || data === null) {
    document.getElementById("trades-empty").style.display = "block";
    document.querySelector("#trades-empty .empty-title").textContent = "Veri alınamadı";
    document.querySelector("#trades-empty .empty-desc").textContent = error || "bilinmeyen hata";
    return;
  }
  _allTrades = data || [];
  populateSymbolFilter(_allTrades);
  applyFiltersAndRender();
}

document.querySelectorAll("#trades-table th.sortable").forEach(th => {
  th.addEventListener("click", () => {
    const key = th.dataset.key;
    _sortDir = (_sortKey === key) ? -_sortDir : -1;
    _sortKey = key;
    applyFiltersAndRender();
  });
});

["f-symbol", "f-result", "f-source"].forEach(id => document.getElementById(id).addEventListener("change", applyFiltersAndRender));
document.getElementById("f-search").addEventListener("input", applyFiltersAndRender);
document.getElementById("f-days").addEventListener("change", loadTrades);

loadTrades();
setInterval(loadTrades, 30000);
