// Dashboard sayfasi -- KPI kartlari, equity egrisi, bekleyen sinyaller, acik pozisyonlar.
const fmtMoney = (v) => (v === null || v === undefined) ? "–" : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtPct = (v) => (v === null || v === undefined) ? "–" : (v * 100).toFixed(1) + "%";
const fmtR = (v) => (v === null || v === undefined) ? "–" : (v >= 0 ? "+" : "") + v.toFixed(4);

function eaBadge(row) {
  if (row.is_ea_trade) return `<span class="src-badge src-ea" title="${escapeHtml(row.ea_name)}">BOT</span>`;
  return `<span class="src-badge src-foreign" title="magic=${row.magic}">HARİCİ</span>`;
}

function setStale(isStale) {
  document.getElementById("kpi-grid")?.classList.toggle("stale", isStale);
  document.getElementById("positions-section")?.classList.toggle("stale", isStale);
}

// ---------- Hesap / KPI ----------
async function refreshAccount() {
  const { data, error } = await getJSON("/api/mt5/account");
  const statusEl = document.getElementById("conn-status");
  if (error || !data) {
    if (statusEl) { statusEl.textContent = "MT5 bağlantısı yok" + (error ? ": " + error : ""); statusEl.className = "badge badge-error"; }
    setStale(true);
    return;
  }
  setStale(false);
  if (statusEl) { statusEl.textContent = `Bağlı — #${data.login} @ ${data.server}`; statusEl.className = "badge badge-ok"; }
  document.getElementById("kpi-equity").textContent = fmtMoney(data.equity) + " " + data.currency;
  const sub = document.getElementById("kpi-equity-sub");
  sub.textContent = "bakiye " + fmtMoney(data.balance);
}

async function refreshTodayPnl() {
  const { data, error } = await getJSON("/api/mt5/history?days=1");
  const el = document.getElementById("kpi-today");
  const sub = document.getElementById("kpi-today-sub");
  if (error || data === null) { el.textContent = "–"; return; }
  const botDeals = (data || []).filter(d => d.is_ea_trade);
  if (!botDeals.length) {
    el.textContent = "$0.00"; el.className = "kpi-value tabular-num";
    sub.textContent = "bugün bot işlemi yok"; return;
  }
  const total = botDeals.reduce((s, d) => s + d.profit, 0);
  el.textContent = (total >= 0 ? "+$" : "-$") + Math.abs(total).toFixed(2);
  el.className = "kpi-value tabular-num " + (total >= 0 ? "pos" : "neg");
  sub.textContent = `${botDeals.length} işlem`;
}

async function refreshBacktestKpis() {
  const { data, error } = await getJSON("/api/diagnostics/module_diagnostic_full_scan_results.json");
  const winEl = document.getElementById("kpi-winrate");
  const expEl = document.getElementById("kpi-expectancy");
  const netrEl = document.getElementById("kpi-netr");
  if (error || !data) { return; }
  let totalTaken = 0, totalWinSum = 0, totalR = 0;
  for (const info of Object.values(data)) {
    const pl = info.portfolio_level;
    if (!pl) continue;
    totalTaken += pl.n_taken_into_portfolio;
    totalWinSum += pl.portfolio_win_rate * pl.n_taken_into_portfolio;
    totalR += pl.portfolio_expectancy_r * pl.n_taken_into_portfolio;
  }
  if (!totalTaken) return;
  const combinedWinRate = totalWinSum / totalTaken;
  const combinedExp = totalR / totalTaken;
  winEl.textContent = fmtPct(combinedWinRate);
  expEl.textContent = fmtR(combinedExp) + "R";
  expEl.className = "kpi-value tabular-num " + (combinedExp >= 0 ? "pos" : "neg");
  netrEl.textContent = fmtR(totalR) + "R";
  netrEl.className = "kpi-value tabular-num " + (totalR >= 0 ? "pos" : "neg");
}

async function refreshPositions() {
  const { data, error } = await getJSON("/api/mt5/positions");
  const tbody = document.querySelector("#positions-table tbody");
  const empty = document.getElementById("positions-empty");
  if (error || data === null) return;
  tbody.innerHTML = "";
  const rows = data || [];
  document.getElementById("positions-count").textContent = rows.length ? `(${rows.length})` : "";
  if (!rows.length) { empty.style.display = "block"; return; }
  empty.style.display = "none";
  for (const p of rows) {
    const tr = document.createElement("tr");
    if (!p.is_ea_trade) tr.className = "foreign-row";
    tr.innerHTML = `
      <td>${eaBadge(p)}</td>
      <td>${escapeHtml(p.symbol)}</td>
      <td><span class="dir-badge dir-${p.type === 'BUY' ? 'buy' : 'sell'}">${p.type}</span></td>
      <td class="num">${p.volume}</td>
      <td class="num">${p.price_open}</td>
      <td class="num">${p.price_current}</td>
      <td class="num">${p.sl || "–"}</td>
      <td class="num">${p.tp || "–"}</td>
      <td class="num ${p.profit >= 0 ? "pos" : "neg"}">${fmtMoney(p.profit)}</td>
      <td>${escapeHtml(p.comment) || "–"}</td>`;
    tbody.appendChild(tr);
  }
}

