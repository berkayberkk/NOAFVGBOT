"""
Phase 4D Robustness Evaluation Runner Script.
Runs local parameter perturbations on BASELINE_CONFIG_V1 over out-of-sample validation windows ONLY.
Outputs backtest/results/robustness_v1.json artifact.
"""

import hashlib
import json
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parent.parent / "trade-bot"
sys.path.insert(0, str(project_root))

from data.loader import load_candles_from_csv
from backtest.data_quality import audit_dataset
from backtest.robustness import run_robustness_analysis
from strategy.config import StrategyConfig


def compute_dataset_hash(filepath: Path) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()[:16]


def main():
    data_path = project_root / "data" / "GOLD_M30_2yil.csv"
    candles = load_candles_from_csv(str(data_path))
    dataset_hash = compute_dataset_hash(data_path)

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
        spread=0.30,
        slippage=0.10,
        commission=0.10,
    )

    print("Running Phase 4D Local Parameter Sensitivity & Robustness Analysis...")
    reports, summary = run_robustness_analysis(
        candles,
        baseline_config=baseline_config,
        num_wf_windows=4,
        dataset_hash=dataset_hash,
    )

    # Export JSON artifact
    out_dir = project_root / "backtest" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "robustness_v1.json"

    export_dict = {
        "baseline_hash": summary.baseline_hash,
        "dataset_hash": summary.dataset_hash,
        "overall_classification": summary.overall_classification,
        "total_variants_tested": summary.total_variants_tested,
        "positive_expectancy_pct": summary.positive_expectancy_pct,
        "positive_total_net_r_pct": summary.positive_total_net_r_pct,
        "high_win_window_pct": summary.high_win_window_pct,
        "worst_case": {
            "variant": summary.worst_case_variant,
            "expectancy_r": round(summary.worst_case_expectancy_r, 4),
            "total_net_r": round(summary.worst_case_total_net_r, 2),
            "max_drawdown_r": round(summary.worst_case_max_drawdown_r, 2),
        },
        "trade_count_range": {
            "min": summary.min_trade_count,
            "median": summary.median_trade_count,
            "max": summary.max_trade_count,
        },
        "parameter_reports": [
            {
                "parameter_name": pr.parameter_name,
                "baseline_value": pr.baseline_value,
                "classification": pr.classification,
                "plateau": pr.plateau,
                "worst_expectancy_r": round(pr.worst_expectancy_r, 4),
                "worst_total_net_r": round(pr.worst_total_net_r, 2),
                "worst_max_drawdown_r": round(pr.worst_max_drawdown_r, 2),
                "variants": [
                    {
                        "variant_value": v.variant_value,
                        "pct_change": v.percentage_change,
                        "filled_trades": v.filled_trades,
                        "win_rate": round(v.win_rate, 4),
                        "total_net_r": round(v.total_net_r, 2),
                        "expectancy_r": round(v.expectancy_r, 4),
                        "profit_factor": round(v.profit_factor, 2),
                        "max_drawdown_r": round(v.max_drawdown_r, 2),
                        "profitable_windows": v.profitable_windows,
                        "expectancy_degradation_pct": round(v.expectancy_degradation_pct, 2),
                    }
                    for v in pr.variants
                ],
            }
            for pr in reports
        ],
        "final_test_evaluated": False,
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(export_dict, f, indent=2)

    print(f"Robustness Analysis Completed. Saved to {out_file}")
    print(f"Overall Classification: {summary.overall_classification}")
    print(f"Positive Expectancy: {summary.positive_expectancy_pct}% ({summary.positive_expectancy_variants}/{summary.total_variants_tested})")
    print(f"Positive Total Net R: {summary.positive_total_net_r_pct}% ({summary.positive_total_net_r_variants}/{summary.total_variants_tested})")
    print(f"High Win Windows (>=3/4): {summary.high_win_window_pct}% ({summary.high_win_window_variants}/{summary.total_variants_tested})")


if __name__ == "__main__":
    main()
