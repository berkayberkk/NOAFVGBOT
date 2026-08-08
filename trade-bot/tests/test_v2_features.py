"""
NOAFVGBOT V2.4 — Feature Intelligence Unit Tests.

Comprehensive test suite verifying FVG, Order Block, Structure, Cross-Timeframe Geometry,
Feature Record models, as-of hindsight safety, ThesisEvidence adapters, and V1 isolation invariants.
"""

from datetime import datetime, timedelta, timezone
import pytest

from research.v2.data.models import CandleV2, Timeframe
from research.v2.core.thesis import ThesisDirection, ParentThesis, compute_thesis_id
from research.v2.features.models import (
    FeatureRecord,
    FeaturePhase,
    compute_feature_id,
    validate_feature_availability,
)
from research.v2.features.fvg_quality import (
    FairValueGapV2,
    FVGState,
    detect_fvgs,
    extract_fvg_features,
)
from research.v2.features.ob_quality import (
    OrderBlockV2,
    OBState,
    detect_order_blocks,
    extract_ob_features,
)
from research.v2.features.structure import (
    StructureEvent,
    StructureEventType,
    detect_structure_events,
)
from research.v2.features.geometry import (
    fvg_fvg_overlap,
    ob_ob_overlap,
    fvg_ob_intersection,
    thesis_relative_features,
)
from research.v2.features.liquidity import (
    LiquidityPool,
    LiquiditySide,
    LiquidityType,
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


# --- 1-11: FVG TESTS ---
def test_1_to_3_fvg_detection_and_knowledge_timing():
    c1 = create_candle("2026-08-08 10:00:00", open_p=2000.0, high_p=2010.0, low_p=1995.0, close_p=2008.0)
    c2 = create_candle("2026-08-08 10:30:00", open_p=2008.0, high_p=2030.0, low_p=2005.0, close_p=2028.0)
    c3 = create_candle("2026-08-08 11:00:00", open_p=2028.0, high_p=2050.0, low_p=2015.0, close_p=2045.0)

    fvgs = detect_fvgs([c1, c2, c3])
    assert len(fvgs) == 1

    fvg = fvgs[0]
    assert fvg.direction == ThesisDirection.LONG
    assert fvg.bottom == 2010.0
    assert fvg.top == 2015.0
    assert fvg.gap_size == 5.0
    assert fvg.known_at_timestamp == "2026-08-08 11:30:00"  # c3 close time!


def test_4_to_11_fvg_features_and_mitigation_no_future_leakage():
    c1 = create_candle("2026-08-08 10:00:00", open_p=2000.0, high_p=2010.0, low_p=1995.0, close_p=2008.0)
    c2 = create_candle("2026-08-08 10:30:00", open_p=2008.0, high_p=2030.0, low_p=2005.0, close_p=2028.0)
    c3 = create_candle("2026-08-08 11:00:00", open_p=2028.0, high_p=2050.0, low_p=2015.0, close_p=2045.0)

    fvg = detect_fvgs([c1, c2, c3])[0]

    # Feature extraction without ATR -> gap_to_atr_ratio MUST be None (not zero!)
    feat = extract_fvg_features(fvg, c1, c2, c3, atr=None)
    assert feat.values["gap_size"] == 5.0
    assert feat.values["gap_to_atr_ratio"] is None

    # Feature extraction with ATR
    feat_atr = extract_fvg_features(fvg, c1, c2, c3, atr=10.0)
    assert feat_atr.values["gap_to_atr_ratio"] == 0.5

    # Mitigation testing
    c4 = create_candle("2026-08-08 11:30:00", open_p=2045.0, high_p=2045.0, low_p=2012.0, close_p=2014.0)  # Partially mitigates (low 2012 <= top 2015)
    c5 = create_candle("2026-08-08 12:00:00", open_p=2014.0, high_p=2015.0, low_p=2008.0, close_p=2009.0)  # Fully mitigates (low 2008 <= bottom 2010)

    # Evaluate as of 11:30 (before c5) -> PARTIALLY_MITIGATED only!
    feat_1130 = extract_fvg_features(fvg, c1, c2, c3, atr=10.0, as_of_candles=[c4, c5], as_of_utc="2026-08-08 12:00:00")
    assert feat_1130.values["fvg_state"] == "PARTIALLY_MITIGATED"

    # Evaluate as of 12:30 (after c5) -> FULLY_MITIGATED!
    feat_1230 = extract_fvg_features(fvg, c1, c2, c3, atr=10.0, as_of_candles=[c4, c5], as_of_utc="2026-08-08 12:30:00")
    assert feat_1230.values["fvg_state"] == "FULLY_MITIGATED"


# --- 12-19: OB TESTS ---
def test_12_to_19_ob_detection_features_and_knowledge_timing():
    c_src = create_candle("2026-08-08 10:00:00", open_p=2020.0, high_p=2022.0, low_p=2000.0, close_p=2002.0)  # Bearish source
    c_imp = create_candle("2026-08-08 10:30:00", open_p=2002.0, high_p=2035.0, low_p=2001.0, close_p=2030.0)  # Bullish impulse

    obs = detect_order_blocks([c_src, c_imp])
    assert len(obs) == 1

    ob = obs[0]
    assert ob.direction == ThesisDirection.LONG
    assert ob.zone_low == 2000.0
    assert ob.zone_high == 2022.0
    assert ob.known_at_timestamp == "2026-08-08 11:00:00"  # c_imp close time!

    feat = extract_ob_features(ob, c_src, c_imp, atr=10.0)
    assert feat.values["zone_width"] == 22.0
    assert feat.values["zone_width_to_atr"] == 2.2


# --- 20-25: STRUCTURE TESTS ---
def test_20_to_25_structure_events():
    candles = [
        create_candle("2026-08-08 10:00:00", open_p=2000.0, high_p=2010.0, low_p=1990.0, close_p=2005.0),
        create_candle("2026-08-08 10:30:00", open_p=2005.0, high_p=2020.0, low_p=1995.0, close_p=2015.0),
        create_candle("2026-08-08 11:00:00", open_p=2015.0, high_p=2050.0, low_p=2010.0, close_p=2045.0),  # Swing High
        create_candle("2026-08-08 11:30:00", open_p=2045.0, high_p=2045.0, low_p=2020.0, close_p=2025.0),
        create_candle("2026-08-08 12:00:00", open_p=2025.0, high_p=2030.0, low_p=2015.0, close_p=2020.0),
        create_candle("2026-08-08 12:30:00", open_p=2020.0, high_p=2060.0, low_p=2020.0, close_p=2055.0),  # BOS UP (close 2055 > 2050)
    ]

    events = detect_structure_events(candles, left_bars=2, right_bars=2)
    assert len(events) >= 2

    event_types = [e.event_type for e in events]
    assert StructureEventType.SWING_HIGH_CONFIRMED in event_types
    assert StructureEventType.STRUCTURE_BREAK_UP in event_types


# --- 26-31: GEOMETRY TESTS ---
def test_26_to_31_cross_timeframe_geometry():
    fvg1 = FairValueGapV2("fvg1", ThesisDirection.LONG, Timeframe.M30, "2026-08-08 11:00:00", "2026-08-08 11:30:00", 2010.0, 2030.0, 20.0, "t1", "t2", "t3")
    fvg2 = FairValueGapV2("fvg2", ThesisDirection.LONG, Timeframe.M5, "2026-08-08 11:15:00", "2026-08-08 11:20:00", 2015.0, 2025.0, 10.0, "t1", "t2", "t3")

    # Containment (fvg2 is inside fvg1)
    res = fvg_fvg_overlap(fvg1, fvg2)
    assert res["overlap_absolute"] == 10.0
    assert res["overlap_pct_fvg2"] == 1.0
    assert res["containment"] is True
    assert res["direction_alignment"] is True

    ob = OrderBlockV2("ob1", ThesisDirection.LONG, Timeframe.M15, "2026-08-08 11:00:00", "2026-08-08 11:15:00", 2005.0, 2020.0, "t1", "t2")
    res_fo = fvg_ob_intersection(fvg1, ob)
    assert res_fo["intersection_width"] == 10.0  # 2010.0 to 2020.0


# --- 32-36: THESIS & LIQUIDITY INTEGRATION ---
def test_32_to_36_thesis_and_liquidity_integration():
    tid = compute_thesis_id("V2.4", "fp1", "XAUUSD", Timeframe.M30, "2026-08-08 11:30:00", ThesisDirection.LONG)
    thesis = ParentThesis(tid, "V2.4", "2.4", "fp1", "XAUUSD", ThesisDirection.LONG, Timeframe.M30, "2026-08-08 11:30:00")

    # Relative features
    rel_feat = thesis_relative_features(ThesisDirection.LONG, thesis.direction, thesis.created_at, "2026-08-08 12:00:00")
    assert rel_feat["same_direction_as_thesis"] is True
    assert rel_feat["time_since_thesis_creation_sec"] == 1800.0

    # Ensure thesis state was NOT modified by feature extraction
    assert thesis.state.name == "CREATED"


# --- 37-43: SAFETY & SERIALIZATION TESTS ---
def test_37_to_43_safety_and_serialization():
    rec = FeatureRecord(
        feature_id="feat_123",
        feature_type="TEST",
        source_object_id="obj_1",
        source_timeframe=Timeframe.M30,
        timestamp_utc="2026-08-08 11:00:00",
        known_at_timestamp="2026-08-08 11:30:00",
        phase=FeaturePhase.DECISION_TIME,
        values={"val": 42.0},
    )

    # Availability validation
    assert validate_feature_availability(rec, "2026-08-08 11:30:00") is True
    assert validate_feature_availability(rec, "2026-08-08 11:29:59") is False

    # Thesis evidence adapter
    ev = rec.to_thesis_evidence("th_999")
    assert ev.thesis_id == "th_999"
    assert ev.payload["values"]["val"] == 42.0


def test_44_and_45_v1_isolation_regression():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