// ---------- Bekleyen sinyaller ----------
async function refreshPending() {
  const { data, error } = await getJSON("/api/pending");
  const container = document.getElementById("pending-container");
  if (error || !data) {
    container.innerHTML = `<div class="empty-state" style="display:block"><div class="empty-title">Veri alınamadı</div><div class="empty-desc">${escapeHtml(error || "bilinmeyen hata")}</div></div>`;
    return;
  }
  container.innerHTML = "";
  let anyAvailable = false;
  for (const [symbol, info] of Object.entries(data)) {
    const box = document.createElement("div");
    box.className = "pending-symbol-box";
    if (!info.available) {
      box.innerHTML = `<h4>${escapeHtml(symbol)}</h4><div class="hint">EA bu sembol için hiç çalışmadı (henüz bir grafiğe eklenip aktif olmamış) — veri yok.</div>`;
      container.appendChild(box);
      continue;
    }
    anyAvailable = true;
    const ageMin = (Date.now() - new Date(info.updated).getTime()) / 60000;
    const staleWarn = ageMin > 10 ? `<span class="stale-pill">bayat (${ageMin.toFixed(0)} dk önce)</span>` : "";
    box.innerHTML = `<h4>${escapeHtml(symbol)} <span class="count">(${info.items.length})</span> ${staleWarn}</h4>`;
    if (!info.items.length) {
      box.innerHTML += '<div class="hint">Şu an bekleyen aday yok.</div>';
    } else {
      const table = document.createElement("table");
      table.innerHTML = `<thead><tr><th>Modül</th><th>Yön</th><th class="num">Giriş</th><th class="num">SL</th><th class="num">TP</th><th>Sinyal Zamanı</th></tr></thead><tbody>${
        info.items.map(it => `<tr><td>${escapeHtml(it.module)}</td><td><span class="dir-badge dir-${it.direction === 'BUY' ? 'buy' : 'sell'}">${escapeHtml(it.direction)}</span></td><td class="num">${it.entry}</td><td class="num">${it.sl}</td><td class="num">${it.tp}</td><td>${escapeHtml(it.signal_time)}</td></tr>`).join("")
      }</tbody>`;
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      wrap.appendChild(table);
      box.appendChild(wrap);
    }
    container.appendChild(box);
  }
  if (!anyAvailable) {
    container.insertAdjacentHTML("afterbegin", '<div class="hint">EA şu an hiçbir grafikte aktif çalışmıyor gibi görünüyor — bu bölüm EA bir grafiğe eklenip çalışmaya başlayınca dolacak.</div>');
  }
}

