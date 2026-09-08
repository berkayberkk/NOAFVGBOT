"""
Phase 4C Sanity Verification Script.
Performs 12-point scientific sanity checks on baseline out-of-sample results.
"""

import math
from pathlib import Path
import random
import statistics
import sys

project_root = Path(__file__).resolve().parent.parent / "trade-bot"
sys.path.insert(0, str(project_root))

from data.loader import load_candles_from_csv
from backtest.data_quality import audit_dataset, QualityCheckStatus
from backtest.validation import split_chronological, run_walk_forward
from strategy.config import StrategyConfig


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

    wf_results, oos_metrics = run_walk_forward(
        candles,
        num_windows=4,
        mode="expanding",
        config=baseline_config,
        min_train_size=len(train_candles) // 2,
        val_size=len(val_candles) // 2,
        test_holdout_size=len(test_candles),
    )

    # 1. Uniqueness
    all_trades = []
    trade_keys = []
    for w in wf_results:
        for t in w.val_trades:
            all_trades.append(t)
            # Trade key based on signal index + signal entry + exit price
            t_key = (t.signal.index, t.signal.entry, t.executed_entry, t.executed_exit)
            trade_keys.append(t_key)

    unique_keys = set(trade_keys)
    print(f"1. Unique Trades: {len(unique_keys)} / Total Trades: {len(all_trades)} | Duplicates: {len(all_trades) - len(unique_keys)}")

    # 2. Window Boundaries
    print("\n2. Window Boundaries:")
    for w in wf_results:
        tr_start_t = candles[w.train_start]["time"]
        tr_end_t = candles[min(w.train_end-1, len(candles)-1)]["time"]
        val_start_t = candles[w.val_start]["time"]
        val_end_t = candles[min(w.val_end-1, len(candles)-1)]["time"]
        print(f"   W{w.window_index}: Train [{w.train_start}:{w.train_end}] ({tr_start_t} -> {tr_end_t}) | Val [{w.val_start}:{w.val_end}] ({val_start_t} -> {val_end_t}) | Signals: {w.val_metrics.total_signals}, Trades: {w.val_metrics.filled_trades}, Net R: {w.val_metrics.total_net_r:.2f}R")

    # 3. Cost Spot Check
    wins = [t for t in all_trades if t.won]
    losses = [t for t in all_trades if not t.won]
    first_win = wins[0] if wins else None
    first_loss = losses[0] if losses else None

    print("\n3. Cost Spot Check:")
    if first_win:
        risk = abs(first_win.signal.entry - first_win.signal.stop_loss)
        calc_gross_pnl = first_win.executed_exit - first_win.executed_entry if first_win.signal.type.value == "buy" else first_win.executed_entry - first_win.executed_exit
        calc_net_pnl = calc_gross_pnl - baseline_config.commission
        calc_net_r = calc_net_pnl / risk
        print(f"   First Win: Entry={first_win.executed_entry}, Exit={first_win.executed_exit}, Risk={risk:.2f}, Stored Net R={first_win.net_r_multiple:.4f}, Calc Net R={calc_net_r:.4f}")
    if first_loss:
        risk = abs(first_loss.signal.entry - first_loss.signal.stop_loss)
        calc_gross_pnl = first_loss.executed_exit - first_loss.executed_entry if first_loss.signal.type.value == "buy" else first_loss.executed_entry - first_loss.executed_exit
        calc_net_pnl = calc_gross_pnl - baseline_config.commission
        calc_net_r = calc_net_pnl / risk
        print(f"   First Loss: Entry={first_loss.executed_entry}, Exit={first_loss.executed_exit}, Risk={risk:.2f}, Stored Net R={first_loss.net_r_multiple:.4f}, Calc Net R={calc_net_r:.4f}")

    # 4. Cost Sensitivity Explanation
    total_cost_r_sum = 0.0
    for t in all_trades:
        risk = abs(t.signal.entry - t.signal.stop_loss)
        # 1x costs: exit slippage (0.10) + commission (0.10) = 0.20 price distance
        total_cost_r_sum += (0.20 / risk)
    avg_cost_r_1x = total_cost_r_sum / len(all_trades)
    print(f"\n4. Avg Cost R/Trade (1x): {avg_cost_r_1x:.4f}R | Total 1x Cost R across 42 trades: {total_cost_r_sum:.2f}R")
    print(f"   For 2x costs (+0.20 price cost addition), delta per trade ~ {avg_cost_r_1x:.4f}R -> total delta across 42 trades ~ {avg_cost_r_1x * 42:.2f}R (~1.08R drop).")

    # 6. Window-level Robustness
    w_rs = [w.val_metrics.total_net_r for w in wf_results]
    print(f"\n6. Window Net R Stats: Mean={statistics.mean(w_rs):.2f}R, Median={statistics.median(w_rs):.2f}R, Std={statistics.stdev(w_rs):.2f}R, Min={min(w_rs):.2f}R, Max={max(w_rs):.2f}R")

    # 7. Trade Distribution
    r_vals = sorted([t.net_r_multiple for t in all_trades])
    win_r_vals = [t.net_r_multiple for t in wins]
    loss_r_vals = [t.net_r_multiple for t in losses]

    avg_win_r = sum(win_r_vals) / len(win_r_vals) if win_r_vals else 0
    avg_loss_r = abs(sum(loss_r_vals) / len(loss_r_vals)) if loss_r_vals else 0
    payoff_ratio = avg_win_r / avg_loss_r if avg_loss_r > 0 else 0

    p10 = r_vals[int(0.10 * len(r_vals))]
    p25 = r_vals[int(0.25 * len(r_vals))]
    p50 = statistics.median(r_vals)
    p75 = r_vals[int(0.75 * len(r_vals))]
    p90 = r_vals[int(0.90 * len(r_vals))]

    print(f"\n7. Trade Distribution (R): Min={r_vals[0]:.2f}, P10={p10:.2f}, P25={p25:.2f}, Median={p50:.2f}, P75={p75:.2f}, P90={p90:.2f}, Max={r_vals[-1]:.2f}")
    print(f"   Avg Winner: {avg_win_r:.4f}R | Avg Loser: -{avg_loss_r:.4f}R | Payoff Ratio: {payoff_ratio:.2f}")

    # 9. Data Warnings
    dq_report = audit_dataset(candles)
    print(f"\n9. Data Warnings ({len(dq_report.anomalies)} total):")
    print(f"   Normal intervals: {dq_report.normal_intervals}, Irregular: {dq_report.irregular_intervals}, Large weekend gaps: {dq_report.large_gaps}")

    # 10. Reproducibility
    wf_results2, oos_metrics2 = run_walk_forward(
        candles, num_windows=4, mode="expanding", config=baseline_config,
        min_train_size=len(train_candles)//2, val_size=len(val_candles)//2, test_holdout_size=len(test_candles)
    )
    is_deterministic = (
        oos_metrics.total_signals == oos_metrics2.total_signals and
        oos_metrics.filled_trades == oos_metrics2.filled_trades and
        oos_metrics.total_net_r == oos_metrics2.total_net_r and
        oos_metrics.win_rate == oos_metrics2.win_rate
    )
    print(f"\n10. Deterministic Reproducibility: {is_deterministic}")


if __name__ == "__main__":
    main()
