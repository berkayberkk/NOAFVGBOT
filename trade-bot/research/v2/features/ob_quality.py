"""
NOAFVGBOT V2.4 — Order Block Raw Feature Extraction Module.

Provides hindsight-safe detection and raw feature extraction for Order Blocks (OBs).

INVARIANTS:
- Order Block becomes observable ONLY when confirming impulse candle closes (known_at_timestamp = impulse_c.close_utc).
- No arbitrary quality scores, weights, or trade authorizations.
- Missing ATR context returns None for zone_width_to_atr.
- Mitigation features use ONLY candles closed at or before as_of_utc.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Dict, List, Optional

from research.v2.data.models import CandleV2, Timeframe
from research.v2.core.thesis import ThesisDirection
from research.v2.features.models import (
    FeatureRecord,
    FeaturePhase,
    compute_feature_id,
)


class OBState(Enum):
    OPEN = "OPEN"
    TOUCHED = "TOUCHED"
    MITIGATED = "MITIGATED"
    INVALIDATED = "INVALIDATED"


def compute_ob_id(
    direction: ThesisDirection,
    source_timeframe: Timeframe,
    zone_low: float,
    zone_high: float,
    source_c_ts: str,
    impulse_c_ts: str,
) -> str:
    raw = f"{direction.value}|{source_timeframe.name}|{zone_low:.4f}|{zone_high:.4f}|{source_c_ts}|{impulse_c_ts}"
    return "ob_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class OrderBlockV2:
    ob_id: str
    direction: ThesisDirection
    source_timeframe: Timeframe
    created_at: str
    known_at_timestamp: str
    zone_low: float
    zone_high: float
    source_c_ts: str
    impulse_c_ts: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.zone_low >= self.zone_high:
            raise ValueError(f"OB zone_low ({self.zone_low}) must be < zone_high ({self.zone_high})")


def detect_order_blocks(candles: List[CandleV2]) -> List[OrderBlockV2]:
    """Detects Order Blocks deterministically from candle sequences."""
    obs: List[OrderBlockV2] = []
    if len(candles) < 2:
        return obs

    for i in range(len(candles) - 1):
        c_src, c_imp = candles[i], candles[i + 1]
        tf = c_src.timeframe
        known_ts = c_imp.timestamp_close_utc

        # Bullish OB: Bearish source candle followed by strong bullish impulse
        if c_src.close < c_src.open and c_imp.close > c_imp.open and c_imp.close > c_src.high:
            z_low = c_src.low
            z_high = c_src.high
            oid = compute_ob_id(ThesisDirection.LONG, tf, z_low, z_high, c_src.timestamp_close_utc, c_imp.timestamp_close_utc)
            obs.append(
                OrderBlockV2(
                    ob_id=oid,
                    direction=ThesisDirection.LONG,
                    source_timeframe=tf,
                    created_at=c_imp.timestamp_close_utc,
                    known_at_timestamp=known_ts,
                    zone_low=z_low,
                    zone_high=z_high,
                    source_c_ts=c_src.timestamp_close_utc,
                    impulse_c_ts=c_imp.timestamp_close_utc,
                )
            )

        # Bearish OB: Bullish source candle followed by strong bearish impulse
        elif c_src.close > c_src.open and c_imp.close < c_imp.open and c_imp.close < c_src.low:
            z_low = c_src.low
            z_high = c_src.high
            oid = compute_ob_id(ThesisDirection.SHORT, tf, z_low, z_high, c_src.timestamp_close_utc, c_imp.timestamp_close_utc)
            obs.append(
                OrderBlockV2(
                    ob_id=oid,
                    direction=ThesisDirection.SHORT,
                    source_timeframe=tf,
                    created_at=c_imp.timestamp_close_utc,
                    known_at_timestamp=known_ts,
                    zone_low=z_low,
                    zone_high=z_high,
                    source_c_ts=c_src.timestamp_close_utc,
                    impulse_c_ts=c_imp.timestamp_close_utc,
                )
            )

    return obs


def extract_ob_features(
    ob: OrderBlockV2,
    source_c: CandleV2,
    impulse_c: CandleV2,
    atr: Optional[float] = None,
    as_of_candles: Optional[List[CandleV2]] = None,
    as_of_utc: Optional[str] = None,
) -> FeatureRecord:
    """Extracts raw decision-time and optional post-event mitigation features for an Order Block."""
    zone_w = ob.zone_high - ob.zone_low
    src_range = source_c.high - source_c.low
    src_body = abs(source_c.close - source_c.open)
    src_body_ratio = (src_body / src_range) if src_range > 1e-9 else None

    imp_range = impulse_c.high - impulse_c.low
    imp_body = abs(impulse_c.close - impulse_c.open)

    disp_dist = abs(impulse_c.close - source_c.close)
    zone_w_atr = (zone_w / atr) if (atr is not None and atr > 0) else None

    values: Dict[str, Any] = {
        "zone_width": zone_w,
        "zone_width_to_atr": zone_w_atr,
        "source_candle_range": src_range,
        "source_candle_body": src_body,
        "source_body_to_range": src_body_ratio,
        "impulse_range": imp_range,
        "impulse_body": imp_body,
        "displacement_distance": disp_dist,
    }

    phase = FeaturePhase.DECISION_TIME
    if as_of_candles and as_of_utc:
        phase = FeaturePhase.POST_EVENT
        t_limit = datetime.fromisoformat(as_of_utc).replace(tzinfo=timezone.utc)
        eval_candles = [
            c for c in as_of_candles
            if datetime.fromisoformat(c.timestamp_close_utc).replace(tzinfo=timezone.utc) <= t_limit
            and datetime.fromisoformat(c.timestamp_close_utc).replace(tzinfo=timezone.utc) > datetime.fromisoformat(ob.known_at_timestamp).replace(tzinfo=timezone.utc)
        ]

        mitigation_count = 0
        max_depth = 0.0
        ob_state = OBState.OPEN

        for c in eval_candles:
            if ob.direction == ThesisDirection.LONG:
                if c.low <= ob.zone_high:
                    mitigation_count += 1
                    depth = ob.zone_high - min(c.low, ob.zone_high)
                    max_depth = max(max_depth, depth)
                    if c.low <= ob.zone_low:
                        ob_state = OBState.INVALIDATED
                    else:
                        ob_state = OBState.TOUCHED
            else:  # SHORT
                if c.high >= ob.zone_low:
                    mitigation_count += 1
                    depth = max(c.high, ob.zone_low) - ob.zone_low
                    max_depth = max(max_depth, depth)
                    if c.high >= ob.zone_high:
                        ob_state = OBState.INVALIDATED
                    else:
                        ob_state = OBState.TOUCHED

        mit_pct = min(1.0, max_depth / zone_w) if zone_w > 0 else 0.0

        values.update({
            "mitigation_count": mitigation_count,
            "max_mitigation_depth": max_depth,
            "mitigation_depth_pct": mit_pct,
            "ob_state": ob_state.value,
        })

    fid = compute_feature_id("OB_RAW_FEATURES", ob.ob_id, ob.source_timeframe, ob.known_at_timestamp)

    return FeatureRecord(
        feature_id=fid,
        feature_type="OB_RAW_FEATURES",
        source_object_id=ob.ob_id,
        source_timeframe=ob.source_timeframe,
        timestamp_utc=ob.created_at,
        known_at_timestamp=as_of_utc or ob.known_at_timestamp,
        phase=phase,
        values=values,
        provenance={"ob_id": ob.ob_id, "direction": ob.direction.value},
    )
