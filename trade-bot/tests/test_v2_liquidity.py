"""
NOAFVGBOT V2.3 — Liquidity Feature Intelligence Unit Tests.

Comprehensive test suite verifying hindsight-free swing high/low detection, equal highs/lows,
PDH/PDL, session high/low, sweep/reclaim confirmation, as-of filtering, ThesisEvidence adapter,
and V1 isolation invariants.
"""

from datetime import datetime, timedelta, timezone
import pytest

from research.v2.data.models import CandleV2, Timeframe
from research.v2.features.liquidity import (
    LiquidityPool,
    LiquidityEvent,
    LiquiditySide,
    LiquidityType,
    LiquidityEventType,
    PoolState,
    SessionDefinition,
    compute_pool_id,
    detect_swings,
    detect_equal_highs_lows,
    detect_pdh_pdl,
    detect_session_high_low,
    analyze_sweeps_and_touches,
    active_pools_as_of,
    distance_to_nearest_pool,
)


def create_candle(ts_open: str, open_p: float = 2000.0, high_p: float = 2005.0, low_p: float = 1995.0, close_p: float = 2002.0, tf: Timeframe = Timeframe.M30) -> CandleV2:
    dt_open = datetime.fromisoformat(ts_open).replace(tzinfo=timezone.utc)
    dt_close = dt_open + timedelta(seconds=tf.seconds)
    return CandleV2(
        timestamp_open_utc=dt_open.strftime("%Y-%m-%d %H:%M:%S"),
        timestamp_close_utc=dt_close.strftime("%Y-%m-%d %H:%M:%S"),
        timeframe=tf,
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        volume=10.0,
    )


def test_1_to_3_swing_detection_and_confirmation_delay():
    # Build 5 candles where index 2 (11:00) is a swing high (high=2050) and index 2 is low=1950
    candles = [
        create_candle("2026-08-08 10:00:00", high_p=2010.0, low_p=1990.0),
        create_candle("2026-08-08 10:30:00", high_p=2020.0, low_p=1980.0),
        create_candle("2026-08-08 11:00:00", high_p=2050.0, low_p=1950.0),  # Swing High & Low
        create_candle("2026-08-08 11:30:00", high_p=2030.0, low_p=1970.0),
        create_candle("2026-08-08 12:00:00", high_p=2015.0, low_p=1985.0),
    ]

    pools = detect_swings(candles, left_bars=2, right_bars=2)
    assert len(pools) == 2

    high_pool = next(p for p in pools if p.side == LiquiditySide.BUY_SIDE)
    low_pool = next(p for p in pools if p.side == LiquiditySide.SELL_SIDE)

    assert high_pool.price == 2050.0
    assert high_pool.origin_timestamp == "2026-08-08 11:30:00"  # Candle 2 close timestamp
    assert high_pool.known_at_timestamp == "2026-08-08 12:30:00"  # Candle 4 close timestamp (confirmation delay!)

    assert low_pool.price == 1950.0
    assert low_pool.known_at_timestamp == "2026-08-08 12:30:00"


def test_4_to_7_equal_highs_and_lows_clustering():
    p1 = LiquidityPool("p1", LiquidityType.SWING_HIGH, LiquiditySide.BUY_SIDE, 2050.0, Timeframe.M30, "2026-08-08 11:30:00", "2026-08-08 12:30:00")
    p2 = LiquidityPool("p2", LiquidityType.SWING_HIGH, LiquiditySide.BUY_SIDE, 2050.3, Timeframe.M30, "2026-08-08 14:30:00", "2026-08-08 15:30:00")
    p3 = LiquidityPool("p3", LiquidityType.SWING_HIGH, LiquiditySide.BUY_SIDE, 2080.0, Timeframe.M30, "2026-08-08 17:30:00", "2026-08-08 18:30:00")

    # Within tolerance 0.50 -> p1 and p2 form an Equal Highs cluster!
    eq_pools = detect_equal_highs_lows([p1, p2, p3], tolerance_pts=0.50)
    assert len(eq_pools) == 1
    assert eq_pools[0].liquidity_type == LiquidityType.EQUAL_HIGHS
    assert eq_pools[0].member_count == 2
    assert abs(eq_pools[0].price - 2050.15) < 1e-4


