"""
V1 stratejisini (FVG + Order Block + Destek/Direnç), research/v2/data/run_multi_symbol_acquisition.py
ile toplanan yeni enstrümanların M1 canonical verisi üzerinde M30'a resample edip, GOLD için zaten
kullanılan train/val/holdout metodolojisiyle (chronological split + block-bootstrap CI) test eder.

Amaç: FVG+OB+SR confluence edge'inin GOLD'a özgü mü yoksa diğer majors/index/silver'da da
genelleşiyor mu olduğunu görmek. Bu GOLD'un frozen final_holdout_v1.json'ını hiçbir şekilde
değiştirmez / kullanmaz -- her sembol kendi val partition'ına göre değerlendirilir (GOLD'un
sabit val_expectancy_r=0.5253 gibi değerleri burada KULLANILMAZ, çünkü instrument'a özgü
olduklarından başka bir sembole uygulamak yanıltıcı olurdu).

Sonuçlar backtest/results/V2_MULTI_{SYMBOL}_validation.json içine yazılır (GOLD'un
backtest/results/final_holdout_v1.json'ından ayrı, ona hiç dokunulmaz).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from research.v2.data.models import CandleV2, Timeframe
from research.v2.data.acquisition import convert_raw_to_canonical_m1
from research.v2.data.resampler import resample_m1

from strategy.config import StrategyConfig
from strategy.signal_engine import generate_signals
from backtest.engine import run_backtest
from backtest.validation import split_chronological, calculate_metrics, WalkForwardWindowResult
from backtest.final_holdout import ValidationComparison, classify_holdout_evidence
from backtest.regime import (
    extract_enriched_oos_trades, analyze_time_distribution, analyze_volatility_regimes,
    analyze_market_states, analyze_directions, analyze_concentration, compute_block_bootstrap,
)
from backtest.data_quality import audit_dataset

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANONICAL_DIR = os.path.join(REPO_ROOT, "data", "canonical")
RESULTS_DIR = os.path.join(REPO_ROOT, "backtest", "results")
SUMMARY_PATH = os.path.join(RESULTS_DIR, "V2_MULTI_validation_summary.json")

SYMBOLS = [
    "EURUSD", "GBPUSD", "USDCHF", "USDCAD", "AUDCAD",
    "EURGBP", "USDJPY", "EURJPY", "EURCAD", "NASDAQ", "SILVER",
    "AUDUSD", "NZDUSD", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY",
    "EURAUD", "EURNZD", "EURCHF", "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD",
    "AUDCHF", "AUDNZD", "CADCHF", "NZDCAD", "NZDCHF", "BTCUSD", "WTI",
]


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_m1_canonical_as_candlev2(csv_path: str) -> List[CandleV2]:
    """research/v2/data/run_multi_symbol_acquisition.py'nin yazdığı tab-separated MT5-export
    formatındaki M1 canonical CSV'yi CandleV2 listesine çevirir (data/loader.py + manuel dönüşüm,
    research/v2 tarafının convert_raw_to_canonical_m1'ini raw-dict formatı üzerinden yeniden kullanır)."""
    from data.loader import load_candles_from_csv
    raw_dicts = load_candles_from_csv(csv_path)
    raw_rates = [
        {
            "time": int(d["time"].timestamp()),
            "timestamp_open_utc": d["time"].strftime("%Y-%m-%d %H:%M:%S"),
            "open": d["open"], "high": d["high"], "low": d["low"], "close": d["close"],
            "tick_volume": d["tick_volume"], "spread": d["spread"],
        }
        for d in raw_dicts
    ]
    return convert_raw_to_canonical_m1(raw_rates)


def candlev2_to_strategy_dict(c: CandleV2) -> Dict[str, Any]:
    return {
        "time": datetime.fromisoformat(c.timestamp_open_utc),
        "open": c.open, "high": c.high, "low": c.low, "close": c.close,
        "tick_volume": int(c.volume), "spread": 0,
    }


def resolve_symbol_config(mt5, broker_symbol: str) -> StrategyConfig:
    """Enstrümana özgü gerçek spread'i MT5'ten okuyup StrategyConfig'e price-distance
    cinsinden yansıtır (GOLD'un sabit 0.30/0.10/0.10 değerlerini başka bir enstrümana
    kopyalamak anlamsız olurdu -- her sembolün quote ölçeği farklı)."""
    info = mt5.symbol_info(broker_symbol)
    point = info.point if info else 0.0001
    spread_points = info.spread if info and info.spread else 20
    spread_price = spread_points * point
    slippage_price = point * 1
    return StrategyConfig(spread=spread_price, slippage=slippage_price, commission=0.0)


