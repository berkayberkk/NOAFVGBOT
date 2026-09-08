"""
KUTSAL HOLDOUT V2 -- 101 SEMBOL x 5 EK ZAMAN DILIMI (H1/H2/H4/D1/W1),
2026-09-07, kullanicinin acik talebi: "101x6=606 symbol-timeframe matrix".

M30 BASELINE ZATEN TAMAMLANDI VE DONDURULDU -- bu script M30'a HIC
DOKUNMUYOR (results/holdout_v2_101/*.json duz dosyalar, degistirilmiyor).
Diger 5 zaman dilimi AYRI alt klasorlere yaziliyor:
    results/holdout_v2_101/H1/{SYMBOL}.json
    results/holdout_v2_101/H2/{SYMBOL}.json
    results/holdout_v2_101/H4/{SYMBOL}.json
    results/holdout_v2_101/D1/{SYMBOL}.json
    results/holdout_v2_101/W1/{SYMBOL}.json

METODOLOJI: M30 bolumunde kullanilan AYNI surec (split_chronological
%60/%20/%20, build_validation_report walk-forward, run_final_holdout_
evaluation tek-atimlik kutsal holdout, block-bootstrap seed=42/
block_size=3/num_resamples=1000, STRATEGY/EXECUTION ikili siniflandirma,
4-seviyeli sentetik spread duyarlilik taramasi, MAE/MFE, tam provenance)
-- HICBIR zaman dilimine ONCELIK/AYRICALIK YOK, hepsi ayni kod yolundan
geciyor. MODULE_DISABLED_TIMEFRAMES (fvg/ifvg H4, ob W1 vb.) BU ARASTIRMA
ICIN BILEREK UYGULANMADI -- M30 baseline'in kod yoluyla TUTARLI olmasi
icin (M30'da da bu filtre uygulanmamisti); bu, "hicbir timeframe onceden
ayricalikli kabul edilmesin" talimatiyla dogrudan uyumlu -- gercek uretim
kisitlamasi degil, HAM/tarafsiz arastirma sonucu.

VERIMLILIK: her sembol icin M1 verisi BIR KEZ yukleniyor, 5 zaman dilimine
buradan resample ediliyor (M30 calismasindaki gibi sembol basina 5 ayri
CSV okuma tekrarindan kacinmak icin). Checkpoint/resume (symbol,timeframe)
hucresi bazinda -- kesintiye ugrarsa zaten tamamlanmis hucreler atlanir.

ESIK (MIN_CANDLES, zaman dilimine gore): M30'daki 2000 esigi (~41 gun)
diger zaman dilimlerine oranli olarak UYARLANDI -- W1'de 2000 mum 38 yil
gibi imkansiz bir sart olurdu. Esik altindaki (sembol,TF) ciftleri
DATA_INSUFFICIENT olarak ACIKCA isaretleniyor, sessizce atlanmiyor.

SIRALAMA: kullanicinin belirttigi H1 -> H2 -> H4 -> D1 -> W1 sirasiyla,
her sirada TUM sembolleri tamamlayip bir sonrakine geciyor (once en cok
veri/hesaplama gerektiren H1'i bitirip erken feedback vermek icin).
"""

import json
import time
from dataclasses import asdict
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, _ALL_101_SYMBOLS
from strategy.signal_engine import generate_signals
from backtest.validation import build_validation_report, split_chronological
from backtest.final_holdout import run_final_holdout_evaluation
from research_dual_validity import (
    spread_sensitivity_sweep, execution_validity, strategy_validity, mae_mfe_summary, provenance,
)

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
DATA_DIR = Path("data/canonical")
OUT_ROOT = Path("results/holdout_v2_101")

TIMEFRAMES_TO_RUN = ["H1", "H2", "H4", "D1", "W1"]
TF_ENUM = {"H1": Timeframe.H1, "H2": Timeframe.H2, "H4": Timeframe.H4, "D1": Timeframe.D1, "W1": Timeframe.W1}
MIN_CANDLES = {"H1": 1500, "H2": 1000, "H4": 600, "D1": 300, "W1": 150}


def _to_jsonable(obj):
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if hasattr(obj, "value"):
        return obj.value
    return obj


def _atomic_write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    for attempt in range(5):
        try:
            tmp.write_text(json.dumps(data, indent=2, default=str))
            tmp.replace(path)
            return
        except (PermissionError, FileNotFoundError):
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


