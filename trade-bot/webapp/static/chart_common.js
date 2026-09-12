/* Paylasilan mum grafigi cizim kodu -- module.js (modul-basi kazanan/kaybeden
 * ornekleri) ve visual_review.js (FAZ A gorsel inceleme paneli) TARAFINDAN
 * ORTAK kullanilir. Cizim mantigi tek yerde -- iki sayfa da AYNI canvas
 * motoruyla calisir, kopya kod YOK. */

const MODULE_ZONE_LABEL = {
  fvg: "FVG boşluğu", ifvg: "iFVG (kırılma+retest) bölgesi", ob: "Order Block gövdesi", trendline: null,
};

const CHART_W = 1040, CHART_H = 460;
const PAD_TOP = 20, PAD_BOTTOM = 20, PAD_LEFT = 90, PAD_RIGHT = 78;
const MIN_VISIBLE_BARS = 12;

function findBarIndex(candles, isoTime) {
  if (!isoTime) return -1;
  const t = new Date(isoTime).getTime();
  let best = -1, bestDiff = Infinity;
  for (let i = 0; i < candles.length; i++) {
    const diff = Math.abs(new Date(candles[i].t).getTime() - t);
    if (diff < bestDiff) { bestDiff = diff; best = i; }
  }
  return best;
}

function drawArrowhead(ctx, x, y, angle, size, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x - size * Math.cos(angle - Math.PI / 7), y - size * Math.sin(angle - Math.PI / 7));
  ctx.lineTo(x - size * Math.cos(angle + Math.PI / 7), y - size * Math.sin(angle + Math.PI / 7));
  ctx.closePath();
  ctx.fill();
}

/**
 * Grafigin TEK gorevi olan saf cizim fonksiyonu -- verilen [view.start,view.end)
 * bar araligini SABIT canvas boyutuna (CHART_W x CHART_H) sigdirir. Zoom/pan,
 * bu view araligini degistirip yeniden cagirmaktan ibaret (TradingView'daki
 * gibi) -- canvas'in kendisi buyumez/kuculmez, sadece icerigi degisir.
 *
 * ex.entry/ex.sl/ex.tp NULL olabilir (gecersiz/filtrelenmis sinyal -- hicbir
 * zaman islem acilmadi) -- bu durumda sadece zone/kutu cizilir, giris
 * isareti/cizgileri/ok ATLANIR (bkz. asagidaki null kontrolleri).
 */
