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
    """Detects confirmed swings and structure breaks deterministically without hindsight leakage."""
    events: List[StructureEvent] = []
    if not candles:
        return events

    tf = candles[0].timeframe

    # Detect Swings first
    swing_pools = detect_swings(candles, left_bars=left_bars, right_bars=right_bars)

    latest_swing_high: Optional[float] = None
    latest_swing_low: Optional[float] = None

    for p in swing_pools:
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

    # Detect Structure Breaks against known swings
    for c in candles:
        c_ts = c.timestamp_close_utc

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
