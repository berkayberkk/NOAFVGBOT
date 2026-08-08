"""
NOAFVGBOT V2 — Candlestick Trade Gallery Generator.

Renders high-resolution PNG gallery showing actual TradePassport lifecycle windows
(20 pre-entry bars -> Entry -> Outcome Candle -> 10 post-outcome bars).

INVARIANTS:
- Consumes real TradePassport records only. Never fabricates missing outcomes.
- Prominently displays QUARANTINED warning banner.
"""

import os
from typing import List, Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont

from research.v2.telemetry.passport import TradePassport, OutcomeState
from research.v2.telemetry.visualizer import render_trade_chart_window, PathObservation


def generate_trade_gallery(
    passports: List[TradePassport],
    full_market_path: List[PathObservation],
    output_path: str = "research/v2/results/v2_trade_gallery.png",
    is_quarantined: bool = True,
) -> str:
    """Renders a 1920x1080 trade gallery PNG."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img = Image.new("RGB", (1920, 1080), color="#0D1117")
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("arial.ttf", 24)
        font_header = ImageFont.truetype("arial.ttf", 16)
        font_body = ImageFont.truetype("arial.ttf", 12)
        font_small = ImageFont.truetype("arial.ttf", 10)
    except IOError:
        font_title = font_header = font_body = font_small = ImageFont.load_default()

    # Header
    draw.rectangle([(20, 20), (1900, 80)], fill="#161B22", outline="#30363D", width=1)
    draw.text((35, 30), "NOAFVGBOT V2 — CANDLESTICK TRADE LIFECYCLE GALLERY", fill="#58A6FF", font=font_title)

    if is_quarantined:
        draw.rectangle([(1380, 30), (1885, 70)], fill="#DA3633", outline="#F85149", width=1)
        draw.text((1395, 40), "RESEARCH / QUARANTINED — PARTIAL SMOKE", fill="#FFFFFF", font=font_header)

    targets = [p for p in passports if p.outcome_state == OutcomeState.TARGET_REACHED][:4]
    stops = [p for p in passports if p.outcome_state == OutcomeState.STOP_REACHED][:4]
    opens = [p for p in passports if p.outcome_state in (OutcomeState.ENTRY_TOUCHED, OutcomeState.OPEN)][:2]

    # Grid slots: 2 rows x 3 cols
    slots = [
        ("TARGET_REACHED #1", targets[0] if len(targets) > 0 else None),
        ("TARGET_REACHED #2", targets[1] if len(targets) > 1 else None),
        ("TARGET_REACHED #3", targets[2] if len(targets) > 2 else None),
        ("STOP_REACHED #1", stops[0] if len(stops) > 0 else None),
        ("STOP_REACHED #2", stops[1] if len(stops) > 1 else None),
        ("ENTRY_TOUCHED / OPEN #1", opens[0] if len(opens) > 0 else None),
    ]

    col_w, row_h = 610, 440
    for idx, (title, p) in enumerate(slots):
        r = idx // 3
        c = idx % 3
        x0 = 20 + c * 625
        y0 = 100 + r * 460
        x1 = x0 + col_w
        y1 = y0 + row_h

        draw.rectangle([(x0, y0), (x1, y1)], fill="#161B22", outline="#30363D", width=1)
        draw.text((x0 + 15, y0 + 12), title, fill="#C9D1D9", font=font_header)

        if p is None:
            msg = "NO STOP_REACHED IN CURRENT SAMPLE" if "STOP" in title else "NO DATA IN CURRENT SAMPLE"
            draw.text((x0 + 80, y0 + 200), msg, fill="#8B949E", font=font_header)
            continue

        # Render chart window for passport
        try:
            chart = render_trade_chart_window(p, full_market_path, pre_context=20, post_context=10)
            candles = chart.candles

            if candles:
                min_p = min(c.low for c in candles)
                max_p = max(c.high for c in candles)
                p_range = max(0.1, max_p - min_p)

                chart_x0 = x0 + 20
                chart_y0 = y0 + 50
                chart_w = col_w - 40
                chart_h = row_h - 100

                draw.rectangle([(chart_x0, chart_y0), (chart_x0 + chart_w, chart_y0 + chart_h)], fill="#0D1117", outline="#21262D")

                # Draw levels
                snap = p.decision_snapshot
                for level_val, color, lbl in [
                    (snap.structural_entry, "#58A6FF", "Entry"),
                    (snap.structural_stop, "#F85149", "SL"),
                    (snap.structural_target, "#3FB950", "TP"),
                ]:
                    if level_val is not None and min_p <= level_val <= max_p:
                        ly = chart_y0 + chart_h - int(((level_val - min_p) / p_range) * chart_h)
                        draw.line([(chart_x0, ly), (chart_x0 + chart_w, ly)], fill=color, width=1)
                        draw.text((chart_x0 + 5, ly - 12), f"{lbl}: {level_val:.2f}", fill=color, font=font_small)

                # Draw candles
                n_c = len(candles)
                bar_w = max(2, chart_w // max(1, n_c))

                for i, c_obs in enumerate(candles):
                    cx = chart_x0 + i * bar_w + bar_w // 2
                    cy_high = chart_y0 + chart_h - int(((c_obs.high - min_p) / p_range) * chart_h)
                    cy_low = chart_y0 + chart_h - int(((c_obs.low - min_p) / p_range) * chart_h)
                    cy_open = chart_y0 + chart_h - int(((c_obs.open - min_p) / p_range) * chart_h)
                    cy_close = chart_y0 + chart_h - int(((c_obs.close - min_p) / p_range) * chart_h)

                    c_color = "#3FB950" if c_obs.close >= c_obs.open else "#F85149"
                    draw.line([(cx, cy_high), (cx, cy_low)], fill=c_color, width=1)
                    draw.rectangle([(cx - max(1, bar_w // 4), min(cy_open, cy_close)), (cx + max(1, bar_w // 4), max(cy_open, cy_close))], fill=c_color)

            # Metadata info
            meta_str = f"ID: {p.passport_id[:8]} | Dir: {p.direction.name} | TF: {p.candidate_timeframe.name} | State: {p.outcome_state.value}"
            draw.text((x0 + 15, y1 - 35), meta_str, fill="#8B949E", font=font_body)
            ex = p.get_excursion()
            draw.text((x0 + 15, y1 - 20), f"MAE: {ex.mae_r:.2f}R | MFE: {ex.mfe_r:.2f}R", fill="#C9D1D9", font=font_small)

        except Exception as e:
            draw.text((x0 + 50, y0 + 180), f"Render Error: {str(e)}", fill="#F85149", font=font_small)

    img.save(output_path, "PNG")
    return output_path
