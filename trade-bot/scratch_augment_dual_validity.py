"""
Zaten hesaplanmis (results/holdout_v2_101/*.json) sembollere -- GOLD/BTCUSD/
EURGBP dahil -- STRATEGY VALIDITY / EXECUTION VALIDITY ikili siniflandirmasini
ve spread-duyarlilik taramasini SONRADAN ekler. train/val/walk-forward/
holdout/bootstrap sayilari HIC DOKUNULMUYOR -- "mevcut pilot sonuclari
tekrar calistirma" talimatina uyularak SADECE yeni alanlar ekleniyor.

Spread sweep icin test partisyonu split_chronological(candles,.6,.2,.2) ile
DETERMINISTIK olarak yeniden turetiliyor (ayni oranlar, ayni mumlar -> ayni
son %20) -- run_final_holdout_evaluation'in kendi icinde kullandigi
partisyonla BIREBIR ayni.
"""

import json
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig
from strategy.signal_engine import generate_signals
from backtest.validation import split_chronological
from research_dual_validity import spread_sensitivity_sweep, execution_validity, strategy_validity

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
OUT_DIR = Path("results/holdout_v2_101")
DATA_DIR = Path("data/canonical")


def augment(path: Path):
    record = json.loads(path.read_text())
    symbol = record["symbol"]

    if record.get("data_status") != "ok" or record.get("structural_failure"):
        # DATA_INSUFFICIENT / STRUCTURAL_FAILURE -- sadece etiketleri normalize et, sweep yok
        record["strategy_validity"] = {"status": "NOT_TESTED" if record.get("data_status") != "ok" else "FAIL",
                                        "reason": record.get("reason", "yapisal basarisizlik -- 0 sinyal")}
        record["execution_validity"] = None
        record["spread_sensitivity"] = None
        path.write_text(json.dumps(record, indent=2, default=str))
        print(f"{symbol}: relabeled (no sweep -- {record.get('data_status')})", flush=True)
        return

    if "spread_sensitivity" in record and record["spread_sensitivity"] is not None:
        print(f"{symbol}: zaten guncel, atlaniyor", flush=True)
        return

    m1 = load_m1_canonical_as_candlev2(str(DATA_DIR / f"V2_MULTI_{symbol}_M1_canonical.csv"))
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]

    spread = SPREAD_BY_SYMBOL.get(symbol, record.get("spread_used", 0.0))
    config = StrategyConfig(spread=spread)
    spread_source = "representative_estimate" if symbol in SPREAD_BY_SYMBOL else "uncalibrated_zero"

    _, (_, _, test_candles) = split_chronological(candles, 0.60, 0.20, 0.20)
    test_signals = generate_signals(test_candles, config=config)

    sweep = spread_sensitivity_sweep(test_candles, test_signals, config)

    record["spread_sensitivity"] = sweep
    record["strategy_validity"] = strategy_validity(record["holdout"])
    record["execution_validity"] = execution_validity(symbol, spread_source)
    record["classification"] = f"{record['strategy_validity']['status']} / {record['execution_validity']['status']}"

    path.write_text(json.dumps(record, indent=2, default=str))
    print(f"{symbol}: STRATEGY={record['strategy_validity']['status']:10} EXECUTION={record['execution_validity']['status']:10} "
          f"flips_negative_at={sweep['flips_negative_at']}", flush=True)


def main():
    files = sorted(OUT_DIR.glob("*.json"))
    print(f"{len(files)} dosya bulundu, augment ediliyor...", flush=True)
    for f in files:
        try:
            augment(f)
        except Exception as e:
            print(f"{f.stem}: HATA -- {type(e).__name__}: {e}", flush=True)
    print("TAMAMLANDI", flush=True)


if __name__ == "__main__":
    main()
