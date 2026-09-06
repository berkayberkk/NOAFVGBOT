// EA'nin kendi kaynagindaki (mql5/TradeBot_NOA_Recal.mq5 input) varsayilan
// tavan -- canli MT5 API'sinde EA'nin calisan input degerlerini okuyacak bir
// yol yok (bu bir MQL5 input, Python tarafina yayinlanmiyor), bu yuzden
// KAYNAK KODUNDAKI varsayilan deger kullaniliyor ve acikca belirtiliyor.
const MAX_PORTFOLIO_RISK_PCT = 4.0;
const fmtMoneyR = (v) => (v === null || v === undefined) ? "–" : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function riskLevel(pct) {
  if (pct >= MAX_PORTFOLIO_RISK_PCT * 0.85) return "elevated";
  if (pct >= MAX_PORTFOLIO_RISK_PCT * 0.5) return "moderate";
  return "low";
}

async function refreshRisk() {
  const { data: acc, error: accErr } = await getJSON("/api/mt5/account");
  const { data: positions, error: posErr } = await getJSON("/api/mt5/positions");

  if (accErr || !acc) {
    document.getElementById("risk-status-pill").textContent = "VERİ YOK";
    document.getElementById("risk-status-pill").className = "risk-pill elevated";
    document.getElementById("risk-content").style.display = "none";
    document.getElementById("risk-conn-error").style.display = "block";
    document.getElementById("risk-conn-error-desc").textContent = accErr || "MT5 bağlantısı yok.";
    return;
  }
  document.getElementById("risk-conn-error").style.display = "none";
  document.getElementById("risk-content").style.display = "block";

  document.getElementById("r-equity").textContent = fmtMoneyR(acc.equity) + " " + acc.currency;
  document.getElementById("r-balance").textContent = fmtMoneyR(acc.balance) + " " + acc.currency;
  document.getElementById("r-margin").textContent = fmtMoneyR(acc.margin) + " " + acc.currency;
  document.getElementById("r-freemargin").textContent = fmtMoneyR(acc.margin_free) + " " + acc.currency;

  const rows = positions || [];
  document.getElementById("r-openpos").textContent = rows.length;

  const tbody = document.querySelector("#risk-table tbody");
  const empty = document.getElementById("risk-empty");
  tbody.innerHTML = "";
  let totalRiskPct = 0;
  if (!rows.length) {
    empty.style.display = "block";
  } else {
    empty.style.display = "none";
    for (const p of rows) {
      if (p.risk_percent) totalRiskPct += p.risk_percent;
      const slDist = p.sl ? Math.abs(p.price_open - p.sl) : null;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(p.symbol)}</td>
        <td><span class="dir-badge dir-${p.type === 'BUY' ? 'buy' : 'sell'}">${p.type}</span></td>
        <td class="num">${p.volume}</td>
        <td class="num">${slDist !== null ? slDist.toFixed(5) : "SL yok"}</td>
        <td class="num">${p.risk_percent !== null && p.risk_percent !== undefined ? p.risk_percent.toFixed(2) + "%" : "–"}</td>
        <td class="num ${p.profit >= 0 ? 'pos' : 'neg'}">${fmtMoneyR(p.profit)}</td>`;
      tbody.appendChild(tr);
    }
  }

  document.getElementById("r-totalrisk").textContent = totalRiskPct.toFixed(2) + "%";
  const level = riskLevel(totalRiskPct);
  const pillLabels = { low: "LOW", moderate: "MODERATE", elevated: "ELEVATED" };
  const pill = document.getElementById("risk-status-pill");
  pill.textContent = pillLabels[level];
  pill.className = "risk-pill " + level;

  const fill = document.getElementById("risk-meter-fill");
  fill.className = "risk-meter-fill " + level;
  fill.style.width = Math.min(100, (totalRiskPct / MAX_PORTFOLIO_RISK_PCT) * 100) + "%";
  document.getElementById("risk-meter-label").textContent =
    `%${totalRiskPct.toFixed(2)} / %${MAX_PORTFOLIO_RISK_PCT.toFixed(2)} tavan (EA kaynak-kodu varsayılanı)`;
}

refreshRisk();
setInterval(refreshRisk, 10000);
