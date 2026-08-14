"""
NOAFVGBOT V2.4 — Market Structure Feature Extraction Module.

Provides hindsight-safe detection of confirmed swings and market structure breaks (BOS).

INVARIANTS:
- Swings become observable ONLY after right_bars confirmation candles close.
- Structure breaks become observable ONLY when breaching candle closes (or wicks beyond).
- Zero hindsight leakage: known_at_timestamp explicitly recorded.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Dict, List, Optional

from research.v2.data.models import CandleV2, Timeframe
from research.v2.features.liquidity import detect_swings, LiquiditySide, LiquidityType
from research.v2.features.models import FeatureRecord, FeaturePhase


class StructureEventType(Enum):
    SWING_HIGH_CONFIRMED = "SWING_HIGH_CONFIRMED"
    SWING_LOW_CONFIRMED = "SWING_LOW_CONFIRMED"
    STRUCTURE_BREAK_UP = "STRUCTURE_BREAK_UP"
    STRUCTURE_BREAK_DOWN = "STRUCTURE_BREAK_DOWN"


def compute_structure_event_id(
    event_type: StructureEventType,
    timeframe: Timeframe,
    timestamp_utc: str,
    price: float,
) -> str:
    raw = f"{event_type.value}|{timeframe.name}|{timestamp_utc}|{price:.4f}"
    return "se_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class StructureEvent:
    event_id: str
    event_type: StructureEventType
    timestamp_utc: str
    known_at_timestamp: str
    price: float
    timeframe: Timeframe
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError(f"StructureEvent price must be positive, got: {self.price}")


def detect_structure_events(
    candles: List[CandleV2],
    left_bars: int = 2,
    right_bars: int = 2,
) -> List[StructureEvent]:
    """Detects confirmed swings and structure breaks deterministically without hindsight leakage.

    V2.10C causality fix: structure-break detection must compare each candle's close only
    against the swing level that was ALREADY confirmed (known_at_timestamp <= that candle's
    close) at that point in time, updating progressively as new swings are confirmed and
    resetting after a break -- exactly as this module's own docstring already promised
    ("Structure breaks become observable ONLY when breaching candle closes... Zero hindsight
    leakage"). The previous implementation computed swings across the FULL candle history
    first, then tested EVERY candle in the array against whichever swing happened to be last
    in the entire dataset -- a full-history lookahead bug that let a swing confirmed near the
    end of the data retroactively "break" candles from near the start. This fix is a
    semantics-preserving correctness fix (same swing/break definitions, same event fields,
    same known_at_timestamp semantics per swing) -- not a redesign of structure rules.
    """
    events: List[StructureEvent] = []
    if not candles:
        return events

    tf = candles[0].timeframe

    # Detect Swings first (each swing already carries its own correct, delayed
    # known_at_timestamp = candles[i + right_bars].close -- see detect_swings).
    swing_pools = detect_swings(candles, left_bars=left_bars, right_bars=right_bars)

    # Index swings by the candle close timestamp at which they become knowable, so they can
    # be released into the break-scan in strict chronological (causal) order.
    swings_by_known_at: Dict[str, List] = {}
    for p in swing_pools:
        swings_by_known_at.setdefault(p.known_at_timestamp, []).append(p)

    latest_swing_high: Optional[float] = None
    latest_swing_low: Optional[float] = None

    # Single chronological pass: release any swings that became known AT this candle's close
    # BEFORE testing that same candle for a break, then test breaks using only
    # already-known swing levels.
    for c in candles:
        c_ts = c.timestamp_close_utc

        for p in swings_by_known_at.get(c_ts, []):
            if p.liquidity_type == LiquidityType.SWING_HIGH:
                eid = compute_structure_event_id(StructureEventType.SWING_HIGH_CONFIRMED, tf, p.origin_timestamp, p.price)
                events.append(
                    StructureEvent(
                        event_id=eid,
                        event_type=StructureEventType.SWING_HIGH_CONFIRMED,
                        timestamp_utc=p.origin_timestamp,
                        known_at_timestamp=p.known_at_timestamp,
                        price=p.price,
                        timeframe=tf,
                    )
                )
                latest_swing_high = p.price
            elif p.liquidity_type == LiquidityType.SWING_LOW:
                eid = compute_structure_event_id(StructureEventType.SWING_LOW_CONFIRMED, tf, p.origin_timestamp, p.price)
                events.append(
                    StructureEvent(
                        event_id=eid,
                        event_type=StructureEventType.SWING_LOW_CONFIRMED,
                        timestamp_utc=p.origin_timestamp,
                        known_at_timestamp=p.known_at_timestamp,
                        price=p.price,
                        timeframe=tf,
                    )
                )
                latest_swing_low = p.price

        if latest_swing_high is not None and c.close > latest_swing_high:
            eid = compute_structure_event_id(StructureEventType.STRUCTURE_BREAK_UP, tf, c_ts, c.close)
            events.append(
                StructureEvent(
                    event_id=eid,
                    event_type=StructureEventType.STRUCTURE_BREAK_UP,
                    timestamp_utc=c_ts,
                    known_at_timestamp=c_ts,
                    price=c.close,
                    timeframe=tf,
                    metadata={"broken_level": latest_swing_high, "breach_type": "CLOSE_BREACH"},
                )
            )
            latest_swing_high = None  # Reset after break

        if latest_swing_low is not None and c.close < latest_swing_low:
            eid = compute_structure_event_id(StructureEventType.STRUCTURE_BREAK_DOWN, tf, c_ts, c.close)
            events.append(
                StructureEvent(
                    event_id=eid,
                    event_type=StructureEventType.STRUCTURE_BREAK_DOWN,
                    timestamp_utc=c_ts,
                    known_at_timestamp=c_ts,
                    price=c.close,
                    timeframe=tf,
                    metadata={"broken_level": latest_swing_low, "breach_type": "CLOSE_BREACH"},
                )
            )
            latest_swing_low = None  # Reset after break

    return events


def compute_structure_feature_id(event: StructureEvent) -> str:
    raw = f"STRUCTURE_EVENT|{event.event_id}|{event.timeframe.name}|{event.known_at_timestamp}"
    return "feat_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def extract_structure_features(event: StructureEvent) -> FeatureRecord:
    """Thin adapter: wraps a StructureEvent as a decision-time FeatureRecord so it can flow
    into DecisionSnapshot.feature_records / the research dataset builder through the existing
    generic FeatureRecord contract, without inventing any new structure-detection logic."""
    values: Dict[str, Any] = {
        "event_type": event.event_type.value,
        "price": event.price,
        "broken_level": event.metadata.get("broken_level"),
    }

    return FeatureRecord(
        feature_id=compute_structure_feature_id(event),
        feature_type="STRUCTURE_EVENT",
        source_object_id=event.event_id,
        source_timeframe=event.timeframe,
        timestamp_utc=event.timestamp_utc,
        known_at_timestamp=event.known_at_timestamp,
        phase=FeaturePhase.DECISION_TIME,
        values=values,
        provenance={"event_type": event.event_type.value},
    )
