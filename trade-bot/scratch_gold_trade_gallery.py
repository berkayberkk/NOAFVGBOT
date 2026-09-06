"""
PROTOTIP (scratch, kalici degil): kullanicinin istegi -- GOLD icin, elimizdeki
TUM modulleri (FVG/iFVG/OB/Trendline) kullanarak, TUM veriyle test edip
GERCEKTEN ALINAN (tek-pozisyon modelinde) her islemi -- kaynak yapisini
(FVG/OB/iFVG bolgesi ya da Trendline cizgisi) da iceren -- bir "islem
galerisi" JSON'una donusturur. Bu, HTML tarafinda her islemi mum
grafiginde, zon/cizgi overlay'iyle birlikte gorsellestirmek icin.

YONTEM: strategy/signal_engine.py'nin generate_signals fonksiyonunu
BIREBIR ayni formullerle (resmi MODULE_R_MULTIPLE/MODULE_SL_BUFFER_RATIO,
bugunku Aday 6/7/8 SL tamponu degerleri dahil) burada tekrar uretiyoruz --
ama her Signal'i, onu dogrudan kendisinden turettigimiz kaynak yapiya
(FVG/iFVG/OB nesnesi ya da Trendline slope/intercept) esleyen bir yan
sozluk (id(signal) -> geometry) ile birlikte. Sonra bu sinyaller GERCEK
backtest/engine.py'den (run_backtest) geciriliyor -- yani islem sonuclari
(entry/exit/won/r_multiple) production motorunun ta kendisinden geliyor,
sadece geometri bilgisi ekstra. En son, scratch_corrected_account_simulation.py
'deki AYNI tek-pozisyon "taken" secim mantigi uygulanip GERCEKTEN alinan
islemler filtreleniyor (KEPT_SYMBOLS/$10k hesap simulasyonuyla birebir
tutarli olsun diye).

Cikti: results/trade_gallery/GOLD_all_modules.json
"""

import json
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import (
    StrategyConfig, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO,
    BREAKEVEN_TRIGGER_PCT, BREAKEVEN_ENABLED_MODULES,
)
from strategy.fvg import detect_fvgs, FVGDirection, compute_atr_series
from strategy.ifvg import detect_confirmed_ifvgs
from strategy.order_block import detect_order_blocks, OBDirection
from strategy.trendline import detect_trendlines, detect_trendline_reversals, TrendlineDirection
from strategy.signal_engine import Signal, SignalType, Confidence, SetupType
from backtest.engine import run_backtest

SYMBOL = "GOLD"
SPREAD = 0.25
CONFIG = StrategyConfig(spread=SPREAD)
N_BEFORE = 20   # pencere: formasyon basindan kac bar once
N_AFTER = 12    # pencere: cikistan kac bar sonra
OUT_DIR = Path("results/trade_gallery")


def _breakeven_pct(module: str):
    return BREAKEVEN_TRIGGER_PCT if module in BREAKEVEN_ENABLED_MODULES else None


