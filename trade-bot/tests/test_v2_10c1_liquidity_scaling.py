"""
NOAFVGBOT V2.10C.1 -- Liquidity Sweep/Touch Scaling Hardening Parity Tests.

Performance-only change: research/v2/features/liquidity.py::analyze_sweeps_and_touches was
rewritten to avoid O(pools x candles) per-pair datetime parsing (via bisect on pre-sorted,
fixed-width timestamp strings) while producing byte-identical output to the pre-V2.10C.1
implementation, preserved verbatim as _analyze_sweeps_and_touches_reference for exactly this
purpose. Every test in this file either proves exact parity against that reference oracle, or
proves a structural (non-wall-clock) reduction in wasted work per section 29 of the V2.10C.1
mission ("A coarse performance guard may use operation counts rather than milliseconds").

No strategy semantics, thesis policy, or dataset content are touched by this file.
"""

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from research.v2.data.models import CandleV2, Timeframe
from research.v2.features.liquidity import (
    LiquidityPool,
    LiquiditySide,
    LiquidityType,
    LiquidityEventType,
    detect_swings,
    detect_equal_highs_lows,
    analyze_sweeps_and_touches,
    _analyze_sweeps_and_touches_reference,
)


def create_candle(ts_open: str, o: float, h: float, l: float, c: float, tf: Timeframe = Timeframe.M5) -> CandleV2:
    dt_open = datetime.fromisoformat(ts_open).replace(tzinfo=timezone.utc)
    dt_close = dt_open + timedelta(seconds=tf.seconds)
    return CandleV2(
        timestamp_open_utc=dt_open.strftime("%Y-%m-%d %H:%M:%S"),
        timestamp_close_utc=dt_close.strftime("%Y-%m-%d %H:%M:%S"),
        timeframe=tf,
        open=o, high=h, low=l, close=c, volume=10.0,
    )


def generate_m1_series(start_ts: str, count: int, seed: int = 11, tf: Timeframe = Timeframe.M5) -> "list[CandleV2]":
    """Deterministic (no RNG) zig-zag walk, reused pattern from test_v2_10c_feature_wiring.py --
    varied enough to reliably produce touches/breaches/sweeps on both sides."""
    dt = datetime.fromisoformat(start_ts).replace(tzinfo=timezone.utc)
    res = []
    p = 2400.0 + seed
    for i in range(count):
        ts_open = dt.strftime("%Y-%m-%d %H:%M:%S")
        phase = i % 17
        move = (phase - 8) * 0.9 + (0.4 if i % 3 == 0 else -0.2)
        o = p
        c = p + move
        h = max(o, c) + 1.0 + (i % 5) * 0.1
        l = min(o, c) - 1.0 - (i % 4) * 0.1
        res.append(create_candle(ts_open, o, h, l, c, tf=tf))
        p = c
        dt += timedelta(seconds=tf.seconds)
    return res


def _event_tuple(e):
    return (e.event_id, e.pool_id, e.event_type, e.timestamp_utc, e.price_at_event, e.breach_distance,
            e.metadata.get("source_timeframe"), e.metadata.get("reclaim"))


def assert_exact_parity(pools, candles):
    ref = _analyze_sweeps_and_touches_reference(pools, candles)
    opt = analyze_sweeps_and_touches(pools, candles)
    # Exact ordering parity (not just set parity) -- event insertion order is itself part of
    # the current contract (pool-major, then candle-ascending, touch-before-breach-before-sweep).
    assert [_event_tuple(e) for e in ref] == [_event_tuple(e) for e in opt]
    return ref, opt


def make_pool(side: LiquiditySide, price: float, known_at: str, ltype: LiquidityType = None,
              tf: Timeframe = Timeframe.M5, origin: str = None) -> LiquidityPool:
    ltype = ltype or (LiquidityType.SWING_HIGH if side == LiquiditySide.BUY_SIDE else LiquidityType.SWING_LOW)
    origin = origin or known_at
    return LiquidityPool(
        pool_id=f"lp_test_{side.value}_{price}_{known_at}",
        liquidity_type=ltype,
        side=side,
        price=price,
        source_timeframe=tf,
        origin_timestamp=origin,
        known_at_timestamp=known_at,
    )


