"""
Phase 4C Baseline Evaluation Script.
Reads historical dataset, audits data quality, freezes BASELINE_CONFIG_V1,
and performs out-of-sample walk-forward validation WITHOUT touching the TEST holdout.
"""

import hashlib
import json
from pathlib import Path
import random
import sys
from typing import Dict, Any

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent / "trade-bot"
sys.path.insert(0, str(project_root))

from data.loader import load_candles_from_csv
from backtest.data_quality import audit_dataset, QualityCheckStatus
from backtest.validation import (
    split_chronological,
    calculate_metrics,
    run_walk_forward,
    build_validation_report,
    SplitDefinition,
    BacktestMetrics,
)
from strategy.config import StrategyConfig
from strategy.signal_engine import generate_signals
from backtest.engine import run_backtest, Trade


def compute_dataset_hash(filepath: Path) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()[:16]


def bootstrap_ci_mean_r(trades: list[Trade], n_bootstraps: int = 2000, seed: int = 42) -> dict:
    if not trades:
        return {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0}

    r_vals = [t.net_r_multiple for t in trades if t.net_r_multiple is not None]
    if not r_vals:
        return {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0}

    rng = random.Random(seed)
    means = []
    n = len(r_vals)
    for _ in range(n_bootstraps):
        sample = [rng.choice(r_vals) for _ in range(n)]
        means.append(sum(sample) / n)

    means.sort()
    low_idx = int(0.025 * n_bootstraps)
    high_idx = int(0.975 * n_bootstraps)
    
    mean_val = sum(r_vals) / n
    return {
        "mean": round(mean_val, 4),
        "ci_lower": round(means[low_idx], 4),
        "ci_upper": round(means[high_idx], 4),
    }


