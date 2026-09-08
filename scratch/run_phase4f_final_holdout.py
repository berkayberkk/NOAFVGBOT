"""
Runner script for Phase 4F: FINAL SACRED HOLDOUT EVALUATION.
Runs ONE-SHOT evaluation of BASELINE_CONFIG_V1 on the final 20% holdout partition (candles[18813:]).
Saves results to trade-bot/backtest/results/final_holdout_v1.json.
"""

from dataclasses import asdict
import json
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parent.parent / "trade-bot"
sys.path.insert(0, str(project_root))

from data.loader import load_candles_from_csv
from backtest.final_holdout import run_final_holdout_evaluation
from strategy.config import StrategyConfig


def main():
    print("Running Phase 4F: FINAL SACRED HOLDOUT EVALUATION (ONE-SHOT)...")
    data_path = project_root / "data" / "GOLD_M30_2yil.csv"
    candles = load_candles_from_csv(str(data_path))

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

    report = run_final_holdout_evaluation(
        candles,
        git_commit="2a2bf12",
        baseline_fingerprint="5a56639725048f3d",
        dataset_fingerprint="gold_m30_2yil_clean",
        config=baseline_config,
    )

    out_path = project_root / "backtest" / "results" / "final_holdout_v1.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2)

    print(f"Final Holdout Analysis Saved to {out_path}")
    print(f"Date Range: {report.test_start_date} to {report.test_end_date} ({report.test_candle_count} candles)")
    print(f"Data Quality: {report.data_quality_status}")
    print(f"Signals: {report.test_metrics.total_signals}")
    print(f"Filled Trades: {report.test_metrics.filled_trades}")
    print(f"Total Net R: {report.test_metrics.total_net_r:.2f}R")
    print(f"Expectancy R: {report.test_metrics.expectancy_r:.4f}R")
    print(f"Profit Factor: {report.test_metrics.profit_factor:.2f}")
    print(f"Win Rate: {report.test_metrics.win_rate*100:.1f}%")
    print(f"Max Drawdown: {report.test_metrics.max_drawdown_r:.2f}R")
    print(f"Classification: {report.evidence_classification}")
    print(f"Reason: {report.evidence_reason}")
    print(f"FINAL TEST EVALUATED: {report.final_test_evaluated}")
    print(f"FINAL TEST CONSUMED: {report.final_test_consumed}")


if __name__ == "__main__":
    main()
