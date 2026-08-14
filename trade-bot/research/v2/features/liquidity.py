"""
NOAFVGBOT V2.3 — Liquidity Feature Intelligence Module.

Provides hindsight-free detection of swing highs/lows, equal highs/lows, PDH/PDL,
session high/low, and sweep/reclaim events across multi-timeframe candle datasets.

INVARIANTS:
- Zero hindsight leakage: A pool or event is visible if and only if known_at_timestamp <= as_of_utc.
- Swings require right-side confirmation candles before becoming known.
- PDH/PDL of day D-1 becomes observable at 00:00 UTC of day D.
- Sweeps are confirmed ONLY when price closes back inside the level.
- Observational research feature layer only (no trade authorization or strategy execution).
"""

import bisect
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from research.v2.data.models import CandleV2, Timeframe
from research.v2.core.thesis import ThesisEvidence, EvidenceType
from research.v2.features.models import FeatureRecord, FeaturePhase, compute_feature_id


class LiquiditySide(Enum):
    BUY_SIDE = "BUY_SIDE"
    SELL_SIDE = "SELL_SIDE"


class LiquidityType(Enum):
    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"
    EQUAL_HIGHS = "EQUAL_HIGHS"
    EQUAL_LOWS = "EQUAL_LOWS"
    PREVIOUS_DAY_HIGH = "PREVIOUS_DAY_HIGH"
    PREVIOUS_DAY_LOW = "PREVIOUS_DAY_LOW"
    SESSION_HIGH = "SESSION_HIGH"
    SESSION_LOW = "SESSION_LOW"


class LiquidityEventType(Enum):
    POOL_IDENTIFIED = "POOL_IDENTIFIED"
    TOUCH = "TOUCH"
    BREACH = "BREACH"
    SWEEP = "SWEEP"
    RECLAIM = "RECLAIM"


class PoolState(Enum):
    ACTIVE = "ACTIVE"
    TOUCHED = "TOUCHED"
    BREACHED = "BREACHED"
    SWEPT = "SWEPT"
    INVALIDATED = "INVALIDATED"


def compute_pool_id(
    liquidity_type: LiquidityType,
    side: LiquiditySide,
    price: float,
    source_timeframe: Timeframe,
    origin_timestamp: str,
) -> str:
    raw = f"{liquidity_type.value}|{side.value}|{price:.4f}|{source_timeframe.name}|{origin_timestamp}"
    return "lp_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def compute_event_id(
    pool_id: str,
    event_type: LiquidityEventType,
    timestamp_utc: str,
    price: float,
) -> str:
    raw = f"{pool_id}|{event_type.value}|{timestamp_utc}|{price:.4f}"
    return "lpe_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class LiquidityPool:
    pool_id: str
    liquidity_type: LiquidityType
    side: LiquiditySide
    price: float
    source_timeframe: Timeframe
    origin_timestamp: str
    known_at_timestamp: str
    member_count: int = 1
    source_ids: Tuple[str, ...] = ()
    state: PoolState = PoolState.ACTIVE
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError(f"Liquidity pool price must be positive, got: {self.price}")

        t_orig = datetime.fromisoformat(self.origin_timestamp).replace(tzinfo=timezone.utc)
        t_known = datetime.fromisoformat(self.known_at_timestamp).replace(tzinfo=timezone.utc)

        if t_known < t_orig:
            raise ValueError(f"known_at_timestamp ({self.known_at_timestamp}) cannot be < origin_timestamp ({self.origin_timestamp})")


@dataclass(frozen=True)
class LiquidityEvent:
    event_id: str
    pool_id: str
    event_type: LiquidityEventType
    timestamp_utc: str
    price_at_event: float
    breach_distance: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_thesis_evidence(self, thesis_id: str) -> ThesisEvidence:
        """Converts LiquidityEvent into immutable ThesisEvidence record."""
        return ThesisEvidence(
            evidence_id=f"ev_liq_{self.event_id}",
            thesis_id=thesis_id,
            timestamp_utc=self.timestamp_utc,
            timeframe=Timeframe[self.metadata.get("source_timeframe", "M30")],
            evidence_type=EvidenceType.M1_OBSERVATION,
            payload={
                "liquidity_event_id": self.event_id,
                "pool_id": self.pool_id,
                "event_type": self.event_type.value,
                "price_at_event": self.price_at_event,
                "breach_distance": self.breach_distance,
                **self.metadata,
            },
            source_candle_close_timestamp=self.timestamp_utc,
        )