def main():
    data_path = project_root / "data" / "GOLD_M30_2yil.csv"
    if not data_path.exists():
        print("BLOCKED — HISTORICAL DATA REQUIRED")
        return

    candles = load_candles_from_csv(str(data_path))
    dataset_hash = compute_dataset_hash(data_path)

    print(f"Dataset Loaded: {len(candles)} candles")
    print(f"Start: {candles[0]['time']}, End: {candles[-1]['time']}")
    print(f"Dataset Hash: {dataset_hash}")

    # Step 1: Data Audit
    dq_report = audit_dataset(candles)
    print(f"Data Quality Status: {dq_report.status.value}")
    if dq_report.status == QualityCheckStatus.FAIL:
        print("BLOCKED — DATA QUALITY AUDIT FAILED")
        return

    # Step 2: Frozen Baseline Config
    baseline_config = StrategyConfig(
        atr_period=14,
        min_gap_to_atr_ratio=0.15,
        max_gap_to_atr_ratio=2.5,
        max_middle_candle_ratio=3.0,
        avg_range_period=14,
        strong_move_ratio=2.0,
        swing_lookback=5,
        tolerance_atr_ratio=0.5,
        min_level_touch_count=2,
        ema_period=50,
        spread=0.30,      # 0.30 USD spread on XAUUSD
        slippage=0.10,    # 0.10 USD adverse entry/exit slippage
        commission=0.10,  # 0.10 USD round-turn normalized commission
    )

    config_str = str(baseline_config)
    config_hash = hashlib.sha256(config_str.encode("utf-8")).hexdigest()[:16]

    # Step 3: Chronological Split (60% Train, 20% Val, 20% Test)
    split_def, (train_candles, val_candles, test_candles) = split_chronological(candles, 0.60, 0.20, 0.20)
    print(f"Train: {len(train_candles)} candles ({candles[split_def.train_start]['time']} -> {candles[split_def.train_end-1]['time']})")
    print(f"Val: {len(val_candles)} candles ({candles[split_def.val_start]['time']} -> {candles[split_def.val_end-1]['time']})")
    print(f"Test (LOCKED/HOLDOUT): {len(test_candles)} candles ({candles[split_def.test_start]['time']} -> {candles[split_def.test_end-1]['time']})")

    # Step 4: Walk-Forward OOS Evaluation on Validation partition ONLY
    wf_results, oos_metrics = run_walk_forward(
        candles,
        num_windows=4,
        mode="expanding",
        config=baseline_config,
        min_train_size=len(train_candles) // 2,
        val_size=len(val_candles) // 2,
        test_holdout_size=len(test_candles),
    )

    # Step 5: Cost Sensitivity Analysis (1.0x, 1.5x, 2.0x)
    cost_sensitivity = {}
    for multiplier in [1.0, 1.5, 2.0]:
        cfg_cost = StrategyConfig(
            spread=baseline_config.spread * multiplier,
            slippage=baseline_config.slippage * multiplier,
            commission=baseline_config.commission * multiplier,
        )
        _, oos_m_cost = run_walk_forward(
            candles,
            num_windows=4,
            mode="expanding",
            config=cfg_cost,
            min_train_size=len(train_candles) // 2,
            val_size=len(val_candles) // 2,
            test_holdout_size=len(test_candles),
        )
        cost_sensitivity[f"{multiplier}x"] = {
            "spread": cfg_cost.spread,
            "slippage": cfg_cost.slippage,
            "commission": cfg_cost.commission,
            "total_net_r": round(oos_m_cost.total_net_r, 2),
            "expectancy_r": round(oos_m_cost.expectancy_r, 4),
            "profit_factor": round(oos_m_cost.profit_factor, 2),
            "win_rate": round(oos_m_cost.win_rate, 4),
        }

    # Step 6: Stability & Uncertainty
    all_oos_trades = []
    for w in wf_results:
        all_oos_trades.extend(w.val_trades)

    ci_bootstrap = bootstrap_ci_mean_r(all_oos_trades, seed=42)

    profitable_windows = sum(1 for w in wf_results if w.val_metrics.total_net_r > 0)
    losing_windows = len(wf_results) - profitable_windows
    window_net_rs = [round(w.val_metrics.total_net_r, 2) for w in wf_results]

    if profitable_windows == len(wf_results):
        stability_class = "CONSISTENT"
    elif profitable_windows > 0:
        stability_class = "MIXED"
    else:
        stability_class = "UNSTABLE"

    sample_size_assessment = (
        "SUFFICIENT SAMPLE" if len(all_oos_trades) >= 30 else "INSUFFICIENT SAMPLE FOR STRONG CONCLUSIONS"
    )

    # Step 7: Export JSON Artifact
    results_dir = project_root / "backtest" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_file = results_dir / "baseline_validation_v1.json"

    export_data = {
        "baseline_version": "BASELINE_CONFIG_V1",
        "config_hash": config_hash,
        "dataset_hash": dataset_hash,
        "instrument": "GOLD / XAUUSD",
        "timeframe": "M30",
        "candle_count": len(candles),
        "start_time": str(candles[0]["time"]),
        "end_time": str(candles[-1]["time"]),
        "data_quality_status": dq_report.status.value,
        "data_quality_warnings": [a.message for a in dq_report.anomalies if a.severity == QualityCheckStatus.WARNING],
        "split": {
            "train_range": [str(candles[split_def.train_start]["time"]), str(candles[split_def.train_end-1]["time"])],
            "val_range": [str(candles[split_def.val_start]["time"]), str(candles[split_def.val_end-1]["time"])],
            "test_range": [str(candles[split_def.test_start]["time"]), str(candles[split_def.test_end-1]["time"])],
            "train_count": len(train_candles),
            "val_count": len(val_candles),
            "test_count": len(test_candles),
        },
        "execution_assumptions": {
            "spread": baseline_config.spread,
            "slippage": baseline_config.slippage,
            "commission": baseline_config.commission,
        },
        "per_window_oos_metrics": [
            {
                "window_index": w.window_index,
                "val_range": [str(candles[w.val_start]["time"]), str(candles[min(w.val_end-1, len(candles)-1)]["time"])],
                "signals": w.val_metrics.total_signals,
                "filled_trades": w.val_metrics.filled_trades,
                "unfilled_orders": w.val_metrics.unfilled_orders,
                "win_rate": round(w.val_metrics.win_rate, 4),
                "total_net_r": round(w.val_metrics.total_net_r, 2),
                "expectancy_r": round(w.val_metrics.expectancy_r, 4),
                "profit_factor": round(w.val_metrics.profit_factor, 2),
                "max_drawdown_r": round(w.val_metrics.max_drawdown_r, 2),
                "longest_losing_streak": w.val_metrics.longest_losing_streak,
            }
            for w in wf_results
        ],
        "aggregate_oos_metrics": {
            "total_signals": oos_metrics.total_signals,
            "filled_trades": oos_metrics.filled_trades,
            "unfilled_orders": oos_metrics.unfilled_orders,
            "fill_rate": round(oos_metrics.fill_rate, 4),
            "wins": oos_metrics.wins,
            "losses": oos_metrics.losses,
            "win_rate": round(oos_metrics.win_rate, 4),
            "total_net_r": round(oos_metrics.total_net_r, 2),
            "avg_net_r": round(oos_metrics.avg_net_r, 4),
            "median_net_r": round(oos_metrics.median_net_r, 4),
            "expectancy_r": round(oos_metrics.expectancy_r, 4),
            "profit_factor": round(oos_metrics.profit_factor, 2),
            "max_drawdown_r": round(oos_metrics.max_drawdown_r, 2),
            "longest_losing_streak": oos_metrics.longest_losing_streak,
            "std_dev_net_r": round(oos_metrics.std_dev_net_r, 4),
            "downside_dev_net_r": round(oos_metrics.downside_dev_net_r, 4),
        },
        "stability": {
            "classification": stability_class,
            "profitable_windows": profitable_windows,
            "losing_windows": losing_windows,
            "window_net_rs": window_net_rs,
        },
        "sample_size_assessment": sample_size_assessment,
        "uncertainty_bootstrap_ci": ci_bootstrap,
        "cost_sensitivity": cost_sensitivity,
        "final_test_evaluated": False,
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2)

    print(f"\nBaseline Evaluation Completed. Results exported to {out_file}")
    print(f"Aggregate OOS Net R: {oos_metrics.total_net_r:.2f}R | Expectancy: {oos_metrics.expectancy_r:.4f}R | Win Rate: {oos_metrics.win_rate*100:.1f}%")
    print(f"Final TEST Evaluated: False (HOLDOUT LOCKED)")


if __name__ == "__main__":
    main()