def generate_signals_with_geometry(candles: list[dict], config: StrategyConfig):
    """generate_signals ile BIREBIR ayni formuller, ama (signal, geometry) ciftleri doner."""
    pairs = []  # list[(Signal, dict)]

    # --- FVG ---
    for f in detect_fvgs(candles, config=config):
        if not f.valid or not f.volume_confirmed:
            continue
        is_bull = f.direction == FVGDirection.BULLISH
        signal_index = f.end_index
        if signal_index >= len(candles):
            continue
        entry = f.entry_price
        buffer = (f.top - f.bottom) * MODULE_SL_BUFFER_RATIO["fvg"]
        stop_loss = f.bottom - buffer if is_bull else f.top + buffer
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        r_mult = MODULE_R_MULTIPLE["fvg"]
        take_profit = entry + r_mult * risk if is_bull else entry - r_mult * risk
        s = Signal(index=signal_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                   confidence=Confidence.MEDIUM, setup_type=SetupType.FVG_ONLY,
                   entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                   breakeven_trigger_pct=_breakeven_pct("fvg"),
                   in_killzone=f.in_killzone, volume_confirmed=f.volume_confirmed,
                   reason=f"FVG({f.direction.value})")
        geom = {"kind": "zone", "label": "FVG", "top": f.top, "bottom": f.bottom,
                "left_index": f.start_index, "right_index": f.end_index}
        pairs.append((s, geom))

    # --- iFVG ---
    for e in detect_confirmed_ifvgs(candles, config=config):
        is_bull = e.new_dir == FVGDirection.BULLISH
        signal_index = e.retest_index
        if signal_index >= len(candles):
            continue
        entry = e.consequent_encroachment
        buffer = (e.top - e.bottom) * MODULE_SL_BUFFER_RATIO["ifvg"]
        stop_loss = (e.bottom - buffer) if is_bull else (e.top + buffer)
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        r_mult = MODULE_R_MULTIPLE["ifvg"]
        take_profit = entry + r_mult * risk if is_bull else entry - r_mult * risk
        s = Signal(index=signal_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                   confidence=Confidence.MEDIUM, setup_type=SetupType.IFVG_ONLY,
                   entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                   breakeven_trigger_pct=_breakeven_pct("ifvg"),
                   reason=f"iFVG({e.new_dir.value})")
        geom = {"kind": "zone", "label": "iFVG", "top": e.top, "bottom": e.bottom,
                "left_index": e.broken_index, "right_index": e.retest_index}
        pairs.append((s, geom))

    # --- Order Block ---
    for ob in detect_order_blocks(candles, config=config):
        is_bull = ob.direction == OBDirection.BULLISH
        signal_index = ob.impulse_index
        if signal_index >= len(candles):
            continue
        entry = ob.top if is_bull else ob.bottom
        buffer = (ob.top - ob.bottom) * MODULE_SL_BUFFER_RATIO["ob"]
        stop_loss = (ob.bottom - buffer) if is_bull else (ob.top + buffer)
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        r_mult = MODULE_R_MULTIPLE["ob"]
        take_profit = entry + r_mult * risk if is_bull else entry - r_mult * risk
        s = Signal(index=signal_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                   confidence=Confidence.MEDIUM, setup_type=SetupType.OB_ONLY,
                   entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                   breakeven_trigger_pct=_breakeven_pct("ob"),
                   in_killzone=ob.in_killzone, volume_confirmed=ob.volume_confirmed,
                   reason=f"OB({ob.direction.value})")
        geom = {"kind": "zone", "label": "OB", "top": ob.top, "bottom": ob.bottom,
                "left_index": ob.index, "right_index": ob.impulse_index}
        pairs.append((s, geom))

    # --- Trendline (sicrama + kirilim+retest) ---
    r_mult_tl = MODULE_R_MULTIPLE["trendline"]
    sl_ratio_tl = MODULE_SL_BUFFER_RATIO["trendline"]
    atr_series = compute_atr_series(candles, config.atr_period)
    lines = detect_trendlines(candles, config=config)

    for tl in lines:
        is_bull = tl.direction == TrendlineDirection.ASCENDING
        start = tl.known_index + 1
        end = tl.broken_index if tl.broken_index is not None else len(candles)
        was_touching = False
        for k in range(max(start, 0), min(end, len(candles))):
            line_price = tl.price_at(k)
            tol = (atr_series[k] or 0) * config.trendline_touch_tolerance_atr_ratio
            c = candles[k]
            touched = (c["low"] <= line_price + tol) if is_bull else (c["high"] >= line_price - tol)
            if touched and not was_touching:
                touch_price = c["low"] if is_bull else c["high"]
                buffer = (atr_series[k] or 0) * sl_ratio_tl
                entry = touch_price
                stop_loss = entry - buffer if is_bull else entry + buffer
                risk = abs(entry - stop_loss)
                signal_index = k - 1
                if risk > 0 and signal_index >= 0:
                    take_profit = entry + r_mult_tl * risk if is_bull else entry - r_mult_tl * risk
                    s = Signal(index=signal_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                               confidence=Confidence.MEDIUM, setup_type=SetupType.TRENDLINE_ONLY,
                               entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                               breakeven_trigger_pct=_breakeven_pct("trendline"),
                               reason=f"Trendline-bounce({tl.direction.value})")
                    geom = {"kind": "line", "label": "Trendline", "slope": tl.slope,
                            "intercept": tl.intercept, "left_index": tl.known_index}
                    pairs.append((s, geom))
            was_touching = touched

    reversals = detect_trendline_reversals(candles, lines, config=config)
    for r in reversals:
        rc = candles[r.retest_index]
        buffer = (atr_series[r.retest_index] or 0) * sl_ratio_tl
        entry = rc["close"]
        stop_loss = (rc["low"] - buffer) if r.is_bullish else (rc["high"] + buffer)
        risk = abs(entry - stop_loss)
        signal_index = r.retest_index - 1
        if risk <= 0 or signal_index < 0:
            continue
        take_profit = entry + r_mult_tl * risk if r.is_bullish else entry - r_mult_tl * risk
        s = Signal(index=signal_index, type=SignalType.BUY if r.is_bullish else SignalType.SELL,
                   confidence=Confidence.MEDIUM, setup_type=SetupType.TRENDLINE_ONLY,
                   entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                   breakeven_trigger_pct=_breakeven_pct("trendline"),
                   reason=f"Trendline-reversal({'bullish' if r.is_bullish else 'bearish'})")
        tl = r.source_trendline
        geom = {"kind": "line", "label": "Trendline", "slope": tl.slope,
                "intercept": tl.intercept, "left_index": tl.known_index}
        pairs.append((s, geom))

    pairs.sort(key=lambda sg: sg[0].index)
    return pairs


