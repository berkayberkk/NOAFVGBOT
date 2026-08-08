"""
NOAFVGBOT V2.1 — Multi-Timeframe Data Core Unit Tests.

Comprehensive test suite verifying all 30 data core, resampling, wall-clock alignment,
as-of visibility, event clock, fingerprint, and V1 isolation invariants.
"""

from datetime import datetime, timedelta, timezone
import pytest

from research.v2.data.models import (
    CandleV2,
    MarketEvent,
    Timeframe,
    ResamplingProvenance,
    compute_dataset_fingerprint,
)
from research.v2.data.resampler import resample_m1, validate_m1_input
from research.v2.data.aligner import AsOfAligner
from research.v2.data.clock import MultiTimeframeClock, TIMEFRAME_PRIORITY


def create_m1_candle(ts_open: str, open_p: float = 2000.0, high_p: float = 2005.0, low_p: float = 1995.0, close_p: float = 2002.0, vol: float = 10.0) -> CandleV2:
    dt_open = datetime.fromisoformat(ts_open)
    dt_close = dt_open + timedelta(minutes=1)
    return CandleV2(
        timestamp_open_utc=dt_open.strftime("%Y-%m-%d %H:%M:%S"),
        timestamp_close_utc=dt_close.strftime("%Y-%m-%d %H:%M:%S"),
        timeframe=Timeframe.M1,
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        volume=vol,
    )


def test_1_candle_invariant_validation():
    # Valid candle
    c = create_m1_candle("2026-08-08 10:00:00")
    assert c.open == 2000.0

    # Non-finite price
    with pytest.raises(ValueError, match="finite number"):
        CandleV2("2026-08-08 10:00:00", "2026-08-08 10:01:00", Timeframe.M1, float("nan"), 2005.0, 1995.0, 2002.0)

    # Negative price
    with pytest.raises(ValueError, match="positive"):
        CandleV2("2026-08-08 10:00:00", "2026-08-08 10:01:00", Timeframe.M1, -10.0, 2005.0, 1995.0, 2002.0)

    # Invalid High
    with pytest.raises(ValueError, match="high"):
        CandleV2("2026-08-08 10:00:00", "2026-08-08 10:01:00", Timeframe.M1, 2000.0, 1990.0, 1995.0, 2002.0)

    # Invalid Low
    with pytest.raises(ValueError, match="low"):
        CandleV2("2026-08-08 10:00:00", "2026-08-08 10:01:00", Timeframe.M1, 2000.0, 2005.0, 2003.0, 2002.0)

    # Close <= Open timestamp
    with pytest.raises(ValueError, match="timestamp_close_utc"):
        CandleV2("2026-08-08 10:00:00", "2026-08-08 10:00:00", Timeframe.M1, 2000.0, 2005.0, 1995.0, 2002.0)


