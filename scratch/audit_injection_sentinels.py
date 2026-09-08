"""
Phase 4D Correctness Audit Script.
Verifies runtime parameter injection, extreme sentinel tests, baseline reproduction,
trade/signal identity shifts, and reruns real local sensitivity.
"""

from pathlib import Path
import sys

project_root = Path(__file__).resolve().parent.parent / "trade-bot"
sys.path.insert(0, str(project_root))

from data.loader import load_candles_from_csv
from backtest.validation import split_chronological, run_walk_forward
from backtest.robustness import run_robustness_analysis
from strategy.config import StrategyConfig
from strategy.signal_engine import generate_signals


def main():
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

    # Step 1: Baseline Fingerprint & Reproduction
    _, base_oos = run_walk_forward(
        candles, num_windows=4, mode="expanding", config=baseline_config,
        min_train_size=len(train_candles)//2, val_size=len(val_candles)//2, test_holdout_size=test_holdout_size
    )

    base_signals = []
    base_trades = []
    for w in range(4):
        v_start = split_def.train_start if w==0 else (len(train_candles)//2 + w * ((len(candles)-test_holdout_size - len(train_candles)//2 - len(val_candles)//2)//3))
        v_end = min(v_start + len(val_candles)//2, len(candles)-test_holdout_size)
        v_candles = candles[v_start:v_end]
        sigs = generate_signals(v_candles, config=baseline_config)
        base_signals.append(len(sigs))

    print("=== 1. BASELINE REPRODUCTION ===")
    print(f"Filled Trades: {base_oos.filled_trades} (Expected: 42)")
    print(f"Total Net R: {base_oos.total_net_r:.2f}R (Expected: 22.06R)")
    print(f"Expectancy R: {base_oos.expectancy_r:.4f}R (Expected: 0.5253R)")

    # Step 2: Extreme Sentinel Tests
    print("\n=== 2. EXTREME SENTINEL TESTS ===")
    sentinels = [
        ("min_gap_to_atr_ratio=10.0", StrategyConfig(min_gap_to_atr_ratio=10.0, spread=0.3, slippage=0.1, commission=0.1)),
        ("max_gap_to_atr_ratio=0.01", StrategyConfig(max_gap_to_atr_ratio=0.01, spread=0.3, slippage=0.1, commission=0.1)),
        ("min_level_touch_count=5", StrategyConfig(min_level_touch_count=5, spread=0.3, slippage=0.1, commission=0.1)),
        ("strong_move_ratio=10.0", StrategyConfig(strong_move_ratio=10.0, spread=0.3, slippage=0.1, commission=0.1)),
    ]

    sentinel_passed = True
    for name, s_cfg in sentinels:
        _, s_oos = run_walk_forward(
            candles, num_windows=4, mode="expanding", config=s_cfg,
            min_train_size=len(train_candles)//2, val_size=len(val_candles)//2, test_holdout_size=test_holdout_size
        )
        changed = (s_oos.total_signals != base_oos.total_signals or s_oos.filled_trades != base_oos.filled_trades or s_oos.total_net_r != base_oos.total_net_r)
        print(f"   Sentinel {name}: Signals={s_oos.total_signals}, Trades={s_oos.filled_trades}, Net R={s_oos.total_net_r:.2f}R | Changed from baseline: {changed}")
        if not changed:
            sentinel_passed = False

    print(f"Sentinel Audit Result: {'PASS' if sentinel_passed else 'FAIL'}")

    # Step 3: Real Local Robustness Analysis
    print("\n=== 3. REAL LOCAL ROBUSTNESS RERUN ===")
    reports, summary = run_robustness_analysis(candles, baseline_config=baseline_config, num_wf_windows=4)

    changed_signal_count = 0
    changed_trade_count = 0

    for pr in reports:
        for v in pr.variants:
            if v.total_signals != base_oos.total_signals:
                changed_signal_count += 1
            if v.filled_trades != base_oos.filled_trades or v.total_net_r != base_oos.total_net_r:
                changed_trade_count += 1

    print(f"Total Variants Tested: {summary.total_variants_tested}")
    print(f"Overall Classification: {summary.overall_classification}")
    print(f"Positive Expectancy %: {summary.positive_expectancy_pct}% ({summary.positive_expectancy_variants}/{summary.total_variants_tested})")
    print(f"Worst Case Expectancy: {summary.worst_case_expectancy_r:.4f}R ({summary.worst_case_variant})")
    print(f"Worst Case Total Net R: {summary.worst_case_total_net_r:.2f}R")
    print(f"Worst Case Max DD: {summary.worst_case_max_drawdown_r:.2f}R")
    print(f"Variants with Changed Signals: {changed_signal_count}")
    print(f"Variants with Changed Trades/Results: {changed_trade_count}")
    print(f"FINAL TEST EVALUATED: {summary.final_test_evaluated}")


if __name__ == "__main__":
    main()
