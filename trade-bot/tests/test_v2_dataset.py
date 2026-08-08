"""
NOAFVGBOT V2.6 — Scientific Integrity & Fingerprint Provenance Unit Tests.

Comprehensive test suite verifying fingerprint content sensitivity, manifest validation,
aggregate feature lineage, label temporal safety, same-thesis split protection, and V1 isolation invariants.
"""

import os
import tempfile
import pytest

from research.v2.data.models import Timeframe
from research.v2.core.thesis import ThesisDirection
from research.v2.features.models import FeatureRecord, FeaturePhase
from research.v2.features.liquidity import LiquidityPool, LiquiditySide, LiquidityType
from research.v2.telemetry.excursion import PathObservation
from research.v2.telemetry.passport import (
    TradePassport,
    DecisionSnapshot,
    OutcomeState,
    compute_passport_id,
)
from research.v2.dataset.schema import (
    ResearchRow,
    ResearchLabels,
    validate_no_leakage,
    FEATURE_MANIFEST,
    LABEL_MANIFEST,
)
from research.v2.dataset.builder import (
    build_research_row,
    compute_dataset_fingerprint,
    DatasetBuilder,
    export_jsonl,
    export_csv,
    import_jsonl,
)
from research.v2.dataset.splits import (
    GroupedChronologicalSplitter,
    DatasetSplit,
)


def create_passport(thesis_id: str = "th_100", cand_id: str = "cand_1", cand_created_at: str = "2026-08-08 11:30:00") -> TradePassport:
    rec = FeatureRecord(
        feature_id=f"f_{cand_id}",
        feature_type="FVG",
        source_object_id="fvg1",
        source_timeframe=Timeframe.M5,
        timestamp_utc="2026-08-08 11:00:00",
        known_at_timestamp="2026-08-08 11:30:00",
        phase=FeaturePhase.DECISION_TIME,
        values={"gap_size": 5.0},
    )
    snap = DecisionSnapshot(
        thesis_id=thesis_id,
        direction=ThesisDirection.LONG,
        candidate_id=cand_id,
        candidate_created_at=cand_created_at,
        candidate_timeframe=Timeframe.M5,
        structural_entry=2400.0,
        structural_stop=2390.0,
        structural_target=2420.0,
        feature_records=(rec,),
        mtf_trace={"M30": "parent", "M5": "candidate"},
    )
    pid = compute_passport_id(thesis_id, cand_id, "fp123", cand_created_at)
    p = TradePassport(
        passport_id=pid,
        strategy_version="V2.6",
        schema_version="2.6",
        config_fingerprint="fp123",
        thesis_id=thesis_id,
        candidate_id=cand_id,
        symbol="XAUUSD",
        direction=ThesisDirection.LONG,
        candidate_timeframe=Timeframe.M5,
        created_at=cand_created_at,
        decision_snapshot=snap,
    )
    return p


# --- 1 to 6: FINGERPRINT SENSITIVITY TESTS ---
def test_1_x_mutation_changes_fingerprint():
    p1 = create_passport("th_100", "cand_1")
    row1 = build_research_row(p1)

    row2_dict = row1.to_flat_dict()
    row2_dict["x.fvg.gap_size"] = 10.0  # mutated x feature!

    fp1 = compute_dataset_fingerprint([row1])
    row2 = ResearchRow(
        id_fields=row1.id_fields,
        x_features={**row1.x_features, "fvg.gap_size": 10.0},
        y_labels=row1.y_labels,
        meta_fields=row1.meta_fields,
    )
    fp2 = compute_dataset_fingerprint([row2])
    assert fp1 != fp2


def test_2_y_mutation_changes_fingerprint():
    p1 = create_passport("th_100", "cand_1")
    row1 = build_research_row(p1)
    fp1 = compute_dataset_fingerprint([row1])

    row2 = ResearchRow(
        id_fields=row1.id_fields,
        x_features=row1.x_features,
        y_labels={**row1.y_labels, "mae_r": 2.5},  # mutated y label!
        meta_fields=row1.meta_fields,
    )
    fp2 = compute_dataset_fingerprint([row2])
    assert fp1 != fp2


def test_3_null_mutation_changes_fingerprint():
    p1 = create_passport("th_100", "cand_1")
    row1 = build_research_row(p1)
    fp1 = compute_dataset_fingerprint([row1])

    row2 = ResearchRow(
        id_fields=row1.id_fields,
        x_features={**row1.x_features, "liquidity_nearest_buy_distance": 15.0},  # null -> non-null!
        y_labels=row1.y_labels,
        meta_fields=row1.meta_fields,
    )
    fp2 = compute_dataset_fingerprint([row2])
    assert fp1 != fp2


