"""
PROTOTIP (scratch, kalici degil): win-rate arastirmasinin (bkz.
NOA_KONSEPTI_KAYNAK_ANALIZI.md) ikinci adayi -- FVG giris derinligi.

BULGU: mevcut kod, bullish FVG icin entry_price=bottom (gap'in EN UZAK/
DERIN kenari -- TAM retracement gerektirir) kullaniyor. Ama arastirilan
ICT kaynaklarinin cogu "Consequent Encroachment (CE)" denen %50 orta
noktasini "en yuksek olasilikli giris" olarak tanimliyor -- ki bu zaten
projenin KENDI iFVG modulunde (`consequent_encroachment = (top+bottom)/2`)
kullanilan tanim, ama plain FVG'de degil. Bu script, giris derinligini
(0.0=sig/yakin kenar, 1.0=mevcut/derin kenar) tarayarak hangi noktanin
GERCEKTEN daha iyi win rate/beklenti verdigini test ediyor.

DUZELTILMIS motorla (strategy/signal_engine.py yerine burada DOGRUDAN
Signal insa ediliyor, ama AYNI SL/TP formulleri + backtest/engine.py
kullanilarak) KEPT_SYMBOLS + gercekci spread ile test edilir.
"""

import json

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, KEPT_SYMBOLS, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO, BREAKEVEN_TRIGGER_PCT, BREAKEVEN_ENABLED_MODULES
from strategy.fvg import detect_fvgs, FVGDirection
from strategy.signal_engine import Signal, SignalType, Confidence, SetupType
from backtest.engine import run_backtest
from backtest.validation import calculate_metrics

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
ENTRY_FRACTIONS = [0.0, 0.25, 0.5, 0.618, 0.705, 0.79, 1.0]  # 0=sig kenar, 1=mevcut/derin kenar (bugunku varsayilan)


def _fvg_signals_at_depth(candles, config, fraction: float) -> list[Signal]:
    r_mult = MODULE_R_MULTIPLE["fvg"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["fvg"]
    be_pct = BREAKEVEN_TRIGGER_PCT if "fvg" in BREAKEVEN_ENABLED_MODULES else None
    signals = []
    for f in detect_fvgs(candles, config=config):
        if not f.valid:
            continue
        is_bull = f.direction == FVGDirection.BULLISH
        signal_index = f.end_index
        if signal_index >= len(candles):
            continue
        # fraction=0 -> sig kenar (top for bull, bottom for bear), fraction=1 -> derin kenar (mevcut varsayilan)
        entry = (f.top - fraction * (f.top - f.bottom)) if is_bull else (f.bottom + fraction * (f.top - f.bottom))
        buffer = (f.top - f.bottom) * sl_ratio
        stop_loss = f.bottom - buffer if is_bull else f.top + buffer
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        take_profit = entry + r_mult * risk if is_bull else entry - r_mult * risk
        signals.append(Signal(
            index=signal_index, type=SignalType.BUY if is_bull else SignalType.SELL,
            confidence=Confidence.MEDIUM, setup_type=SetupType.FVG_ONLY,
            entry=entry, stop_loss=stop_loss, take_profit=take_profit,
            breakeven_trigger_pct=be_pct, reason=f"FVG-depth{fraction}",
        ))
    return signals


def main():
    results = {}
    for symbol in KEPT_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
        config = StrategyConfig(spread=SPREAD_BY_SYMBOL[symbol])

        sym_result = {}
        for frac in ENTRY_FRACTIONS:
            sigs = _fvg_signals_at_depth(candles, config, frac)
            result = run_backtest(candles, sigs, config=config)
            metrics = calculate_metrics(result.trades, total_signals=len(sigs),
                                        unfilled_orders=result.unfilled_orders, skipped_no_tp=result.skipped_no_tp)
            sym_result[str(frac)] = {
                "n_signals": len(sigs), "n_filled": metrics.filled_trades,
                "win_rate": metrics.win_rate, "expectancy_r": metrics.expectancy_r,
                "profit_factor": metrics.profit_factor, "total_net_r": metrics.total_net_r,
            }
            print(f"  frac={frac:.3f} n_sig={len(sigs):5} n_filled={metrics.filled_trades:5} "
                  f"win={metrics.win_rate:.1%} exp={metrics.expectancy_r:.4f} pf={metrics.profit_factor:.2f}", flush=True)
        results[symbol] = sym_result

    with open("fvg_entry_depth_study_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: fvg_entry_depth_study_results.json")

    print("\n=== HAVUZLANMIS (3 sembol) ===")
    for frac in ENTRY_FRACTIONS:
        n = sum(results[s][str(frac)]["n_filled"] for s in KEPT_SYMBOLS)
        if n == 0:
            print(f"  frac={frac:.3f} n=0")
            continue
        total_r = sum(results[s][str(frac)]["total_net_r"] for s in KEPT_SYMBOLS)
        wins = sum(round(results[s][str(frac)]["win_rate"] * results[s][str(frac)]["n_filled"]) for s in KEPT_SYMBOLS)
        print(f"  frac={frac:.3f} n={n:6} win={wins/n:.1%} exp={total_r/n:.4f}")


if __name__ == "__main__":
    main()
