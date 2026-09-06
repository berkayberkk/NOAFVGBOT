"""
PROTOTIP (scratch, kalici degil): win rate arastirmasinin bir sonraki
adimi -- MODULE_R_MULTIPLE ve MODULE_SL_BUFFER_RATIO (strategy/config.py)
bu oturumun EN BASINDA, eski (same-bar-iyimserlikli) scratch metodolojisi
ile kalibre edilmisti. Artik DUZELTILMIS motor + yeni giris derinligi
(sig kenar) benimsendigine gore, bu parametrelerin OPTIMAL degerleri
DEGISMIS olabilir -- eski kalibrasyon artik gecerli olmayabilir.

Bu script, FVG ve OB icin R-katini (TP hedefini) DUZELTILMIS motorla,
YENI (sig kenar) giris kuraliyla, KEPT_SYMBOLS + gercekci spread ile
yeniden tarar -- SL tamponu sabit tutuluyor (mevcut degerler), sadece
R-multiple sweep ediliyor (SL tamponu ayri bir calismada ele alinacak).
"""

import json
from dataclasses import replace

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, KEPT_SYMBOLS, MODULE_SL_BUFFER_RATIO, BREAKEVEN_TRIGGER_PCT, BREAKEVEN_ENABLED_MODULES
from strategy.fvg import detect_fvgs, FVGDirection
from strategy.order_block import detect_order_blocks, OBDirection
from strategy.signal_engine import Signal, SignalType, Confidence, SetupType
from backtest.engine import run_backtest
from backtest.validation import calculate_metrics

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
R_MULTIPLES = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]


def _fvg_signals(candles, config, r_mult):
    sl_ratio = MODULE_SL_BUFFER_RATIO["fvg"]
    be_pct = BREAKEVEN_TRIGGER_PCT if "fvg" in BREAKEVEN_ENABLED_MODULES else None
    out = []
    for f in detect_fvgs(candles, config=config):
        if not f.valid:
            continue
        is_bull = f.direction == FVGDirection.BULLISH
        if f.end_index >= len(candles):
            continue
        entry = f.entry_price  # artik sig/yakin kenar (2026-09-03 guncellemesi)
        buffer = (f.top - f.bottom) * sl_ratio
        stop_loss = f.bottom - buffer if is_bull else f.top + buffer
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        take_profit = entry + r_mult * risk if is_bull else entry - r_mult * risk
        out.append(Signal(index=f.end_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                          confidence=Confidence.MEDIUM, setup_type=SetupType.FVG_ONLY,
                          entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                          breakeven_trigger_pct=be_pct, reason="fvg-recal"))
    return out


def _ob_signals(candles, config, r_mult):
    sl_ratio = MODULE_SL_BUFFER_RATIO["ob"]
    be_pct = BREAKEVEN_TRIGGER_PCT if "ob" in BREAKEVEN_ENABLED_MODULES else None
    out = []
    for ob in detect_order_blocks(candles, config=config):
        is_bull = ob.direction == OBDirection.BULLISH
        if ob.impulse_index >= len(candles):
            continue
        entry = ob.top if is_bull else ob.bottom  # artik sig/yakin kenar
        buffer = (ob.top - ob.bottom) * sl_ratio
        stop_loss = (ob.bottom - buffer) if is_bull else (ob.top + buffer)
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        take_profit = entry + r_mult * risk if is_bull else entry - r_mult * risk
        out.append(Signal(index=ob.impulse_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                          confidence=Confidence.MEDIUM, setup_type=SetupType.OB_ONLY,
                          entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                          breakeven_trigger_pct=be_pct, reason="ob-recal"))
    return out


def main():
    results = {}
    for symbol in KEPT_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
        config = StrategyConfig(spread=SPREAD_BY_SYMBOL[symbol])

        sym_result = {"fvg": {}, "ob": {}}
        for r_mult in R_MULTIPLES:
            for mod_name, fn in [("fvg", _fvg_signals), ("ob", _ob_signals)]:
                sigs = fn(candles, config, r_mult)
                result = run_backtest(candles, sigs, config=config)
                metrics = calculate_metrics(result.trades, total_signals=len(sigs),
                                            unfilled_orders=result.unfilled_orders, skipped_no_tp=result.skipped_no_tp)
                sym_result[mod_name][str(r_mult)] = {
                    "n_filled": metrics.filled_trades, "win_rate": metrics.win_rate,
                    "expectancy_r": metrics.expectancy_r, "profit_factor": metrics.profit_factor,
                    "total_net_r": metrics.total_net_r,
                }
                print(f"  {mod_name:4} R={r_mult:.1f} n={metrics.filled_trades:5} win={metrics.win_rate:.1%} "
                      f"exp={metrics.expectancy_r:.4f} pf={metrics.profit_factor:.2f}", flush=True)
        results[symbol] = sym_result

    with open("r_multiple_recalibration_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: r_multiple_recalibration_results.json")

    print("\n=== HAVUZLANMIS (3 sembol) ===")
    for mod_name in ["fvg", "ob"]:
        print(f"-- {mod_name} --")
        for r_mult in R_MULTIPLES:
            n = sum(results[s][mod_name][str(r_mult)]["n_filled"] for s in KEPT_SYMBOLS)
            if n == 0:
                continue
            total_r = sum(results[s][mod_name][str(r_mult)]["total_net_r"] for s in KEPT_SYMBOLS)
            wins = sum(round(results[s][mod_name][str(r_mult)]["win_rate"] * results[s][mod_name][str(r_mult)]["n_filled"]) for s in KEPT_SYMBOLS)
            print(f"  R={r_mult:.1f} n={n:6} win={wins/n:.1%} exp={total_r/n:.4f}")


if __name__ == "__main__":
    main()