def detect_swings(
    candles: List[CandleV2],
    left_bars: int = 2,
    right_bars: int = 2,
) -> List[LiquidityPool]:
    """
    Detects swing highs and swing lows deterministically without hindsight leakage.
    Swing at index i becomes observable ONLY at candle i + right_bars close time.
    """
    pools: List[LiquidityPool] = []
    n = len(candles)

    for i in range(left_bars, n - right_bars):
        c_target = candles[i]
        tf = c_target.timeframe

        # Check Swing High
        is_swing_high = True
        for l in range(1, left_bars + 1):
            if candles[i - l].high >= c_target.high:
                is_swing_high = False
                break
        for r in range(1, right_bars + 1):
            if candles[i + r].high > c_target.high:
                is_swing_high = False
                break

        if is_swing_high:
            origin_ts = c_target.timestamp_close_utc
            known_ts = candles[i + right_bars].timestamp_close_utc
            pid = compute_pool_id(LiquidityType.SWING_HIGH, LiquiditySide.BUY_SIDE, c_target.high, tf, origin_ts)
            pools.append(
                LiquidityPool(
                    pool_id=pid,
                    liquidity_type=LiquidityType.SWING_HIGH,
                    side=LiquiditySide.BUY_SIDE,
                    price=c_target.high,
                    source_timeframe=tf,
                    origin_timestamp=origin_ts,
                    known_at_timestamp=known_ts,
                )
            )

        # Check Swing Low
        is_swing_low = True
        for l in range(1, left_bars + 1):
            if candles[i - l].low <= c_target.low:
                is_swing_low = False
                break
        for r in range(1, right_bars + 1):
            if candles[i + r].low < c_target.low:
                is_swing_low = False
                break

        if is_swing_low:
            origin_ts = c_target.timestamp_close_utc
            known_ts = candles[i + right_bars].timestamp_close_utc
            pid = compute_pool_id(LiquidityType.SWING_LOW, LiquiditySide.SELL_SIDE, c_target.low, tf, origin_ts)
            pools.append(
                LiquidityPool(
                    pool_id=pid,
                    liquidity_type=LiquidityType.SWING_LOW,
                    side=LiquiditySide.SELL_SIDE,
                    price=c_target.low,
                    source_timeframe=tf,
                    origin_timestamp=origin_ts,
                    known_at_timestamp=known_ts,
                )
            )

    return pools


def detect_equal_highs_lows(
    pools: List[LiquidityPool],
    tolerance_pts: float = 0.50,
) -> List[LiquidityPool]:
    """Clusters swing pools into Equal Highs or Equal Lows within price tolerance."""
    eq_pools: List[LiquidityPool] = []
    
    by_side: Dict[LiquiditySide, List[LiquidityPool]] = {LiquiditySide.BUY_SIDE: [], LiquiditySide.SELL_SIDE: []}
    for p in pools:
        if p.liquidity_type in (LiquidityType.SWING_HIGH, LiquidityType.SWING_LOW):
            by_side[p.side].append(p)

    for side, side_pools in by_side.items():
        sorted_pools = sorted(side_pools, key=lambda p: p.known_at_timestamp)
        visited = set()

        for i in range(len(sorted_pools)):
            if sorted_pools[i].pool_id in visited:
                continue

            cluster = [sorted_pools[i]]
            for j in range(i + 1, len(sorted_pools)):
                if abs(sorted_pools[j].price - sorted_pools[i].price) <= tolerance_pts:
                    cluster.append(sorted_pools[j])

            if len(cluster) >= 2:
                for item in cluster:
                    visited.add(item.pool_id)

                avg_price = sum(c.price for c in cluster) / len(cluster)
                orig_ts = min(c.origin_timestamp for c in cluster)
                known_ts = max(c.known_at_timestamp for c in cluster)
                ltype = LiquidityType.EQUAL_HIGHS if side == LiquiditySide.BUY_SIDE else LiquidityType.EQUAL_LOWS
                tf = cluster[0].source_timeframe

                pid = compute_pool_id(ltype, side, avg_price, tf, orig_ts)
                eq_pools.append(
                    LiquidityPool(
                        pool_id=pid,
                        liquidity_type=ltype,
                        side=side,
                        price=avg_price,
                        source_timeframe=tf,
                        origin_timestamp=orig_ts,
                        known_at_timestamp=known_ts,
                        member_count=len(cluster),
                        source_ids=tuple(c.pool_id for c in cluster),
                    )
                )

    return eq_pools


