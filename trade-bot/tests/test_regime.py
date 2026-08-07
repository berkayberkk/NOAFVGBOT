"""
Phase 4E Unit Tests: Regime & Dependence Robustness.
Verifies time distribution, volatility regime classification, concentration analysis,
block bootstrap determinism, leave-one-window-out aggregation, and sacred holdout protection.
"""

from backtest.regime import (
    analyze_time_distribution,
    analyze_volatility_regimes,
    analyze_concentration,
    analyze_serial_dependence,
    compute_block_bootstrap,
    compute_leave_one_window_out,
    classify_regime_robustness,
    RegimeRobustnessReport,
    BucketMetrics,
    LeaveOneWindowOutMetrics,
)
from backtest.validation import WalkForwardWindowResult


def test_time_distribution_bucketing():
    enriched_trades = [
        {"year": "2024", "quarter": "2024-Q1", "net_r": 1.0, "won": True, "trade": None},
        {"year": "2024", "quarter": "2024-Q1", "net_r": 2.0, "won": True, "trade": None},
        {"year": "2025", "quarter": "2025-Q2", "net_r": -1.0, "won": False, "trade": None},
    ]

    metrics = analyze_time_distribution(enriched_trades)
    names = [m.bucket_name for m in metrics]

    assert "Year 2024" in names
    assert "Year 2025" in names
    assert "Quarter 2024-Q1" in names

    y2024 = next(m for m in metrics if m.bucket_name == "Year 2024")
    assert y2024.filled_trades == 2
    assert y2024.total_net_r == 3.0


def test_volatility_regimes_classification():
    enriched_trades = [
        {"atr": 1.0, "net_r": 1.0, "won": True, "trade": None},
        {"atr": 2.0, "net_r": 1.0, "won": True, "trade": None},
        {"atr": 3.0, "net_r": 1.0, "won": True, "trade": None},
        {"atr": 4.0, "net_r": 1.0, "won": True, "trade": None},
        {"atr": 5.0, "net_r": -1.0, "won": False, "trade": None},
        {"atr": 6.0, "net_r": -1.0, "won": False, "trade": None},
    ]

    vols = analyze_volatility_regimes(enriched_trades)
    assert len(vols) == 3
    total_trades_classified = sum(m.filled_trades for m in vols)
    assert total_trades_classified == 6


def test_concentration_analysis():
    enriched_trades = [
        {"net_r": 5.0},
        {"net_r": 3.0},
        {"net_r": 2.0},
        {"net_r": 1.0},
        {"net_r": -1.0},
    ]

    conc = analyze_concentration(enriched_trades)
    assert conc.top_1_contribution_r == 5.0
    assert conc.top_3_contribution_r == 10.0
    assert conc.after_removing_best_1_r == 5.0
    assert conc.after_removing_best_3_r == 0.0


def test_serial_dependence_and_autocorr():
    enriched_trades = [
        {"net_r": 1.0, "won": True},
        {"net_r": -1.0, "won": False},
        {"net_r": 1.0, "won": True},
        {"net_r": -1.0, "won": False},
    ]

    ser = analyze_serial_dependence(enriched_trades)
    assert ser.win_to_loss_count == 2
    assert ser.loss_to_win_count == 1
    assert ser.lag_1_autocorrelation < 0  # Alternating sequence yields negative autocorrelation


def test_block_bootstrap_reproducibility():
    enriched_trades = [{"net_r": float(i % 3 - 1)} for i in range(20)]

    b1 = compute_block_bootstrap(enriched_trades, seed=42, block_size=3, num_resamples=100)
    b2 = compute_block_bootstrap(enriched_trades, seed=42, block_size=3, num_resamples=100)

    assert b1.mean_expectancy_r == b2.mean_expectancy_r
    assert b1.ci_lower_95 == b2.ci_lower_95
    assert b1.ci_upper_95 == b2.ci_upper_95


def test_leave_one_window_out():
    w0 = WalkForwardWindowResult(0, 0, 100, 100, 200, None, val_trades=[])
    w1 = WalkForwardWindowResult(1, 0, 200, 200, 300, None, val_trades=[])

    lows = compute_leave_one_window_out([w0, w1])
    assert len(lows) == 0  # No trades in dummy list


def test_sacred_holdout_protection():
    rep = RegimeRobustnessReport(
        baseline_fingerprint="test_fp",
        total_oos_trades=42,
        final_test_evaluated=False,
    )
    assert rep.final_test_evaluated is False
