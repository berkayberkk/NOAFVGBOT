"""
PROTOTIP (scratch, kalici degil): bu oturumda kalibre edilen stratejinin
(FVG/iFVG/Order Block/Trendline, resmi R-katlari/SL tamponlari/breakeven-
stop -- hepsi guncellenmis strategy/signal_engine.py + backtest/engine.py
uzerinden) mevcut, onceden kurulmus walk-forward/holdout/block-bootstrap
altyapisindan (backtest/validation.py, final_holdout.py, regime.py)
GECIRILMESI. Bu, projenin daha once V1'in (eski FVG+OB+S/R, trend
filtreli) "92.7% win rate" iddiasini "FAILED TO GENERALIZE"e cevirdigi
AYNI disiplinli metodoloji -- bu oturumun TUM bulgularinin (breakeven-
stop, R-katlari, sembol daraltmasi) gercekten genellesip genellesmedigini
test eden ilk calisma.

KUTSAL HOLDOUT UYARISI: run_final_holdout_evaluation her sembol icin
SADECE BIR KEZ calistirilmali -- sonucu begenmeyip parametre degistirip
tekrar calistirmak, holdout'un butun amacini (gercekten hic gormedigi
veride test etmek) gecersiz kilar. Bu script calistirildiktan SONRA
hicbir kalibrasyon parametresi bu sonuca gore degistirilmeyecek.

Spread: DEFAULT_CONFIG'in spread=0 varsayimi yerine, breakeven esik
taramasinda kullanilan AYNI temsili degerler kullanildi (GOLD=0.25,
BTCUSD=20, EURGBP=0.0002) -- veri kaynaginda gercek spread hic
kayitli degil (bkz. scratch_breakeven_trigger_spread_sweep_study.py
docstring'i), bu degerler kalibre edilmedi.
"""

import json
from dataclasses import asdict, replace

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, KEPT_SYMBOLS
from backtest.validation import build_validation_report
from backtest.final_holdout import run_final_holdout_evaluation

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}


def _to_jsonable(obj):
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if hasattr(obj, "value"):  # Enum
        return obj.value
    return obj


def main():
    results = {}
    for symbol in KEPT_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
        print(f"{len(candles)} M30 mumu, {candles[0]['time']} - {candles[-1]['time']}", flush=True)

        config = StrategyConfig(spread=SPREAD_BY_SYMBOL[symbol])

        print("train/val/walk-forward hesaplaniyor...", flush=True)
        val_report = build_validation_report(candles, config=config)
        print(f"  TRAIN: n={val_report.train_metrics.filled_trades} exp={val_report.train_metrics.expectancy_r:.4f} "
              f"pf={val_report.train_metrics.profit_factor:.2f} win={val_report.train_metrics.win_rate:.1%}", flush=True)
        print(f"  VAL:   n={val_report.val_metrics.filled_trades} exp={val_report.val_metrics.expectancy_r:.4f} "
              f"pf={val_report.val_metrics.profit_factor:.2f} win={val_report.val_metrics.win_rate:.1%}", flush=True)
        print(f"  WALK-FORWARD (OOS, val'den bagimsiz pencereler): n={val_report.oos_val_metrics.filled_trades} "
              f"exp={val_report.oos_val_metrics.expectancy_r:.4f} pf={val_report.oos_val_metrics.profit_factor:.2f} "
              f"win={val_report.oos_val_metrics.win_rate:.1%}", flush=True)

        print("KUTSAL HOLDOUT calistiriliyor (tek atimlik)...", flush=True)
        holdout = run_final_holdout_evaluation(candles, config=config, val_metrics=val_report.val_metrics)
        print(f"  HOLDOUT: n={holdout.test_metrics.filled_trades} exp={holdout.test_metrics.expectancy_r:.4f} "
              f"pf={holdout.test_metrics.profit_factor:.2f} win={holdout.test_metrics.win_rate:.1%} "
              f"maxDD={holdout.test_metrics.max_drawdown_r:.2f}R", flush=True)
        print(f"  SONUC: {holdout.evidence_classification} -- {holdout.evidence_reason}", flush=True)
        print(f"  Block-bootstrap 95% CI: [{holdout.block_bootstrap.ci_lower_95:.4f}, {holdout.block_bootstrap.ci_upper_95:.4f}]", flush=True)

        results[symbol] = {
            "spread_used": SPREAD_BY_SYMBOL[symbol],
            "train_metrics": _to_jsonable(val_report.train_metrics),
            "val_metrics": _to_jsonable(val_report.val_metrics),
            "walk_forward_oos_metrics": _to_jsonable(val_report.oos_val_metrics),
            "holdout": _to_jsonable(holdout),
        }

    with open("holdout_validation_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: holdout_validation_results.json")

    print("\n=== OZET ===")
    for symbol in KEPT_SYMBOLS:
        h = results[symbol]["holdout"]
        print(f"{symbol:8} {h['evidence_classification']:22} exp={h['test_metrics']['expectancy_r']:+.4f} "
              f"pf={h['test_metrics']['profit_factor']:.2f} win={h['test_metrics']['win_rate']:.1%} "
              f"CI=[{h['block_bootstrap']['ci_lower_95']:+.4f}, {h['block_bootstrap']['ci_upper_95']:+.4f}]")


if __name__ == "__main__":
    main()
