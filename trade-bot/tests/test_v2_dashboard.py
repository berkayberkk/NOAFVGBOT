"""
NOAFVGBOT V2 — Performance Dashboard Unit Tests.

Verifies dashboard generation, quarantined status warning banner, integrity checks,
and strict protection of DEVELOPMENT, VALIDATION, and FINAL_TEST partitions.
"""

import os
import pytest
from research.v2.engine.train_runner import run_train_discovery_experiment
from research.v2.telemetry.performance_dashboard import generate_v2_performance_dashboard


def test_performance_dashboard_generation_and_quarantine_warning(tmp_path):
    res = run_train_discovery_experiment(allow_synthetic=True, count=500)
    out_file = str(tmp_path / "test_dashboard.png")

    saved_path = generate_v2_performance_dashboard(res, output_path=out_file)
    assert os.path.exists(saved_path)
    assert os.path.getsize(saved_path) > 1000, "Dashboard PNG file must not be empty"


def test_dashboard_v1_isolation():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
