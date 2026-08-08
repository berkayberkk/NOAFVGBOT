"""
NOAFVGBOT V2.4 — Cross-Timeframe & Zone Geometry Module.

Provides raw mathematical overlap, containment, confluence, and thesis-relative
geometric calculations without assigning trade signal quality or predictive weights.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from research.v2.core.thesis import ThesisDirection
from research.v2.features.fvg_quality import FairValueGapV2
from research.v2.features.ob_quality import OrderBlockV2


def fvg_fvg_overlap(fvg1: FairValueGapV2, fvg2: FairValueGapV2) -> Dict[str, Any]:
    """Calculates raw geometric overlap between two Fair Value Gaps."""
    overlap_bottom = max(fvg1.bottom, fvg2.bottom)
    overlap_top = min(fvg1.top, fvg2.top)

    overlap_abs = max(0.0, overlap_top - overlap_bottom)
    pct_fvg1 = (overlap_abs / fvg1.gap_size) if fvg1.gap_size > 0 else 0.0
    pct_fvg2 = (overlap_abs / fvg2.gap_size) if fvg2.gap_size > 0 else 0.0

    fvg1_center = (fvg1.bottom + fvg1.top) / 2.0
    fvg2_center = (fvg2.bottom + fvg2.top) / 2.0

    is_contained = (fvg1.bottom >= fvg2.bottom and fvg1.top <= fvg2.top) or (fvg2.bottom >= fvg1.bottom and fvg2.top <= fvg1.top)

    return {
        "overlap_absolute": overlap_abs,
        "overlap_pct_fvg1": pct_fvg1,
        "overlap_pct_fvg2": pct_fvg2,
        "containment": is_contained,
        "center_distance": abs(fvg1_center - fvg2_center),
        "direction_alignment": fvg1.direction == fvg2.direction,
    }


def ob_ob_overlap(ob1: OrderBlockV2, ob2: OrderBlockV2) -> Dict[str, Any]:
    """Calculates raw geometric overlap between two Order Blocks."""
    w1 = ob1.zone_high - ob1.zone_low
    w2 = ob2.zone_high - ob2.zone_low

    overlap_bottom = max(ob1.zone_low, ob2.zone_low)
    overlap_top = min(ob1.zone_high, ob2.zone_high)

    overlap_abs = max(0.0, overlap_top - overlap_bottom)
    pct_ob1 = (overlap_abs / w1) if w1 > 0 else 0.0
    pct_ob2 = (overlap_abs / w2) if w2 > 0 else 0.0

    ob1_center = (ob1.zone_low + ob1.zone_high) / 2.0
    ob2_center = (ob2.zone_low + ob2.zone_high) / 2.0

    is_contained = (ob1.zone_low >= ob2.zone_low and ob1.zone_high <= ob2.zone_high) or (ob2.zone_low >= ob1.zone_low and ob2.zone_high <= ob1.zone_high)

    return {
        "overlap_absolute": overlap_abs,
        "overlap_pct_ob1": pct_ob1,
        "overlap_pct_ob2": pct_ob2,
        "containment": is_contained,
        "center_distance": abs(ob1_center - ob2_center),
        "direction_alignment": ob1.direction == ob2.direction,
    }


def fvg_ob_intersection(fvg: FairValueGapV2, ob: OrderBlockV2) -> Dict[str, Any]:
    """Calculates raw intersection geometry between an FVG and an Order Block."""
    ob_w = ob.zone_high - ob.zone_low

    inter_bottom = max(fvg.bottom, ob.zone_low)
    inter_top = min(fvg.top, ob.zone_high)

    inter_w = max(0.0, inter_top - inter_bottom)
    pct_fvg = (inter_w / fvg.gap_size) if fvg.gap_size > 0 else 0.0
    pct_ob = (inter_w / ob_w) if ob_w > 0 else 0.0

    return {
        "intersection_width": inter_w,
        "intersection_pct_fvg": pct_fvg,
        "intersection_pct_ob": pct_ob,
        "direction_alignment": fvg.direction == ob.direction,
    }


def thesis_relative_features(
    zone_direction: ThesisDirection,
    thesis_direction: ThesisDirection,
    thesis_created_at: str,
    current_ts: str,
) -> Dict[str, Any]:
    """Calculates raw thesis-relative geometry and timing without mutating thesis state."""
    t_thesis = datetime.fromisoformat(thesis_created_at).replace(tzinfo=timezone.utc)
    t_curr = datetime.fromisoformat(current_ts).replace(tzinfo=timezone.utc)

    elapsed_sec = max(0.0, (t_curr - t_thesis).total_seconds())

    return {
        "same_direction_as_thesis": zone_direction == thesis_direction,
        "time_since_thesis_creation_sec": elapsed_sec,
    }
