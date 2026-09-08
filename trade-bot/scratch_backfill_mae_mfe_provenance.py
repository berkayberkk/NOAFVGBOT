"""
Ikinci backfill gecisi: research_dual_validity.py'ye MAE/MFE + provenance +
sentetik-maliyet uyarisi EKLENDIKTEN SONRA calisan ilk augment gecisinin
(scratch_augment_dual_validity.py) islemis oldugu 18 sembole bu YENI
alanlari ekler. train/val/walk_forward_oos/holdout/strategy_validity/
execution_validity/spread_sensitivity'nin MEVCUT sayisal degerlerine
KESINLIKLE dokunulmuyor -- sadece eksik alanlar (mae_mfe, provenance,
spread_sensitivity.disclaimer) EKLENIYOR. Idempotent: zaten dolu alanlar
atlanir.
"""

import json
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig
from strategy.signal_engine import generate_signals
from backtest.validation import split_chronological
from research_dual_validity import mae_mfe_summary, provenance, SYNTHETIC_COST_DISCLAIMER

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
OUT_DIR = Path("results/holdout_v2_101")
DATA_DIR = Path("data/canonical")


def backfill(path: Path):
    record = json.loads(path.read_text())
    symbol = record["symbol"]
    changed = False

    if "provenance" not in record:
        record["provenance"] = provenance(symbol)
        changed = True

    if record.get("data_status") == "ok" and not record.get("structural_failure"):
        if record.get("spread_sensitivity") and "disclaimer" not in record["spread_sensitivity"]:
            record["spread_sensitivity"]["disclaimer"] = SYNTHETIC_COST_DISCLAIMER
            changed = True

        if "mae_mfe" not in record:
            m1 = load_m1_canonical_as_candlev2(str(DATA_DIR / f"V2_MULTI_{symbol}_M1_canonical.csv"))
            m30_v2, _ = resample_m1(m1, Timeframe.M30)
            candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
            spread = SPREAD_BY_SYMBOL.get(symbol, record.get("spread_used", 0.0))
            config = StrategyConfig(spread=spread)
            _, (_, _, test_candles) = split_chronological(candles, 0.60, 0.20, 0.20)
            test_signals = generate_signals(test_candles, config=config)
            record["mae_mfe"] = mae_mfe_summary(test_candles, test_signals, config)
            changed = True

        # classification metnini kullanicinin istedigi acik formata cek
        sv = record["strategy_validity"]["status"]
        ev = record["execution_validity"]["status"]
        new_cls = f"STRATEGY {sv} / EXECUTION {ev}"
        if record.get("classification") != new_cls:
            record["classification"] = new_cls
            changed = True
    else:
        if record.get("classification") is None or "/" not in str(record.get("classification", "")):
            sv = record.get("strategy_validity", {}).get("status", "NOT_TESTED")
            record["classification"] = f"STRATEGY {sv} / EXECUTION N/A"
            changed = True

    if changed:
        path.write_text(json.dumps(record, indent=2, default=str))
        print(f"{symbol}: backfilled (mae_mfe={'mae_mfe' in record}, provenance=True)", flush=True)
    else:
        print(f"{symbol}: zaten guncel", flush=True)


def main():
    files = sorted(OUT_DIR.glob("*.json"))
    print(f"{len(files)} dosya, backfill basliyor...", flush=True)
    for f in files:
        try:
            backfill(f)
        except Exception as e:
            print(f"{f.stem}: HATA -- {type(e).__name__}: {e}", flush=True)
    print("TAMAMLANDI", flush=True)


if __name__ == "__main__":
    main()
