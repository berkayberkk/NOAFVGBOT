function eaBadgeP(row) {
  if (row.is_ea_trade) return `<span class="src-badge src-ea" title="${escapeHtml(row.ea_name)}">BOT</span>`;
  return `<span class="src-badge src-foreign" title="magic=${row.magic}">HARİCİ</span>`;
}
const fmtMoneyP = (v) => (v === null || v === undefined) ? "–" : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

async function refreshPositions() {
  const { data, error } = await getJSON("/api/mt5/positions");
  const tbody = document.querySelector("#positions-table tbody");
  const empty = document.getElementById("positions-empty");
  const errBox = document.getElementById("positions-error");
  if (error || data === null) {
    tbody.innerHTML = "";
    empty.style.display = "none";
    errBox.style.display = "block";
    document.getElementById("positions-error-desc").textContent = error || "MT5 verisi alınamadı.";
    return;
  }
  errBox.style.display = "none";
  tbody.innerHTML = "";
  const rows = data || [];
  document.getElementById("positions-count").textContent = rows.length ? `(${rows.length})` : "";
  if (!rows.length) { empty.style.display = "block"; return; }
  empty.style.display = "none";
  for (const p of rows) {
    const tr = document.createElement("tr");
    if (!p.is_ea_trade) tr.className = "foreign-row";
    tr.innerHTML = `
      <td>${eaBadgeP(p)}</td>
      <td>${escapeHtml(p.symbol)}</td>
      <td><span class="dir-badge dir-${p.type === 'BUY' ? 'buy' : 'sell'}">${p.type}</span></td>
      <td class="num">${p.volume}</td>
      <td class="num">${p.price_open}</td>
      <td class="num">${p.price_current}</td>
      <td class="num">${p.sl || "–"}</td>
      <td class="num">${p.tp || "–"}</td>
      <td class="num">${p.risk_percent !== null && p.risk_percent !== undefined ? p.risk_percent.toFixed(2) + "%" : "–"}</td>
      <td class="num ${p.profit >= 0 ? "pos" : "neg"}">${fmtMoneyP(p.profit)}</td>
      <td>${escapeHtml(p.comment) || "–"}</td>
      <td>${fmtTime(p.time)}</td>`;
    tbody.appendChild(tr);
  }
}

refreshPositions();
setInterval(refreshPositions, 10000);
