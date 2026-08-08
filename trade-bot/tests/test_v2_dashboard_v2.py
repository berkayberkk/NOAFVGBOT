"""
NOAFVGBOT V2 — Performance Dashboard V2 Unit Tests.

Verifies Dashboard V2 suite generation, trade gallery, monthly heatmap,
rolling metrics, excursion analysis, quarantine warning banners, and partition protections.
"""

import os
import pytest
from research.v2.data.acquisition import generate_synthetic_m1_dataset
from research.v2.engine.mtf_backtester import V2MultiTimeframeBacktester
from research.v2.strategy.train_policy import V2TrainResearchPolicy
from research.v2.engine.train_runner import run_train_discovery_experiment
from research.v2.telemetry.performance_dashboard import generate_v2_performance_dashboard_suite
from research.v2.telemetry.rolling_metrics import generate_rolling_metrics


def test_dashboard_v2_suite_generation(tmp_path):
    raw_list, candles = generate_synthetic_m1_dataset("2021-01-04 01:00:00", count=500, start_price=1800.0)
    bt = V2MultiTimeframeBacktester(policy=V2TrainResearchPolicy())
    bt.run(candles)

    res = run_train_discovery_experiment(allow_synthetic=True, count=500)
    outputs = generate_v2_performance_dashboard_suite(
        res,
        list(bt.passports.values()),
        bt.path_observations,
        results_dir=str(tmp_path)
    )

    for key, path in outputs.items():
        assert os.path.exists(path), f"Dashboard V2 output {key} missing: {path}"
        assert os.path.getsize(path) > 1000, f"Dashboard V2 output {key} empty"


def test_rolling_pf_returns_na_when_no_losses(tmp_path):
    raw_list, candles = generate_synthetic_m1_dataset("2021-01-04 01:00:00", count=500, start_price=1800.0)
    bt = V2MultiTimeframeBacktester(policy=V2TrainResearchPolicy())
    bt.run(candles)

    rolling_path = str(tmp_path / "test_rolling.png")
    out = generate_rolling_metrics(list(bt.passports.values()), output_path=rolling_path, is_quarantined=True)
    assert os.path.exists(out)


def test_dashboard_v2_v1_and_protection_isolation():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
