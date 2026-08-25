"""
NOAFVGBOT V2.10C.3 -- DatasetBuilder Performance Hardening Parity Tests.

Performance-only change targeting two profiled redundancies in
research/v2/dataset/schema.py (ResearchRow.__post_init__) and
research/v2/dataset/builder.py (build_research_row):

1. ResearchRow.__post_init__ called json.dumps() four times (once each on id_fields,
   x_features, y_labels, meta_fields), discarding every result -- purely to prove
   JSON-serializability. This is combined into a single json.dumps() call over a
   wrapper dict with keys in the SAME order ("id", "x", "y", "meta") the four
   original calls checked, so the first-failure exception (class ValueError,
   message text, and which field fails first) is byte-identical to before: the
   same underlying json encoder machinery raises the same underlying exception
   with the same str(e) text, and dict traversal is insertion-order depth-first
   either way.

2. build_research_row called `rec.feature_type.lower()` once per (FeatureRecord,
   value) pair, inside the innermost loop, even though feature_type is constant
   for a given FeatureRecord and drawn from a tiny repeated vocabulary
   (FVG_RAW_FEATURES, OB_RAW_FEATURES, STRUCTURE_EVENT, LIQUIDITY_SWEEP_EVENT, plus
   legacy fixture values). It now memoizes .lower() per distinct feature_type
   string in a plain dict local to that single build_research_row() call --
   discarded on return, never shared across rows or process lifetime.

Every test in this file either proves exact parity against the verbatim
pre-V2.10C.3 logic (preserved as OLD_* below, copied from commit d9af16f), or
proves a structural reduction in redundant work (call counts), never wall-clock
timing. No strategy semantics, candidate/passport creation, thesis policy,
entry/stop/target geometry, liquidity semantics, or dataset content are touched
by this file.
"""

import json
import math

import pytest

from research.v2.data.models import Timeframe
from research.v2.core.thesis import ThesisDirection
from research.v2.features.models import FeatureRecord, FeaturePhase
from research.v2.features.liquidity import LiquidityPool, LiquiditySide, LiquidityType
from research.v2.telemetry.passport import (
    TradePassport,
    DecisionSnapshot,
    OutcomeState,
    compute_passport_id,
)
from research.v2.dataset.schema import ResearchRow, SCHEMA_VERSION
from research.v2.dataset import builder as builder_mod
from research.v2.dataset.builder import build_research_row, DatasetBuilder


# ---------------------------------------------------------------------------------------------
# Reference oracles -- verbatim pre-V2.10C.3 logic (commit d9af16f), kept ONLY for parity tests.
# ---------------------------------------------------------------------------------------------

def OLD_researchrow_validate(id_fields, x_features, y_labels, meta_fields) -> None:
    """Verbatim body of ResearchRow.__post_init__ before V2.10C.3 (schema.py:139-146)."""
    try:
        json.dumps(id_fields)
        json.dumps(x_features)
        json.dumps(y_labels)
        json.dumps(meta_fields)
    except Exception as e:
        raise ValueError(f"ResearchRow fields must be JSON-serializable: {e}")


