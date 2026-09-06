function card(title, rows) {
  const div = document.createElement("div");
  div.className = "config-card";
  div.innerHTML = `<h3>${escapeHtml(title)}</h3>` +
    `<table class="config-table"><tbody>${rows.map(([k, v]) =>
      `<tr><td class="k">${escapeHtml(k)}</td><td class="v">${escapeHtml(String(v))}</td></tr>`).join("")}</tbody></table>`;
  return div;
}

async function init() {
  const { data, error } = await getJSON("/api/strategy_config");
  const container = document.getElementById("config-container");
  if (error || !data) {
    container.innerHTML = `<div class="empty-state" style="display:block">${escapeHtml(error || "yüklenemedi")}</div>`;
    return;
  }

  const grid = document.createElement("div");
  grid.className = "config-grid";

  grid.appendChild(card("Kapsam", [
    ["KEPT_SYMBOLS (canlı işlem)", data.kept_symbols.join(", ")],
    ["Hariç tutulan sembol sayısı", data.excluded_symbols_count],
  ]));

  grid.appendChild(card("Modül R-katı (TP hedefi)", Object.entries(data.module_r_multiple).map(([k, v]) => [k, v + "R"])));

  grid.appendChild(card("Modül SL Tamponu (kat)", Object.entries(data.module_sl_buffer_ratio).map(([k, v]) => [k, v + "x"])));

  grid.appendChild(card("Devre Dışı Zaman Dilimleri", Object.entries(data.module_disabled_timeframes).map(([k, v]) => [k, v.length ? v.join(", ") : "–"])));

  grid.appendChild(card("Breakeven-Stop", [
    ["Tetik eşiği", (data.breakeven_trigger_pct * 100).toFixed(0) + "% (TP mesafesinin)"],
    ["Etkin modüller", data.breakeven_enabled_modules.join(", ") || "–"],
  ]));

  const dc = data.default_config;
  grid.appendChild(card("FVG Geometri", [
    ["ATR periyodu", dc.atr_period],
    ["Min gap/ATR", dc.min_gap_to_atr_ratio],
    ["Max gap/ATR", dc.max_gap_to_atr_ratio],
    ["Max orta mum oranı", dc.max_middle_candle_ratio],
  ]));

  grid.appendChild(card("Order Block Geometri", [
    ["Ortalama aralık periyodu", dc.avg_range_period],
    ["Güçlü hareket oranı", dc.strong_move_ratio],
  ]));

  grid.appendChild(card("Hacim Teyidi (FVG)", [
    ["Periyot", dc.volume_confirm_period],
    ["Oran", dc.volume_confirm_ratio + "x"],
  ]));

  grid.appendChild(card("Destek/Direnç & Trendline", [
    ["Swing lookback (S/R)", dc.swing_lookback],
    ["Tolerans (ATR katı)", dc.tolerance_atr_ratio],
    ["Min dokunuş sayısı", dc.min_level_touch_count],
    ["Trendline swing lookback", dc.trendline_swing_lookback],
    ["Trendline min dokunuş", dc.trendline_min_touches],
    ["Trendline dokunuş toleransı", dc.trendline_touch_tolerance_atr_ratio],
  ]));

  container.appendChild(grid);
}

init();
