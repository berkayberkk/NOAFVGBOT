"""
Phase 4F Unit Tests: Final Sacred Holdout Evaluation.
Verifies evidence classification, comparison delta calculations, and consumed status flags.
"""

from backtest.final_holdout import (
    classify_holdout_evidence,
    ValidationComparison,
    FinalHoldoutReport,
)
from backtest.validation import BacktestMetrics


def test_classify_holdout_evidence_strong():
    m = BacktestMetrics(
        expectancy_r=0.45,
        total_net_r=15.0,
        profit_factor=3.5,
        max_drawdown_r=1.5,
    )
    vc = ValidationComparison()
    status, reason = classify_holdout_evidence(m, vc)
    assert status == "VALIDATED STRONG"


def test_classify_holdout_evidence_failed():
    m = BacktestMetrics(
        expectancy_r=-0.10,
        total_net_r=-2.0,
        profit_factor=0.8,
        max_drawdown_r=4.0,
    )
    vc = ValidationComparison()
    status, reason = classify_holdout_evidence(m, vc)
    assert status == "FAILED TO GENERALIZE"


def test_final_holdout_consumed_flags():
    rep = FinalHoldoutReport(
        git_commit="2a2bf12",
        baseline_fingerprint="fp",
        dataset_fingerprint="ds",
        test_start_index=18813,
        test_end_index=23517,
        test_start_date="2026-03-03",
        test_end_date="2026-07-24",
        test_candle_count=4704,
        data_quality_status="PASS",
        final_test_evaluated=True,
        final_test_consumed=True,
    )
    assert rep.final_test_evaluated is True
    assert rep.final_test_consumed is True
