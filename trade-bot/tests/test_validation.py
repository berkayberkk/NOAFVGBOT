"""
Doğrulama Çerçevesi Birim ve Entegrasyon Testleri (Unit Tests for backtest/validation.py).
"""

from datetime import datetime, timedelta
import pytest

from backtest.engine import Trade
from backtest.validation import (
    split_chronological,
    calculate_metrics,
    run_walk_forward,
    build_validation_report,
    SplitDefinition,
    BacktestMetrics,
)
from strategy.signal_engine import Signal, SignalType, Confidence, SetupType


def _make_dummy_candles(n: int) -> list[dict]:
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


def test_chronological_60_20_20_split():
    candles = _make_dummy_candles(100)
    split_def, (train, val, test) = split_chronological(candles, 0.60, 0.20, 0.20)

    assert len(train) == 60
    assert len(val) == 20
    assert len(test) == 20
    assert split_def.train_start == 0 and split_def.train_end == 60
    assert split_def.val_start == 60 and split_def.val_end == 80
    assert split_def.test_start == 80 and split_def.test_end == 100


def test_no_overlap_between_splits():
    candles = _make_dummy_candles(100)
    _, (train, val, test) = split_chronological(candles, 0.60, 0.20, 0.20)

    train_times = {c["time"] for c in train}
    val_times = {c["time"] for c in val}
    test_times = {c["time"] for c in test}

    assert train_times.isdisjoint(val_times)
    assert val_times.isdisjoint(test_times)
    assert train_times.isdisjoint(test_times)


def test_full_observation_coverage():
    candles = _make_dummy_candles(100)
    _, (train, val, test) = split_chronological(candles, 0.60, 0.20, 0.20)

    assert len(train) + len(val) + len(test) == 100
    assert train[0]["time"] == candles[0]["time"]
    assert test[-1]["time"] == candles[-1]["time"]


def test_invalid_split_ratios_rejected():
    candles = _make_dummy_candles(100)
    with pytest.raises(ValueError, match="toplamı 1.0 olmalıdır"):
        split_chronological(candles, 0.50, 0.20, 0.20)

    with pytest.raises(ValueError, match="pozitif olmalıdır"):
        split_chronological(candles, 0.80, 0.20, 0.0)


def test_insufficient_dataset_rejected():
    candles = _make_dummy_candles(30)
    with pytest.raises(ValueError, match="Yetersiz veriseti"):
        split_chronological(candles, 0.60, 0.20, 0.20, min_candles=50)


def test_walk_forward_boundaries_advance():
    candles = _make_dummy_candles(300)
    wf_results, _ = run_walk_forward(
        candles, num_windows=3, mode="expanding", min_train_size=100, val_size=40, test_holdout_size=0
    )

    assert len(wf_results) == 3
    assert wf_results[0].val_start < wf_results[1].val_start < wf_results[2].val_start
    assert wf_results[0].train_end <= wf_results[1].train_end


def test_test_holdout_never_enters_walk_forward():
    candles = _make_dummy_candles(300)
    wf_results, _ = run_walk_forward(
        candles, num_windows=3, mode="expanding", min_train_size=100, val_size=40, test_holdout_size=60
    )

    max_wf_val_end = max(w.val_end for w in wf_results)
    assert max_wf_val_end <= 240  # 300 - 60 holdout


def test_expanding_and_rolling_modes():
    candles = _make_dummy_candles(300)
    res_exp, _ = run_walk_forward(candles, num_windows=3, mode="expanding", min_train_size=100, val_size=40)
    res_roll, _ = run_walk_forward(candles, num_windows=3, mode="rolling", min_train_size=100, val_size=40)

    assert res_exp[1].train_start == 0
    assert res_roll[1].train_start > 0


def test_metrics_known_r_sequence():
    sig = Signal(index=1, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100, stop_loss=98, reason="test")
    trades = [
        Trade(signal=sig, entry_index=1, won=True, net_r_multiple=2.0, r_multiple=2.0),
        Trade(signal=sig, entry_index=2, won=False, net_r_multiple=-1.0, r_multiple=-1.0),
        Trade(signal=sig, entry_index=3, won=True, net_r_multiple=4.0, r_multiple=4.0),
    ]

    metrics = calculate_metrics(trades, total_signals=3, unfilled_orders=0)
    assert metrics.total_net_r == pytest.approx(5.0)
    assert metrics.avg_net_r == pytest.approx(5.0 / 3.0)
    assert metrics.wins == 2
    assert metrics.losses == 1
    assert metrics.win_rate == pytest.approx(2.0 / 3.0)


