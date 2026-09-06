"""
PROTOTIP (scratch, kalici degil): GOLD'da bulunan "M30+H1 birlesimi
TOPLAM sonucu KOTULESTIRIYOR" bulgusunun (bkz.
scratch_gold_mtf_account_simulation.py, NOA_KONSEPTI_KAYNAK_ANALIZI.md
"GOLD islem galerisi + coklu-zaman-dilimi (M30+H1) hesap simulasyonu"
bolumu) KEPT_SYMBOLS'un TUMUNE (GOLD/BTCUSD/EURGBP) genellenip
genellenmedigini, kutsal-holdout disipliniyle test eder.

H1'i MODULE_DISABLED_TIMEFRAMES'e eklemek == H1'den hic sinyal
alinmamasi ile ESDEGERDIR (tum modullerde). Yani karsilastirilan iki
"aday" aslinda: (A) M30 tek basina [= H1 tum moduller icin disable
edilirse ortaya cikacak durum] vs (B) M30+H1 birlesik tek-pozisyon
havuzu [= mevcut fiili davranis, cunku MODULE_DISABLED_TIMEFRAMES'te H1
hicbir modul icin listelenmiyor].

Serbest parametre YOK (taranacak bir sayi araligi degil, ikili bir
secim) -- bu yuzden onceki SL-tamponu calismalarindaki gibi trainval'da
"aday secimi" adimina gerek yok; iki secenek de dogrudan hem trainval'da
(gozlem icin) hem HIC BAKILMAMIS test'te (karar icin) calistirilir.
Ayni kutsal-holdout disiplini: M30 split_chronological ile (%60/%20/%20)
bolunup test kesim zamani baz alinarak H1 da AYNI zaman sinirina gore
bolunuyor (H1'in kendi index'i M30'unkiyle karsilastirilamaz, zaman
karsilastirilabilir).
"""

import json

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from backtest.validation import split_chronological, calculate_metrics
from strategy.config import StrategyConfig, KEPT_SYMBOLS
from backtest.engine import run_backtest
from scratch_gold_mtf_account_simulation import generate_signals_with_geometry

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
STARTING_EQUITY = 10_000.0
RISK_PCT = 0.01


def _signals_only(candles, config, tf_name):
    pairs = generate_signals_with_geometry(candles, config, tf_name)
    return [s for s, g in pairs]


def _combined_taken(m30_candles, h1_candles, config, include_h1):
    m30_sigs = _signals_only(m30_candles, config, "M30")
    m30_result = run_backtest(m30_candles, m30_sigs, config=config)
    records = [{"candles": m30_candles, "trade": t} for t in m30_result.trades]
    total_signals = len(m30_sigs)

    if include_h1:
        h1_sigs = _signals_only(h1_candles, config, "H1")
        h1_result = run_backtest(h1_candles, h1_sigs, config=config)
        records += [{"candles": h1_candles, "trade": t} for t in h1_result.trades]
        total_signals += len(h1_sigs)

    def fill_time(rec):
        t = rec["trade"]
        c = rec["candles"]
        fi = t.entry_fill_index if t.entry_fill_index is not None else t.entry_index
        return c[min(fi, len(c) - 1)]["time"]

    def exit_time(rec):
        t = rec["trade"]
        c = rec["candles"]
        fi = t.entry_fill_index if t.entry_fill_index is not None else t.entry_index
        ei = t.exit_index if t.exit_index is not None else fi
        return c[min(ei, len(c) - 1)]["time"]

    records.sort(key=fill_time)
    taken = []
    next_available = None
    for rec in records:
        ft = fill_time(rec)
        if next_available is not None and ft < next_available:
            continue
        taken.append(rec)
        next_available = exit_time(rec)

    return taken, total_signals


def _eval(m30_candles, h1_candles, config, include_h1):
    taken, total_signals = _combined_taken(m30_candles, h1_candles, config, include_h1)
    trades = [rec["trade"] for rec in taken]
    m = calculate_metrics(trades, total_signals=total_signals)

    equity = STARTING_EQUITY
    for t in trades:
        equity += (equity * RISK_PCT) * t.r_multiple
    fixed_risk = STARTING_EQUITY * RISK_PCT
    fixed_equity = STARTING_EQUITY + sum(fixed_risk * t.r_multiple for t in trades)

    return {
        "n_filled": m.filled_trades, "win_rate": m.win_rate,
        "expectancy_r": m.expectancy_r, "profit_factor": m.profit_factor,
        "total_net_r": m.total_net_r,
        "final_equity_compound": round(equity, 2),
        "final_equity_fixed": round(fixed_equity, 2),
    }


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

        _, (m30_train, m30_val, m30_test) = split_chronological(m30, 0.60, 0.20, 0.20)
        m30_trainval = m30_train + m30_val
        cutoff_time = m30_test[0]["time"]

        h1_trainval = [c for c in h1 if c["time"] < cutoff_time]
        h1_test = [c for c in h1 if c["time"] >= cutoff_time]

        print(f"  trainval M30 n={len(m30_trainval)} H1 n={len(h1_trainval)} | "
              f"test(holdout) M30 n={len(m30_test)} H1 n={len(h1_test)}", flush=True)

        sym_out = {}
        for label, include_h1 in [("M30-alone", False), ("M30+H1-combined", True)]:
            trainval_r = _eval(m30_trainval, h1_trainval, config, include_h1)
            test_r = _eval(m30_test, h1_test, config, include_h1)
            sym_out[label] = {"trainval": trainval_r, "test": test_r}
            print(f"  [trainval] {label:18} n={trainval_r['n_filled']:5} "
                  f"win={trainval_r['win_rate']:.1%} exp={trainval_r['expectancy_r']:.4f} "
                  f"fixed=${trainval_r['final_equity_fixed']:,.2f}", flush=True)
            print(f"  [HOLDOUT ] {label:18} n={test_r['n_filled']:5} "
                  f"win={test_r['win_rate']:.1%} exp={test_r['expectancy_r']:.4f} "
                  f"fixed=${test_r['final_equity_fixed']:,.2f}", flush=True)

        results[symbol] = sym_out

    with open("h1_disable_holdout_check_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: h1_disable_holdout_check_results.json")

    print("\n=== OZET (HOLDOUT/test) ===")
    for symbol in KEPT_SYMBOLS:
        for label in ["M30-alone", "M30+H1-combined"]:
            r = results[symbol][label]["test"]
            print(f"  {symbol:8} {label:18} n={r['n_filled']:5} win={r['win_rate']:.1%} "
                  f"exp={r['expectancy_r']:.4f} fixed=${r['final_equity_fixed']:,.2f}")


if __name__ == "__main__":
    main()
