"""
PROTOTIP (scratch, kalici degil): Order Block'un eksik ICT filtrelerinin
(engulfing, likidite supurmesi, HTF premium/discount -- bkz. strategy/
order_block.py modul docstring'i, 2026-09-02 eklentisi) ablation testi.

Bu filtreler detect_order_blocks tarafindan HENUZ elemek icin
KULLANILMIYOR -- her OrderBlock uzerinde sadece bilgi amacli boolean
alan olarak duruyorlar (engulfing, swept_liquidity, htf_discount_aligned).
Bu script, resmi OB metodolojisiyle (R=3.0, SL=govde*3.0, breakeven-stop
acik -- bkz. scratch_ob_tp_sl_study.py) ayni simulate_ob_trade fonksiyonunu
kullanarak BASELINE (tum OB'ler) ile her filtrenin TEK BASINA ve
KOMBINASYON halindeki alt kumelerini KARSILASTIRIR. Kapsam:
strategy/config.py:KEPT_SYMBOLS (GOLD, BTCUSD, EURGBP), M30.

Disiplin (breakeven-stop presedaniyla ayni): hicbir filtre, burada PF/
beklenti artisi ampirik olarak DOGRULANMADAN detect_order_blocks'un
ELEME mantigina veya resmi metodolojiye (strategy/config.py) islenmeyecek.
"""

import json

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, KEPT_SYMBOLS
from strategy.order_block import detect_order_blocks
from scratch_ob_tp_sl_study import simulate_ob_trade, _metrics, OB_OFFICIAL_R_MULTIPLE

CONFIG = StrategyConfig()

# Test edilecek alt kumeler: (etiket, filtre-fonksiyonu)
FILTER_SETS = [
    ("baseline_all", lambda ob: True),
    ("engulfing_only", lambda ob: ob.engulfing),
    ("swept_liquidity_only", lambda ob: ob.swept_liquidity),
    ("htf_discount_only", lambda ob: ob.htf_discount_aligned),
    ("engulfing_AND_sweep", lambda ob: ob.engulfing and ob.swept_liquidity),
    ("engulfing_AND_htf", lambda ob: ob.engulfing and ob.htf_discount_aligned),
    ("sweep_AND_htf", lambda ob: ob.swept_liquidity and ob.htf_discount_aligned),
    ("all_three", lambda ob: ob.engulfing and ob.swept_liquidity and ob.htf_discount_aligned),
]


def main():
    results = {}
    for symbol in KEPT_SYMBOLS:
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
        obs = detect_order_blocks(candles, config=CONFIG)
        print(f"{symbol}: {len(candles)} M30 mumu, {len(obs)} OB", flush=True)

        # Her OB icin bir kez simule et, sonra filtre kombinasyonlarina gore alt kumelere ayir --
        # her filtre seti icin ayri ayri simulasyon tekrarlamaya gerek yok (ayni R/SL/breakeven).
        outcomes_by_ob = {}
        for i, ob in enumerate(obs):
            o = simulate_ob_trade(candles, ob, OB_OFFICIAL_R_MULTIPLE)
            if o is not None:
                outcomes_by_ob[i] = o

        sym_result = {}
        for label, pred in FILTER_SETS:
            outcomes = [outcomes_by_ob[i] for i, ob in enumerate(obs) if pred(ob) and i in outcomes_by_ob]
            n_matching_obs = sum(1 for ob in obs if pred(ob))
            m = _metrics(outcomes)
            m["n_obs_matching_filter"] = n_matching_obs
            sym_result[label] = m
            print(f"  {label:22} obs={n_matching_obs:5} n={m.get('n',0):5} "
                  f"win={m.get('win_rate',0):.1%} exp={m.get('expectancy_r',0):.3f} pf={m.get('profit_factor',0):.2f}",
                  flush=True)
        results[symbol] = sym_result

    with open("ob_filters_study_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: ob_filters_study_results.json")

    # havuzlanmis (3 sembol) filtre seti bazinda ozet
    print("\n=== HAVUZLANMIS (3 sembol) ===")
    for label, _ in FILTER_SETS:
        n = sum(results[s][label].get("n", 0) for s in KEPT_SYMBOLS)
        if n == 0:
            print(f"{label:22} n=0")
            continue
        total_r = sum(results[s][label].get("total_r", 0) for s in KEPT_SYMBOLS)
        wins = sum(results[s][label].get("wins", 0) for s in KEPT_SYMBOLS)
        exp_r = total_r / n
        win_rate = wins / n
        print(f"{label:22} n={n:5} win={win_rate:.1%} exp={exp_r:.3f}")


if __name__ == "__main__":
    main()
