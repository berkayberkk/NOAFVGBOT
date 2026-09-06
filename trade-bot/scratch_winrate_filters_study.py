"""
PROTOTIP (scratch, kalici degil): "win rate'i nasil artirabiliriz"
arastirmasinin (bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md "Win rate
iyilestirme arastirmasi", 2026-09-03 -- WebSearch ile ICT/SMC
literaturunden derlendi) ablation testi.

Iki YENI aday filtre test ediliyor (FVG + Order Block icin, bkz.
strategy/fvg.py:FVG.in_killzone/volume_confirmed,
strategy/order_block.py:OrderBlock.in_killzone/volume_confirmed):
1. Killzone: sinyal, ICT killzone saatlerinde (Londra/NY AM/NY PM,
   UTC) mi olustu.
2. Hacim teyidi: displacement/impuls mumunun tick_volume'u son 20
   mumun ortalamasinin 1.5 katindan fazla mi.

METODOLOJIK DISIPLIN: bu test, ARTIK DUZELTILMIS motoru
(strategy/signal_engine.py + backtest/engine.py -- same-bar-
iyimserligi YOK) kullanir, eski scratch metodolojisini DEGIL --
cunku MPM Research'un bagimsiz bulgusu (ayni arastirma notunda) tam
olarak bu tur "iyilestirme" iddialarinin naif backtest'lerde sahte
gorunebilecegini gosteriyor. KEPT_SYMBOLS uzerinde, GERCEKCI temsili
spread ile (breakeven arastirmasindaki AYNI degerler) test ediliyor.
"""

import json
from dataclasses import replace

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, KEPT_SYMBOLS
from strategy.signal_engine import generate_signals, SetupType
from backtest.engine import run_backtest
from backtest.validation import calculate_metrics

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}

FILTER_SETS = [
    ("baseline_all", lambda s: True),
    ("killzone_only", lambda s: s.in_killzone),
    ("volume_only", lambda s: s.volume_confirmed),
    ("killzone_AND_volume", lambda s: s.in_killzone and s.volume_confirmed),
]


def main():
    results = {}
    for symbol in KEPT_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
        config = StrategyConfig(spread=SPREAD_BY_SYMBOL[symbol])

        all_signals = generate_signals(candles, config=config)
        sym_result = {}
        for module_name, setup_type in [("fvg", SetupType.FVG_ONLY), ("ob", SetupType.OB_ONLY)]:
            module_signals = [s for s in all_signals if s.setup_type == setup_type]
            mod_result = {}
            for label, pred in FILTER_SETS:
                filtered = [s for s in module_signals if pred(s)]
                result = run_backtest(candles, filtered, config=config)
                metrics = calculate_metrics(result.trades, total_signals=len(filtered),
                                            unfilled_orders=result.unfilled_orders, skipped_no_tp=result.skipped_no_tp)
                mod_result[label] = {
                    "n_signals": len(filtered), "n_filled": metrics.filled_trades,
                    "win_rate": metrics.win_rate, "expectancy_r": metrics.expectancy_r,
                    "profit_factor": metrics.profit_factor, "total_net_r": metrics.total_net_r,
                }
                print(f"  {module_name:4} {label:22} n_sig={len(filtered):5} n_filled={metrics.filled_trades:5} "
                      f"win={metrics.win_rate:.1%} exp={metrics.expectancy_r:.4f} pf={metrics.profit_factor:.2f}", flush=True)
            sym_result[module_name] = mod_result
        results[symbol] = sym_result

    with open("winrate_filters_study_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: winrate_filters_study_results.json")

    print("\n=== HAVUZLANMIS (3 sembol) ===")
    for module_name in ["fvg", "ob"]:
        print(f"-- {module_name} --")
        for label, _ in FILTER_SETS:
            n = sum(results[s][module_name][label]["n_filled"] for s in KEPT_SYMBOLS)
            if n == 0:
                print(f"  {label:22} n=0")
                continue
            total_r = sum(results[s][module_name][label]["total_net_r"] for s in KEPT_SYMBOLS)
            wins = sum(round(results[s][module_name][label]["win_rate"] * results[s][module_name][label]["n_filled"]) for s in KEPT_SYMBOLS)
            print(f"  {label:22} n={n:6} win={wins/n:.1%} exp={total_r/n:.4f}")


if __name__ == "__main__":
    main()
