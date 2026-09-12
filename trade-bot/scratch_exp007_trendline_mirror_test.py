"""
Experiment #007, ADIM 2 -- Trendline-only ayna testi (regime-artifact
kontrolu). Deney #004b'nin AYNI metodolojisi (mirror_candles, ayni 6
sembol), ama SADECE Trendline modulu (mevcut sabit R-kati TP, S/R-TP
DEGIL) kullanilarak.

KUTSAL KURAL: SADECE train+val (%80), holdout HIC KULLANILMADI.
"""

import json
from strategy.config import StrategyConfig
from backtest.engine import run_backtest
from backtest.validation import split_chronological
from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1

import scratch_exp004b_mirror_symmetry_test as m4b
import scratch_exp005_sr_based_tp_test as m5

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
TEST_SYMBOLS = ["GOLD", "UK100", "USDTRY", "EURTRY", "BTCUSD", "EURGBP"]


def run_trendline_only(candles, config):
    base_events = m5._trendline_base_signals(candles, config)
    if not base_events:
        return {"buy": {"n": 0, "win_rate": None, "expectancy_r": None},
                "sell": {"n": 0, "win_rate": None, "expectancy_r": None}}
    signals = m5._build_signals(base_events, "trendline", config, candles, use_sr_tp=False)
    result = run_backtest(candles, signals, config=config)
    return m4b.direction_breakdown(result.trades)


def analyze_symbol(symbol):
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]

    spread = SPREAD_BY_SYMBOL.get(symbol, 0.0)
    config = StrategyConfig(spread=spread)

    _, (train_candles, val_candles, _) = split_chronological(candles, 0.60, 0.20, 0.20)
    trainval = train_candles + val_candles  # holdout'a HIC dokunulmuyor

    orig_breakdown = run_trendline_only(trainval, config)
    mirrored = m4b.mirror_candles(trainval)
    mir_breakdown = run_trendline_only(mirrored, config)

    return {"original": orig_breakdown, "mirrored": mir_breakdown}


def main():
    all_results = {}
    for symbol in TEST_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        res = analyze_symbol(symbol)
        all_results[symbol] = res
        o, m = res["original"], res["mirrored"]
        print(f"  ORIJINAL  LONG:  n={o['buy']['n']:>5} win={o['buy']['win_rate']!s:>7} exp={o['buy']['expectancy_r']!s:>8}", flush=True)
        print(f"  ORIJINAL  SHORT: n={o['sell']['n']:>5} win={o['sell']['win_rate']!s:>7} exp={o['sell']['expectancy_r']!s:>8}", flush=True)
        print(f"  AYNALI    LONG:  n={m['buy']['n']:>5} win={m['buy']['win_rate']!s:>7} exp={m['buy']['expectancy_r']!s:>8}", flush=True)
        print(f"  AYNALI    SHORT: n={m['sell']['n']:>5} win={m['sell']['win_rate']!s:>7} exp={m['sell']['expectancy_r']!s:>8}", flush=True)
        print(f"  [orijinal LONG exp={o['buy']['expectancy_r']} vs aynali SHORT exp={m['sell']['expectancy_r']}] -- yakinsa SIMETRIK (rejim etkisi)", flush=True)
        print(f"  [orijinal SHORT exp={o['sell']['expectancy_r']} vs aynali LONG exp={m['buy']['expectancy_r']}] -- yakinsa SIMETRIK (rejim etkisi)", flush=True)

    with open("scratch_exp007_trendline_mirror_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print("\nyazildi: scratch_exp007_trendline_mirror_results.json", flush=True)


if __name__ == "__main__":
    main()