def OLD_build_research_row(passport: TradePassport) -> ResearchRow:
    """Verbatim body of build_research_row before V2.10C.3 (builder.py:52-178), including the
    un-hoisted rec.feature_type.lower() call inside the innermost loop."""
    from research.v2.dataset.schema import validate_no_leakage, FEATURE_MANIFEST, LABEL_MANIFEST, BUILDER_VERSION
    from typing import Any, Dict, Optional

    snap = passport.decision_snapshot

    id_fields = {
        "passport_id": passport.passport_id,
        "thesis_id": passport.thesis_id,
        "candidate_id": passport.candidate_id,
        "symbol": passport.symbol,
        "direction": passport.direction.value,
        "candidate_timeframe": passport.candidate_timeframe.name,
        "candidate_created_at": passport.created_at,
    }

    x_features: Dict[str, Any] = {
        "candidate_structural_entry": snap.structural_entry,
        "candidate_structural_stop": snap.structural_stop,
        "candidate_structural_target": snap.structural_target,
        "candidate_risk_distance": abs(snap.structural_entry - snap.structural_stop),
        "candidate_target_distance": abs(snap.structural_target - snap.structural_entry) if snap.structural_target else None,
        "mtf_m15_confirmation_present": "M15" in snap.mtf_trace,
        "mtf_m3_refinement_present": "M3" in snap.mtf_trace,
    }

    feature_known_at: Dict[str, str] = {}
    feature_lineage: Dict[str, Dict[str, Any]] = {}

    for rec in snap.feature_records:
        for val_key, val in rec.values.items():
            feat_col_name = f"{rec.feature_type.lower()}.{val_key}"
            x_features[feat_col_name] = val
            feature_known_at[feat_col_name] = rec.known_at_timestamp
            feature_lineage[feat_col_name] = {
                "source_type": rec.feature_type,
                "known_at_timestamp": rec.known_at_timestamp,
                "phase": rec.phase.value,
                "aggregation_rule": "EXACT",
            }

    nearest_buy: Optional[float] = None
    nearest_sell: Optional[float] = None
    buy_known_at: Optional[str] = None
    sell_known_at: Optional[str] = None

    for lp in snap.liquidity_pools:
        dist = abs(lp.price - snap.structural_entry)
        if lp.side.name == "BUY_SIDE":
            if nearest_buy is None or dist < nearest_buy:
                nearest_buy = dist
                buy_known_at = lp.known_at_timestamp
        elif lp.side.name == "SELL_SIDE":
            if nearest_sell is None or dist < nearest_sell:
                nearest_sell = dist
                sell_known_at = lp.known_at_timestamp

    x_features["liquidity_nearest_buy_distance"] = nearest_buy
    x_features["liquidity_nearest_sell_distance"] = nearest_sell
    if buy_known_at:
        feature_known_at["liquidity_nearest_buy_distance"] = buy_known_at
        feature_lineage["liquidity_nearest_buy_distance"] = {
            "source_type": "LIQUIDITY_POOL",
            "known_at_timestamp": buy_known_at,
            "aggregation_rule": "MIN_DISTANCE",
        }
    if sell_known_at:
        feature_known_at["liquidity_nearest_sell_distance"] = sell_known_at
        feature_lineage["liquidity_nearest_sell_distance"] = {
            "source_type": "LIQUIDITY_POOL",
            "known_at_timestamp": sell_known_at,
            "aggregation_rule": "MIN_DISTANCE",
        }

    ex = passport.get_excursion()
    touched = passport._entry_touched
    state_str = passport.outcome_state.value

    clean_label: Optional[str] = None
    if touched and not passport.is_censored:
        if passport.outcome_state == OutcomeState.TARGET_REACHED:
            clean_label = "TARGET"
        elif passport.outcome_state == OutcomeState.STOP_REACHED:
            clean_label = "STOP"

    y_labels: Dict[str, Any] = {
        "entry_touched": touched,
        "outcome_state": state_str,
        "clean_label": clean_label,
        "mae_r": ex.mae_r,
        "mfe_r": ex.mfe_r,
        "mae_absolute": ex.mae_absolute,
        "mfe_absolute": ex.mfe_absolute,
        "is_ambiguous": passport.outcome_state == OutcomeState.AMBIGUOUS_SAME_BAR,
        "is_censored": passport.is_censored,
        "censor_reason": passport._censor_reason,
    }

    label_known_at: Dict[str, str] = {}
    last_obs_ts = passport.post_entry_path[-1].timestamp_utc if passport.post_entry_path else passport.created_at
    for y_key in y_labels.keys():
        label_known_at[y_key] = last_obs_ts

    meta_fields = {
        "config_fingerprint": passport.config_fingerprint,
        "strategy_version": passport.strategy_version,
        "schema_version": SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "feature_known_at": feature_known_at,
        "label_known_at": label_known_at,
        "feature_lineage": feature_lineage,
    }

    row = ResearchRow(
        id_fields=id_fields,
        x_features=x_features,
        y_labels=y_labels,
        meta_fields=meta_fields,
        schema_version=SCHEMA_VERSION,
    )

    validate_no_leakage(row)
    return row


# ---------------------------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------------------------

