async function getJSON(url, opts) {
  try {
    const res = await fetch(url, opts);
    if (!res.ok) return { data: null, error: `HTTP ${res.status}` };
    return await res.json();
  } catch (e) {
    return { data: null, error: "sunucuya ulaşılamıyor (" + e.message + ")" };
  }
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s ?? "";
  return div.innerHTML;
}

function fmtTime(iso) {
  try { return new Date(iso).toLocaleString("tr-TR", { hour12: false }); } catch { return iso; }
}

function fmtTradeR(v) {
  return (v === null || v === undefined) ? "–" : (v >= 0 ? "+" : "") + v.toFixed(2) + "R";
}