def test_9_to_11_pdh_pdl_calculation_no_same_day_leakage():
    # Day 1: 2026-08-07 candles
    # Day 2: 2026-08-08 candles
    candles = [
        create_candle("2026-08-07 10:00:00", high_p=2030.0, low_p=1970.0),
        create_candle("2026-08-07 14:00:00", high_p=2060.0, low_p=1950.0),
        create_candle("2026-08-08 00:00:00", high_p=2040.0, low_p=1990.0),
    ]

    pdh_pdl_pools = detect_pdh_pdl(candles)
    assert len(pdh_pdl_pools) == 2

    pdh = next(p for p in pdh_pdl_pools if p.liquidity_type == LiquidityType.PREVIOUS_DAY_HIGH)
    pdl = next(p for p in pdh_pdl_pools if p.liquidity_type == LiquidityType.PREVIOUS_DAY_LOW)

    assert pdh.price == 2060.0
    assert pdl.price == 1950.0
    # Day 1 high/low observable at 00:00:00 of Day 2!
    assert pdh.known_at_timestamp == "2026-08-08 00:00:00"


def test_12_to_15_session_high_low():
    sess_def = SessionDefinition("LONDON", "08:00:00", "13:00:00")
    candles = [
        create_candle("2026-08-08 08:00:00", high_p=2020.0, low_p=1990.0),
        create_candle("2026-08-08 10:00:00", high_p=2070.0, low_p=1980.0),
        create_candle("2026-08-08 12:30:00", high_p=2050.0, low_p=1970.0),  # Close 13:00:00
    ]

    sess_pools = detect_session_high_low(candles, sess_def)
    assert len(sess_pools) == 2

    sh = next(p for p in sess_pools if p.liquidity_type == LiquidityType.SESSION_HIGH)
    sl = next(p for p in sess_pools if p.liquidity_type == LiquidityType.SESSION_LOW)

    assert sh.price == 2070.0
    assert sl.price == 1970.0
    assert sh.known_at_timestamp == "2026-08-08 13:00:00"  # Observable only at session close!


def test_16_to_21_touch_breach_sweep_reclaim():
    pool = LiquidityPool("lp_test", LiquidityType.SWING_HIGH, LiquiditySide.BUY_SIDE, 2050.0, Timeframe.M30, "2026-08-08 11:30:00", "2026-08-08 12:30:00")

    candles = [
        create_candle("2026-08-08 13:00:00", open_p=2042.0, high_p=2049.5, low_p=2040.0, close_p=2045.0),  # Below
        create_candle("2026-08-08 13:30:00", open_p=2047.0, high_p=2052.0, low_p=2045.0, close_p=2048.0),  # Breaches 2050 and closes back inside (2048) -> BREACH + SWEEP!
    ]

    events = analyze_sweeps_and_touches([pool], candles)
    assert len(events) == 3

    event_types = [e.event_type for e in events]
    assert LiquidityEventType.TOUCH in event_types
    assert LiquidityEventType.BREACH in event_types
    assert LiquidityEventType.SWEEP in event_types

    sweep_ev = next(e for e in events if e.event_type == LiquidityEventType.SWEEP)
    assert sweep_ev.price_at_event == 2048.0
    assert sweep_ev.breach_distance == 2.0  # 2052.0 - 2050.0


def test_22_to_27_distance_and_as_of_filtering():
    p1 = LiquidityPool("p1", LiquidityType.SWING_HIGH, LiquiditySide.BUY_SIDE, 2050.0, Timeframe.M30, "2026-08-08 11:30:00", "2026-08-08 12:30:00")
    p2 = LiquidityPool("p2", LiquidityType.SWING_HIGH, LiquiditySide.BUY_SIDE, 2080.0, Timeframe.M30, "2026-08-08 14:30:00", "2026-08-08 15:30:00")

    # At 13:00:00 -> p1 is visible, p2 is NOT visible!
    visible_at_13 = active_pools_as_of([p1, p2], "2026-08-08 13:00:00")
    assert len(visible_at_13) == 1
    assert visible_at_13[0].pool_id == "p1"

    dist = distance_to_nearest_pool([p1, p2], current_price=2040.0, side=LiquiditySide.BUY_SIDE, as_of_utc="2026-08-08 13:00:00")
    assert dist == 10.0  # |2050.0 - 2040.0|


def test_28_and_29_evidence_adapter_and_serialization():
    pool = LiquidityPool("lp_test", LiquidityType.SWING_HIGH, LiquiditySide.BUY_SIDE, 2050.0, Timeframe.M30, "2026-08-08 11:30:00", "2026-08-08 12:30:00")
    c = create_candle("2026-08-08 13:30:00", high_p=2052.0, close_p=2048.0)
    events = analyze_sweeps_and_touches([pool], [c])
    sweep_ev = next(e for e in events if e.event_type == LiquidityEventType.SWEEP)

    thesis_ev = sweep_ev.to_thesis_evidence("th_12345")
    assert thesis_ev.thesis_id == "th_12345"
    assert thesis_ev.timestamp_utc == "2026-08-08 14:00:00"
    assert thesis_ev.payload["event_type"] == "SWEEP"


def test_31_and_32_v1_isolation_regression():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