def make_feature_record(feature_type, values, known_at="2026-08-08 11:30:00",
                         timestamp_utc="2026-08-08 11:00:00", feature_id="f1", source_object_id="obj1"):
    return FeatureRecord(
        feature_id=feature_id,
        feature_type=feature_type,
        source_object_id=source_object_id,
        source_timeframe=Timeframe.M5,
        timestamp_utc=timestamp_utc,
        known_at_timestamp=known_at,
        phase=FeaturePhase.DECISION_TIME,
        values=values,
    )


def make_liquidity_pool(price, side, known_at="2026-08-08 11:20:00", pool_id="lp1"):
    return LiquidityPool(
        pool_id=pool_id,
        liquidity_type=LiquidityType.SWING_HIGH if side == LiquiditySide.SELL_SIDE else LiquidityType.SWING_LOW,
        side=side,
        price=price,
        source_timeframe=Timeframe.M15,
        origin_timestamp="2026-08-08 10:00:00",
        known_at_timestamp=known_at,
    )


def make_passport(feature_records=(), liquidity_pools=(), thesis_id="th_100", cand_id="cand_1",
                   cand_created_at="2026-08-08 11:30:00", passport_id=None):
    snap = DecisionSnapshot(
        thesis_id=thesis_id,
        direction=ThesisDirection.LONG,
        candidate_id=cand_id,
        candidate_created_at=cand_created_at,
        candidate_timeframe=Timeframe.M5,
        structural_entry=2400.0,
        structural_stop=2390.0,
        structural_target=2420.0,
        feature_records=tuple(feature_records),
        liquidity_pools=tuple(liquidity_pools),
        mtf_trace={"M30": "parent", "M5": "candidate"},
    )
    pid = passport_id or compute_passport_id(thesis_id, cand_id, "fp123", cand_created_at)
    return TradePassport(
        passport_id=pid,
        strategy_version="V2.6",
        schema_version=SCHEMA_VERSION,
        config_fingerprint="fp123",
        thesis_id=thesis_id,
        candidate_id=cand_id,
        symbol="XAUUSD",
        direction=ThesisDirection.LONG,
        candidate_timeframe=Timeframe.M5,
        created_at=cand_created_at,
        decision_snapshot=snap,
    )


# ---------------------------------------------------------------------------------------------
# 1. build_research_row: NEW vs OLD exact parity across a fixture matrix
# ---------------------------------------------------------------------------------------------

def _assert_row_parity(row_old: ResearchRow, row_new: ResearchRow):
    assert row_old.id_fields == row_new.id_fields
    assert row_old.x_features == row_new.x_features
    assert row_old.y_labels == row_new.y_labels
    assert row_old.meta_fields == row_new.meta_fields
    assert row_old.schema_version == row_new.schema_version
    assert row_old.to_flat_dict() == row_new.to_flat_dict()


def test_ordinary_valid_row_with_all_known_feature_types():
    recs = [
        make_feature_record("FVG_RAW_FEATURES", {"gap_size": 5.0, "gap_to_atr_ratio": 0.4}),
        make_feature_record("OB_RAW_FEATURES", {"zone_width": 3.2}),
        make_feature_record("STRUCTURE_EVENT", {"event_type": "SWING_HIGH_CONFIRMED", "price": 2405.0, "broken_level": None}),
        make_feature_record("LIQUIDITY_SWEEP_EVENT", {"event_type": "SWEEP", "pool_liquidity_type": "SWING_HIGH",
                                                        "pool_side": "SELL_SIDE", "pool_price": 2410.0,
                                                        "price_at_event": 2411.0, "breach_distance": 1.0}),
    ]
    pools = [make_liquidity_pool(2415.0, LiquiditySide.SELL_SIDE), make_liquidity_pool(2385.0, LiquiditySide.BUY_SIDE)]
    p = make_passport(feature_records=recs, liquidity_pools=pools)
    row_old = OLD_build_research_row(p)
    row_new = build_research_row(p)
    _assert_row_parity(row_old, row_new)


def test_no_feature_records_no_liquidity_pools():
    p = make_passport(feature_records=(), liquidity_pools=())
    row_old = OLD_build_research_row(p)
    row_new = build_research_row(p)
    _assert_row_parity(row_old, row_new)


def test_empty_values_dict_on_feature_record():
    recs = [make_feature_record("FVG_RAW_FEATURES", {})]
    p = make_passport(feature_records=recs)
    row_old = OLD_build_research_row(p)
    row_new = build_research_row(p)
    _assert_row_parity(row_old, row_new)