# --- 1: untouched active pool ------------------------------------------------------------------

def test_1_untouched_active_pool():
    candles = generate_m1_series("2026-01-01 00:00:00", 5, seed=1)
    # Pool far above all highs -- never touched/breached.
    pool = make_pool(LiquiditySide.BUY_SIDE, 999999.0, candles[0].timestamp_close_utc)
    ref, opt = assert_exact_parity([pool], candles)
    assert ref == []


# --- 2: simple touch (no breach) ----------------------------------------------------------------

def test_2_simple_touch_no_breach():
    candles = [
        create_candle("2026-01-02 00:00:00", 2000, 2010, 1995, 2005),
        create_candle("2026-01-02 00:05:00", 2005, 2010, 1998, 2003),  # exact touch at high==2010
    ]
    pool = make_pool(LiquiditySide.BUY_SIDE, 2010.0, candles[0].timestamp_close_utc)
    ref, opt = assert_exact_parity([pool], candles)
    assert any(e.event_type == LiquidityEventType.TOUCH for e in ref)
    assert not any(e.event_type == LiquidityEventType.BREACH for e in ref)


# --- 3: breach without reclaim -------------------------------------------------------------------

def test_3_breach_without_reclaim():
    candles = [
        create_candle("2026-01-03 00:00:00", 2000, 2005, 1995, 2002),
        create_candle("2026-01-03 00:05:00", 2002, 2020, 1998, 2018),  # breach, closes ABOVE level -> no reclaim
    ]
    pool = make_pool(LiquiditySide.BUY_SIDE, 2010.0, candles[0].timestamp_close_utc)
    ref, opt = assert_exact_parity([pool], candles)
    assert any(e.event_type == LiquidityEventType.BREACH for e in ref)
    assert not any(e.event_type == LiquidityEventType.SWEEP for e in ref)


# --- 4: breach then reclaim = sweep --------------------------------------------------------------

def test_4_breach_then_reclaim_is_sweep():
    candles = [
        create_candle("2026-01-04 00:00:00", 2000, 2005, 1995, 2002),
        create_candle("2026-01-04 00:05:00", 2002, 2020, 1998, 2005),  # breach high 2020, closes back below 2010
    ]
    pool = make_pool(LiquiditySide.BUY_SIDE, 2010.0, candles[0].timestamp_close_utc)
    ref, opt = assert_exact_parity([pool], candles)
    types = [e.event_type for e in ref]
    assert LiquidityEventType.BREACH in types
    assert LiquidityEventType.SWEEP in types


# --- 5: same-candle touch/breach/reclaim ----------------------------------------------------------

def test_5_same_candle_touch_breach_reclaim():
    candles = [
        create_candle("2026-01-05 00:00:00", 2000, 2005, 1995, 2002),
        create_candle("2026-01-05 00:05:00", 2002, 2050, 1998, 2005),  # touch+breach+reclaim all on ONE candle
    ]
    pool = make_pool(LiquiditySide.BUY_SIDE, 2010.0, candles[0].timestamp_close_utc)
    ref, opt = assert_exact_parity([pool], candles)
    same_candle_events = [e for e in ref if e.timestamp_utc == candles[1].timestamp_close_utc]
    assert {e.event_type for e in same_candle_events} == {LiquidityEventType.TOUCH, LiquidityEventType.BREACH, LiquidityEventType.SWEEP}
    # Preserve exact ordering: touch-check fires before breach/sweep-check within the same candle.
    assert same_candle_events[0].event_type == LiquidityEventType.TOUCH


# --- 6 & 7: LONG (BUY_SIDE) and SHORT (SELL_SIDE) liquidity ---------------------------------------

def test_6_buy_side_liquidity():
    candles = generate_m1_series("2026-01-06 00:00:00", 30, seed=2)
    pool = make_pool(LiquiditySide.BUY_SIDE, 2400.0, candles[0].timestamp_close_utc)
    assert_exact_parity([pool], candles)


def test_7_sell_side_liquidity():
    candles = generate_m1_series("2026-01-07 00:00:00", 30, seed=3)
    pool = make_pool(LiquiditySide.SELL_SIDE, 2380.0, candles[0].timestamp_close_utc)
    assert_exact_parity([pool], candles)