def select_taken_trades(trades):
    """scratch_corrected_account_simulation.py::simulate_account ile BIREBIR ayni tek-pozisyon secimi."""
    ordered = sorted(trades, key=lambda t: t.entry_fill_index if t.entry_fill_index is not None else t.entry_index)
    taken = []
    next_available = -1
    for t in ordered:
        fi = t.entry_fill_index if t.entry_fill_index is not None else t.entry_index
        if fi < next_available:
            continue
        taken.append(t)
        next_available = (t.exit_index if t.exit_index is not None else fi) + 1
    return taken


def _fmt_time(c):
    t = c["time"]
    return t.isoformat() if hasattr(t, "isoformat") else str(t)


def main():
    print(f"veri yukleniyor: {SYMBOL}", flush=True)
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{SYMBOL}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
    print(f"{len(candles)} M30 mumu, {candles[0]['time']} - {candles[-1]['time']}", flush=True)

    pairs = generate_signals_with_geometry(candles, CONFIG)
    geom_by_id = {id(s): g for s, g in pairs}
    signals = [s for s, g in pairs]
    print(f"aday sinyal: {len(signals)}", flush=True)

    result = run_backtest(candles, signals, config=CONFIG)
    print(f"islem (dolan): {len(result.trades)}, dolmayan: {result.unfilled_orders}", flush=True)

    taken = select_taken_trades(result.trades)
    print(f"tek-pozisyon modelinde GERCEKTEN alinan: {len(taken)}", flush=True)

    def _cc(c):
        return {"t": _fmt_time(c), "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]}

    gallery = []
    n_split = 0
    for i, t in enumerate(taken):
        geom = geom_by_id[id(t.signal)]
        anchor = t.signal.index
        fill_idx = t.entry_fill_index if t.entry_fill_index is not None else anchor
        exit_idx = t.exit_index if t.exit_index is not None else fill_idx

        # PENCERE FORMASYON ANKORUNA (anchor/geom.left_index) DEGIL, DOLUM
        # barina (fill_idx) gore kuruluyor -- cunku formasyon ile dolum
        # arasinda da (limit fiyati uzak olabildigi icin) bazen binlerce bar
        # gecebiliyor. Zon/cizgi geometrisi formasyondan cok once basliyor
        # olsa bile absolut fiyat seviyesi (top/bottom/slope) olarak
        # saklaniyor -- frontend, pencere disina tasan kismini kirpar
        # (sol kenar negatifse "goruntu disinda basliyor" olarak yorumlanir).
        entry_lo = max(0, fill_idx - N_BEFORE)
        entry_hi = min(len(candles), fill_idx + N_AFTER + 1)

        # Genis SL/TP tamponu bazi islemleri COK uzun surede cozuyor (bazen
        # binlerce bar) -- bu yuzden dolum ile cikis arasindaki TUM araligi
        # saklamak yerine, cikis COK uzaktaysa (entry_hi'nin >5 bar otesindeyse)
        # ayri, kompakt bir "cikis yakin cekimi" penceresi tutuluyor, arada
        # atlanan bar sayisi ayrica kaydediliyor (frontend'de "... N bar
        # atlandi ..." bosluguyla gosterilecek).
        if exit_idx <= entry_hi + 5:
            lo = entry_lo
            hi = min(len(candles), exit_idx + N_AFTER + 1)
            window = candles[lo:hi]
            exit_window = None
            skipped_bars = 0
        else:
            n_split += 1
            window = candles[entry_lo:entry_hi]
            exit_lo = max(entry_hi, exit_idx - N_BEFORE)
            exit_hi = min(len(candles), exit_idx + N_AFTER + 1)
            exit_window = candles[exit_lo:exit_hi]
            skipped_bars = exit_lo - entry_hi
            lo = entry_lo  # entry penceresinin index donusumu icin

        geom_out = dict(geom)
        geom_out["left_index_in_window"] = geom["left_index"] - lo
        if geom["kind"] == "zone":
            zone_right_abs = min(geom["right_index"], lo + len(window) - 1)
            geom_out["right_index_in_window"] = zone_right_abs - lo
        else:
            # frontend kolayligi icin: price(x_local) = slope*x_local + local_intercept
            # (x_local = pencere ici bar index'i, mutlak index'e gerek kalmadan).
            geom_out["right_index_in_window"] = len(window) - 1
            geom_out["local_intercept"] = geom["slope"] * lo + geom["intercept"]
            if exit_window is not None:
                geom_out["exit_local_intercept"] = geom["slope"] * exit_lo + geom["intercept"]

        gallery.append({
            "id": i,
            "module": t.signal.setup_type.value,
            "direction": t.signal.type.value,
            "reason": t.signal.reason,
            "won": t.won,
            "is_breakeven": t.is_breakeven,
            "r_multiple": t.r_multiple,
            "entry": t.executed_entry,
            "stop_loss": t.stop_loss,
            "take_profit": t.take_profit,
            "exit_price": t.executed_exit,
            "signal_index_in_window": anchor - lo,
            "fill_index_in_window": fill_idx - lo,
            "exit_index_in_window": None if exit_window is not None else (exit_idx - lo),
            "entry_time": _fmt_time(candles[fill_idx]),
            "exit_time": _fmt_time(candles[exit_idx]) if exit_idx < len(candles) else None,
            "geometry": geom_out,
            "candles": [_cc(c) for c in window],
            "skipped_bars": skipped_bars,
            "exit_candles": [_cc(c) for c in exit_window] if exit_window is not None else None,
            "exit_marker_index_in_exit_window": (exit_idx - exit_lo) if exit_window is not None else None,
        })
    print(f"bolunmus (uzun sureli) islem: {n_split}/{len(taken)}", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{SYMBOL}_all_modules.json"
    with open(out_path, "w") as f:
        json.dump({"symbol": SYMBOL, "spread": SPREAD, "n_taken": len(gallery), "trades": gallery}, f)
    print(f"\nyazildi: {out_path} ({len(gallery)} islem)")

    by_module = {}
    for tr in gallery:
        by_module.setdefault(tr["module"], {"n": 0, "win": 0})
        by_module[tr["module"]]["n"] += 1
        if tr["won"]:
            by_module[tr["module"]]["win"] += 1
    print("\n=== MODUL DAGILIMI ===")
    for m, v in by_module.items():
        print(f"  {m:10} n={v['n']:4} win={v['win']/v['n']:.1%}")


if __name__ == "__main__":
    main()
