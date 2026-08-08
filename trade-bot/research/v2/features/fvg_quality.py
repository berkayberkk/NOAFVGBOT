"""
NOAFVGBOT V2.4 — Fair Value Gap Raw Feature Extraction Module.

Provides hindsight-safe detection and raw feature extraction for Fair Value Gaps (FVGs).

INVARIANTS:
- 3-candle FVG becomes observable ONLY when the third candle closes (known_at_timestamp = c3.close_utc).
- No arbitrary quality scores, weights, or trade authorizations.
- Missing ATR context returns None for gap_to_atr_ratio (never zero).
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


class FVGState(Enum):
    OPEN = "OPEN"
    PARTIALLY_MITIGATED = "PARTIALLY_MITIGATED"
    FULLY_MITIGATED = "FULLY_MITIGATED"
    INVALIDATED = "INVALIDATED"


def compute_fvg_id(
    direction: ThesisDirection,
    source_timeframe: Timeframe,
    bottom: float,
    top: float,
    c1_ts: str,
    c3_ts: str,
) -> str:
    raw = f"{direction.value}|{source_timeframe.name}|{bottom:.4f}|{top:.4f}|{c1_ts}|{c3_ts}"
    return "fvg_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class FairValueGapV2:
    fvg_id: str
    direction: ThesisDirection
    source_timeframe: Timeframe
    created_at: str
    known_at_timestamp: str
    bottom: float
    top: float
    gap_size: float
    c1_ts: str
    c2_ts: str
    c3_ts: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.gap_size <= 0:
            raise ValueError(f"FVG gap_size must be positive (> 0), got: {self.gap_size}")
        if self.bottom >= self.top:
            raise ValueError(f"FVG bottom ({self.bottom}) must be < top ({self.top})")


def detect_fvgs(candles: List[CandleV2]) -> List[FairValueGapV2]:
    """Detects 3-candle Fair Value Gaps deterministically."""
    fvgs: List[FairValueGapV2] = []
    if len(candles) < 3:
        return fvgs

    for i in range(len(candles) - 2):
        c1, c2, c3 = candles[i], candles[i + 1], candles[i + 2]
        tf = c1.timeframe
        known_ts = c3.timestamp_close_utc

        # Bullish FVG: c3.low > c1.high
        if c3.low > c1.high:
            bottom = c1.high
            top = c3.low
            gap_size = top - bottom
            fid = compute_fvg_id(ThesisDirection.LONG, tf, bottom, top, c1.timestamp_close_utc, c3.timestamp_close_utc)
            fvgs.append(
                FairValueGapV2(
                    fvg_id=fid,
                    direction=ThesisDirection.LONG,
                    source_timeframe=tf,
                    created_at=c3.timestamp_close_utc,
                    known_at_timestamp=known_ts,
                    bottom=bottom,
                    top=top,
                    gap_size=gap_size,
                    c1_ts=c1.timestamp_close_utc,
                    c2_ts=c2.timestamp_close_utc,
                    c3_ts=c3.timestamp_close_utc,
                )
            )

        # Bearish FVG: c3.high < c1.low
        elif c3.high < c1.low:
            bottom = c3.high
            top = c1.low
            gap_size = top - bottom
            fid = compute_fvg_id(ThesisDirection.SHORT, tf, bottom, top, c1.timestamp_close_utc, c3.timestamp_close_utc)
            fvgs.append(
                FairValueGapV2(
                    fvg_id=fid,
                    direction=ThesisDirection.SHORT,
                    source_timeframe=tf,
                    created_at=c3.timestamp_close_utc,
                    known_at_timestamp=known_ts,
                    bottom=bottom,
                    top=top,
                    gap_size=gap_size,
                    c1_ts=c1.timestamp_close_utc,
                    c2_ts=c2.timestamp_close_utc,
                    c3_ts=c3.timestamp_close_utc,
                )
            )

    return fvgs


def extract_fvg_features(
    fvg: FairValueGapV2,
    c1: CandleV2,
    c2: CandleV2,
    c3: CandleV2,
    atr: Optional[float] = None,
    as_of_candles: Optional[List[CandleV2]] = None,
    as_of_utc: Optional[str] = None,
) -> FeatureRecord:
    """Extracts raw decision-time and optional post-event mitigation features for an FVG."""
    # Decision-time Candle Geometry
    mid_range = c2.high - c2.low
    mid_body = abs(c2.close - c2.open)
    mid_body_ratio = (mid_body / mid_range) if mid_range > 1e-9 else None

    disp_range = c3.high - c3.low
    disp_body = abs(c3.close - c3.open)

    gap_to_atr = (fvg.gap_size / atr) if (atr is not None and atr > 0) else None

    values: Dict[str, Any] = {
        "gap_size": fvg.gap_size,
        "gap_to_atr_ratio": gap_to_atr,
        "middle_candle_range": mid_range,
        "middle_candle_body": mid_body,
        "middle_body_to_range_ratio": mid_body_ratio,
        "displacement_range": disp_range,
        "displacement_body": disp_body,
        "source_zone_width": fvg.top - fvg.bottom,
    }

    # Post-Event Mitigation Telemetry (hindsight-safe)
    phase = FeaturePhase.DECISION_TIME
    if as_of_candles and as_of_utc:
        phase = FeaturePhase.POST_EVENT
        t_limit = datetime.fromisoformat(as_of_utc).replace(tzinfo=timezone.utc)
        eval_candles = [
            c for c in as_of_candles
            if datetime.fromisoformat(c.timestamp_close_utc).replace(tzinfo=timezone.utc) <= t_limit
            and datetime.fromisoformat(c.timestamp_close_utc).replace(tzinfo=timezone.utc) > datetime.fromisoformat(fvg.known_at_timestamp).replace(tzinfo=timezone.utc)
        ]

        max_mitigation_depth = 0.0
        fvg_state = FVGState.OPEN

        for c in eval_candles:
            if fvg.direction == ThesisDirection.LONG:
                if c.low <= fvg.top:
                    depth = fvg.top - min(c.low, fvg.top)
                    max_mitigation_depth = max(max_mitigation_depth, depth)
                    if c.low <= fvg.bottom:
                        fvg_state = FVGState.FULLY_MITIGATED
                    else:
                        fvg_state = FVGState.PARTIALLY_MITIGATED
            else:  # SHORT
                if c.high >= fvg.bottom:
                    depth = max(c.high, fvg.bottom) - fvg.bottom
                    max_mitigation_depth = max(max_mitigation_depth, depth)
                    if c.high >= fvg.top:
                        fvg_state = FVGState.FULLY_MITIGATED
                    else:
                        fvg_state = FVGState.PARTIALLY_MITIGATED

        filled_pct = min(1.0, max_mitigation_depth / fvg.gap_size) if fvg.gap_size > 0 else 0.0

        values.update({
            "mitigation_depth_absolute": max_mitigation_depth,
            "filled_pct": filled_pct,
            "fvg_state": fvg_state.value,
            "eval_bar_count": len(eval_candles),
        })

    fid = compute_feature_id("FVG_RAW_FEATURES", fvg.fvg_id, fvg.source_timeframe, fvg.known_at_timestamp)

    return FeatureRecord(
        feature_id=fid,
        feature_type="FVG_RAW_FEATURES",
        source_object_id=fvg.fvg_id,
        source_timeframe=fvg.source_timeframe,
        timestamp_utc=fvg.created_at,
        known_at_timestamp=as_of_utc or fvg.known_at_timestamp,
        phase=phase,
        values=values,
        provenance={"fvg_id": fvg.fvg_id, "direction": fvg.direction.value},
    )