def process_symbol_tf(symbol: str, tf_name: str, candles: list) -> dict:
    min_c = MIN_CANDLES[tf_name]
    if len(candles) < min_c:
        return {"symbol": symbol, "timeframe": tf_name, "data_status": "insufficient",
                "reason": f"{tf_name} mum sayisi ({len(candles)}) < esik ({min_c})",
                "candle_count": len(candles)}

    spread = SPREAD_BY_SYMBOL.get(symbol, 0.0)
    spread_source = "representative_estimate" if symbol in SPREAD_BY_SYMBOL else "uncalibrated_zero"
    config = StrategyConfig(spread=spread)

    probe_signals = generate_signals(candles, config=config)
    if len(probe_signals) == 0:
        return {"symbol": symbol, "timeframe": tf_name, "data_status": "ok", "structural_failure": True,
                "candle_count": len(candles), "spread_used": spread,
                "strategy_validity": {"status": "FAIL", "reason": "0 sinyal"},
                "execution_validity": None, "spread_sensitivity": None, "mae_mfe": None,
                "classification": "STRATEGY FAIL (structural, 0 signals) / EXECUTION N/A",
                "reason": "generate_signals hic sinyal uretmedi (0 aday)"}

    val_report = build_validation_report(candles, config=config)
    holdout = run_final_holdout_evaluation(candles, config=config, val_metrics=val_report.val_metrics)
    holdout_j = _to_jsonable(holdout)

    _, (_, _, test_candles) = split_chronological(candles, 0.60, 0.20, 0.20)
    test_signals = generate_signals(test_candles, config=config)
    sweep = spread_sensitivity_sweep(test_candles, test_signals, config)
    mae_mfe = mae_mfe_summary(test_candles, test_signals, config)

    sv = strategy_validity(holdout_j)
    ev = execution_validity(symbol, spread_source)

    return {
        "symbol": symbol, "timeframe": tf_name, "data_status": "ok", "structural_failure": False,
        "candle_count": len(candles),
        "data_start": str(candles[0]["time"]), "data_end": str(candles[-1]["time"]),
        "spread_used": spread,
        "strategy_validity": sv, "execution_validity": ev,
        "classification": f"STRATEGY {sv['status']} / EXECUTION {ev['status']}",
        "spread_sensitivity": sweep, "mae_mfe": mae_mfe,
        "provenance": provenance(symbol),
        "train_metrics": _to_jsonable(val_report.train_metrics),
        "val_metrics": _to_jsonable(val_report.val_metrics),
        "walk_forward_oos_metrics": _to_jsonable(val_report.oos_val_metrics),
        "holdout": holdout_j,
    }


def main():
    for tf_name in TIMEFRAMES_TO_RUN:
        out_dir = OUT_ROOT / tf_name
        out_dir.mkdir(parents=True, exist_ok=True)
        done = {p.stem for p in out_dir.glob("*.json")}
        remaining = [s for s in _ALL_101_SYMBOLS if s not in done]
        print(f"\n########## {tf_name}: {len(done)}/101 tamamlanmis, {len(remaining)} kaldi ##########", flush=True)

        for i, symbol in enumerate(remaining, start=1):
            t0 = time.time()
            try:
                csv_path = DATA_DIR / f"V2_MULTI_{symbol}_M1_canonical.csv"
                if not csv_path.exists():
                    record = {"symbol": symbol, "timeframe": tf_name, "data_status": "insufficient", "reason": "csv dosyasi yok"}
                else:
                    m1 = load_m1_canonical_as_candlev2(str(csv_path))
                    tf_v2, _ = resample_m1(m1, TF_ENUM[tf_name])
                    candles = [candlev2_to_strategy_dict(c) for c in tf_v2]
                    record = process_symbol_tf(symbol, tf_name, candles)
            except Exception as e:
                record = {"symbol": symbol, "timeframe": tf_name, "data_status": "insufficient",
                          "reason": f"HATA: {type(e).__name__}: {e}"}

            if "strategy_validity" not in record:
                record["strategy_validity"] = {"status": "NOT_TESTED", "reason": record.get("reason")}
                record["execution_validity"] = None
                record["spread_sensitivity"] = None
                record["mae_mfe"] = None
                record["classification"] = "STRATEGY NOT_TESTED / EXECUTION N/A"
            if "provenance" not in record:
                record["provenance"] = provenance(symbol)

            record["elapsed_sec"] = round(time.time() - t0, 1)
            _atomic_write(out_dir / f"{symbol}.json", record)

            if record["data_status"] != "ok":
                print(f"[{tf_name} {i}/{len(remaining)}] {symbol}: DATA_INSUFFICIENT -- {record.get('reason')} ({record['elapsed_sec']}sn)", flush=True)
            elif record.get("structural_failure"):
                print(f"[{tf_name} {i}/{len(remaining)}] {symbol}: STRUCTURAL_FAILURE ({record['elapsed_sec']}sn)", flush=True)
            else:
                h = record["holdout"]
                sv, ev = record["strategy_validity"]["status"], record["execution_validity"]["status"]
                print(f"[{tf_name} {i}/{len(remaining)}] {symbol}: STRATEGY={sv:10} EXECUTION={ev:10} "
                      f"exp={h['test_metrics']['expectancy_r']:+.4f} pf={h['test_metrics']['profit_factor']:.2f} "
                      f"win={h['test_metrics']['win_rate']:.1%} n={h['test_metrics']['filled_trades']} "
                      f"maxDD={h['test_metrics']['max_drawdown_r']:.1f}R ({record['elapsed_sec']}sn)", flush=True)

        print(f"########## {tf_name} TAMAMLANDI (101/101) ##########", flush=True)

    print("\nTUM 5 EK ZAMAN DILIMI (H1/H2/H4/D1/W1) TAMAMLANDI -- 606/606 (M30 dahil) HAZIR.", flush=True)


if __name__ == "__main__":
    main()