def evaluate_symbol(research_symbol: str, mt5) -> Dict[str, Any]:
    canonical_csv = os.path.join(CANONICAL_DIR, f"V2_MULTI_{research_symbol}_M1_canonical.csv")
    if not os.path.exists(canonical_csv):
        raise FileNotFoundError(f"canonical M1 CSV not found: {canonical_csv}")

    m1_candles = load_m1_canonical_as_candlev2(canonical_csv)
    if len(m1_candles) < 500:
        raise ValueError(f"only {len(m1_candles)} M1 candles -- too little for a meaningful M30 backtest")

    m30_candles_v2, _prov = resample_m1(m1_candles, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_candles_v2]

    manifest_path = os.path.join(CANONICAL_DIR, f"V2_MULTI_{research_symbol}_manifest.json")
    with open(manifest_path, "r") as f:
        symbol_manifest = json.load(f)
    broker_symbol = symbol_manifest["broker_symbol"]

    config = resolve_symbol_config(mt5, broker_symbol)

    split_def, (train_c, val_c, test_c) = split_chronological(candles, 0.60, 0.20, 0.20)

    def _part_metrics(part_candles):
        sigs = generate_signals(part_candles, config=config)
        res = run_backtest(part_candles, sigs, config=config)
        return calculate_metrics(res.trades, total_signals=len(sigs),
                                  unfilled_orders=res.unfilled_orders, skipped_no_tp=res.skipped_no_tp), sigs, res

    train_metrics, _, _ = _part_metrics(train_c)
    val_metrics, _, _ = _part_metrics(val_c)
    test_metrics, test_signals, test_result = _part_metrics(test_c)

    dq_report = audit_dataset(test_c)

    val_comp = ValidationComparison(
        val_expectancy_r=round(val_metrics.expectancy_r, 4),
        val_total_net_r=round(val_metrics.total_net_r, 4),
        val_profit_factor=round(val_metrics.profit_factor, 4) if val_metrics.profit_factor != float("inf") else 999.0,
        val_win_rate=round(val_metrics.win_rate, 4),
        val_max_drawdown_r=round(val_metrics.max_drawdown_r, 4),
        test_expectancy_r=round(test_metrics.expectancy_r, 4),
        test_total_net_r=round(test_metrics.total_net_r, 4),
        test_profit_factor=round(test_metrics.profit_factor, 4) if test_metrics.profit_factor != float("inf") else 999.0,
        test_win_rate=round(test_metrics.win_rate, 4),
        test_max_drawdown_r=round(test_metrics.max_drawdown_r, 4),
        expectancy_delta_r=round(test_metrics.expectancy_r - val_metrics.expectancy_r, 4),
        pf_delta=0.0, win_rate_delta=round(test_metrics.win_rate - val_metrics.win_rate, 4),
        max_dd_delta_r=round(test_metrics.max_drawdown_r - val_metrics.max_drawdown_r, 4),
    )
    classification, reason = classify_holdout_evidence(test_metrics, val_comp)

    dummy_wres = [WalkForwardWindowResult(0, 0, 0, 0, len(test_c), test_metrics, test_result.trades)]
    enriched = extract_enriched_oos_trades(test_c, dummy_wres, config=config)
    boot_m = compute_block_bootstrap(enriched, seed=42, block_size=3, num_resamples=1000) if enriched else None

    return {
        "research_symbol": research_symbol,
        "broker_symbol": broker_symbol,
        "config": asdict(config),
        "m1_row_count": len(m1_candles),
        "m30_row_count": len(candles),
        "split": {"train": len(train_c), "val": len(val_c), "test": len(test_c)},
        "data_quality_status_test": dq_report.status.value,
        "train_metrics": asdict(train_metrics),
        "val_metrics": asdict(val_metrics),
        "test_metrics": asdict(test_metrics),
        "validation_comparison": asdict(val_comp),
        "evidence_classification": classification,
        "evidence_reason": reason,
        "block_bootstrap": asdict(boot_m) if boot_m else None,
        "concentration": asdict(analyze_concentration(enriched)) if enriched else None,
    }


def load_summary() -> Dict[str, Any]:
    if os.path.exists(SUMMARY_PATH):
        with open(SUMMARY_PATH, "r") as f:
            return json.load(f)
    return {"symbols": {}}


def save_summary(summary: Dict[str, Any]) -> None:
    summary["updated_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    tmp = SUMMARY_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True, default=str)
    os.replace(tmp, SUMMARY_PATH)


def run() -> Dict[str, Any]:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"mt5.initialize() failed: {mt5.last_error()}")

    summary = load_summary()
    try:
        for research_symbol in SYMBOLS:
            if summary["symbols"].get(research_symbol, {}).get("status") == "DONE":
                _log(f"{research_symbol}: already DONE, skipping")
                continue
            _log(f"{research_symbol}: evaluating")
            try:
                result = evaluate_symbol(research_symbol, mt5)
                out_path = os.path.join(RESULTS_DIR, f"V2_MULTI_{research_symbol}_validation.json")
                os.makedirs(RESULTS_DIR, exist_ok=True)
                with open(out_path, "w") as f:
                    json.dump(result, f, indent=2, sort_keys=False, default=str)
                _log(f"{research_symbol}: DONE -- classification={result['evidence_classification']} "
                     f"test_expectancy_r={result['test_metrics']['expectancy_r']:.4f} "
                     f"test_trades={result['test_metrics']['filled_trades']}")
                summary["symbols"][research_symbol] = {
                    "status": "DONE",
                    "evidence_classification": result["evidence_classification"],
                    "test_expectancy_r": result["test_metrics"]["expectancy_r"],
                    "test_profit_factor": result["test_metrics"]["profit_factor"],
                    "test_win_rate": result["test_metrics"]["win_rate"],
                    "test_filled_trades": result["test_metrics"]["filled_trades"],
                    "result_path": out_path,
                }
            except Exception as e:
                _log(f"{research_symbol}: FAILED -- {e}")
                summary["symbols"][research_symbol] = {"status": "FAILED", "error": str(e)}
            save_summary(summary)
    finally:
        mt5.shutdown()

    return summary


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, default=str))