def detect_pdh_pdl(candles: List[CandleV2]) -> List[LiquidityPool]:
    """Calculates PDH/PDL from completed UTC days. Day D-1 high/low becomes observable at 00:00 UTC Day D."""
    pools: List[LiquidityPool] = []
    days: Dict[str, List[CandleV2]] = {}

    for c in candles:
        dt = datetime.fromisoformat(c.timestamp_open_utc).replace(tzinfo=timezone.utc)
        day_str = dt.strftime("%Y-%m-%d")
        if day_str not in days:
            days[day_str] = []
        days[day_str].append(c)

    sorted_days = sorted(days.keys())
    for idx in range(1, len(sorted_days)):
        prev_day = sorted_days[idx - 1]
        curr_day = sorted_days[idx]

        day_candles = days[prev_day]
        pdh = max(c.high for c in day_candles)
        pdl = min(c.low for c in day_candles)

        orig_ts = day_candles[-1].timestamp_close_utc
        known_ts = f"{curr_day} 00:00:00"

        tf = day_candles[0].timeframe

        pid_h = compute_pool_id(LiquidityType.PREVIOUS_DAY_HIGH, LiquiditySide.BUY_SIDE, pdh, tf, orig_ts)
        pools.append(
            LiquidityPool(
                pool_id=pid_h,
                liquidity_type=LiquidityType.PREVIOUS_DAY_HIGH,
                side=LiquiditySide.BUY_SIDE,
                price=pdh,
                source_timeframe=tf,
                origin_timestamp=orig_ts,
                known_at_timestamp=known_ts,
                metadata={"day": prev_day},
            )
        )

        pid_l = compute_pool_id(LiquidityType.PREVIOUS_DAY_LOW, LiquiditySide.SELL_SIDE, pdl, tf, orig_ts)
        pools.append(
            LiquidityPool(
                pool_id=pid_l,
                liquidity_type=LiquidityType.PREVIOUS_DAY_LOW,
                side=LiquiditySide.SELL_SIDE,
                price=pdl,
                source_timeframe=tf,
                origin_timestamp=orig_ts,
                known_at_timestamp=known_ts,
                metadata={"day": prev_day},
            )
        )

    return pools


@dataclass(frozen=True)
class SessionDefinition:
    name: str
    start_time_utc: str  # "HH:MM:SS"
    end_time_utc: str    # "HH:MM:SS"


def detect_session_high_low(
    candles: List[CandleV2],
    session_def: SessionDefinition,
) -> List[LiquidityPool]:
    """Calculates Session High and Session Low. Final level is observable ONLY after session closes."""
    pools: List[LiquidityPool] = []
    current_session_candles: List[CandleV2] = []
    in_session = False
    session_date = ""

    for c in candles:
        dt = datetime.fromisoformat(c.timestamp_open_utc).replace(tzinfo=timezone.utc)
        time_str = dt.strftime("%H:%M:%S")
        date_str = dt.strftime("%Y-%m-%d")

        if time_str == session_def.start_time_utc:
            in_session = True
            current_session_candles = [c]
            session_date = date_str
        elif in_session:
            current_session_candles.append(c)
            if time_str == session_def.end_time_utc or c.timestamp_close_utc.endswith(session_def.end_time_utc):
                in_session = False
                sh = max(sc.high for sc in current_session_candles)
                sl = min(sc.low for sc in current_session_candles)

                orig_ts = current_session_candles[-1].timestamp_close_utc
                known_ts = orig_ts
                tf = current_session_candles[0].timeframe

                pid_h = compute_pool_id(LiquidityType.SESSION_HIGH, LiquiditySide.BUY_SIDE, sh, tf, orig_ts)
                pools.append(
                    LiquidityPool(
                        pool_id=pid_h,
                        liquidity_type=LiquidityType.SESSION_HIGH,
                        side=LiquiditySide.BUY_SIDE,
                        price=sh,
                        source_timeframe=tf,
                        origin_timestamp=orig_ts,
                        known_at_timestamp=known_ts,
                        metadata={"session": session_def.name, "date": session_date},
                    )
                )

                pid_l = compute_pool_id(LiquidityType.SESSION_LOW, LiquiditySide.SELL_SIDE, sl, tf, orig_ts)
                pools.append(
                    LiquidityPool(
                        pool_id=pid_l,
                        liquidity_type=LiquidityType.SESSION_LOW,
                        side=LiquiditySide.SELL_SIDE,
                        price=sl,
                        source_timeframe=tf,
                        origin_timestamp=orig_ts,
                        known_at_timestamp=known_ts,
                        metadata={"session": session_def.name, "date": session_date},
                    )
                )

    return pools