function paintChart(canvas, ex, view, hoverIdx) {
  const candles = ex.candles;
  const width = CHART_W, height = CHART_H;
  const padTop = PAD_TOP, padBottom = PAD_BOTTOM, padLeft = PAD_LEFT, padRight = PAD_RIGHT;
  canvas.width = width + padLeft + padRight;
  canvas.height = height + padTop + padBottom;
  const ctx = canvas.getContext("2d");

  const vStart = Math.max(0, view.start), vEnd = Math.min(candles.length, view.end);
  const visCount = vEnd - vStart;
  const barW = width / visCount;
  const xOf = (i) => padLeft + (i - vStart) * barW + barW / 2;
  const inView = (i) => i >= vStart - 1 && i < vEnd + 1;

  const hasEntry = ex.entry !== null && ex.entry !== undefined;

  // Fiyat araligi: GORUNEN mumlar + entry/sl/tp (varsa) -- TradingView'in
  // "autoscale visible range" davranisi.
  const visCandles = candles.slice(vStart, vEnd);
  let lo = Math.min(...visCandles.map(c => c.l));
  let hi = Math.max(...visCandles.map(c => c.h));
  if (hasEntry) {
    for (const v of [ex.entry, ex.sl, ex.tp]) { if (v !== null && v !== undefined) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }
  }
  if (ex.zone) { lo = Math.min(lo, ex.zone.bottom); hi = Math.max(hi, ex.zone.top); }
  const range = (hi - lo) || 1;
  lo -= range * 0.08; hi += range * 0.08;
  const yOf = (price) => padTop + height * (1 - (price - lo) / (hi - lo));

  ctx.fillStyle = "#0f1216";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.save();
  ctx.beginPath();
  ctx.rect(padLeft, 0, width, canvas.height);
  ctx.clip();

  // Destek/Direnc seviyeleri
  let lastLabelY = -Infinity;
  const sortedLevels = [...(ex.sr_levels || [])].sort((a, b) => yOf(a.price) - yOf(b.price));
  for (const lvl of sortedLevels) {
    const y = yOf(lvl.price);
    if (y < padTop - 20 || y > padTop + height + 20) continue;
    ctx.strokeStyle = lvl.type === "resistance" ? "rgba(240,85,107,0.35)" : "rgba(62,207,142,0.35)";
    ctx.setLineDash([2, 3]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(padLeft + width, y);
    ctx.stroke();
    ctx.setLineDash([]);
    if (y - lastLabelY >= 11) {
      ctx.fillStyle = "#5a6270";
      ctx.font = "9.5px monospace";
      ctx.textAlign = "right";
      ctx.fillText(`${lvl.type === "resistance" ? "D" : "S"} ${lvl.price.toFixed(2)} (${lvl.touch_count}x)`, padLeft - 6, y + 3);
      ctx.textAlign = "left";
      lastLabelY = y;
    }
  }

  const signalBarIdx = findBarIndex(candles, ex.signal_time);
  const entryBarIdx = findBarIndex(candles, ex.entry_fill_time || ex.signal_time);
  const zoneEndBarIdx = entryBarIdx >= 0 ? entryBarIdx : candles.length - 1;

  // Zone (FVG/iFVG/OB) -- olustugu bardan dokunuldugu bara kadar kutu
  if (ex.zone && signalBarIdx >= 0) {
    const zoneStartIdx = ex.module === "fvg" ? Math.max(0, signalBarIdx - 2) : signalBarIdx;
    if (inView(zoneStartIdx) || inView(zoneEndBarIdx) || (zoneStartIdx < vStart && zoneEndBarIdx > vEnd)) {
      const boxX0 = Math.max(padLeft, xOf(zoneStartIdx) - barW / 2);
      const boxX1 = Math.min(padLeft + width, xOf(zoneEndBarIdx) + barW / 2);
      const zTop = yOf(ex.zone.top), zBot = yOf(ex.zone.bottom);
      const color = ex.direction === "BUY" ? "62,207,142" : "240,85,107";
      ctx.fillStyle = `rgba(${color},0.20)`;
      ctx.fillRect(boxX0, zTop, boxX1 - boxX0, Math.max(1.5, zBot - zTop));
      ctx.strokeStyle = `rgba(${color},0.55)`;
      ctx.lineWidth = 1;
      ctx.strokeRect(boxX0, zTop, boxX1 - boxX0, Math.max(1.5, zBot - zTop));
      const label = MODULE_ZONE_LABEL[ex.module];
      if (label && boxX1 - boxX0 > 30) {
        ctx.fillStyle = "rgba(230,233,239,0.75)";
        ctx.font = "10.5px sans-serif";
        ctx.fillText(label, boxX0 + 6, Math.min(zTop, zBot) - 4);
      }
    }
  }

  // Mumlar (sadece gorunenler)
  for (let i = vStart; i < vEnd; i++) {
    const c = candles[i];
    const x = xOf(i);
    const up = c.c >= c.o;
    ctx.strokeStyle = ctx.fillStyle = up ? "#3ecf8e" : "#f0556b";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, yOf(c.h));
    ctx.lineTo(x, yOf(c.l));
    ctx.stroke();
    const bodyTop = yOf(Math.max(c.o, c.c));
    const bodyBot = yOf(Math.min(c.o, c.c));
    const bw = Math.max(1, barW * 0.7);
    ctx.fillRect(x - bw / 2, bodyTop, bw, Math.max(1, bodyBot - bodyTop));
  }

  // Entry / SL / TP cizgileri + etiket -- SADECE gercek bir islem varsa (hasEntry)
  const lines = hasEntry ? [
    { price: ex.entry, color: "#4f8cff", label: `Giriş — ${ex.reason || ex.module.toUpperCase()}` },
    { price: ex.sl, color: "#f0556b", label: `Zarar-Dur (SL) ${ex.sl}` },
    { price: ex.tp, color: "#3ecf8e", label: `Hedef (TP) ${ex.tp}` },
  ] : [];
  for (const l of lines) {
    if (l.price === null || l.price === undefined) continue;
    const y = yOf(l.price);
    ctx.strokeStyle = l.color;
    ctx.setLineDash([5, 4]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(padLeft + width, y);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Giristen hedefe kesik ok
  if (hasEntry && entryBarIdx >= 0 && ex.tp !== null && ex.tp !== undefined && inView(entryBarIdx)) {
    const ex_ = xOf(entryBarIdx), ey = yOf(ex.entry);
    const tx = Math.min(padLeft + width - 4, ex_ + 220), ty = yOf(ex.tp);
    ctx.strokeStyle = "rgba(79,140,255,0.6)";
    ctx.setLineDash([3, 3]);
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(ex_, ey);
    ctx.lineTo(tx, ty);
    ctx.stroke();
    ctx.setLineDash([]);
    const angle = Math.atan2(ty - ey, tx - ex_);
    drawArrowhead(ctx, tx, ty, angle, 7, "rgba(79,140,255,0.85)");
  }

  // Dokunus/Giris isareti -- SADECE gercek bir islem varsa
  if (hasEntry && entryBarIdx >= 0 && inView(entryBarIdx)) {
    const ex_ = xOf(entryBarIdx), ey = yOf(ex.entry);
    const markColor = ex.direction === "BUY" ? "#3ecf8e" : "#f0556b";
    ctx.strokeStyle = markColor;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(ex_, ey, 8, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = markColor;
    ctx.beginPath();
    ctx.arc(ex_, ey, 2.5, 0, Math.PI * 2);
    ctx.fill();

    const triSize = 5;
    const triY = ex.direction === "BUY" ? ey - 16 : ey + 16;
    ctx.beginPath();
    if (ex.direction === "BUY") {
      ctx.moveTo(ex_, triY - triSize); ctx.lineTo(ex_ - triSize, triY + triSize); ctx.lineTo(ex_ + triSize, triY + triSize);
    } else {
      ctx.moveTo(ex_, triY + triSize); ctx.lineTo(ex_ - triSize, triY - triSize); ctx.lineTo(ex_ + triSize, triY - triSize);
    }
    ctx.closePath();
    ctx.fill();

    const labelText = "Giriş";
    ctx.font = "bold 10px sans-serif";
    const labelW = ctx.measureText(labelText).width + 10;
    const labelY = ex.direction === "BUY" ? triY - 22 : triY + 12;
    ctx.fillStyle = markColor;
    ctx.fillRect(ex_ - labelW / 2, labelY, labelW, 15);
    ctx.fillStyle = "#0f1216";
    ctx.textAlign = "center";
    ctx.fillText(labelText, ex_, labelY + 11);
    ctx.textAlign = "left";
  }

  // Gecersiz/filtrelenmis sinyal isareti (hasEntry=false) -- X isareti
  if (!hasEntry && signalBarIdx >= 0 && inView(signalBarIdx)) {
    const sx = xOf(signalBarIdx);
    const sy = padTop + 14;
    ctx.strokeStyle = "#e0a638";
    ctx.lineWidth = 2;
    const s = 6;
    ctx.beginPath();
    ctx.moveTo(sx - s, sy - s); ctx.lineTo(sx + s, sy + s);
    ctx.moveTo(sx + s, sy - s); ctx.lineTo(sx - s, sy + s);
    ctx.stroke();
  }

  // Crosshair + OHLC tooltip (hover)
  if (hoverIdx !== null && hoverIdx >= vStart && hoverIdx < vEnd) {
    const c = candles[hoverIdx];
    const x = xOf(hoverIdx);
    ctx.strokeStyle = "rgba(230,233,239,0.35)";
    ctx.setLineDash([3, 3]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, padTop);
    ctx.lineTo(x, padTop + height);
    ctx.stroke();
    ctx.setLineDash([]);

    const boxLines = [fmtTime(c.t), `A ${c.o}  Y ${c.h}`, `D ${c.l}  K ${c.c}`];
    ctx.font = "10.5px monospace";
    const boxW = Math.max(...boxLines.map(t => ctx.measureText(t).width)) + 14;
    const boxX = Math.min(x + 8, padLeft + width - boxW - 4);
    ctx.fillStyle = "rgba(23,27,33,0.95)";
    ctx.strokeStyle = "#262c35";
    ctx.lineWidth = 1;
    ctx.fillRect(boxX, padTop + 4, boxW, 42);
    ctx.strokeRect(boxX, padTop + 4, boxW, 42);
    ctx.fillStyle = "#e6e9ef";
    boxLines.forEach((t, i) => ctx.fillText(t, boxX + 7, padTop + 17 + i * 12));
  }

  ctx.restore();

  // Sag kenar fiyat etiketleri (Giris/SL/TP) -- clip DISINDA, hep gorunur
  for (const l of lines) {
    if (l.price === null || l.price === undefined) continue;
    const y = yOf(l.price);
    ctx.fillStyle = l.color;
    ctx.font = "11px monospace";
    ctx.fillText(l.label, padLeft + width + 6, y + 3);
  }
}

/** Zoom (tekerlek) + pan (surukle) + crosshair (hover) ekleyip ilk cizimi yapar. */
function createInteractiveChart(canvas, ex) {
  const n = ex.candles.length;
  const view = { start: 0, end: n };
  let hoverIdx = null;
  let dragging = false, dragStartX = 0, dragStartView = null;

  canvas.style.cursor = "crosshair";
  const repaint = () => paintChart(canvas, ex, view, hoverIdx);
  repaint();

  function clampView(v) {
    const len = Math.max(MIN_VISIBLE_BARS, Math.min(n, v.end - v.start));
    let start = v.start, end = start + len;
    if (start < 0) { start = 0; end = len; }
    if (end > n) { end = n; start = Math.max(0, end - len); }
    return { start, end };
  }

  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const mouseX = (e.clientX - rect.left) * scaleX;
    const curLen = view.end - view.start;
    const zoomFactor = e.deltaY > 0 ? 1.18 : 1 / 1.18;
    const newLen = Math.round(Math.max(MIN_VISIBLE_BARS, Math.min(n, curLen * zoomFactor)));
    const frac = Math.min(1, Math.max(0, (mouseX - PAD_LEFT) / CHART_W));
    const mouseBarIdx = view.start + frac * curLen;
    const newStart = Math.round(mouseBarIdx - frac * newLen);
    Object.assign(view, clampView({ start: newStart, end: newStart + newLen }));
    repaint();
  }, { passive: false });

  canvas.addEventListener("mousedown", (e) => {
    dragging = true;
    dragStartX = e.clientX;
    dragStartView = { ...view };
    canvas.style.cursor = "grabbing";
  });

  window.addEventListener("mousemove", (e) => {
    if (dragging) {
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const dx = (e.clientX - dragStartX) * scaleX;
      const barW = CHART_W / (dragStartView.end - dragStartView.start);
      const barsDelta = Math.round(-dx / barW);
      const len = dragStartView.end - dragStartView.start;
      Object.assign(view, clampView({ start: dragStartView.start + barsDelta, end: dragStartView.start + barsDelta + len }));
      repaint();
      return;
    }
    const rect = canvas.getBoundingClientRect();
    if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) {
      if (hoverIdx !== null) { hoverIdx = null; repaint(); }
      return;
    }
    const scaleX = canvas.width / rect.width;
    const mouseX = (e.clientX - rect.left) * scaleX;
    const barW = CHART_W / (view.end - view.start);
    const idx = view.start + Math.floor((mouseX - PAD_LEFT) / barW);
    if (idx !== hoverIdx) { hoverIdx = idx; repaint(); }
  });

  window.addEventListener("mouseup", () => {
    if (dragging) { dragging = false; canvas.style.cursor = "crosshair"; }
  });

  canvas.addEventListener("mouseleave", () => {
    if (!dragging && hoverIdx !== null) { hoverIdx = null; repaint(); }
  });

  canvas.addEventListener("dblclick", () => {
    Object.assign(view, { start: 0, end: n });
    repaint();
  });

  return { resetView: () => { Object.assign(view, { start: 0, end: n }); repaint(); } };
}

function outcomeBadge(outcome) {
  const map = {
    win: ["Kazandı", "win"], loss: ["Kaybetti", "loss"], breakeven: ["Breakeven", "breakeven"],
    invalid: ["Geçersiz/Filtrelendi", "invalid"],
  };
  const [label, cls] = map[outcome] || [outcome, ""];
  return `<span class="outcome-badge outcome-${cls}">${label}</span>`;
}
