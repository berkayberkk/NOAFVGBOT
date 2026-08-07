"""
Veri Kalitesi ve Denetim Katmanı Birim Testleri (Unit Tests for backtest/data_quality.py).
"""

from datetime import datetime, timedelta
import math
import pytest

from backtest.data_quality import (
    audit_dataset,
    infer_timeframe_seconds,
    QualityCheckStatus,
    IntervalType,
)


def _make_clean_candles(n: int = 20, timeframe_minutes: int = 30) -> list[dict]:
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    candles = []
    for i in range(n):
        candles.append({
            "time": base_time + timedelta(minutes=timeframe_minutes * i),
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 102.0,
            "tick_volume": 100,
            "spread": 10,
        })
    return candles


def test_clean_ohlc_dataset_pass():
    candles = _make_clean_candles(20)
    report = audit_dataset(candles)
    assert report.status == QualityCheckStatus.PASS
    assert report.candle_count == 20
    assert report.missing_fields == 0
    assert report.invalid_numeric_values == 0
    assert report.ohlc_violations == 0
    assert report.out_of_order_timestamps == 0


def test_high_less_than_open_fail():
    candles = _make_clean_candles(10)
    candles[3]["high"] = 98.0  # open is 100.0 -> high < open violation
    report = audit_dataset(candles)
    assert report.status == QualityCheckStatus.FAIL
    assert report.ohlc_violations == 1


def test_low_greater_than_close_fail():
    candles = _make_clean_candles(10)
    candles[5]["low"] = 103.0  # close is 102.0 -> low > close violation
    report = audit_dataset(candles)
    assert report.status == QualityCheckStatus.FAIL
    assert report.ohlc_violations == 1


def test_nan_price_fail():
    candles = _make_clean_candles(10)
    candles[2]["close"] = float("nan")
    report = audit_dataset(candles)
    assert report.status == QualityCheckStatus.FAIL
    assert report.invalid_numeric_values == 1


def test_inf_price_fail():
    candles = _make_clean_candles(10)
    candles[4]["high"] = float("inf")
    report = audit_dataset(candles)
    assert report.status == QualityCheckStatus.FAIL
    assert report.invalid_numeric_values == 1


def test_zero_price_fail():
    candles = _make_clean_candles(10)
    candles[1]["low"] = 0.0
    report = audit_dataset(candles)
    assert report.status == QualityCheckStatus.FAIL
    assert report.invalid_numeric_values == 1


def test_negative_price_fail():
    candles = _make_clean_candles(10)
    candles[6]["open"] = -10.0
    report = audit_dataset(candles)
    assert report.status == QualityCheckStatus.FAIL
    assert report.invalid_numeric_values == 1


def test_duplicate_identical_timestamp_candle():
    candles = _make_clean_candles(10)
    # Duplicate candle 2 at same timestamp
    candles[3] = dict(candles[2])
    report = audit_dataset(candles)
    assert report.duplicate_timestamps == 1
    assert report.conflicting_duplicates == 0
    assert report.status == QualityCheckStatus.WARNING


def test_conflicting_duplicate_fail():
    candles = _make_clean_candles(10)
    # Same timestamp as candle 2, but different OHLC values
    candles[3] = dict(candles[2])
    candles[3]["close"] = 104.0
    report = audit_dataset(candles)
    assert report.duplicate_timestamps == 1
    assert report.conflicting_duplicates == 1
    assert report.status == QualityCheckStatus.FAIL


def test_reversed_out_of_order_timestamp_fail():
    candles = _make_clean_candles(10)
    # Swap timestamps of candles 4 and 5
    candles[4]["time"], candles[5]["time"] = candles[5]["time"], candles[4]["time"]
    report = audit_dataset(candles)
    assert report.out_of_order_timestamps >= 1
    assert report.status == QualityCheckStatus.FAIL


def test_clean_fixed_timeframe():
    candles = _make_clean_candles(15, timeframe_minutes=30)
    tf = infer_timeframe_seconds(candles)
    assert tf == 1800.0  # 30 minutes


def test_one_missing_intrasession_candle_detected():
    candles = _make_clean_candles(10, timeframe_minutes=30)
    # Remove candle 5, introducing a 60 min gap (1 missing 30-min bar)
    candles.pop(5)
    report = audit_dataset(candles)
    assert report.irregular_intervals == 1
    assert report.total_estimated_missing_bars == 1


def test_multiple_missing_bars_estimated_correctly():
    candles = _make_clean_candles(10, timeframe_minutes=30)
    # Create a 2-hour gap between candle 4 and next candle (3 missing 30-min bars)
    base_time = candles[4]["time"]
    candles[5]["time"] = base_time + timedelta(hours=2)
    report = audit_dataset(candles)
    assert report.total_estimated_missing_bars == 3


def test_large_weekend_like_gap_reported_without_interpolation():
    candles = _make_clean_candles(10, timeframe_minutes=30)
    # Create 60-hour gap (weekend closure)
    candles[5]["time"] = candles[4]["time"] + timedelta(hours=60)
    report = audit_dataset(candles)
    assert report.large_gaps == 1
    assert len(candles) == 10  # Veri kümesine sentetik mum eklenmedi!


def test_extreme_candle_produces_warning_not_automatic_fail():
    candles = _make_clean_candles(15)
    # Normal range is 10.0 (105-95). Make candle 7 range = 100.0 (high=195, low=95)
    candles[7]["high"] = 195.0
    report = audit_dataset(candles)
    assert report.status == QualityCheckStatus.WARNING
    assert any(a.anomaly_type == "EXTREME_RANGE_WARNING" for a in report.anomalies)


def test_extreme_close_jump_produces_warning():
    candles = _make_clean_candles(15)
    # Add small normal close fluctuations (e.g. 0.20)
    for i in range(15):
        candles[i]["close"] = 100.0 + (i % 2) * 0.20
    # Jump close of candle 8 to 200.0
    candles[8]["high"] = 205.0
    candles[8]["close"] = 200.0
    report = audit_dataset(candles)
    assert report.status == QualityCheckStatus.WARNING
    assert any(a.anomaly_type == "EXTREME_JUMP_WARNING" for a in report.anomalies)


def test_dataset_too_small_handled_safely():
    candles = _make_clean_candles(1)
    report = audit_dataset(candles)
    assert report.candle_count == 1
    assert report.expected_timeframe_seconds is None
    assert report.status == QualityCheckStatus.PASS


def test_report_severity_aggregation():
    candles = _make_clean_candles(10)
    # Contains a warning (duplicate) AND a fail (high < open)
    candles[3] = dict(candles[2])
    candles[5]["high"] = 90.0  # high < open
    report = audit_dataset(candles)
    assert report.status == QualityCheckStatus.FAIL