def _analyze_sweeps_and_touches_reference(
    pools: List[LiquidityPool],
    candles: List[CandleV2],
) -> List[LiquidityEvent]:
    """V2.10C.1 -- REFERENCE ORACLE, retained verbatim (byte-identical logic to the pre-V2.10C.1
    implementation) for parity testing only. NOT used in the production hot path -- see
    analyze_sweeps_and_touches() below for the optimized implementation this is checked against.
    Deliberately kept simple/obviously-correct even though it is O(pools x candles) with
    per-pair datetime parsing, so it can serve as ground truth for tests/test_v2_10c1_liquidity_scaling.py.
    """
    events: List[LiquidityEvent] = []

    for pool in pools:
        p_known = datetime.fromisoformat(pool.known_at_timestamp).replace(tzinfo=timezone.utc)
        is_breached = False

        for c in candles:
            c_close_dt = datetime.fromisoformat(c.timestamp_close_utc).replace(tzinfo=timezone.utc)
            if c_close_dt < p_known:
                continue

            # Touch Check
            if pool.side == LiquiditySide.BUY_SIDE and c.high >= pool.price and not is_breached:
                eid = compute_event_id(pool.pool_id, LiquidityEventType.TOUCH, c.timestamp_close_utc, c.high)
                events.append(
                    LiquidityEvent(
                        event_id=eid,
                        pool_id=pool.pool_id,
                        event_type=LiquidityEventType.TOUCH,
                        timestamp_utc=c.timestamp_close_utc,
                        price_at_event=c.high,
                        metadata={"source_timeframe": c.timeframe.name},
                    )
                )

            elif pool.side == LiquiditySide.SELL_SIDE and c.low <= pool.price and not is_breached:
                eid = compute_event_id(pool.pool_id, LiquidityEventType.TOUCH, c.timestamp_close_utc, c.low)
                events.append(
                    LiquidityEvent(
                        event_id=eid,
                        pool_id=pool.pool_id,
                        event_type=LiquidityEventType.TOUCH,
                        timestamp_utc=c.timestamp_close_utc,
                        price_at_event=c.low,
                        metadata={"source_timeframe": c.timeframe.name},
                    )
                )

            # Breach & Sweep Check
            if pool.side == LiquiditySide.BUY_SIDE and c.high > pool.price:
                is_breached = True
                breach_dist = c.high - pool.price
                eid_b = compute_event_id(pool.pool_id, LiquidityEventType.BREACH, c.timestamp_close_utc, c.high)
                events.append(
                    LiquidityEvent(
                        event_id=eid_b,
                        pool_id=pool.pool_id,
                        event_type=LiquidityEventType.BREACH,
                        timestamp_utc=c.timestamp_close_utc,
                        price_at_event=c.high,
                        breach_distance=breach_dist,
                        metadata={"source_timeframe": c.timeframe.name},
                    )
                )

                # Reclaim check: Candle closes back below buy-side level
                if c.close < pool.price:
                    eid_s = compute_event_id(pool.pool_id, LiquidityEventType.SWEEP, c.timestamp_close_utc, c.close)
                    events.append(
                        LiquidityEvent(
                            event_id=eid_s,
                            pool_id=pool.pool_id,
                            event_type=LiquidityEventType.SWEEP,
                            timestamp_utc=c.timestamp_close_utc,
                            price_at_event=c.close,
                            breach_distance=breach_dist,
                            metadata={"source_timeframe": c.timeframe.name, "reclaim": True},
                        )
                    )

            elif pool.side == LiquiditySide.SELL_SIDE and c.low < pool.price:
                is_breached = True
                breach_dist = pool.price - c.low
                eid_b = compute_event_id(pool.pool_id, LiquidityEventType.BREACH, c.timestamp_close_utc, c.low)
                events.append(
                    LiquidityEvent(
                        event_id=eid_b,
                        pool_id=pool.pool_id,
                        event_type=LiquidityEventType.BREACH,
                        timestamp_utc=c.timestamp_close_utc,
                        price_at_event=c.low,
                        breach_distance=breach_dist,
                        metadata={"source_timeframe": c.timeframe.name},
                    )
                )

                # Reclaim check: Candle closes back above sell-side level
                if c.close > pool.price:
                    eid_s = compute_event_id(pool.pool_id, LiquidityEventType.SWEEP, c.timestamp_close_utc, c.close)
                    events.append(
                        LiquidityEvent(
                            event_id=eid_s,
                            pool_id=pool.pool_id,
                            event_type=LiquidityEventType.SWEEP,
                            timestamp_utc=c.timestamp_close_utc,
                            price_at_event=c.close,
                            breach_distance=breach_dist,
                            metadata={"source_timeframe": c.timeframe.name, "reclaim": True},
                        )
                    )

    return events