# --- 8: multiple pools same side -------------------------------------------------------------------

def test_8_multiple_pools_same_side():
    candles = generate_m1_series("2026-01-08 00:00:00", 40, seed=4)
    pools = [
        make_pool(LiquiditySide.BUY_SIDE, 2405.0, candles[0].timestamp_close_utc),
        make_pool(LiquiditySide.BUY_SIDE, 2415.0, candles[5].timestamp_close_utc),
        make_pool(LiquiditySide.BUY_SIDE, 2425.0, candles[10].timestamp_close_utc),
    ]
    assert_exact_parity(pools, candles)


# --- 9: pools both sides ------------------------------------------------------------------------

def test_9_pools_both_sides():
    candles = generate_m1_series("2026-01-09 00:00:00", 40, seed=5)
    pools = [
        make_pool(LiquiditySide.BUY_SIDE, 2410.0, candles[0].timestamp_close_utc),
        make_pool(LiquiditySide.SELL_SIDE, 2390.0, candles[0].timestamp_close_utc),
    ]
    assert_exact_parity(pools, candles)


# --- 10: overlapping price levels -----------------------------------------------------------------

def test_10_overlapping_price_levels():
    candles = generate_m1_series("2026-01-10 00:00:00", 40, seed=6)
    pools = [
        make_pool(LiquiditySide.BUY_SIDE, 2405.0, candles[0].timestamp_close_utc),
        make_pool(LiquiditySide.BUY_SIDE, 2405.25, candles[0].timestamp_close_utc),  # overlapping/near-identical level
    ]
    assert_exact_parity(pools, candles)


# --- 11 & 12: equal-high / equal-low clustering feeds into the same analyzer -----------------------

def test_11_12_equal_high_low_clusters_feed_analyzer_unchanged():
    candles = generate_m1_series("2026-01-11 00:00:00", 200, seed=7)
    swings = detect_swings(candles)
    eq_pools = detect_equal_highs_lows(swings)
    all_pools = swings + eq_pools
    assert eq_pools, "expected at least one equal-high/low cluster in this fixture"
    assert_exact_parity(all_pools, candles)


# --- 13: swing confirmation delay is untouched by this change (detect_swings not modified) --------

def test_13_swing_confirmation_delay_untouched():
    candles = [
        create_candle("2026-01-13 00:00:00", 2000, 2010, 1990, 2005),
        create_candle("2026-01-13 00:05:00", 2005, 2020, 1995, 2015),
        create_candle("2026-01-13 00:10:00", 2015, 2050, 2010, 2045),
        create_candle("2026-01-13 00:15:00", 2045, 2045, 2020, 2025),
        create_candle("2026-01-13 00:20:00", 2025, 2030, 2015, 2020),
    ]
    pools = detect_swings(candles, left_bars=2, right_bars=2)
    highs = [p for p in pools if p.liquidity_type == LiquidityType.SWING_HIGH]
    assert highs[0].known_at_timestamp == candles[4].timestamp_close_utc
    assert_exact_parity(pools, candles)


# --- 14: pool becomes known late in a long series ---------------------------------------------------

def test_14_pool_becomes_known_late():
    candles = generate_m1_series("2026-01-14 00:00:00", 300, seed=8)
    late_known_at = candles[280].timestamp_close_utc
    pool = make_pool(LiquiditySide.SELL_SIDE, 2390.0, late_known_at)
    ref, opt = assert_exact_parity([pool], candles)
    # Nothing before known_at could have produced an event.
    assert all(e.timestamp_utc >= late_known_at for e in ref)


# --- 15: candle strictly before known_at is ignored --------------------------------------------------

def test_15_candle_before_known_at_ignored():
    candles = [
        create_candle("2026-01-15 00:00:00", 2000, 2050, 1950, 2010),  # would touch/breach if visible
        create_candle("2026-01-15 00:05:00", 2010, 2011, 2005, 2008),
    ]
    # known_at AFTER the dramatic first candle -- that candle must be invisible to this pool.
    pool = make_pool(LiquiditySide.BUY_SIDE, 2010.0, candles[1].timestamp_close_utc)
    ref, opt = assert_exact_parity([pool], candles)
    assert all(e.timestamp_utc != candles[0].timestamp_close_utc for e in ref)


