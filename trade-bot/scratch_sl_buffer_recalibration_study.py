"""
PROTOTIP (scratch, kalici degil): win rate arastirmasinin bir sonraki
adimi -- MODULE_SL_BUFFER_RATIO'nun (strategy/config.py) YENI giris
kuraliyla (sig kenar) yeniden kalibre edilmesi gerekip gerekmedigini
test eder. Ayni R-katı taramasinin SL tamponu versiyonu -- R sabit
tutuluyor (mevcut resmi degerler), sadece SL tamponu sweep ediliyor.
"""

import json

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, KEPT_SYMBOLS, MODULE_R_MULTIPLE, BREAKEVEN_TRIGGER_PCT, BREAKEVEN_ENABLED_MODULES
from strategy.fvg import detect_fvgs, FVGDirection
from strategy.order_block import detect_order_blocks, OBDirection
from strategy.signal_engine import Signal, SignalType, Confidence, SetupType
from backtest.engine import run_backtest
from backtest.validation import calculate_metrics

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
SL_RATIOS_FVG = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]   # mevcut resmi = 1.0
SL_RATIOS_OB = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0]        # mevcut resmi = 3.0


def _fvg_signals(candles, config, sl_ratio):
    r_mult = MODULE_R_MULTIPLE["fvg"]
    be_pct = BREAKEVEN_TRIGGER_PCT if "fvg" in BREAKEVEN_ENABLED_MODULES else None
    out = []
    for f in detect_fvgs(candles, config=config):
        if not f.valid or f.end_index >= len(candles):
            continue
        is_bull = f.direction == FVGDirection.BULLISH
        entry = f.entry_price
        buffer = (f.top - f.bottom) * sl_ratio
        stop_loss = f.bottom - buffer if is_bull else f.top + buffer
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        take_profit = entry + r_mult * risk if is_bull else entry - r_mult * risk
        out.append(Signal(index=f.end_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                          confidence=Confidence.MEDIUM, setup_type=SetupType.FVG_ONLY,
                          entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                          breakeven_trigger_pct=be_pct, reason="fvg-slrecal"))
    return out


def _ob_signals(candles, config, sl_ratio):
    r_mult = MODULE_R_MULTIPLE["ob"]
    be_pct = BREAKEVEN_TRIGGER_PCT if "ob" in BREAKEVEN_ENABLED_MODULES else None
    out = []
    for ob in detect_order_blocks(candles, config=config):
        if ob.impulse_index >= len(candles):
            continue
        is_bull = ob.direction == OBDirection.BULLISH
        entry = ob.top if is_bull else ob.bottom
        buffer = (ob.top - ob.bottom) * sl_ratio
        stop_loss = (ob.bottom - buffer) if is_bull else (ob.top + buffer)
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        take_profit = entry + r_mult * risk if is_bull else entry - r_mult * risk
        out.append(Signal(index=ob.impulse_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                          confidence=Confidence.MEDIUM, setup_type=SetupType.OB_ONLY,
                          entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                          breakeven_trigger_pct=be_pct, reason="ob-slrecal"))
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
        for sl_ratio in SL_RATIOS_FVG:
            sigs = _fvg_signals(candles, config, sl_ratio)
            result = run_backtest(candles, sigs, config=config)
            metrics = calculate_metrics(result.trades, total_signals=len(sigs),
                                        unfilled_orders=result.unfilled_orders, skipped_no_tp=result.skipped_no_tp)
            sym_result["fvg"][str(sl_ratio)] = {
                "n_filled": metrics.filled_trades, "win_rate": metrics.win_rate,
                "expectancy_r": metrics.expectancy_r, "profit_factor": metrics.profit_factor,
                "total_net_r": metrics.total_net_r,
            }
            print(f"  fvg sl={sl_ratio:.2f} n={metrics.filled_trades:5} win={metrics.win_rate:.1%} "
                  f"exp={metrics.expectancy_r:.4f} pf={metrics.profit_factor:.2f}", flush=True)
        for sl_ratio in SL_RATIOS_OB:
            sigs = _ob_signals(candles, config, sl_ratio)
            result = run_backtest(candles, sigs, config=config)
            metrics = calculate_metrics(result.trades, total_signals=len(sigs),
                                        unfilled_orders=result.unfilled_orders, skipped_no_tp=result.skipped_no_tp)
            sym_result["ob"][str(sl_ratio)] = {
                "n_filled": metrics.filled_trades, "win_rate": metrics.win_rate,
                "expectancy_r": metrics.expectancy_r, "profit_factor": metrics.profit_factor,
                "total_net_r": metrics.total_net_r,
            }
            print(f"  ob  sl={sl_ratio:.2f} n={metrics.filled_trades:5} win={metrics.win_rate:.1%} "
                  f"exp={metrics.expectancy_r:.4f} pf={metrics.profit_factor:.2f}", flush=True)
        results[symbol] = sym_result

    with open("sl_buffer_recalibration_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: sl_buffer_recalibration_results.json")

    print("\n=== HAVUZLANMIS (3 sembol) ===")
    for mod_name, ratios in [("fvg", SL_RATIOS_FVG), ("ob", SL_RATIOS_OB)]:
        print(f"-- {mod_name} --")
        for sl_ratio in ratios:
            n = sum(results[s][mod_name][str(sl_ratio)]["n_filled"] for s in KEPT_SYMBOLS)
            if n == 0:
                continue
            total_r = sum(results[s][mod_name][str(sl_ratio)]["total_net_r"] for s in KEPT_SYMBOLS)
            wins = sum(round(results[s][mod_name][str(sl_ratio)]["win_rate"] * results[s][mod_name][str(sl_ratio)]["n_filled"]) for s in KEPT_SYMBOLS)
            print(f"  sl={sl_ratio:.2f} n={n:6} win={wins/n:.1%} exp={total_r/n:.4f}")


if __name__ == "__main__":
    main()
