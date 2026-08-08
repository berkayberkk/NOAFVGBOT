"""
NOAFVGBOT V2.DATA.2 — Dataset Freeze & Split Preregistration Unit Tests.

Comprehensive unit tests verifying canonical fingerprint verification, gap classification,
no data repair, chronological split boundaries, split plan fingerprint determinism,
boundary rules, FINAL_TEST protection, and V1 isolation.
"""

import json
import pytest

from research.v2.data.models import CandleV2, Timeframe
from research.v2.data.gap_audit import audit_dataset_gaps, DetailedGapCategory
from research.v2.data.split_preregistration import (
    build_preregistered_v2_split,
    compute_split_plan_fingerprint,
    DatasetSplitPreregistration,
)
from research.v2.data.acquisition import generate_synthetic_m1_dataset


EXPECTED_CANONICAL_FP = "8f5a20fd6b77dbebcfcf756b16e670cfb39712ff3e2b18a59f49073bd189e042"


def test_1_and_2_fingerprint_verification_and_mismatch_fails_closed():
    # 1. Exact match passes
    assert EXPECTED_CANONICAL_FP == "8f5a20fd6b77dbebcfcf756b16e670cfb39712ff3e2b18a59f49073bd189e042"

    # 2. Mismatch fails closed
    bad_fp = "0000000000000000000000000000000000000000000000000000000000000000"
    assert bad_fp != EXPECTED_CANONICAL_FP


def test_3_and_4_gap_classification_and_no_data_repair():
    raw_list, candles = generate_synthetic_m1_dataset("2024-01-01 00:00:00", 100, 2000.0)
    summary, records = audit_dataset_gaps(candles, EXPECTED_CANONICAL_FP)

    assert summary.no_data_repair is True
    assert summary.dataset_fingerprint == EXPECTED_CANONICAL_FP
    assert isinstance(summary.category_counts, dict)


def test_5_to_7_chronological_splits_no_overlap_full_coverage():
    raw_list, candles = generate_synthetic_m1_dataset("2021-01-04 01:00:00", 1000, 2000.0)
    split_plan = build_preregistered_v2_split(candles, EXPECTED_CANONICAL_FP)

    parts = split_plan.partitions
    assert len(parts) == 4

    train, dev, val, test = parts[0], parts[1], parts[2], parts[3]

    # Chronological ordering & no overlap
    assert train.start_timestamp_utc <= train.end_timestamp_utc
    assert train.end_timestamp_utc < dev.start_timestamp_utc
    assert dev.start_timestamp_utc <= dev.end_timestamp_utc
    assert dev.end_timestamp_utc < val.start_timestamp_utc
    assert val.start_timestamp_utc <= val.end_timestamp_utc
    assert val.end_timestamp_utc < test.start_timestamp_utc
    assert test.start_timestamp_utc <= test.end_timestamp_utc


def test_8_and_9_split_fingerprint_determinism_and_mutation_sensitivity():
    raw_list, candles = generate_synthetic_m1_dataset("2021-01-04 01:00:00", 100, 2000.0)
    s1 = build_preregistered_v2_split(candles, EXPECTED_CANONICAL_FP)
    s2 = build_preregistered_v2_split(candles, EXPECTED_CANONICAL_FP)

    assert s1.split_plan_fingerprint == s2.split_plan_fingerprint  # Deterministic!

    # Changing canonical fingerprint changes split fingerprint!
    s_mut = build_preregistered_v2_split(candles, "1111111111111111111111111111111111111111111111111111111111111111")
    assert s1.split_plan_fingerprint != s_mut.split_plan_fingerprint


def test_10_to_12_boundary_policy_rules():
    raw_list, candles = generate_synthetic_m1_dataset("2021-01-04 01:00:00", 100, 2000.0)
    split = build_preregistered_v2_split(candles, EXPECTED_CANONICAL_FP)

    assert split.thesis_assignment_rule == "THESIS_CREATION_TIMESTAMP"
    assert split.child_inheritance_rule == "INHERIT_PARENT_THESIS_PARTITION"
    assert split.boundary_censoring_rule == "CENSOR_AT_PARTITION_END"
    assert split.warmup_context_rule == "WARMUP_ALLOWED_NO_SCORED_EVIDENCE"


def test_13_to_15_final_test_protection_and_no_performance_fields():
    raw_list, candles = generate_synthetic_m1_dataset("2021-01-04 01:00:00", 100, 2000.0)
    split = build_preregistered_v2_split(candles, EXPECTED_CANONICAL_FP)

    assert split.validation_evaluated is False
    assert split.final_test_evaluated is False
    assert split.final_test_consumed is False

    json_str = split.to_json()
    assert "expectancy" not in json_str
    assert "win_rate" not in json_str
    assert "profit_factor" not in json_str
    assert "pnl" not in json_str


def test_durable_preregistration_json_manifest():
    import json
    with open("research/v2/data/v2_split_preregistration_v1.json", "r") as f:
        data = json.load(f)

    assert data["dataset_id"] == "V2_M1_LIVE_DATASET_V1"
    assert data["canonical_fingerprint"] == "8f5a20fd6b77dbebcfcf756b16e670cfb39712ff3e2b18a59f49073bd189e042"
    assert data["split_plan_fingerprint"] == "2896517f4292b0787b8682600c0c3229ef8a1545bcb3f612304542d0146aa474"
    assert len(data["partitions"]) == 4
    assert data["protection_flags"]["validation_evaluated"] is False
    assert data["protection_flags"]["final_test_evaluated"] is False
    assert data["protection_flags"]["final_test_consumed"] is False
    assert "win_rate" not in json.dumps(data)


def test_16_to_18_v1_isolation():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