// ---------- Mini sparkline (KPI kartlarinda) ----------
function drawSparkline(canvasId, points, color) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || points.length < 2) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const values = points.map(p => p.equity);
  let lo = Math.min(...values), hi = Math.max(...values);
  const range = (hi - lo) || 1;
  const pad = 3;
  const xOf = (i) => pad + (w - pad * 2) * (i / (points.length - 1));
  const yOf = (v) => pad + (h - pad * 2) * (1 - (v - lo) / range);

  // hafif dolgu (globalAlpha ile -- renk hex/rgb hangi formatta olursa olsun calisir)
  ctx.beginPath();
  ctx.moveTo(xOf(0), h);
  points.forEach((p, i) => ctx.lineTo(xOf(i), yOf(p.equity)));
  ctx.lineTo(xOf(points.length - 1), h);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.12;
  ctx.fill();
  ctx.globalAlpha = 1;

  ctx.beginPath();
  points.forEach((p, i) => {
    const x = xOf(i), y = yOf(p.equity);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.4;
  ctx.stroke();

  // son nokta
  const last = points[points.length - 1];
  ctx.beginPath();
  ctx.arc(xOf(points.length - 1), yOf(last.equity), 2, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
}

// ---------- Equity grafiği + max drawdown ----------
async function refreshEquityChart() {
  const days = document.getElementById("equity-days").value;
  const { data, error } = await getJSON(`/api/mt5/equity_history?days=${days}`);
  const canvas = document.getElementById("equity-canvas");
  if (error || !data) return;
  drawEquityChart(canvas, data);
  computeMaxDrawdown(data.bot_only || []);

  const styles = getComputedStyle(document.documentElement);
  const accentColor = styles.getPropertyValue("--accent").trim() || "#4f8cff";
  const dangerColor = styles.getPropertyValue("--danger").trim() || "#f0556b";
  const sparkPoints = (data.all || []).slice(-30);
  drawSparkline("kpi-equity-spark", sparkPoints, accentColor);
  drawSparkline("kpi-maxdd-spark", sparkPoints, dangerColor);
}

function computeMaxDrawdown(points) {
  const el = document.getElementById("kpi-maxdd");
  if (!el) return;
  if (points.length < 2) { el.textContent = "–"; return; }
  let peak = points[0].equity, maxDd = 0, maxDdPct = 0;
  for (const p of points) {
    peak = Math.max(peak, p.equity);
    const dd = peak - p.equity;
    const ddPct = peak !== 0 ? (dd / Math.abs(peak)) * 100 : 0;
    if (dd > maxDd) { maxDd = dd; maxDdPct = ddPct; }
  }
  el.textContent = "-" + fmtMoney(maxDd);
  el.className = "kpi-value tabular-num " + (maxDd > 0 ? "neg" : "");
  document.querySelector("#kpi-maxdd").parentElement.querySelector(".kpi-sub").textContent = "-" + maxDdPct.toFixed(2) + "% (tepe-dip)";
}

function drawEquityChart(canvas, data) {
  const width = 1100, height = 240, padTop = 14, padBottom = 24, padLeft = 4, padRight = 74;
  canvas.width = width + padLeft + padRight;
  canvas.height = height + padTop + padBottom;
  const ctx = canvas.getContext("2d");
  const styles = getComputedStyle(document.documentElement);
  const bgColor = styles.getPropertyValue("--surface").trim() || "#12161d";
  const gridColor = styles.getPropertyValue("--border-soft").trim() || "#1a1e25";
  const accentColor = styles.getPropertyValue("--accent").trim() || "#4f8cff";
  const successColor = styles.getPropertyValue("--success").trim() || "#3ecf8e";
  const dimColor = styles.getPropertyValue("--text-tertiary").trim() || "#5b6472";
  ctx.fillStyle = bgColor;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const all = data.all || [];
  const bot = data.bot_only || [];
  if (all.length < 2) {
    ctx.fillStyle = dimColor;
    ctx.font = "12px sans-serif";
    ctx.fillText("Bu aralıkta kapanan işlem yok.", 12, height / 2);
    return;
  }

  const allValues = all.map(p => p.equity).concat(bot.map(p => p.equity));
  let lo = Math.min(...allValues), hi = Math.max(...allValues);
  const range = (hi - lo) || 1;
  lo -= range * 0.08; hi += range * 0.08;

  const t0 = new Date(all[0].time).getTime();
  const t1 = new Date(all[all.length - 1].time).getTime();
  const tRange = (t1 - t0) || 1;

  const xOf = (iso) => padLeft + width * (new Date(iso).getTime() - t0) / tRange;
  const yOf = (v) => padTop + height * (1 - (v - lo) / (hi - lo));

  // hafif grid
  ctx.strokeStyle = gridColor;
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padTop + (height / 4) * i;
    ctx.beginPath(); ctx.moveTo(padLeft, y); ctx.lineTo(padLeft + width, y); ctx.stroke();
  }

  function drawLine(points, color) {
    if (points.length < 2) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    points.forEach((p, i) => {
      const x = xOf(p.time), y = yOf(p.equity);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    const last = points[points.length - 1];
    ctx.fillStyle = color;
    ctx.font = "11px monospace";
    ctx.fillText(last.equity.toFixed(0), padLeft + width + 6, yOf(last.equity) + 3);
  }

  drawLine(all, accentColor);
  drawLine(bot, successColor);
}

document.getElementById("equity-days")?.addEventListener("change", refreshEquityChart);

// ---------- Top Trade Candidates (scanner/, tum enstrumanlar) ----------
async function refreshTopCandidates() {
  const { data } = await getJSON("/api/scanner/candidates");
  const tbody = document.querySelector("#top-candidates-table tbody");
  const empty = document.getElementById("top-candidates-empty");
  const rows = data || [];
  if (!rows.length) { tbody.innerHTML = ""; empty.style.display = "block"; return; }
  empty.style.display = "none";
  tbody.innerHTML = rows.slice(0, 8).map((c, i) => `
    <tr class="clickable" onclick="location.href='/market-research/${encodeURIComponent(c.symbol)}'">
      <td>${i + 1}</td>
      <td>${escapeHtml(c.symbol)}</td>
      <td>${escapeHtml(c.timeframe)}</td>
      <td><span class="dir-badge dir-${c.direction === 'BUY' ? 'buy' : 'sell'}">${c.direction}</span></td>
      <td class="num">${escapeHtml(c.mtf_alignment_label)}</td>
      <td class="num pos">+${c.expected_r.toFixed(2)}R</td>
    </tr>`).join("");
}

// ---------- Init ----------
function refreshAll() {
  refreshAccount();
  refreshTodayPnl();
  refreshPositions();
  refreshPending();
}

refreshAll();
refreshBacktestKpis();
refreshEquityChart();
refreshTopCandidates();
setInterval(refreshAll, 10000);
setInterval(refreshEquityChart, 60000);
setInterval(refreshTopCandidates, 15000);
