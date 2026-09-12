"""
Experiment #004a -- TESHIS: LONG/SHORT asimetrisi hangi moduden geliyor?

4 PASS sembolde (GOLD/UK100/USDTRY/EURTRY), kutsal holdout partisyonundaki
(son %20, split_chronological ile DETERMINISTIK olarak ayni sekilde
yeniden turetiliyor -- bu YENI bir holdout "bakisi" DEGIL, zaten
Deney #002'de tuketilmis/sabit sonucun modul x yon kirilimina AYRISTIRILMASI,
hicbir yeni parametre/karar bu veriye gore verilmiyor) islemleri
setup_type (FVG/iFVG/OB/Trendline) x direction (LONG/SHORT) kesisimine
gore kiriliyor.
"""

import json
from strategy.config import StrategyConfig
from strategy.signal_engine import generate_signals
from backtest.engine import run_backtest
from backtest.validation import split_chronological
from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
PASS_SYMBOLS = ["GOLD", "UK100", "USDTRY", "EURTRY"]


def analyze_symbol(symbol):
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]

    spread = SPREAD_BY_SYMBOL.get(symbol, 0.0)
    config = StrategyConfig(spread=spread)

    _, (_, _, test_candles) = split_chronological(candles, 0.60, 0.20, 0.20)
    test_signals = generate_signals(test_candles, config=config)
    result = run_backtest(test_candles, test_signals, config=config)

    buckets = {}
    for t in result.trades:
        module = t.signal.setup_type.value if hasattr(t.signal.setup_type, "value") else str(t.signal.setup_type)
        direction = t.signal.type.value
        key = (module, direction)
        buckets.setdefault(key, []).append(t.r_multiple)

    out = {}
    for (module, direction), rs in sorted(buckets.items()):
        n = len(rs)
        wins = sum(1 for r in rs if r > 0)
        total_r = sum(rs)
        out[f"{module}_{direction}"] = {
            "n": n, "win_rate": round(wins / n, 4) if n else None,
            "expectancy_r": round(total_r / n, 4) if n else None,
            "total_r": round(total_r, 2),
        }
    return out


def main():
    all_results = {}
    for symbol in PASS_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        res = analyze_symbol(symbol)
        all_results[symbol] = res
        for k, v in res.items():
            print(f"  {k:20} n={v['n']:>5} win={v['win_rate']!s:>7} exp={v['expectancy_r']!s:>8} total_r={v['total_r']:>10}", flush=True)

    with open("scratch_exp004a_module_direction_breakdown.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print("\nyazildi: scratch_exp004a_module_direction_breakdown.json")


if __name__ == "__main__":
    main()
