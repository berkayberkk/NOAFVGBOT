"""
Dayanıklılık Katmanı Birim Testleri (Unit Tests for backtest/robustness.py).
"""

from datetime import datetime, timedelta
import pytest

from backtest.robustness import (
    generate_parameter_perturbations,
    classify_parameter,
    run_robustness_analysis,
    VariantResult,
)
from strategy.config import StrategyConfig, DEFAULT_CONFIG


def _make_dummy_candles(n: int = 300) -> list[dict]:
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    candles = []
    for i in range(n):
        candles.append({
            "time": base_time + timedelta(minutes=30 * i),
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.0,
            "tick_volume": 100,
            "spread": 10,
        })
    return candles


def test_generate_parameter_perturbations_float():
    perts = generate_parameter_perturbations("min_gap_to_atr_ratio", 0.15)
    assert len(perts) == 4
    vals = [v for v, p in perts]
    assert 0.135 in vals  # -10%
    assert 0.165 in vals  # +10%


def test_generate_parameter_perturbations_int_deduplication():
    # swing_lookback = 5 -> -10% is 4.5 -> round to 4, +10% is 5.5 -> round to 6
    perts = generate_parameter_perturbations("swing_lookback", 5)
    vals = [v for v, p in perts]
    assert len(vals) == len(set(vals))  # No duplicate values
    assert 5 not in vals  # Baseline excluded from perturbation variants


def test_classify_parameter_robust():
    baseline_exp = 0.50
    v1 = VariantResult("atr_period", 12, 14, -10.0, 40, 30, 0.70, 15.0, 0.45, 3.0, 1.5, 4, 0, 10.0, 10.0, 0.0)
    v2 = VariantResult("atr_period", 16, 14, 10.0, 40, 30, 0.70, 16.0, 0.48, 3.2, 1.5, 4, 0, 4.0, 5.0, 0.0)

    classification, plateau = classify_parameter(baseline_exp, 20.0, 1.5, [v1, v2])
    assert classification == "ROBUST"


def test_classify_parameter_fragile_on_negative_exp():
    baseline_exp = 0.50
    v1 = VariantResult("atr_period", 12, 14, -10.0, 40, 30, 0.70, -2.0, -0.10, 0.5, 3.0, 1, 3, 120.0, 110.0, 100.0)

    classification, plateau = classify_parameter(baseline_exp, 20.0, 1.5, [v1])
    assert classification == "FRAGILE"


def test_robustness_analysis_holds_test_sacred():
    candles = _make_dummy_candles(300)
    reports, summary = run_robustness_analysis(candles, baseline_config=DEFAULT_CONFIG, num_wf_windows=2)

    assert summary.final_test_evaluated is False
    assert summary.total_variants_tested > 0
    assert len(reports) > 0