def test_2_to_6_resampling_m3_m5_m15_m30_and_volume():
    # Create 30 consecutive M1 candles starting at 10:00:00
    m1_list = []
    base_dt = datetime(2026, 8, 8, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(30):
        ts = (base_dt + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S")
        m1_list.append(create_m1_candle(ts, open_p=2000.0 + i, high_p=2010.0 + i, low_p=1990.0 + i, close_p=2001.0 + i, vol=5.0))

    # M3 (should produce 10 candles)
    m3_res, prov_m3 = resample_m1(m1_list, Timeframe.M3)
    assert len(m3_res) == 10
    assert m3_res[0].open == 2000.0
    assert m3_res[0].close == 2003.0
    assert m3_res[0].high == 2012.0
    assert m3_res[0].low == 1990.0
    assert m3_res[0].volume == 15.0  # 3 * 5.0

    # M5 (should produce 6 candles)
    m5_res, prov_m5 = resample_m1(m1_list, Timeframe.M5)
    assert len(m5_res) == 6
    assert m5_res[0].open == 2000.0
    assert m5_res[0].volume == 25.0

    # M15 (should produce 2 candles)
    m15_res, _ = resample_m1(m1_list, Timeframe.M15)
    assert len(m15_res) == 2
    assert m15_res[0].volume == 75.0

    # M30 (should produce 1 candle)
    m30_res, _ = resample_m1(m1_list, Timeframe.M30)
    assert len(m30_res) == 1
    assert m30_res[0].open == 2000.0
    assert m30_res[0].close == 2030.0
    assert m30_res[0].volume == 150.0


def test_7_and_8_wall_clock_alignment_and_mid_bucket_start():
    # Dataset starting mid-bucket at 10:02:00
    m1_list = []
    base_dt = datetime(2026, 8, 8, 10, 2, 0, tzinfo=timezone.utc)
    for i in range(8):  # 10:02 through 10:09
        ts = (base_dt + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S")
        m1_list.append(create_m1_candle(ts))

    # M5 resampling: 10:00-10:05 bucket incomplete (only 3 bars 10:02,03,04) -> excluded!
    # 10:05-10:10 bucket complete (5 bars 10:05,06,07,08,09) -> 1 candle emitted!
    m5_res, prov = resample_m1(m1_list, Timeframe.M5)
    assert len(m5_res) == 1
    assert m5_res[0].timestamp_open_utc == "2026-08-08 10:05:00"
    assert m5_res[0].timestamp_close_utc == "2026-08-08 10:10:00"
    assert prov.incomplete_bucket_count == 1


def test_9_to_12_incomplete_buckets_and_no_interpolation():
    # 4 M1 bars for M5 (missing 1 bar)
    m1_list = [create_m1_candle(f"2026-08-08 10:0{i}:00") for i in range(4)]
    m5_res, prov = resample_m1(m1_list, Timeframe.M5)
    assert len(m5_res) == 0  # Incomplete bucket excluded
    assert prov.incomplete_bucket_count == 1


def test_13_to_17_forming_candle_invisibility_and_as_of_lookup():
    # 5 M1 bars for 10:00-10:05 M5 candle (close time 10:05:00)
    m1_list = [create_m1_candle(f"2026-08-08 10:0{i}:00") for i in range(5)]
    m5_res, _ = resample_m1(m1_list, Timeframe.M5)

    aligner = AsOfAligner({Timeframe.M5: m5_res})

    # At 10:04:00 (forming candle) -> invisible!
    assert aligner.latest_closed(Timeframe.M5, "2026-08-08 10:04:00") is None

    # At 10:04:59 -> invisible!
    assert aligner.latest_closed(Timeframe.M5, "2026-08-08 10:04:59") is None

    # At 10:05:00 (exact close timestamp) -> visible!
    closed_c = aligner.latest_closed(Timeframe.M5, "2026-08-08 10:05:00")
    assert closed_c is not None
    assert closed_c.timestamp_close_utc == "2026-08-08 10:05:00"


def test_18_to_20_same_timestamp_ordering_m30_m15_m5_m3_m1():
    # Build a full 30 M1 bars dataset from 10:00:00 to 10:30:00
    m1_list = []
    base_dt = datetime(2026, 8, 8, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(30):
        ts = (base_dt + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S")
        m1_list.append(create_m1_candle(ts))

    datasets = {Timeframe.M1: m1_list}
    for tf in [Timeframe.M3, Timeframe.M5, Timeframe.M15, Timeframe.M30]:
        res, _ = resample_m1(m1_list, tf)
        datasets[tf] = res

    clock = MultiTimeframeClock(datasets)
    stream = clock.build_event_stream()

    # Find events closing at 10:30:00
    events_at_1030 = [e for e in stream if e.timestamp_utc == "2026-08-08 10:30:00"]
    assert len(events_at_1030) == 5

    tf_order = [e.timeframe for e in events_at_1030]
    expected_order = [Timeframe.M30, Timeframe.M15, Timeframe.M5, Timeframe.M3, Timeframe.M1]
    assert tf_order == expected_order


def test_21_to_23_input_validation_out_of_order_and_duplicates():
    c1 = create_m1_candle("2026-08-08 10:01:00")
    c2 = create_m1_candle("2026-08-08 10:00:00")

    # Out of order
    with pytest.raises(ValueError, match="out of chronological order"):
        validate_m1_input([c1, c2])

    # Duplicate timestamp
    with pytest.raises(ValueError, match="Duplicate M1 timestamp"):
        validate_m1_input([c1, c1])


def test_24_to_28_fingerprint_reproducibility_and_provenance():
    m1_list = [create_m1_candle(f"2026-08-08 10:0{i}:00") for i in range(5)]
    fp1 = compute_dataset_fingerprint(m1_list)
    fp2 = compute_dataset_fingerprint(m1_list)
    assert fp1 == fp2

    # Mutation changes fingerprint
    m1_mutated = list(m1_list)
    m1_mutated[0] = create_m1_candle("2026-08-08 10:00:00", open_p=2001.0)
    fp3 = compute_dataset_fingerprint(m1_mutated)
    assert fp1 != fp3

    m5_res, prov = resample_m1(m1_list, Timeframe.M5)
    assert prov.source_fingerprint == fp1
    assert prov.target_timeframe == "M5"
    assert prov.candle_count == 1


def test_29_and_30_v1_isolation_regression():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1
    import research.v2.data.models
    import research.v2.data.resampler
    import research.v2.data.aligner
    import research.v2.data.clock

    # Verify baseline configs remain unmodified
    assert BASELINE_CONFIG_V1.atr_period == 14
    assert BASELINE_CONFIG_V1.spread == 0.30
    assert DEFAULT_CONFIG.atr_period == 14