def analyze_sweeps_and_touches(
    pools: List[LiquidityPool],
    candles: List[CandleV2],
) -> List[LiquidityEvent]:
    """Analyzes price candles against active liquidity pools to detect Touch, Breach, and
    Sweep/Reclaim events.

    V2.10C.1 -- PERFORMANCE ONLY, semantics-preserving. Produces byte-identical output (same
    event_ids, timestamps, known_at semantics, ordering) to _analyze_sweeps_and_touches_reference
    above -- see tests/test_v2_10c1_liquidity_scaling.py for the parity matrix this is checked
    against on every commit.

    What changed and why it's safe:
    - The reference re-parses EVERY candle's timestamp with datetime.fromisoformat() for EVERY
      pool just to find/skip the region before known_at_timestamp -- O(pools x candles) parsing
      that is pure waste for the (typically roughly half, on average) candles before a pool's
      known_at. `candles` is always a single timeframe's chronologically-ordered series (the
      same precondition detect_swings already relies on positionally), and every timestamp in
      this codebase is generated via strftime("%Y-%m-%d %H:%M:%S") -- a fixed-width, zero-padded
      format whose lexicographic string order is identical to chronological order. That makes
      `close_ts` (extracted once, not per pool) a valid bisect.bisect_left() target: the first
      index with close_ts[idx] >= pool.known_at_timestamp is EXACTLY the first candle the
      reference loop does not `continue` past -- no datetime parsing needed to find it, and no
      candle before it is ever inspected (same "ignore pre-known_at candles" semantics).
    - `pool.side`, `pool.price`, `pool.pool_id` are pool-invariant; the reference re-reads them
      (and re-evaluates the enum equality) on every candle. Hoisting them to locals once per
      pool, and branching once on `is_buy` instead of re-comparing `pool.side == ...` in both
      the touch-check and the breach-check, is a pure micro-optimization -- the two branches'
      bodies still fire under EXACTLY the reference's conditions, in the same order (touch-check
      before breach/sweep-check, matching the reference's `if` block order).
    - BREACH/SWEEP are NOT semantically capped here (deliberately -- the reference lets both
      re-fire on every subsequent candle that still satisfies the raw price condition, forever,
      once is_breached is True; only TOUCH is gated by `not is_breached`). This optimization does
      not change that -- doing so would be a semantics change, out of scope for this phase. It is
      the reason total event volume (and therefore total runtime) remains superlinear in candle
      count even after this fix: see SCALING notes in the V2.10C.1 closure report.
    """
    events: List[LiquidityEvent] = []
    n = len(candles)
    if not pools or n == 0:
        return events

    close_ts = [c.timestamp_close_utc for c in candles]

    for pool in pools:
        start_idx = bisect.bisect_left(close_ts, pool.known_at_timestamp)
        if start_idx >= n:
            continue

        is_buy = pool.side == LiquiditySide.BUY_SIDE
        pool_price = pool.price
        pool_id = pool.pool_id
        is_breached = False

        for idx in range(start_idx, n):
            c = candles[idx]
            c_ts = close_ts[idx]

            if is_buy:
                if c.high >= pool_price and not is_breached:
                    eid = compute_event_id(pool_id, LiquidityEventType.TOUCH, c_ts, c.high)
                    events.append(
                        LiquidityEvent(
                            event_id=eid,
                            pool_id=pool_id,
                            event_type=LiquidityEventType.TOUCH,
                            timestamp_utc=c_ts,
                            price_at_event=c.high,
                            metadata={"source_timeframe": c.timeframe.name},
                        )
                    )

                if c.high > pool_price:
                    is_breached = True
                    breach_dist = c.high - pool_price
                    eid_b = compute_event_id(pool_id, LiquidityEventType.BREACH, c_ts, c.high)
                    events.append(
                        LiquidityEvent(
                            event_id=eid_b,
                            pool_id=pool_id,
                            event_type=LiquidityEventType.BREACH,
                            timestamp_utc=c_ts,
                            price_at_event=c.high,
                            breach_distance=breach_dist,
                            metadata={"source_timeframe": c.timeframe.name},
                        )
                    )

                    if c.close < pool_price:
                        eid_s = compute_event_id(pool_id, LiquidityEventType.SWEEP, c_ts, c.close)
                        events.append(
                            LiquidityEvent(
                                event_id=eid_s,
                                pool_id=pool_id,
                                event_type=LiquidityEventType.SWEEP,
                                timestamp_utc=c_ts,
                                price_at_event=c.close,
                                breach_distance=breach_dist,
                                metadata={"source_timeframe": c.timeframe.name, "reclaim": True},
                            )
                        )

            else:
                if c.low <= pool_price and not is_breached:
                    eid = compute_event_id(pool_id, LiquidityEventType.TOUCH, c_ts, c.low)
                    events.append(
                        LiquidityEvent(
                            event_id=eid,
                            pool_id=pool_id,
                            event_type=LiquidityEventType.TOUCH,
                            timestamp_utc=c_ts,
                            price_at_event=c.low,
                            metadata={"source_timeframe": c.timeframe.name},
                        )
                    )

                if c.low < pool_price:
                    is_breached = True
                    breach_dist = pool_price - c.low
                    eid_b = compute_event_id(pool_id, LiquidityEventType.BREACH, c_ts, c.low)
                    events.append(
                        LiquidityEvent(
                            event_id=eid_b,
                            pool_id=pool_id,
                            event_type=LiquidityEventType.BREACH,
                            timestamp_utc=c_ts,
                            price_at_event=c.low,
                            breach_distance=breach_dist,
                            metadata={"source_timeframe": c.timeframe.name},
                        )
                    )

                    if c.close > pool_price:
                        eid_s = compute_event_id(pool_id, LiquidityEventType.SWEEP, c_ts, c.close)
                        events.append(
                            LiquidityEvent(
                                event_id=eid_s,
                                pool_id=pool_id,
                                event_type=LiquidityEventType.SWEEP,
                                timestamp_utc=c_ts,
                                price_at_event=c.close,
                                breach_distance=breach_dist,
                                metadata={"source_timeframe": c.timeframe.name, "reclaim": True},
                            )
                        )

    return events


