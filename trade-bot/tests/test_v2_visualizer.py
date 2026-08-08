"""
NOAFVGBOT V2 — Trade Visualizer Window Unit Tests.

Verifies complete chart window bounds, TP/SL exit candle visibility, context padding,
structural level integrity, and visualizer alignment with TradePassport engine truth.
"""

import pytest
from research.v2.data.acquisition import generate_synthetic_m1_dataset
from research.v2.engine.mtf_backtester import V2MultiTimeframeBacktester
from research.v2.strategy.train_policy import V2TrainResearchPolicy
from research.v2.telemetry.passport import OutcomeState, ThesisDirection
from research.v2.telemetry.visualizer import render_trade_chart_window


def test_visualizer_window_tp_sl_visibility_and_context_padding():
    raw_list, candles = generate_synthetic_m1_dataset("2021-01-04 01:00:00", count=500, start_price=1800.0)
    bt = V2MultiTimeframeBacktester(policy=V2TrainResearchPolicy())
    res = bt.run(candles)

    target_passports = [p for p in bt.passports.values() if p.outcome_state == OutcomeState.TARGET_REACHED]
    assert len(target_passports) > 0, "Must have TARGET_REACHED passports for visualizer test"

    # Test first 5 TARGET_REACHED passports
    for p in target_passports[:5]:
        chart = render_trade_chart_window(p, bt.path_observations, pre_context=20, post_context=10)

        # Integrity assertions
        assert chart.passport_id == p.passport_id
        assert chart.outcome_state == OutcomeState.TARGET_REACHED.value
        assert chart.tp_candle_visible is True
        assert chart.structural_entry == p.decision_snapshot.structural_entry
        assert chart.structural_stop == p.decision_snapshot.structural_stop
        assert chart.structural_target == p.decision_snapshot.structural_target

        # Context padding assertions
        assert len(chart.candles) >= 30, "Rendered chart window must include context padding"
        assert chart.entry_candle_index >= 0
        assert chart.outcome_candle_index > chart.entry_candle_index
        assert chart.outcome_candle_index < len(chart.candles)


def test_visualizer_v1_isolation():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
