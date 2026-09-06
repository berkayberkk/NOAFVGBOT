"""
PROTOTIP (scratch, kalici degil): scratch_h1_timeframe_disable_holdout_check.py'nin
TEK holdout diliminde (son %20, n=32-49 islem/sembol) tutarsiz cikan
sonucunu (2/3 sembolde birlesim kotu, ama GOLD'un kendi holdout'unda
TERS yonde) daha genis bir orneklemle test eder -- bkz.
NOA_KONSEPTI_KAYNAK_ANALIZI.md, "H1 zaman diliminin devre disi
birakilmasi" bolumunun sonundaki KARAR notu: "Daha buyuk orneklem
(ornegin tum KEPT_SYMBOLS'un TUM gecmisini, walk-forward/genisleyen
pencereyle, tek seferlik %20 holdout yerine) olmadan bu konuda karar
verilmeyecek."

METODOLOJI: serbest parametre YOK (once ki calismada da yoktu) --
karsilastirilan iki sabit kural (M30-alone vs M30+H1-combined,
tek-pozisyon havuzu) hicbir veriye bakilarak SECILMIYOR, sadece
OLCULUYOR. Bu yuzden klasik "train'de sec, test'te dogrula" walk-forward
yerine, her sembolun TUM gecmisi N ESIT ARDISIK DILIME (fold) bolunup
HER dilim BAGIMSIZ bir out-of-sample donem olarak degerlendiriliyor --
amac bir parametre secmek degil, TEK holdout diliminin (n kucuk, gurultu
payi yuksek) verdigi sonucun FARKLI zaman donemlerinde (rejimlerde) ne
kadar TUTARLI oldugunu gormek. Ayni disiplin: her fold'un H1 alt kumesi,
o fold'un M30 zaman sinirlarina gore (zaman karsilastirilabilir, index
degil) kesiliyor.

`_eval`/`_combined_taken`/SPREAD_BY_SYMBOL onceki scriptten DEGISTIRILMEDEN
import ediliyor -- ayni tek-pozisyon-havuzu/backtest mantigi.
"""

import json

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, KEPT_SYMBOLS
from scratch_h1_timeframe_disable_holdout_check import _eval, SPREAD_BY_SYMBOL

N_FOLDS = 6


def _equal_folds(candles: list[dict], n_folds: int) -> list[list[dict]]:
    """Candles'i N esit (bar sayisina gore) ardisik dilime boler."""
    n = len(candles)
    fold_size = n // n_folds
    folds = []
    for i in range(n_folds):
        start = i * fold_size
        end = (i + 1) * fold_size if i < n_folds - 1 else n
        folds.append(candles[start:end])
    return folds


def main():
    results = {}
    for symbol in KEPT_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        h1_v2, _ = resample_m1(m1, Timeframe.H1)
        m30 = [candlev2_to_strategy_dict(c) for c in m30_v2]
        h1 = [candlev2_to_strategy_dict(c) for c in h1_v2]
        config = StrategyConfig(spread=SPREAD_BY_SYMBOL[symbol])

        m30_folds = _equal_folds(m30, N_FOLDS)
        sym_folds = []

        for fold_idx, m30_fold in enumerate(m30_folds):
            if len(m30_fold) < 200:
                print(f"  fold {fold_idx}: cok kucuk (n={len(m30_fold)}), atlandi", flush=True)
                continue
            fold_start, fold_end = m30_fold[0]["time"], m30_fold[-1]["time"]
            h1_fold = [c for c in h1 if fold_start <= c["time"] <= fold_end]

            fold_out = {"period": f"{fold_start.date()}..{fold_end.date()}",
                        "m30_n": len(m30_fold), "h1_n": len(h1_fold)}
            for label, include_h1 in [("M30-alone", False), ("M30+H1-combined", True)]:
                r = _eval(m30_fold, h1_fold, config, include_h1)
                fold_out[label] = r

            alone = fold_out["M30-alone"]["expectancy_r"]
            combined = fold_out["M30+H1-combined"]["expectancy_r"]
            better = "COMBINED" if combined > alone else "ALONE"
            print(f"  fold {fold_idx} [{fold_out['period']}] n_m30={len(m30_fold)} n_h1={len(h1_fold)} | "
                  f"alone exp={alone:+.4f} (n={fold_out['M30-alone']['n_filled']}) vs "
                  f"combined exp={combined:+.4f} (n={fold_out['M30+H1-combined']['n_filled']}) "
                  f"-> {better} better", flush=True)

            sym_folds.append(fold_out)

        results[symbol] = sym_folds

    with open("h1_disable_walkforward_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: h1_disable_walkforward_results.json")

    print("\n=== OZET: kac fold'da COMBINED (M30+H1), ALONE'dan (M30 tek basina) daha iyi cikti ===")
    total_folds = 0
    combined_better_count = 0
    for symbol in KEPT_SYMBOLS:
        sym_combined_better = 0
        sym_total = 0
        for fold_out in results[symbol]:
            sym_total += 1
            total_folds += 1
            if fold_out["M30+H1-combined"]["expectancy_r"] > fold_out["M30-alone"]["expectancy_r"]:
                sym_combined_better += 1
                combined_better_count += 1
        print(f"  {symbol:8}: {sym_combined_better}/{sym_total} fold'da COMBINED daha iyi")
    print(f"  TOPLAM: {combined_better_count}/{total_folds} fold'da COMBINED daha iyi "
          f"({100 * combined_better_count / total_folds:.0f}%)")


if __name__ == "__main__":
    main()
