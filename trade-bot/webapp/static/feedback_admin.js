let _allFeedback = [];

function statusOptions(current) {
  const statuses = ["yeni", "incelendi", "uygulandi", "reddedildi"];
  return statuses.map(s => `<option value="${s}" ${s === current ? "selected" : ""}>${s}</option>`).join("");
}

function renderCard(item) {
  const card = document.createElement("div");
  card.className = "feedback-item";
  let contextHtml = "";
  if (item.context) {
    contextHtml = `<div class="feedback-context">bağlam: ${escapeHtml(item.context.module || "")} ${escapeHtml(item.context.symbol || "")} @ ${item.context.signal_time ? fmtTime(item.context.signal_time) : ""}</div>`;
  }
  card.innerHTML = `
    <div class="meta">
      <span>#${item.id} &middot; ${fmtTime(item.timestamp)}</span>
      <span class="status-pill status-${item.status}">${escapeHtml(item.status)}</span>
    </div>
    ${contextHtml}
    <div class="feedback-text"></div>
    ${item.admin_note ? `<div class="admin-note-display">not: <span></span></div>` : ""}
    <div class="admin-controls">
      <select class="status-select">${statusOptions(item.status)}</select>
      <input type="text" class="admin-note-input" placeholder="not ekle (opsiyonel)…" value="${item.admin_note ? escapeHtml(item.admin_note) : ""}">
      <button type="button">Kaydet</button>
      <span class="save-note"></span>
    </div>`;
  card.querySelector(".feedback-text").textContent = item.text;
  if (item.admin_note) card.querySelector(".admin-note-display span").textContent = item.admin_note;

  const btn = card.querySelector("button");
  btn.addEventListener("click", async () => {
    const status = card.querySelector(".status-select").value;
    const admin_note = card.querySelector(".admin-note-input").value.trim();
    const saveNote = card.querySelector(".save-note");
    btn.disabled = true;
    const { data, error } = await getJSON(`/api/feedback/${item.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, admin_note }),
    });
    btn.disabled = false;
    if (error) { saveNote.textContent = "hata: " + error; saveNote.style.color = "var(--danger)"; return; }
    saveNote.textContent = "kaydedildi ✓";
    saveNote.style.color = "var(--success)";
    Object.assign(item, data);
    card.querySelector(".status-pill").className = `status-pill status-${item.status}`;
    card.querySelector(".status-pill").textContent = item.status;
    setTimeout(() => { saveNote.textContent = ""; }, 2500);
  });

  return card;
}

function applyFilter() {
  const status = document.getElementById("filter-status").value;
  const container = document.getElementById("feedback-container");
  container.innerHTML = "";
  const filtered = _allFeedback.filter(f => !status || f.status === status);
  document.getElementById("feedback-count").textContent = `(${filtered.length})`;
  if (!filtered.length) {
    container.innerHTML = '<div class="empty-state" style="display:block">Kayıt yok.</div>';
    return;
  }
  for (const item of filtered) container.appendChild(renderCard(item));
}

async function reloadFeedback() {
  const { data } = await getJSON("/api/feedback");
  _allFeedback = data || [];
  applyFilter();
}

function init() {
  document.getElementById("filter-status").addEventListener("change", applyFilter);
  reloadFeedback();
}

const feedbackForm = document.getElementById("feedback-form");
if (feedbackForm) {
  const feedbackButton = feedbackForm.querySelector("button");
  feedbackForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const textEl = document.getElementById("feedback-text");
    const text = textEl.value.trim();
    if (!text || feedbackButton.disabled) return; // cift-gonderim koruması
    feedbackButton.disabled = true;
    feedbackButton.textContent = "Gönderiliyor…";
    try {
      await getJSON("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      textEl.value = "";
      await reloadFeedback();
    } finally {
      feedbackButton.disabled = false;
      feedbackButton.textContent = "Gönder";
    }
  });
}

init();
