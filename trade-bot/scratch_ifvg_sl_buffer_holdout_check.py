"""
PROTOTIP (scratch, kalici degil): SL tamponu genisletme bulgusunun
(bkz. scratch_sl_buffer_holdout_check.py, NOA_KONSEPTI_KAYNAK_ANALIZI.md
"Aday 6") iFVG'ye GENELLENIP GENELLENEMEYECEGINI test eder. iFVG,
strategy/signal_engine.py'de FVG/OB ile BIREBIR AYNI SL formulunu
kullaniyor (`buffer = (top-bottom) * MODULE_SL_BUFFER_RATIO["ifvg"]`),
ama bugune kadar hic taranmadi (hala eski deger=1.0). $10k hesap
simulasyonu checkpoint'inde iFVG artik EN BUYUK tekil zarar kaynagi
oldugu icin (GOLD -$571, BTCUSD -$946, EURGBP -$1.325) bu dogal bir
sonraki adim.

Ayni "kutsal holdout" disiplini: her sembol kendi icinde kronolojik
%60/%20/%20 bolunur, adaylar SADECE train+val'da degerlendirilir, TEK
bir aday secilip HIC BAKILMAMIS test'te BIR KEZ calistirilir.
"""

import json

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from backtest.validation import split_chronological, calculate_metrics
from strategy.config import StrategyConfig, KEPT_SYMBOLS, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO, BREAKEVEN_TRIGGER_PCT, BREAKEVEN_ENABLED_MODULES
from strategy.ifvg import detect_confirmed_ifvgs
from strategy.fvg import FVGDirection
from strategy.signal_engine import Signal, SignalType, Confidence, SetupType
from backtest.engine import run_backtest

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
CANDIDATES = [1.0, 3.0, 5.0, 7.0, 10.0, 15.0]  # mevcut resmi = 1.0


def _ifvg_signals(candles, config, sl_ratio):
    r_mult = MODULE_R_MULTIPLE["ifvg"]
    be_pct = BREAKEVEN_TRIGGER_PCT if "ifvg" in BREAKEVEN_ENABLED_MODULES else None
    out = []
    for e in detect_confirmed_ifvgs(candles, config=config):
        is_bull = e.new_dir == FVGDirection.BULLISH
        if e.retest_index >= len(candles):
            continue
        entry = e.consequent_encroachment
        buffer = (e.top - e.bottom) * sl_ratio
        stop_loss = (e.bottom - buffer) if is_bull else (e.top + buffer)
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        take_profit = entry + r_mult * risk if is_bull else entry - r_mult * risk
        out.append(Signal(index=e.retest_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                          confidence=Confidence.MEDIUM, setup_type=SetupType.IFVG_ONLY,
                          entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                          breakeven_trigger_pct=be_pct, reason="ifvg-slholdout"))
    return out


def _eval(candles, config, sl_ratio):
    sigs = _ifvg_signals(candles, config, sl_ratio)
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

        sym_out = {"trainval": {}, "test": {}}
        best_ratio, best_exp = None, None
        for sl_ratio in CANDIDATES:
            r = _eval(trainval, config, sl_ratio)
            sym_out["trainval"][str(sl_ratio)] = r
            print(f"  [trainval] ifvg sl={sl_ratio:5.2f} n={r['n_filled']:5} "
                  f"win={r['win_rate']:.1%} exp={r['expectancy_r']:.4f}", flush=True)
            if best_exp is None or r["expectancy_r"] > best_exp:
                best_exp, best_ratio = r["expectancy_r"], sl_ratio

        official_ratio = MODULE_SL_BUFFER_RATIO["ifvg"]
        print(f"  -> ifvg: trainval'da en iyi expectancy sl={best_ratio} "
              f"(mevcut resmi={official_ratio}). SIMDI TEK ATIMLIK holdout testi:", flush=True)

        for sl_ratio in sorted(set([official_ratio, best_ratio])):
            r = _eval(test, config, sl_ratio)
            sym_out["test"][str(sl_ratio)] = r
            tag = "SECILEN-ADAY" if sl_ratio == best_ratio else "MEVCUT-RESMI"
            print(f"  [HOLDOUT/TEST] ifvg sl={sl_ratio:5.2f} ({tag}) n={r['n_filled']:5} "
                  f"win={r['win_rate']:.1%} exp={r['expectancy_r']:.4f}", flush=True)

        results[symbol] = sym_out

    with open("ifvg_sl_buffer_holdout_check_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: ifvg_sl_buffer_holdout_check_results.json")

    print("\n=== OZET (holdout/test) ===")
    for symbol in KEPT_SYMBOLS:
        for ratio_str, r in results[symbol]["test"].items():
            print(f"  {symbol:8} ifvg sl={ratio_str:>6} n={r['n_filled']:5} "
                  f"win={r['win_rate']:.1%} exp={r['expectancy_r']:.4f}")


if __name__ == "__main__":
    main()