def test_repeated_feature_types_multiple_records_same_type():
    recs = [
        make_feature_record("FVG_RAW_FEATURES", {"gap_size": 1.0}, feature_id="f1"),
        make_feature_record("FVG_RAW_FEATURES", {"gap_size": 2.0}, feature_id="f2", source_object_id="obj2"),
        make_feature_record("FVG_RAW_FEATURES", {"gap_size": 3.0}, feature_id="f3", source_object_id="obj3"),
    ]
    p = make_passport(feature_records=recs)
    row_old = OLD_build_research_row(p)
    row_new = build_research_row(p)
    _assert_row_parity(row_old, row_new)
    # Structural proof of the hoist: distinct feature_type count << record count when repeated.
    assert len({r.feature_type for r in recs}) == 1


def test_mixed_case_feature_types_lowercased_consistently():
    recs = [
        make_feature_record("Fvg_Raw_Features", {"gap_size": 1.0}, feature_id="f1"),
        make_feature_record("FVG_RAW_FEATURES", {"gap_size": 2.0}, feature_id="f2", source_object_id="obj2"),
        make_feature_record("fvg_raw_features", {"gap_size": 3.0}, feature_id="f3", source_object_id="obj3"),
    ]
    p = make_passport(feature_records=recs)
    row_old = OLD_build_research_row(p)
    row_new = build_research_row(p)
    _assert_row_parity(row_old, row_new)
    # All three distinct-cased inputs must have lowered to the identical column prefix.
    assert "fvg_raw_features.gap_size" in row_new.x_features


def test_legacy_hand_built_feature_type_still_lowered_correctly():
    # Fixtures elsewhere in the suite construct FeatureRecords by hand with legacy "FVG"/"OB"
    # feature_type strings (see schema.py's backward-compatibility comment). Cache must not
    # assume only the four real-engine feature_type strings occur.
    recs = [make_feature_record("FVG", {"gap_size": 5.0})]
    p = make_passport(feature_records=recs)
    row_old = OLD_build_research_row(p)
    row_new = build_research_row(p)
    _assert_row_parity(row_old, row_new)
    assert "fvg.gap_size" in row_new.x_features


def test_multiple_liquidity_pools_nearest_selection():
    pools = [
        make_liquidity_pool(2415.0, LiquiditySide.SELL_SIDE, pool_id="lp_far_sell"),
        make_liquidity_pool(2405.0, LiquiditySide.SELL_SIDE, pool_id="lp_near_sell"),
        make_liquidity_pool(2385.0, LiquiditySide.BUY_SIDE, pool_id="lp_far_buy"),
        make_liquidity_pool(2395.0, LiquiditySide.BUY_SIDE, pool_id="lp_near_buy"),
    ]
    p = make_passport(liquidity_pools=pools)
    row_old = OLD_build_research_row(p)
    row_new = build_research_row(p)
    _assert_row_parity(row_old, row_new)
    assert row_new.x_features["liquidity_nearest_sell_distance"] == 5.0
    assert row_new.x_features["liquidity_nearest_buy_distance"] == 5.0


def test_no_liquidity_pools_nulls_preserved():
    p = make_passport(liquidity_pools=())
    row_old = OLD_build_research_row(p)
    row_new = build_research_row(p)
    _assert_row_parity(row_old, row_new)
    assert row_new.x_features["liquidity_nearest_buy_distance"] is None
    assert row_new.x_features["liquidity_nearest_sell_distance"] is None


def test_nested_dict_and_list_values_in_feature_record():
    # Value keys must be registered under FEATURE_MANIFEST's "structure_event." prefix
    # (event_type, price, broken_level) for validate_no_leakage to accept the row; the VALUES
    # themselves are shaped to exercise nested dict/list/bool/int/None handling.
    recs = [make_feature_record("STRUCTURE_EVENT", {
        "event_type": {"a": {"b": [1, 2, 3]}},
        "price": [1, "x", None, True, 2.5],
        "broken_level": None,
    })]
    p = make_passport(feature_records=recs)
    row_old = OLD_build_research_row(p)
    row_new = build_research_row(p)
    _assert_row_parity(row_old, row_new)