def active_pools_as_of(pools: List[LiquidityPool], as_of_utc: str) -> List[LiquidityPool]:
    """Filters pools so ONLY pools observable as of as_of_utc are returned."""
    t_as_of = datetime.fromisoformat(as_of_utc).replace(tzinfo=timezone.utc)
    res = []
    for p in pools:
        t_known = datetime.fromisoformat(p.known_at_timestamp).replace(tzinfo=timezone.utc)
        if t_known <= t_as_of:
            res.append(p)
    return res


def extract_liquidity_event_features(event: LiquidityEvent, pool: LiquidityPool) -> FeatureRecord:
    """Thin adapter: wraps a LiquidityEvent (TOUCH/BREACH/SWEEP/RECLAIM) as a decision-time
    FeatureRecord so it can flow through the existing generic FeatureRecord contract into
    DecisionSnapshot.feature_records, without inventing new sweep-detection logic. The event
    fires exactly at the evaluated candle's close, so known_at_timestamp == timestamp_utc."""
    tf = Timeframe[event.metadata["source_timeframe"]] if "source_timeframe" in event.metadata else pool.source_timeframe

    values: Dict[str, Any] = {
        "event_type": event.event_type.value,
        "pool_liquidity_type": pool.liquidity_type.value,
        "pool_side": pool.side.value,
        "pool_price": pool.price,
        "price_at_event": event.price_at_event,
        "breach_distance": event.breach_distance,
    }

    return FeatureRecord(
        feature_id=compute_feature_id("LIQUIDITY_SWEEP_EVENT", event.event_id, tf, event.timestamp_utc),
        feature_type="LIQUIDITY_SWEEP_EVENT",
        source_object_id=event.pool_id,
        source_timeframe=tf,
        timestamp_utc=event.timestamp_utc,
        known_at_timestamp=event.timestamp_utc,
        phase=FeaturePhase.DECISION_TIME,
        values=values,
        provenance={"pool_id": event.pool_id, "event_type": event.event_type.value},
    )


def distance_to_nearest_pool(
    pools: List[LiquidityPool],
    current_price: float,
    side: LiquiditySide,
    as_of_utc: str,
) -> Optional[float]:
    """Calculates absolute price distance to nearest active pool on given side."""
    visible = active_pools_as_of(pools, as_of_utc)
    matching = [p for p in visible if p.side == side]
    if not matching:
        return None
    return min(abs(p.price - current_price) for p in matching)
