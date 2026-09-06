"""
PROTOTIP (scratch, kalici degil): kullanicinin istegi -- GOLD icin $10k
hesap simulasyonunu (a) COKLU zaman dilimine (M30 + H1) genisletmek, yani
ayni hesap her iki zaman diliminden de sinyal alabilsin (tek-pozisyon
kisitlamasi artik GERCEK ZAMANA gore, bar index'ine gore DEGIL -- cunku
M30 index'i ile H1 index'i karsilastirilamaz), (b) her SL/breakeven
islemi icin "neden kaybetti" kok neden siniflandirmasi uretmek (Maximum
Favorable Excursion -- MFE -- analizi ile).

TIMEFRAME KAPSAMI: sadece M30 + H1 (kullanicinin acikca belirttigi
ikisi). H4 (FVG/iFVG/Trendline icin) ve W1 (OB icin) `strategy/config.py:
MODULE_DISABLED_TIMEFRAMES`'te zaten devre disi -- ESKI (duzeltme
oncesi) metodolojiyle kalibre edilmis bir karar, bu script buna
DOKUNMUYOR/yeniden test etmiyor, kapsam disi birakiyor (bilinen bir
sinirlama olarak burada da belirtiliyor).

MFE (Maximum Favorable Excursion) siniflandirmasi -- SADECE kaybeden/
breakeven islemler icin (won=False) anlamli:
  - ani_ters      : mfe_pct < %10  -- giris hemen ters gitti, muhtemelen
                     yanlis zamanlama/sahte sinyal (fakeout)
  - erken_basarisiz: %10 <= mfe_pct < %40 -- biraz lehte hareket oldu ama
                     cabuk sondu
  - yakin_iskalama : %40 <= mfe_pct < %80 -- planli mesafenin onemli bir
                     kismini kat etti, sonra donup SL'e gitti
  - cok_yakin_iskalama: mfe_pct >= %80 -- TP'ye COK yakindi, son anda
                     ters donup kaybetti -- en "can sikici" ve en
                     AKSIYON ALINABILIR kategori (kismi kar alma/trailing
                     stop gibi fikirlerle kurtarilabilir olabilir)
Breakeven (is_breakeven=True) islemler ayri, kendi kategorisinde --
tanim geregi zaten breakeven tetigine (BREAKEVEN_TRIGGER_PCT) kadar
lehte gitmis, sonra girise geri donmus islemler, "gercek" bir kayip
degil.
"""

import json
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import (
    StrategyConfig, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO,
    BREAKEVEN_TRIGGER_PCT, BREAKEVEN_ENABLED_MODULES, MODULE_DISABLED_TIMEFRAMES,
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
STARTING_EQUITY = 10_000.0
RISK_PCT = 0.01
TIMEFRAMES = [Timeframe.M30, Timeframe.H1]
N_BEFORE = 20
N_AFTER = 12
OUT_DIR = Path("results/trade_gallery")

_MODULE_KEY = {"FVG": "fvg", "iFVG": "ifvg", "OB": "ob", "Trendline": "trendline"}


def generate_signals_with_geometry(candles, config, tf_name):
    """generate_signals ile BIREBIR ayni formuller (bkz. strategy/signal_engine.py),
    (signal, geometry) ciftleri doner. MODULE_DISABLED_TIMEFRAMES'e uyar."""
    pairs = []

    def _disabled(module_key):
        return tf_name in MODULE_DISABLED_TIMEFRAMES.get(module_key, ())

    if not _disabled("fvg"):
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
            be = BREAKEVEN_TRIGGER_PCT if "fvg" in BREAKEVEN_ENABLED_MODULES else None
            s = Signal(index=signal_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                       confidence=Confidence.MEDIUM, setup_type=SetupType.FVG_ONLY,
                       entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                       breakeven_trigger_pct=be, in_killzone=f.in_killzone,
                       volume_confirmed=f.volume_confirmed, reason=f"FVG({f.direction.value})")
            geom = {"kind": "zone", "label": "FVG", "top": f.top, "bottom": f.bottom,
                    "left_index": f.start_index, "right_index": f.end_index}
            pairs.append((s, geom))

    if not _disabled("ifvg"):
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
            be = BREAKEVEN_TRIGGER_PCT if "ifvg" in BREAKEVEN_ENABLED_MODULES else None
            s = Signal(index=signal_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                       confidence=Confidence.MEDIUM, setup_type=SetupType.IFVG_ONLY,
                       entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                       breakeven_trigger_pct=be, reason=f"iFVG({e.new_dir.value})")
            geom = {"kind": "zone", "label": "iFVG", "top": e.top, "bottom": e.bottom,
                    "left_index": e.broken_index, "right_index": e.retest_index}
            pairs.append((s, geom))

    if not _disabled("ob"):
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
            be = BREAKEVEN_TRIGGER_PCT if "ob" in BREAKEVEN_ENABLED_MODULES else None
            s = Signal(index=signal_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                       confidence=Confidence.MEDIUM, setup_type=SetupType.OB_ONLY,
                       entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                       breakeven_trigger_pct=be, in_killzone=ob.in_killzone,
                       volume_confirmed=ob.volume_confirmed, reason=f"OB({ob.direction.value})")
            geom = {"kind": "zone", "label": "OB", "top": ob.top, "bottom": ob.bottom,
                    "left_index": ob.index, "right_index": ob.impulse_index}
            pairs.append((s, geom))

    if not _disabled("trendline"):
        r_mult_tl = MODULE_R_MULTIPLE["trendline"]
        sl_ratio_tl = MODULE_SL_BUFFER_RATIO["trendline"]
        be_tl = BREAKEVEN_TRIGGER_PCT if "trendline" in BREAKEVEN_ENABLED_MODULES else None
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
                                   breakeven_trigger_pct=be_tl, reason=f"Trendline-bounce({tl.direction.value})")
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
                       breakeven_trigger_pct=be_tl, reason=f"Trendline-reversal({'bullish' if r.is_bullish else 'bearish'})")
            tl = r.source_trendline
            geom = {"kind": "line", "label": "Trendline", "slope": tl.slope,
                    "intercept": tl.intercept, "left_index": tl.known_index}
            pairs.append((s, geom))

    pairs.sort(key=lambda sg: sg[0].index)
    return pairs