def test_unknown_feature_type_rejected_identically():
    recs = [make_feature_record("TOTALLY_UNKNOWN_TYPE", {"x": 1.0})]
    p = make_passport(feature_records=recs)
    with pytest.raises(ValueError, match="Unregistered feature key") as exc_old:
        OLD_build_research_row(p)
    with pytest.raises(ValueError, match="Unregistered feature key") as exc_new:
        build_research_row(p)
    assert str(exc_old.value) == str(exc_new.value)


def test_real_bounded_fixture_via_datasetbuilder_batch():
    recs1 = [make_feature_record("FVG_RAW_FEATURES", {"gap_size": 1.0}, known_at="2026-08-08 11:00:00")]
    recs2 = [make_feature_record("OB_RAW_FEATURES", {"zone_width": 2.0}, feature_id="f9", source_object_id="obj9",
                                  known_at="2026-08-08 11:05:00")]
    p1 = make_passport(feature_records=recs1, thesis_id="th_1", cand_id="cand_1", cand_created_at="2026-08-08 11:00:00")
    p2 = make_passport(feature_records=recs2, thesis_id="th_2", cand_id="cand_2", cand_created_at="2026-08-08 11:05:00")

    rows_old = [OLD_build_research_row(p1), OLD_build_research_row(p2)]
    rows_new = DatasetBuilder([p1, p2]).build_rows()

    assert len(rows_old) == len(rows_new)
    for ro, rn in zip(rows_old, rows_new):
        _assert_row_parity(ro, rn)
    # Row ordering must be preserved (insertion order, unsorted) by build_rows().
    assert [r.id_fields["passport_id"] for r in rows_new] == [p1.passport_id, p2.passport_id]


# ---------------------------------------------------------------------------------------------
# 2. ResearchRow JSON-serializability validation: NEW vs OLD exact accept/reject parity
# ---------------------------------------------------------------------------------------------

VALID_CASES = {
    "empty_dicts": ({}, {}, {}, {}),
    "plain_scalars": ({"a": "s"}, {"b": 1}, {"c": 1.5}, {"d": True}),
    "none_values": ({"a": None}, {"b": None}, {"c": None}, {"d": None}),
    "nested_dict": ({"a": {"b": {"c": 1}}}, {}, {}, {}),
    "list_values": ({"a": [1, 2, 3]}, {}, {}, {}),
    "tuple_values": ({"a": (1, 2, 3)}, {}, {}, {}),
    "mixed_container": ({"a": [{"b": (1, None, "x", True, 2.5)}]}, {}, {}, {}),
    "bool_and_int_and_float": ({"a": True, "b": 1, "c": 1.25}, {}, {}, {}),
    "timestamps_and_ids": (
        {"passport_id": "pp_1", "candidate_created_at": "2026-08-08 11:30:00"},
        {"candidate_structural_entry": 2400.0},
        {"entry_touched": True},
        {"feature_known_at": {"x.foo": "2026-08-08 11:30:00"}},
    ),
    "nan_and_infinity": ({"a": float("nan")}, {"b": float("inf")}, {"c": float("-inf")}, {}),
    "int_float_bool_none_dict_keys": ({1: "a", 1.5: "b", True: "c", None: "d"}, {}, {}, {}),
}

INVALID_CASES = {
    "set_value": ({"a": {1, 2, 3}}, {}, {}, {}),
    "custom_object_value": ({"a": object()}, {}, {}, {}),
    "bytes_value": ({"a": b"raw"}, {}, {}, {}),
    "non_basic_dict_key": ({(1, 2): "a"}, {}, {}, {}),
    "malformed_feature_record_nested_set": ({}, {"x.feat": {"bad": {1, 2}}}, {}, {}),
}


@pytest.mark.parametrize("name", list(VALID_CASES.keys()))
def test_valid_json_case_accepted_by_both(name):
    id_f, x_f, y_f, meta_f = VALID_CASES[name]
    OLD_researchrow_validate(id_f, x_f, y_f, meta_f)  # must not raise
    row = ResearchRow(id_fields=id_f, x_features=x_f, y_labels=y_f, meta_fields=meta_f)  # must not raise
    assert row.id_fields == id_f
    assert row.x_features == x_f
    assert row.y_labels == y_f
    assert row.meta_fields == meta_f