# --- 16: pools that reach a state keep receiving only semantically-correct further events -----------

def test_16_post_breach_events_remain_semantically_gated():
    """TOUCH must permanently stop firing once is_breached; BREACH/SWEEP may keep firing on later
    candles that independently satisfy the raw price condition again -- this is the pre-existing
    (unmodified) V2.10C contract; this test locks in that exact behavior for both implementations."""
    candles = generate_m1_series("2026-01-16 00:00:00", 60, seed=9)
    pool = make_pool(LiquiditySide.BUY_SIDE, 2402.0, candles[0].timestamp_close_utc)
    ref, opt = assert_exact_parity([pool], candles)
    touch_events = [e for e in ref if e.event_type == LiquidityEventType.TOUCH]
    breach_events = [e for e in ref if e.event_type == LiquidityEventType.BREACH]
    if breach_events:
        first_breach_ts = breach_events[0].timestamp_utc
        assert all(e.timestamp_utc <= first_breach_ts for e in touch_events)


# --- 17: gap between pool creation and next relevant event -------------------------------------------

def test_17_gap_between_known_at_and_first_relevant_candle():
    candles = generate_m1_series("2026-01-17 00:00:00", 100, seed=10)
    # A pool priced far away so many candles pass with zero events before eventual relevance.
    pool = make_pool(LiquiditySide.SELL_SIDE, 2200.0, candles[0].timestamp_close_utc)
    assert_exact_parity([pool], candles)


# --- 18: multiple events at the same timestamp (different pools) preserve deterministic order --------

def test_18_multiple_events_same_timestamp_deterministic_order():
    candles = generate_m1_series("2026-01-18 00:00:00", 40, seed=12)
    pools = [
        make_pool(LiquiditySide.BUY_SIDE, 2404.0, candles[0].timestamp_close_utc),
        make_pool(LiquiditySide.SELL_SIDE, 2396.0, candles[0].timestamp_close_utc),
    ]
    ref, opt = assert_exact_parity(pools, candles)
    # Re-running must reproduce the identical ordering (no reliance on set/dict iteration order).
    ref2 = _analyze_sweeps_and_touches_reference(pools, candles)
    opt2 = analyze_sweeps_and_touches(pools, candles)
    assert [_event_tuple(e) for e in ref] == [_event_tuple(e) for e in ref2]
    assert [_event_tuple(e) for e in opt] == [_event_tuple(e) for e in opt2]


# --- 19: repeated identical input is deterministic ----------------------------------------------------

def test_19_repeated_identical_input_deterministic():
    candles = generate_m1_series("2026-01-19 00:00:00", 150, seed=13)
    swings = detect_swings(candles)
    eq = detect_equal_highs_lows(swings)
    pools = swings + eq
    r1 = analyze_sweeps_and_touches(pools, candles)
    r2 = analyze_sweeps_and_touches(pools, candles)
    assert [_event_tuple(e) for e in r1] == [_event_tuple(e) for e in r2]


# --- 20: reversed pool-container ordering is a REAL ordering change (locked, not silently altered) ---

def test_20_pool_order_determines_event_order_both_implementations_agree():
    """The current contract is pool-major insertion order (not sorted-by-time across pools) --
    reversing the pools list legitimately changes the returned list's order. What must NOT change
    is that BOTH implementations agree with each other for any given pool ordering."""
    candles = generate_m1_series("2026-01-20 00:00:00", 40, seed=14)
    pools = [
        make_pool(LiquiditySide.BUY_SIDE, 2404.0, candles[0].timestamp_close_utc),
        make_pool(LiquiditySide.SELL_SIDE, 2396.0, candles[0].timestamp_close_utc),
    ]
    assert_exact_parity(pools, candles)
    assert_exact_parity(list(reversed(pools)), candles)


# --- Real TRAIN-prefix parity (small, bounded sizes only -- reference is intentionally O(P x C)) ----