def compute_mfe_pct(t, candles):
    is_buy = t.signal.type == SignalType.BUY
    entry = t.executed_entry
    planned = abs(t.take_profit - entry)
    if planned <= 0:
        return 0.0
    fi = t.entry_fill_index
    ei = t.exit_index if t.exit_index is not None else fi
    best = entry
    for i in range(fi, min(ei + 1, len(candles))):
        c = candles[i]
        best = max(best, c["high"]) if is_buy else min(best, c["low"])
    mfe = abs(best - entry)
    return min(1.0, mfe / planned)


def classify_failure(t, mfe_pct):
    if t.won:
        return None
    if t.is_breakeven:
        return "breakeven"
    if mfe_pct < 0.10:
        return "ani_ters"
    if mfe_pct < 0.40:
        return "erken_basarisiz"
    if mfe_pct < 0.80:
        return "yakin_iskalama"
    return "cok_yakin_iskalama"


def _fmt_time(c):
    t = c["time"]
    return t.isoformat() if hasattr(t, "isoformat") else str(t)


def main():
    print(f"veri yukleniyor: {SYMBOL}", flush=True)
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{SYMBOL}_M1_canonical.csv")

    tf_candles = {}
    tf_geom = {}
    all_records = []  # {"tf": str, "trade": Trade}

    for tf in TIMEFRAMES:
        v2, _ = resample_m1(m1, tf)
        candles = [candlev2_to_strategy_dict(c) for c in v2]
        tf_candles[tf.name] = candles
        print(f"{tf.name}: {len(candles)} mum, {candles[0]['time']} - {candles[-1]['time']}", flush=True)

        pairs = generate_signals_with_geometry(candles, CONFIG, tf.name)
        geom_by_id = {id(s): g for s, g in pairs}
        tf_geom[tf.name] = geom_by_id
        signals = [s for s, g in pairs]
        result = run_backtest(candles, signals, config=CONFIG)
        print(f"  aday sinyal={len(signals)} dolan={len(result.trades)} dolmayan={result.unfilled_orders}", flush=True)
        for t in result.trades:
            all_records.append({"tf": tf.name, "trade": t})

    def fill_time(rec):
        t = rec["trade"]
        c = tf_candles[rec["tf"]]
        fi = t.entry_fill_index if t.entry_fill_index is not None else t.entry_index
        return c[min(fi, len(c) - 1)]["time"]

    def exit_time(rec):
        t = rec["trade"]
        c = tf_candles[rec["tf"]]
        fi = t.entry_fill_index if t.entry_fill_index is not None else t.entry_index
        ei = t.exit_index if t.exit_index is not None else fi
        return c[min(ei, len(c) - 1)]["time"]

    all_records.sort(key=fill_time)

    taken = []
    next_available_time = None
    n_skipped_overlap = 0
    for rec in all_records:
        ft = fill_time(rec)
        if next_available_time is not None and ft < next_available_time:
            n_skipped_overlap += 1
            continue
        taken.append(rec)
        next_available_time = exit_time(rec)

    print(f"\ncoklu-zaman-dilimi tek-pozisyon modelinde alinan: {len(taken)}/{len(all_records)} "
          f"(cakisma nedeniyle atlanan: {n_skipped_overlap})", flush=True)

    # --- $10k hesap simulasyonu (compound + fixed), tek-pozisyon, GERCEK ZAMAN sirali ---
    equity = STARTING_EQUITY
    peak = equity
    max_dd_dollar = 0.0
    max_dd_pct = 0.0
    fixed_equity = STARTING_EQUITY
    fixed_risk = STARTING_EQUITY * RISK_PCT
    fixed_peak = fixed_equity
    fixed_max_dd_dollar = 0.0
    fixed_max_dd_pct = 0.0

    module_stats = {}
    tf_stats = {}
    failure_stats = {}
    equity_curve = []
    fixed_curve = []
    gallery = []
    wins = 0
    breakevens = 0

    for i, rec in enumerate(taken):
        t = rec["trade"]
        tf_name = rec["tf"]
        candles = tf_candles[tf_name]
        geom = tf_geom[tf_name][id(t.signal)]
        module = t.signal.setup_type.value

        r = t.r_multiple
        risk_amount = equity * RISK_PCT
        pnl = risk_amount * r
        equity += pnl
        peak = max(peak, equity)
        dd = peak - equity
        max_dd_dollar = max(max_dd_dollar, dd)
        max_dd_pct = max(max_dd_pct, (dd / peak) if peak > 0 else 0.0)

        fixed_equity += fixed_risk * r
        fixed_peak = max(fixed_peak, fixed_equity)
        fdd = fixed_peak - fixed_equity
        fixed_max_dd_dollar = max(fixed_max_dd_dollar, fdd)
        fixed_max_dd_pct = max(fixed_max_dd_pct, (fdd / fixed_peak) if fixed_peak > 0 else 0.0)

        ms = module_stats.setdefault(module, {"n": 0, "wins": 0, "pnl_fixed": 0.0})
        ms["n"] += 1
        ms["pnl_fixed"] += fixed_risk * r
        ts = tf_stats.setdefault(tf_name, {"n": 0, "wins": 0, "pnl_fixed": 0.0})
        ts["n"] += 1
        ts["pnl_fixed"] += fixed_risk * r

        if t.won:
            wins += 1
            ms["wins"] += 1
            ts["wins"] += 1
        if t.is_breakeven:
            breakevens += 1

        equity_curve.append(round(equity, 2))
        fixed_curve.append(round(fixed_equity, 2))

        mfe_pct = compute_mfe_pct(t, candles)
        failure = classify_failure(t, mfe_pct)
        if failure:
            fs = failure_stats.setdefault(failure, {"n": 0, "by_module": {}})
            fs["n"] += 1
            fs["by_module"][module] = fs["by_module"].get(module, 0) + 1

        # --- gorsellestirme penceresi (fill-ankorlu, cok uzun islemler bolunuyor) ---
        anchor = t.signal.index
        fill_idx = t.entry_fill_index if t.entry_fill_index is not None else anchor
        exit_idx = t.exit_index if t.exit_index is not None else fill_idx

        entry_lo = max(0, fill_idx - N_BEFORE)
        entry_hi = min(len(candles), fill_idx + N_AFTER + 1)
        if exit_idx <= entry_hi + 5:
            lo = entry_lo
            hi = min(len(candles), exit_idx + N_AFTER + 1)
            window = candles[lo:hi]
            exit_window = None
            exit_lo = None
            skipped_bars = 0
        else:
            window = candles[entry_lo:entry_hi]
            exit_lo = max(entry_hi, exit_idx - N_BEFORE)
            exit_hi = min(len(candles), exit_idx + N_AFTER + 1)
            exit_window = candles[exit_lo:exit_hi]
            skipped_bars = exit_lo - entry_hi
            lo = entry_lo

        geom_out = dict(geom)
        geom_out["left_index_in_window"] = geom["left_index"] - lo
        if geom["kind"] == "zone":
            zone_right_abs = min(geom["right_index"], lo + len(window) - 1)
            geom_out["right_index_in_window"] = zone_right_abs - lo
        else:
            geom_out["right_index_in_window"] = len(window) - 1
            geom_out["local_intercept"] = geom["slope"] * lo + geom["intercept"]
            if exit_window is not None:
                geom_out["exit_local_intercept"] = geom["slope"] * exit_lo + geom["intercept"]

        gallery.append({
            "id": i,
            "timeframe": tf_name,
            "module": module,
            "direction": t.signal.type.value,
            "reason": t.signal.reason,
            "won": t.won,
            "is_breakeven": t.is_breakeven,
            "r_multiple": t.r_multiple,
            "mfe_pct": round(mfe_pct, 4),
            "failure_reason": failure,
            "entry": t.executed_entry,
            "stop_loss": t.stop_loss,
            "take_profit": t.take_profit,
            "exit_price": t.executed_exit,
            "equity_after_fixed": round(fixed_equity, 2),
            "signal_index_in_window": anchor - lo,
            "fill_index_in_window": fill_idx - lo,
            "exit_index_in_window": None if exit_window is not None else (exit_idx - lo),
            "entry_time": _fmt_time(candles[fill_idx]),
            "exit_time": _fmt_time(candles[min(exit_idx, len(candles) - 1)]),
            "geometry": geom_out,
            "candles": [{"t": _fmt_time(c), "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]} for c in window],
            "skipped_bars": skipped_bars,
            "exit_candles": [{"t": _fmt_time(c), "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]} for c in exit_window] if exit_window is not None else None,
            "exit_marker_index_in_exit_window": (exit_idx - exit_lo) if exit_window is not None else None,
        })

    n = len(taken)
    summary = {
        "symbol": SYMBOL, "spread": SPREAD, "timeframes": [tf.name for tf in TIMEFRAMES],
        "n_candidate_trades": len(all_records), "n_skipped_overlap": n_skipped_overlap, "n_taken": n,
        "win_rate": (wins / n) if n else 0.0, "breakeven_count": breakevens,
        "final_equity_compound": round(equity, 2), "net_pnl_pct_compound": (equity - STARTING_EQUITY) / STARTING_EQUITY,
        "max_drawdown_pct_compound": max_dd_pct, "max_drawdown_dollar_compound": round(max_dd_dollar, 2),
        "final_equity_fixed": round(fixed_equity, 2), "net_pnl_pct_fixed": (fixed_equity - STARTING_EQUITY) / STARTING_EQUITY,
        "max_drawdown_pct_fixed": fixed_max_dd_pct, "max_drawdown_dollar_fixed": round(fixed_max_dd_dollar, 2),
        "module_stats": {m: {"n": v["n"], "win_rate": v["wins"] / v["n"] if v["n"] else 0, "pnl_fixed": round(v["pnl_fixed"], 2)} for m, v in module_stats.items()},
        "timeframe_stats": {tfn: {"n": v["n"], "win_rate": v["wins"] / v["n"] if v["n"] else 0, "pnl_fixed": round(v["pnl_fixed"], 2)} for tfn, v in tf_stats.items()},
        "failure_stats": failure_stats,
        "equity_curve_compound": equity_curve, "equity_curve_fixed": fixed_curve,
    }

    print("\n=== SONUC (M30+H1 birlesik, tek-pozisyon, $10k) ===")
    print(f"alinan: {n}  win={summary['win_rate']:.1%}  breakeven={breakevens}")
    print(f"bilesik: ${equity:,.2f} ({summary['net_pnl_pct_compound']:+.1%})  maxDD={max_dd_pct:.1%}")
    print(f"sabit-$: ${fixed_equity:,.2f} ({summary['net_pnl_pct_fixed']:+.1%})  maxDD={fixed_max_dd_pct:.1%}")
    print("\nmodul:")
    for m, v in summary["module_stats"].items():
        print(f"  {m:10} n={v['n']:4} win={v['win_rate']:.1%} pnl=${v['pnl_fixed']:>10,.2f}")
    print("\nzaman dilimi:")
    for tfn, v in summary["timeframe_stats"].items():
        print(f"  {tfn:6} n={v['n']:4} win={v['win_rate']:.1%} pnl=${v['pnl_fixed']:>10,.2f}")
    print("\nkayip/breakeven kok neden dagilimi:")
    for k, v in failure_stats.items():
        print(f"  {k:20} n={v['n']:4}  {v['by_module']}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / f"{SYMBOL}_mtf_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    with open(OUT_DIR / f"{SYMBOL}_mtf_trades.json", "w") as f:
        json.dump({"symbol": SYMBOL, "n_taken": len(gallery), "trades": gallery}, f)
    print(f"\nyazildi: {OUT_DIR}/{SYMBOL}_mtf_summary.json, {OUT_DIR}/{SYMBOL}_mtf_trades.json")


if __name__ == "__main__":
    main()
