"""
PROTOTIP (scratch, kalici degil): scratch_sl_buffer_recalibration_(extended_)study.py
bulgusunun (SL tamponu genislikce win rate VE expectancy birlikte iyilesiyor,
hatta bazi sembollerde expectancy POZITIFE donuyor) SAHTE (overfitting) olup
olmadigini test eder.

KRITIK METODOLOJIK NOKTA: o iki sweep scriptindeki tum sayilar TAM VERI
SETI (train+val+test karisik) uzerinde hesaplandi -- yani bu oturumun
BASLANGIC noktasi olan "holdout'ta cokme" bulgusuyla AYNI hatanin
tekrarlanma riski var: genis SL orani, ayni veriye COK KEZ bakarak
(0.25'ten 50'ye kadar onlarca nokta) en iyi cikan yerde secilirse, bu
klasik egri-uydurma (curve-fitting) olur.

Bu script `backtest.validation.split_chronological` ile HER sembolu kendi
icinde kronolojik 60/20/20 boluyor. Aday SL oranlari SADECE train+val
(ilk %80) uzerinde degerlendiriliyor -- secim SADECE bu kumeye bakarak
yapiliyor. Sonra TEK BIR secilmis oran, HIC BAKILMAMIS test (%20) kumesinde
BIR KEZ calistirilip sonuc ne cikarsa ciksin dogru rapor ediliyor -- bu
projenin "kutsal holdout" disiplini (bkz. backtest/final_holdout.py) ile
birebir ayni ilke.
"""

import json

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from backtest.validation import split_chronological, calculate_metrics
from strategy.config import StrategyConfig, KEPT_SYMBOLS, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO, BREAKEVEN_TRIGGER_PCT, BREAKEVEN_ENABLED_MODULES
from strategy.fvg import detect_fvgs, FVGDirection
from strategy.order_block import detect_order_blocks, OBDirection
from strategy.signal_engine import Signal, SignalType, Confidence, SetupType
from backtest.engine import run_backtest

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
# Mevcut resmi degerler (1.0/3.0) + genis-tampon taramasinda "ilk pozitife
# gecis"e yakin makul adaylar -- kuyruktaki en asiri noktalar (30/50) BILEREK
# aday listesine konmadi, cunku onlarin GOLD/BTCUSD'de bile sembol basina
# farkli davrandigi (EURGBP hicbir zaman pozitife gecmedi) zaten gorulduu.
CANDIDATES_FVG = [1.0, 5.0, 7.0, 10.0, 15.0]
CANDIDATES_OB = [3.0, 10.0, 15.0, 20.0, 30.0]


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
                          breakeven_trigger_pct=be_pct, reason="fvg-slholdout"))
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
                          breakeven_trigger_pct=be_pct, reason="ob-slholdout"))
    return out


def _eval(candles, config, sl_ratio, fn):
    sigs = fn(candles, config, sl_ratio)
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

        sym_out = {"fvg": {"trainval": {}, "test": {}}, "ob": {"trainval": {}, "test": {}}}

        for mod_name, fn, candidates in [("fvg", _fvg_signals, CANDIDATES_FVG), ("ob", _ob_signals, CANDIDATES_OB)]:
            best_ratio, best_exp = None, None
            for sl_ratio in candidates:
                r = _eval(trainval, config, sl_ratio, fn)
                sym_out[mod_name]["trainval"][str(sl_ratio)] = r
                print(f"  [trainval] {mod_name} sl={sl_ratio:5.2f} n={r['n_filled']:5} "
                      f"win={r['win_rate']:.1%} exp={r['expectancy_r']:.4f}", flush=True)
                if best_exp is None or r["expectancy_r"] > best_exp:
                    best_exp, best_ratio = r["expectancy_r"], sl_ratio

            official_ratio = MODULE_SL_BUFFER_RATIO[mod_name]
            print(f"  -> {mod_name}: trainval'da en iyi expectancy sl={best_ratio} "
                  f"(mevcut resmi={official_ratio}). SIMDI TEK ATIMLIK holdout testi:", flush=True)

            for sl_ratio in sorted(set([official_ratio, best_ratio])):
                r = _eval(test, config, sl_ratio, fn)
                sym_out[mod_name]["test"][str(sl_ratio)] = r
                tag = "SECILEN-ADAY" if sl_ratio == best_ratio else "MEVCUT-RESMI"
                print(f"  [HOLDOUT/TEST] {mod_name} sl={sl_ratio:5.2f} ({tag}) n={r['n_filled']:5} "
                      f"win={r['win_rate']:.1%} exp={r['expectancy_r']:.4f}", flush=True)

        results[symbol] = sym_out

    with open("sl_buffer_holdout_check_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: sl_buffer_holdout_check_results.json")

    print("\n=== OZET (holdout/test, sembol bazinda) ===")
    for symbol in KEPT_SYMBOLS:
        for mod_name in ["fvg", "ob"]:
            for ratio_str, r in results[symbol][mod_name]["test"].items():
                print(f"  {symbol:8} {mod_name:4} sl={ratio_str:>6} n={r['n_filled']:5} "
                      f"win={r['win_rate']:.1%} exp={r['expectancy_r']:.4f}")


if __name__ == "__main__":
    main()