@pytest.mark.parametrize("name", list(INVALID_CASES.keys()))
def test_invalid_json_case_rejected_by_both_same_message(name):
    id_f, x_f, y_f, meta_f = INVALID_CASES[name]
    with pytest.raises(ValueError) as exc_old:
        OLD_researchrow_validate(id_f, x_f, y_f, meta_f)
    with pytest.raises(ValueError) as exc_new:
        ResearchRow(id_fields=id_f, x_features=x_f, y_labels=y_f, meta_fields=meta_f)
    assert str(exc_old.value) == str(exc_new.value)


def test_nan_infinity_preserved_not_substituted():
    row = ResearchRow(id_fields={}, x_features={"a": float("nan")}, y_labels={"b": float("inf")}, meta_fields={})
    assert math.isnan(row.x_features["a"])
    assert row.y_labels["b"] == float("inf")


def test_first_failing_field_order_matches_original_check_order():
    # OLD checked id, then x, then y, then meta, in that order (first exception wins). A bad
    # value in y_labels together with a bad value in id_fields must surface id_fields' error
    # (matching the original sequential short-circuit order), not y_labels'.
    id_f = {"bad": {1, 2}}
    y_f = {"also_bad": object()}
    with pytest.raises(ValueError) as exc_old:
        OLD_researchrow_validate(id_f, {}, y_f, {})
    with pytest.raises(ValueError) as exc_new:
        ResearchRow(id_fields=id_f, x_features={}, y_labels=y_f, meta_fields={})
    assert str(exc_old.value) == str(exc_new.value)
    assert "set" in str(exc_new.value)


# ---------------------------------------------------------------------------------------------
# 3. Call-count reduction proofs (structural, not wall-clock)
# ---------------------------------------------------------------------------------------------

def test_lower_call_count_reduced_for_repeated_feature_type():
    calls = {"n": 0}
    real_lower = str.lower

    class CountingStr(str):
        def lower(self):
            calls["n"] += 1
            return real_lower(self)

    recs = [
        make_feature_record("FVG_RAW_FEATURES", {"gap_size": 1.0, "gap_to_atr_ratio": 0.1, "middle_candle_range": 0.2},
                             feature_id="f1"),
        make_feature_record("FVG_RAW_FEATURES", {"gap_size": 2.0, "gap_to_atr_ratio": 0.2, "middle_candle_range": 0.3},
                             feature_id="f2", source_object_id="obj2"),
        make_feature_record("FVG_RAW_FEATURES", {"gap_size": 3.0, "gap_to_atr_ratio": 0.3, "middle_candle_range": 0.4},
                             feature_id="f3", source_object_id="obj3"),
    ]
    recs = [
        FeatureRecord(
            feature_id=r.feature_id,
            feature_type=CountingStr(r.feature_type),
            source_object_id=r.source_object_id,
            source_timeframe=r.source_timeframe,
            timestamp_utc=r.timestamp_utc,
            known_at_timestamp=r.known_at_timestamp,
            phase=r.phase,
            values=r.values,
        )
        for r in recs
    ]
    p = make_passport(feature_records=recs)
    build_research_row(p)
    # OLD behavior would call .lower() once per (record, value) pair = 3 records * 3 values = 9.
    # NEW behavior must call .lower() at most once per distinct feature_type string = 1.
    assert calls["n"] <= 3, f"expected <=3 (one per record, hoisted out of the value loop), got {calls['n']}"


def test_json_dumps_call_count_reduced_in_post_init():
    calls = {"n": 0}
    real_dumps = json.dumps

    def counting_dumps(*args, **kwargs):
        calls["n"] += 1
        return real_dumps(*args, **kwargs)

    orig = builder_mod.json.dumps
    from research.v2.dataset import schema as schema_mod
    orig_schema_dumps = schema_mod.json.dumps
    schema_mod.json.dumps = counting_dumps
    try:
        ResearchRow(id_fields={"a": 1}, x_features={"b": 2}, y_labels={"c": 3}, meta_fields={"d": 4})
    finally:
        schema_mod.json.dumps = orig_schema_dumps

    assert calls["n"] == 1, f"expected exactly 1 combined json.dumps call, got {calls['n']}"
