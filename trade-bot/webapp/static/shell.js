// Global shell: sidebar toggle (mobil), tema anahtari, saat, sistem durum noktalari.
// Her sayfada base.html tarafindan yuklenir -- sayfaya ozel JS bundan SONRA calisir.

(function () {
  const root = document.documentElement;
  const THEME_KEY = "noafvgbot_theme";
  const saved = localStorage.getItem(THEME_KEY);
  if (saved) root.setAttribute("data-theme", saved);

  const toggleBtn = document.getElementById("theme-toggle-btn");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      const current = root.getAttribute("data-theme") ||
        (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
      const next = current === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      localStorage.setItem(THEME_KEY, next);
    });
  }

  const sidebarToggle = document.getElementById("sidebar-toggle-btn");
  const shell = document.getElementById("app-shell");
  if (sidebarToggle && shell) {
    sidebarToggle.addEventListener("click", () => shell.classList.toggle("sidebar-open"));
    document.addEventListener("click", (e) => {
      if (!shell.classList.contains("sidebar-open")) return;
      if (e.target.closest("#app-sidebar") || e.target === sidebarToggle) return;
      shell.classList.remove("sidebar-open");
    });
  }

  function tickClock() {
    const el = document.getElementById("hdr-clock");
    if (!el) return;
    const now = new Date();
    el.innerHTML = "<b>" + now.toLocaleTimeString("tr-TR", { hour12: false }) + "</b>";
  }
  tickClock();
  setInterval(tickClock, 1000);
})();

// ---------- Paylaşılan sistem durumu (header noktaları + status bar) ----------
function setDot(id, state) {
  // state: "ok" | "warn" | "err" | "unknown"
  const el = document.getElementById(id);
  if (el) el.className = "status-dot " + state;
}

async function refreshShellStatus() {
  const { data: acc, error: accErr } = await getJSON("/api/mt5/account");
  const mt5Ok = !accErr && !!acc;
  setDot("dot-mt5", mt5Ok ? "ok" : "err");
  const sbMt5 = document.getElementById("sb-mt5");
  if (sbMt5) sbMt5.textContent = "MT5: " + (mt5Ok ? `bağlı (#${acc.login})` : "bağlantı yok");

  const { data: pending } = await getJSON("/api/pending");
  let botActive = false, newestUpdate = null;
  if (pending) {
    for (const info of Object.values(pending)) {
      if (info.available) {
        botActive = true;
        const t = new Date(info.updated).getTime();
        if (!newestUpdate || t > newestUpdate) newestUpdate = t;
      }
    }
  }
  setDot("dot-bot", botActive ? "ok" : "warn");
  const sbBot = document.getElementById("sb-bot");
  if (sbBot) sbBot.textContent = "Bot: " + (botActive ? "aktif" : "hiçbir grafikte çalışmıyor");

  const dataFresh = newestUpdate ? (Date.now() - newestUpdate) < 10 * 60 * 1000 : null;
  setDot("dot-data", dataFresh === null ? "unknown" : (dataFresh ? "ok" : "warn"));
  const sbData = document.getElementById("sb-data");
  if (sbData) sbData.textContent = "Veri: " + (newestUpdate ? new Date(newestUpdate).toLocaleTimeString("tr-TR", { hour12: false }) + (dataFresh ? "" : " (bayat)") : "—");

  const sbUpdated = document.getElementById("sb-updated");
  if (sbUpdated) sbUpdated.textContent = "son güncelleme: " + new Date().toLocaleTimeString("tr-TR", { hour12: false });

  return { mt5Ok, botActive, acc };
}

refreshShellStatus();
setInterval(refreshShellStatus, 15000);

// ---------- Paylaşılan drawer (trade detayı vb. sayfalar kullanır) ----------
function openDrawer(el) {
  el.classList.add("open");
  document.getElementById("drawer-backdrop").classList.add("open");
}
function closeDrawer(el) {
  el.classList.remove("open");
  document.getElementById("drawer-backdrop").classList.remove("open");
}
document.getElementById("drawer-backdrop")?.addEventListener("click", () => {
  document.querySelectorAll(".drawer.open").forEach(d => closeDrawer(d));
});
