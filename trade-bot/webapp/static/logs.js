let _allLogs = [];

function renderLogs() {
  const level = document.getElementById("log-level").value;
  const q = document.getElementById("log-search").value.trim().toLowerCase();
  const filtered = _allLogs.filter(l => {
    if (level && l.level !== level) return false;
    if (q && !l.message.toLowerCase().includes(q)) return false;
    return true;
  });
  document.getElementById("log-count").textContent = `(${filtered.length} / ${_allLogs.length})`;
  const viewer = document.getElementById("log-viewer");
  if (!filtered.length) {
    viewer.innerHTML = `<div class="empty-state" style="display:block"><div class="empty-title">Kayıt yok</div><div class="empty-desc">Bu filtreyle eşleşen log satırı bulunamadı.</div></div>`;
    return;
  }
  viewer.innerHTML = filtered.map(l => `
    <div class="log-line">
      <span class="log-time">${escapeHtml(l.time)}</span>
      <span class="log-level ${escapeHtml(l.level)}">${escapeHtml(l.level)}</span>
      <span class="log-msg">${escapeHtml(l.source)} — ${escapeHtml(l.message)}</span>
    </div>`).join("");
  viewer.scrollTop = viewer.scrollHeight;
}

async function loadLogs() {
  const res = await getJSON("/api/logs?n=500");
  if (res.error) {
    document.getElementById("log-viewer").innerHTML =
      `<div class="empty-state" style="display:block"><div class="empty-title">Log okunamadı</div><div class="empty-desc">${escapeHtml(res.error)}</div></div>`;
    return;
  }
  _allLogs = res.data || [];
  const note = document.getElementById("log-date-note");
  if (note) note.textContent = res.is_today ? "" : `(bugün henüz aktivite yok — en son kayıt: ${res.log_date})`;
  renderLogs();
}

document.getElementById("log-level").addEventListener("change", renderLogs);
document.getElementById("log-search").addEventListener("input", renderLogs);
document.getElementById("log-refresh").addEventListener("click", loadLogs);

loadLogs();
setInterval(loadLogs, 20000);