def test_4_and_5_schema_and_builder_version_change_fingerprint():
    p1 = create_passport("th_100", "cand_1")
    row1 = build_research_row(p1)
    fp1 = compute_dataset_fingerprint([row1], builder_version="2.6.0", schema_version="2.6")
    fp2 = compute_dataset_fingerprint([row1], builder_version="2.7.0", schema_version="2.6")
    fp3 = compute_dataset_fingerprint([row1], builder_version="2.6.0", schema_version="2.7")

    assert fp1 != fp2
    assert fp1 != fp3


def test_6_canonical_repeat_identical_fingerprint():
    p1 = create_passport("th_100", "cand_1")
    row1 = build_research_row(p1)
    fp1 = compute_dataset_fingerprint([row1])
    fp2 = compute_dataset_fingerprint([row1])
    assert fp1 == fp2


# --- 7 to 12: MANIFEST & LEAKAGE PROVENANCE TESTS ---
def test_7_unknown_x_feature_rejected():
    p1 = create_passport("th_100", "cand_1")
    row1 = build_research_row(p1)

    bad_row = ResearchRow(
        id_fields=row1.id_fields,
        x_features={**row1.x_features, "unknown_unregistered_feature": 42.0},
        y_labels=row1.y_labels,
        meta_fields=row1.meta_fields,
    )
    with pytest.raises(ValueError, match="Unregistered feature key"):
        validate_no_leakage(bad_row)


def test_8_label_field_under_x_rejected():
    p1 = create_passport("th_100", "cand_1")
    row1 = build_research_row(p1)

    bad_row = ResearchRow(
        id_fields=row1.id_fields,
        x_features={**row1.x_features, "outcome_state": "TARGET_REACHED"},
        y_labels=row1.y_labels,
        meta_fields=row1.meta_fields,
    )
    with pytest.raises(ValueError, match="Unregistered feature key|Target leakage detected"):
        validate_no_leakage(bad_row)


def test_10_and_11_aggregate_lineage_retained_and_future_source_rejected():
    p1 = create_passport("th_100", "cand_1")
    row1 = build_research_row(p1)

    # Lineage is present in meta_fields
    assert "feature_lineage" in row1.meta_fields

    # Future known feature rejected by validate_no_leakage
    bad_meta = {
        **row1.meta_fields,
        "feature_known_at": {**row1.meta_fields["feature_known_at"], "candidate_structural_entry": "2026-08-08 12:00:00"},
    }
    bad_row = ResearchRow(
        id_fields=row1.id_fields,
        x_features=row1.x_features,
        y_labels=row1.y_labels,
        meta_fields=bad_meta,
    )
    with pytest.raises(ValueError, match="Feature timing leakage"):
        validate_no_leakage(bad_row)


# --- 13 & 14: CLEAN LABEL SAFETY TESTS ---
def test_13_ambiguous_clean_label_remains_none():
    p = create_passport("th_100", "cand_1")
    obs_wild = PathObservation("obs_wild", p.passport_id, "2026-08-08 11:35:00", Timeframe.M5, 2400.0, 2425.0, 2385.0, 2410.0, "c1")
    p.add_observation(obs_wild)  # Ambiguous same bar!

    row = build_research_row(p)
    assert row.y_labels["is_ambiguous"] is True
    assert row.y_labels["clean_label"] is None  # MUST be None!


def test_14_censored_unresolved_clean_label_remains_none():
    p = create_passport("th_100", "cand_1")
    p.censor("2026-08-08 11:40:00", reason="END_OF_WINDOW")

    row = build_research_row(p)
    assert row.y_labels["is_censored"] is True
    assert row.y_labels["clean_label"] is None


# --- 15 & 16: GROUPED SPLIT TESTS ---
def test_15_and_16_grouped_thesis_split_protection():
    p1 = create_passport("th_100", "cand_1", "2026-08-08 11:30:00")
    p2 = create_passport("th_100", "cand_2", "2026-08-08 11:45:00")
    p3 = create_passport("th_200", "cand_3", "2026-08-08 12:00:00")

    builder = DatasetBuilder([p1, p2, p3])
    rows = builder.build_rows()

    splitter = GroupedChronologicalSplitter(train_ratio=0.50, val_ratio=0.50, test_ratio=0.0)
    split = splitter.split(rows)

    train_theses = set(r.id_fields["thesis_id"] for r in split.train_rows)
    val_theses = set(r.id_fields["thesis_id"] for r in split.validation_rows)

    assert len(train_theses.intersection(val_theses)) == 0


# --- 17: EXPORT ROUNDTRIP TEST ---
def test_17_jsonl_roundtrip_fingerprint_exact():
    p1 = create_passport("th_100", "cand_1")
    rows = [build_research_row(p1)]
    fp1 = compute_dataset_fingerprint(rows)

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "dataset.jsonl")
        export_jsonl(rows, filepath)

        imported_rows = import_jsonl(filepath)
        fp2 = compute_dataset_fingerprint(imported_rows)

        assert fp1 == fp2  # EXACT FINGERPRINT ROUNDTRIP!


def test_19_and_20_v1_isolation_regression():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
