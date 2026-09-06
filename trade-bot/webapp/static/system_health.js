function setHealthCard(prefix, dotState, text) {
  document.getElementById(`h-dot-${prefix}`).className = "status-dot " + dotState;
  document.getElementById(`h-${prefix}`).textContent = text;
}

function fmtAgo(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return Math.round(seconds) + "sn önce";
  if (seconds < 3600) return Math.round(seconds / 60) + "dk önce";
  return (seconds / 3600).toFixed(1) + "sa önce";
}

async function refreshHealth() {
  const { data, error } = await getJSON("/api/system_health");
  if (error || !data) {
    setHealthCard("bot", "unknown", "veri yok");
    setHealthCard("mt5", "err", "erişilemedi");
    setHealthCard("data", "unknown", "—");
    setHealthCard("api", "err", "hata");
    return;
  }

  setHealthCard("api", "ok", "HEALTHY");

  const mt5Connected = !!(data.mt5 && data.mt5.mt5_connected);
  if (mt5Connected) {
    setHealthCard("mt5", "ok", `CONNECTED (#${data.mt5.account.login})`);
  } else {
    setHealthCard("mt5", "err", "DISCONNECTED" + (data.mt5_error ? ": " + data.mt5_error : ""));
  }

  setHealthCard("bot", data.bot_active ? "ok" : "warn", data.bot_active ? "ONLINE" : "hiçbir grafikte çalışmıyor");
  setHealthCard("data", data.data_fresh ? "ok" : "warn", data.data_fresh ? "HEALTHY" : "bayat/yok");

  const ages = Object.values(data.pending_ages_seconds || {}).filter(a => a !== null);
  document.getElementById("h-lastsignal").textContent = ages.length ? fmtAgo(Math.min(...ages)) : "—";

  const { data: history } = await getJSON("/api/mt5/history?days=30");
  const botDeals = (history || []).filter(d => d.is_ea_trade);
  document.getElementById("h-lasttrade").textContent = botDeals.length
    ? fmtAgo((Date.now() - new Date(botDeals[0].time).getTime()) / 1000)
    : "kayıtlı yok (30 gün)";

  const tbody = document.querySelector("#health-symbol-table tbody");
  tbody.innerHTML = "";
  for (const [symbol, ageSec] of Object.entries(data.pending_ages_seconds || {})) {
    const active = ageSec !== null;
    const fresh = active && ageSec < 600;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(symbol)}</td>
      <td>${active ? "evet" : "hayır — grafiğe eklenmemiş"}</td>
      <td>${active ? fmtAgo(ageSec) : "–"}</td>
      <td><span class="badge ${!active ? 'badge-unknown' : (fresh ? 'badge-ok' : 'badge-warn')}">${!active ? "PASİF" : (fresh ? "HEALTHY" : "BAYAT")}</span></td>`;
    tbody.appendChild(tr);
  }

  const accTbody = document.querySelector("#health-account-table tbody");
  accTbody.innerHTML = "";
  if (data.mt5 && data.mt5.account) {
    const rows = [
      ["Login", "#" + data.mt5.account.login],
      ["Sunucu", data.mt5.account.server],
      ["Bakiye", data.mt5.account.balance],
      ["Trade İzinli (terminal)", data.mt5.terminal ? (data.mt5.terminal.trade_allowed ? "evet" : "hayır") : "–"],
    ];
    accTbody.innerHTML = rows.map(([k, v]) => `<tr><td class="k">${k}</td><td class="v">${escapeHtml(String(v))}</td></tr>`).join("");
  } else {
    accTbody.innerHTML = `<tr><td class="k">Durum</td><td class="v">bağlı değil</td></tr>`;
  }
}

refreshHealth();
setInterval(refreshHealth, 15000);