def test_max_drawdown_calculation():
    sig = Signal(index=1, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100, stop_loss=98, reason="test")
    # Equity curve: 0 -> +3 -> +2 -> +1 -> +4 -> +0 -> +4. Max peak = +4, lowest drop from peak = +0 (drawdown = 4.0)
    trades = [
        Trade(signal=sig, entry_index=1, won=True, net_r_multiple=3.0, r_multiple=3.0),
        Trade(signal=sig, entry_index=2, won=False, net_r_multiple=-1.0, r_multiple=-1.0),
        Trade(signal=sig, entry_index=3, won=False, net_r_multiple=-1.0, r_multiple=-1.0),
        Trade(signal=sig, entry_index=4, won=True, net_r_multiple=3.0, r_multiple=3.0),
        Trade(signal=sig, entry_index=5, won=False, net_r_multiple=-4.0, r_multiple=-4.0),
    ]

    metrics = calculate_metrics(trades)
    assert metrics.max_drawdown_r == pytest.approx(4.0)


def test_profit_factor_calculation():
    sig = Signal(index=1, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100, stop_loss=98, reason="test")
    trades = [
        Trade(signal=sig, entry_index=1, won=True, net_r_multiple=6.0, r_multiple=6.0),
        Trade(signal=sig, entry_index=2, won=False, net_r_multiple=-2.0, r_multiple=-2.0),
    ]

    metrics = calculate_metrics(trades)
    assert metrics.profit_factor == pytest.approx(3.0)  # 6.0 / 2.0 = 3.0


def test_longest_losing_streak():
    sig = Signal(index=1, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100, stop_loss=98, reason="test")
    trades = [
        Trade(signal=sig, entry_index=1, won=False, net_r_multiple=-1.0, r_multiple=-1.0),
        Trade(signal=sig, entry_index=2, won=False, net_r_multiple=-1.0, r_multiple=-1.0),
        Trade(signal=sig, entry_index=3, won=True, net_r_multiple=2.0, r_multiple=2.0),
        Trade(signal=sig, entry_index=4, won=False, net_r_multiple=-1.0, r_multiple=-1.0),
        Trade(signal=sig, entry_index=5, won=False, net_r_multiple=-1.0, r_multiple=-1.0),
        Trade(signal=sig, entry_index=6, won=False, net_r_multiple=-1.0, r_multiple=-1.0),
        Trade(signal=sig, entry_index=7, won=True, net_r_multiple=2.0, r_multiple=2.0),
    ]

    metrics = calculate_metrics(trades)
    assert metrics.longest_losing_streak == 3


def test_zero_trade_safety():
    metrics = calculate_metrics([])
    assert metrics.filled_trades == 0
    assert metrics.total_net_r == 0.0
    assert metrics.win_rate == 0.0
    assert metrics.profit_factor == 0.0
    assert metrics.max_drawdown_r == 0.0
    assert metrics.longest_losing_streak == 0


def test_all_win_safety():
    sig = Signal(index=1, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100, stop_loss=98, reason="test")
    trades = [
        Trade(signal=sig, entry_index=1, won=True, net_r_multiple=2.0, r_multiple=2.0),
        Trade(signal=sig, entry_index=2, won=True, net_r_multiple=3.0, r_multiple=3.0),
    ]

    metrics = calculate_metrics(trades)
    assert metrics.win_rate == 1.0
    assert metrics.losses == 0
    assert metrics.profit_factor == float('inf')
    assert metrics.max_drawdown_r == 0.0


def test_all_loss_safety():
    sig = Signal(index=1, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100, stop_loss=98, reason="test")
    trades = [
        Trade(signal=sig, entry_index=1, won=False, net_r_multiple=-1.0, r_multiple=-1.0),
        Trade(signal=sig, entry_index=2, won=False, net_r_multiple=-1.0, r_multiple=-1.0),
    ]

    metrics = calculate_metrics(trades)
    assert metrics.win_rate == 0.0
    assert metrics.wins == 0
    assert metrics.profit_factor == 0.0
    assert metrics.total_net_r == -2.0


def test_aggregate_oos_metrics_use_validation_trades_only():
    candles = _make_dummy_candles(300)
    wf_results, oos_metrics = run_walk_forward(
        candles, num_windows=2, mode="expanding", min_train_size=100, val_size=50, test_holdout_size=50
    )

    total_val_trades = sum(len(w.val_trades) for w in wf_results)
    assert oos_metrics.filled_trades == total_val_trades


def test_validation_report_holds_test_sacred():
    candles = _make_dummy_candles(300)
    report = build_validation_report(candles)

    assert report.total_candles == 300
    assert report.test_status == "NOT EVALUATED (SACRED HOLDOUT)"
    assert report.split.train_end == 180
    assert report.split.val_end == 240
    assert report.split.test_end == 300
