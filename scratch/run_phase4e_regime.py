"""
Runner script for Phase 4E: Regime & Dependence Robustness Analysis.
Executes time distribution, volatility regime, market state, direction, setup type,
concentration, serial dependence, block bootstrap, and leave-one-window-out analysis.
Saves results to trade-bot/backtest/results/regime_robustness_v1.json.
"""

from dataclasses import asdict
import json
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parent.parent / "trade-bot"
sys.path.insert(0, str(project_root))

from data.loader import load_candles_from_csv
from backtest.validation import split_chronological, run_walk_forward
from backtest.regime import run_regime_robustness_analysis
from strategy.config import StrategyConfig


def main():
    print("Running Phase 4E Regime & Dependence Robustness Analysis...")
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

    split_def, (train_candles, val_candles, test_candles) = split_chronological(candles, 0.60, 0.20, 0.20)
    test_holdout_size = len(test_candles)

    # 4 Walk-Forward Validation Windows (Expanding)
    window_results, oos_metrics = run_walk_forward(
        candles,
        num_windows=4,
        mode="expanding",
        config=baseline_config,
        min_train_size=len(train_candles) // 2,
        val_size=len(val_candles) // 2,
        test_holdout_size=test_holdout_size,
    )

    report = run_regime_robustness_analysis(
        candles,
        window_results,
        baseline_fingerprint="5a56639725048f3d",
        config=baseline_config,
    )

    out_path = project_root / "backtest" / "results" / "regime_robustness_v1.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2)

    print(f"Regime Robustness Analysis Saved to {out_path}")
    print(f"Total OOS Trades: {report.total_oos_trades}")
    print(f"Overall Classification: {report.overall_classification}")
    print(f"Reason: {report.classification_reason}")


if __name__ == "__main__":
    main()