def test_21_real_train_prefix_parity_small():
    """Runs BOTH implementations on a real bounded TRAIN prefix (500 M1 rows, resampled to M5)
    and requires exact parity, per section 20 of the V2.10C.1 mission -- kept small because the
    reference oracle is deliberately not optimized."""
    from research.v2.data.live_dataset import load_authoritative_frozen_v2_dataset
    from research.v2.data.resampler import resample_m1
    from research.v2.data.gap_forensics import PARTITION_BOUNDARIES

    train_end = next(end for name, _s, end in PARTITION_BOUNDARIES if name == "TRAIN")
    candles, _manifest = load_authoritative_frozen_v2_dataset()
    m1 = []
    for c in candles:
        if c.timestamp_open_utc >= train_end:
            break
        m1.append(c)
        if len(m1) >= 500:
            break

    m5, _prov = resample_m1(m1, Timeframe.M5)
    swings = detect_swings(m5)
    eq = detect_equal_highs_lows(swings)
    pools = swings + eq
    assert_exact_parity(pools, m5)


# --- Structural (non-wall-clock) performance guard: eliminates per-pair datetime parsing -----------

def test_22_optimized_path_performs_zero_datetime_parses_for_pre_known_at_region():
    """Section 29 guard: operation counts, not wall-clock. The reference re-parses EVERY candle's
    timestamp for EVERY pool (including all candles strictly before known_at, which it then
    discards). The optimized path must issue ZERO datetime.fromisoformat calls at all inside
    analyze_sweeps_and_touches -- it uses only string comparison via bisect."""
    candles = generate_m1_series("2026-01-22 00:00:00", 500, seed=15)
    # A pool known deep into the series so the reference wastes a large, countable prefix.
    late_pool = make_pool(LiquiditySide.BUY_SIDE, 2402.0, candles[450].timestamp_close_utc)

    import research.v2.features.liquidity as liq_mod
    real_fromisoformat = datetime.fromisoformat

    call_count = {"n": 0}

    class _CountingDatetime(datetime):
        @classmethod
        def fromisoformat(cls, s):
            call_count["n"] += 1
            return real_fromisoformat(s)

    with mock.patch.object(liq_mod, "datetime", _CountingDatetime):
        call_count["n"] = 0
        _analyze_sweeps_and_touches_reference([late_pool], candles)
        reference_calls = call_count["n"]

        call_count["n"] = 0
        analyze_sweeps_and_touches([late_pool], candles)
        optimized_calls = call_count["n"]

    assert reference_calls == len(candles) + 1  # one parse per candle (wasted for ~450 of them) + the pool's own known_at
    assert optimized_calls == 0
    assert optimized_calls < reference_calls


def test_23_optimized_path_never_constructs_events_for_pre_known_at_candles():
    """A pool known only at the very last candle must never produce an event whose timestamp
    predates that candle -- proves the active/indexed scan genuinely starts at known_at, it does
    not merely suppress reporting after scanning everything."""
    candles = generate_m1_series("2026-01-23 00:00:00", 500, seed=16)
    pool = make_pool(LiquiditySide.SELL_SIDE, 2200.0, candles[-1].timestamp_close_utc)
    events = analyze_sweeps_and_touches([pool], candles)
    assert all(e.timestamp_utc == candles[-1].timestamp_close_utc for e in events)


# --- Prefix invariance carried through to the sweep/touch layer ------------------------------------

@pytest.mark.parametrize("cutoff", [40, 90, 150])
def test_24_prefix_invariance_through_sweep_layer(cutoff):
    full = generate_m1_series("2026-01-24 00:00:00", 200, seed=17)
    prefix = full[:cutoff]

    swings_full = detect_swings(full)
    swings_prefix = detect_swings(prefix)
    pools_full = swings_full + detect_equal_highs_lows(swings_full)
    pools_prefix = swings_prefix + detect_equal_highs_lows(swings_prefix)

    events_full = analyze_sweeps_and_touches(pools_full, full)
    events_prefix = analyze_sweeps_and_touches(pools_prefix, prefix)

    prefix_last_close = prefix[-1].timestamp_close_utc
    full_within_prefix_window = {
        (e.event_id, e.event_type, e.timestamp_utc) for e in events_full if e.timestamp_utc <= prefix_last_close
    }
    prefix_events = {(e.event_id, e.event_type, e.timestamp_utc) for e in events_prefix}
    assert prefix_events == full_within_prefix_window
