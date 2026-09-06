"""
PROTOTIP (scratch, kalici degil): SL tamponu genisletme bulgusunun
(Aday 6/7 -- FVG/OB/iFVG) Trendline'a da genellenip genellenemeyecegini
test eder. Trendline farkli bir SL formulu kullanir (bolge boyutu degil,
dokunus/retest barinin ATR'sinin kati -- `buffer = atr * MODULE_SL_BUFFER_RATIO["trendline"]`,
mevcut resmi deger=0.5), ama AYNI additive-buffer mekanizmasi. Trendline
bu oturumun EN GUCLU/EN TUTARLI modulu olarak biliniyordu (results/README.md)
ama hicbir SL/giris filtresi onun uzerinde denenmedi -- bu, o bosluk.

Ayni kutsal-holdout disiplini: train+val'da aday secimi, HIC BAKILMAMIS
test'te tek atimlik dogrulama.
"""

import json

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from backtest.validation import split_chronological, calculate_metrics
from strategy.config import StrategyConfig, KEPT_SYMBOLS, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO, BREAKEVEN_TRIGGER_PCT, BREAKEVEN_ENABLED_MODULES
from strategy.trendline import detect_trendlines, detect_trendline_reversals, TrendlineDirection
from strategy.fvg import compute_atr_series
from strategy.signal_engine import Signal, SignalType, Confidence, SetupType
from backtest.engine import run_backtest

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
CANDIDATES = [0.5, 1.0, 2.0, 3.0, 5.0, 7.0]  # mevcut resmi = 0.5


def _trendline_signals(candles, config, sl_ratio):
    r_mult = MODULE_R_MULTIPLE["trendline"]
    be_pct = BREAKEVEN_TRIGGER_PCT if "trendline" in BREAKEVEN_ENABLED_MODULES else None
    atr_series = compute_atr_series(candles, config.atr_period)
    lines = detect_trendlines(candles, config=config)
    out = []

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
                buffer = (atr_series[k] or 0) * sl_ratio
                entry = touch_price
                stop_loss = entry - buffer if is_bull else entry + buffer
                risk = abs(entry - stop_loss)
                signal_index = k - 1
                if risk > 0 and signal_index >= 0:
                    take_profit = entry + r_mult * risk if is_bull else entry - r_mult * risk
                    out.append(Signal(index=signal_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                                      confidence=Confidence.MEDIUM, setup_type=SetupType.TRENDLINE_ONLY,
                                      entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                                      breakeven_trigger_pct=be_pct, reason="tl-bounce-slholdout"))
            was_touching = touched

    reversals = detect_trendline_reversals(candles, lines, config=config)
    for r in reversals:
        rc = candles[r.retest_index]
        buffer = (atr_series[r.retest_index] or 0) * sl_ratio
        entry = rc["close"]
        stop_loss = (rc["low"] - buffer) if r.is_bullish else (rc["high"] + buffer)
        risk = abs(entry - stop_loss)
        signal_index = r.retest_index - 1
        if risk <= 0 or signal_index < 0:
            continue
        take_profit = entry + r_mult * risk if r.is_bullish else entry - r_mult * risk
        out.append(Signal(index=signal_index, type=SignalType.BUY if r.is_bullish else SignalType.SELL,
                          confidence=Confidence.MEDIUM, setup_type=SetupType.TRENDLINE_ONLY,
                          entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                          breakeven_trigger_pct=be_pct, reason="tl-reversal-slholdout"))

    out.sort(key=lambda s: s.index)
    return out


def _eval(candles, config, sl_ratio):
    sigs = _trendline_signals(candles, config, sl_ratio)
    result = run_backtest(candles, sigs, config=config)
    m = calculate_metrics(result.trades, total_signals=len(sigs),
                           unfilled_orders=result.unfilled_orders, skipped_no_tp=result.skipped_no_tp)
    return {"n_filled": m.filled_trades, "win_rate": m.win_rate,
            "expectancy_r": m.expectancy_r, "profit_factor": m.profit_factor,
            "total_net_r": m.total_net_r}


def main():
    results = {}
    for symbol in KEPT_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
        config = StrategyConfig(spread=SPREAD_BY_SYMBOL[symbol])

        _, (train, val, test) = split_chronological(candles, 0.60, 0.20, 0.20)
        trainval = train + val
        print(f"  trainval n={len(trainval)}  test(holdout) n={len(test)}", flush=True)

        sym_out = {"trainval": {}, "test": {}}
        best_ratio, best_exp = None, None
        for sl_ratio in CANDIDATES:
            r = _eval(trainval, config, sl_ratio)
            sym_out["trainval"][str(sl_ratio)] = r
            print(f"  [trainval] tl sl={sl_ratio:5.2f} n={r['n_filled']:5} "
                  f"win={r['win_rate']:.1%} exp={r['expectancy_r']:.4f}", flush=True)
            if best_exp is None or r["expectancy_r"] > best_exp:
                best_exp, best_ratio = r["expectancy_r"], sl_ratio

        official_ratio = MODULE_SL_BUFFER_RATIO["trendline"]
        print(f"  -> tl: trainval'da en iyi expectancy sl={best_ratio} "
              f"(mevcut resmi={official_ratio}). SIMDI TEK ATIMLIK holdout testi:", flush=True)

        for sl_ratio in sorted(set([official_ratio, best_ratio])):
            r = _eval(test, config, sl_ratio)
            sym_out["test"][str(sl_ratio)] = r
            tag = "SECILEN-ADAY" if sl_ratio == best_ratio else "MEVCUT-RESMI"
            print(f"  [HOLDOUT/TEST] tl sl={sl_ratio:5.2f} ({tag}) n={r['n_filled']:5} "
                  f"win={r['win_rate']:.1%} exp={r['expectancy_r']:.4f}", flush=True)

        results[symbol] = sym_out

    with open("trendline_sl_buffer_holdout_check_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: trendline_sl_buffer_holdout_check_results.json")

    print("\n=== OZET (holdout/test) ===")
    for symbol in KEPT_SYMBOLS:
        for ratio_str, r in results[symbol]["test"].items():
            print(f"  {symbol:8} tl sl={ratio_str:>6} n={r['n_filled']:5} "
                  f"win={r['win_rate']:.1%} exp={r['expectancy_r']:.4f}")


if __name__ == "__main__":
    main()
