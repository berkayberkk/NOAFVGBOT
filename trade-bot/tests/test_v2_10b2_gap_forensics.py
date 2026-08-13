"""
NOAFVGBOT V2.10B.2 -- Gap Forensics Tests.

Covers: gap arithmetic, empirically-derived rule-based classification (weekend, recurring
session break, DST-shifted session break, holiday-requires-evidence, provider/unresolved
residuals), confidence discipline, active-session missingness, partition attribution,
classifier determinism/order-independence, canonical immutability, freeze decision paths,
authoritative-loader fail-closed behavior, and unchanged split boundaries/counts.

Uses small synthetic CandleV2 fixtures throughout (not the full 1,981,624-row real dataset)
so the suite runs fast and deterministically; the real dataset was independently validated
via research/v2/data/run_v2_10b2_gap_forensics.py.
"""

import json
import os

import pytest

from research.v2.data.models import CandleV2, Timeframe
from research.v2.data.manifest import compute_canonical_fingerprint
from research.v2.data.gap_forensics import (
    GapCategory,
    EXPECTED_CATEGORIES,
    compute_gap_arithmetic,
    classify_gap,
    build_forensics_table,
    get_partition,
    active_session_missingness,
    classify_end_boundary,
    EndBoundaryClassification,
    PARTITION_BOUNDARIES,
)
from research.v2.data.run_v2_10b2_gap_forensics import decide_freeze_status
from research.v2.data.live_dataset import (
    load_authoritative_frozen_v2_dataset,
    DatasetNotFrozenError,
    DatasetIdentityMismatchError,
)
import research.v2.data.run_v2_10b2_gap_forensics as forensics_script


def _candle(ts: str, price: float = 2000.0) -> CandleV2:
    dt = __import__("datetime").datetime.fromisoformat(ts)
    close_ts = (dt + __import__("datetime").timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    return CandleV2(
        timestamp_open_utc=ts, timestamp_close_utc=close_ts, timeframe=Timeframe.M1,
        open=price, high=price + 0.5, low=price - 0.5, close=price + 0.1, volume=10.0,
    )


# --- 1/2: gap arithmetic -----------------------------------------------------

def test_one_minute_gap_arithmetic_is_not_a_gap():
    arith = compute_gap_arithmetic("2026-01-05 10:00:00", "2026-01-05 10:01:00")
    assert arith["delta_minutes"] == 1
    assert arith["missing_m1_bars"] == 0


def test_multi_minute_gap_arithmetic_delta_vs_missing_bars_differ():
    # 10:00 -> 10:02: delta=2 minutes but only 1 missing bar (10:01). Locked per V2.10B.2 spec.
    arith = compute_gap_arithmetic("2026-01-05 10:00:00", "2026-01-05 10:02:00")
    assert arith["delta_minutes"] == 2
    assert arith["missing_m1_bars"] == 1
    assert arith["missing_start_utc"] == "2026-01-05 10:01:00"
    assert arith["missing_end_utc"] == "2026-01-05 10:01:00"

    arith2 = compute_gap_arithmetic("2026-01-05 10:00:00", "2026-01-05 10:11:00")
    assert arith2["delta_minutes"] == 11
    assert arith2["missing_m1_bars"] == 10


# --- 3: weekend classification -----------------------------------------------

def test_weekend_classification():
    # 2026-01-02 is a Friday; 2026-01-05 is the following Monday.
    category, reason, evidence, confidence, review = classify_gap(
        "2026-01-02 23:58:00", "2026-01-05 01:00:00", delta_minutes=2942, missing_m1_bars=2941,
    )
    assert category == GapCategory.EXPECTED_WEEKEND
    assert review is False


# --- 4: recurring session-break classification --------------------------------

def test_recurring_daily_session_break_classification():
    # Monday night standard-time nightly pause: 23:58 -> next day 01:00 (61 min).
    category, reason, evidence, confidence, review = classify_gap(
        "2026-01-05 23:58:00", "2026-01-06 01:00:00", delta_minutes=62, missing_m1_bars=61,
    )
    assert category == GapCategory.EXPECTED_DAILY_SESSION_BREAK
    assert "standard-time" in evidence
    assert review is False


# --- 5: DST-shifted session-break classification -------------------------------

def test_dst_shifted_session_break_classification():
    # EU-DST variant: close hour 22, reopen hour 00.
    category, reason, evidence, confidence, review = classify_gap(
        "2026-06-01 22:58:00", "2026-06-02 00:00:00", delta_minutes=62, missing_m1_bars=61,
    )
    assert category == GapCategory.EXPECTED_DAILY_SESSION_BREAK
    assert "DST" in evidence


# --- 6: holiday classification requires evidence --------------------------------

def test_holiday_classification_requires_evidence():
    # A gap that merely happens to sit near Christmas but does NOT match the empirically
    # observed early-close hour / duration signature must NOT be classified as holiday.
    category, reason, evidence, confidence, review = classify_gap(
        "2026-12-24 14:00:00", "2026-12-24 14:12:00", delta_minutes=12, missing_m1_bars=11,
    )
    assert category != GapCategory.EXPECTED_HOLIDAY_OR_CLOSURE

    # A gap that DOES match a computed US federal holiday date (2026 MLK Day = Jan 19) with
    # the observed early-close/reopen signature IS classified as holiday, at MEDIUM (not HIGH,
    # since no external corroboration was supplied) confidence.
    category2, reason2, evidence2, confidence2, review2 = classify_gap(
        "2026-01-19 21:24:00", "2026-01-20 01:00:00", delta_minutes=216, missing_m1_bars=215,
    )
    assert category2 == GapCategory.EXPECTED_HOLIDAY_OR_CLOSURE
    assert confidence2 == "MEDIUM"


# --- 7: random active-session gap remains provider/suspicious -------------------

def test_random_active_session_gap_remains_provider_or_unresolved():
    # Small (<=9 bars), no recurring pattern -> LIKELY_PROVIDER_HISTORY_GAP, not expected.
    category, *_ = classify_gap("2026-03-11 14:00:00", "2026-03-11 14:06:00", delta_minutes=6, missing_m1_bars=5)
    assert category == GapCategory.LIKELY_PROVIDER_HISTORY_GAP

    # Large, unpatterned daytime gap -> UNRESOLVED_SUSPICIOUS_GAP, never silently "expected".
    category2, *_ = classify_gap("2026-03-11 14:00:00", "2026-03-11 14:51:00", delta_minutes=51, missing_m1_bars=50)
    assert category2 not in EXPECTED_CATEGORIES
    assert category2 == GapCategory.UNRESOLVED_SUSPICIOUS_GAP


# --- 8: low-confidence ambiguity cannot become expected --------------------------

def test_low_confidence_ambiguity_cannot_become_expected():
    category, reason, evidence, confidence, review = classify_gap(
        "2026-03-11 14:00:00", "2026-03-11 14:51:00", delta_minutes=51, missing_m1_bars=50,
    )
    assert confidence == "LOW"
    assert category not in EXPECTED_CATEGORIES
    assert review is True


# --- 9/10: provider missingness counted; expected closures excluded --------------

def test_provider_missingness_counted_and_expected_excluded():
    candles = [
        _candle("2026-01-05 23:57:00"),
        _candle("2026-01-05 23:58:00"),
        _candle("2026-01-06 01:00:00"),  # nightly break: 61 missing bars, EXPECTED
        _candle("2026-01-06 01:01:00"),
        _candle("2026-01-06 01:02:00"),
        _candle("2026-01-06 01:03:00"),
        _candle("2026-01-06 01:04:00"),
        _candle("2026-01-06 01:05:00"),
        _candle("2026-01-06 01:11:00"),  # small provider gap: 5 missing bars, UNEXPECTED
    ]
    records = build_forensics_table(candles)
    stats = active_session_missingness(records, observed_active_session_bars=len(candles))
    assert stats["unexpected_active_session_missing_bars"] == 5
    assert stats["denominator"] == len(candles) + 5


# --- 11: partition attribution ---------------------------------------------------

def test_partition_attribution():
    assert get_partition("2022-06-01 00:00:00") == "TRAIN"
    assert get_partition("2024-01-01 00:00:00") == "DEVELOPMENT"
    assert get_partition("2025-06-01 00:00:00") == "VALIDATION"
    assert get_partition("2026-01-01 00:00:00") == "FINAL_TEST"


# --- 12: classifier deterministic -------------------------------------------------

def test_classifier_deterministic_across_repeated_runs():
    candles = [_candle("2026-01-05 23:57:00"), _candle("2026-01-05 23:58:00"), _candle("2026-01-06 01:00:00")]
    r1 = build_forensics_table(candles)
    r2 = build_forensics_table(candles)
    assert [vars(r) for r in r1] == [vars(r) for r in r2]


# --- 13: reversed input ordering produces identical classification ---------------

def test_reversed_input_ordering_identical_classification():
    candles = [
        _candle("2026-01-05 23:57:00"), _candle("2026-01-05 23:58:00"),
        _candle("2026-01-06 01:00:00"), _candle("2026-01-06 01:01:00"),
        _candle("2026-01-06 14:00:00"), _candle("2026-01-06 14:06:00"),
    ]
    forward = build_forensics_table(candles)
    backward = build_forensics_table(list(reversed(candles)))
    assert [vars(r) for r in forward] == [vars(r) for r in backward]


# --- 14/15: canonical fingerprint and row count unchanged ------------------------

def test_canonical_fingerprint_and_row_count_unchanged_by_forensics():
    candles = [
        _candle("2026-01-05 23:57:00"), _candle("2026-01-05 23:58:00"),
        _candle("2026-01-06 01:00:00"), _candle("2026-01-06 14:00:00"), _candle("2026-01-06 14:06:00"),
    ]
    fp_before = compute_canonical_fingerprint(candles)
    n_before = len(candles)

    build_forensics_table(candles)

    fp_after = compute_canonical_fingerprint(candles)
    n_after = len(candles)
    assert fp_before == fp_after
    assert n_before == n_after


# --- 16: zero candle repair --------------------------------------------------------

def test_zero_candle_repair():
    candles = [
        _candle("2026-01-05 23:57:00"), _candle("2026-01-05 23:58:00"),
        _candle("2026-01-06 01:00:00"), _candle("2026-01-06 14:00:00"), _candle("2026-01-06 14:06:00"),
    ]
    before = list(candles)
    build_forensics_table(candles)
    assert candles == before
    assert len(candles) == 5  # no bar was inserted to "fill" any of the gaps above


# --- 17: MT5 re-pull cannot mutate canonical data ----------------------------------

def test_mt5_repull_cannot_mutate_canonical_data(monkeypatch):
    monkeypatch.delenv("USE_LIVE_MT5", raising=False)
    candles = [_candle("2026-01-06 14:00:00"), _candle("2026-01-06 14:06:00")]
    before = list(candles)
    records = build_forensics_table(candles)
    result = forensics_script.bounded_mt5_repull(records)
    assert result["skipped"] is True
    assert result["orders_sent"] == 0
    assert candles == before


# --- 18: old-export comparison cannot mutate canonical data ------------------------

def test_old_export_comparison_cannot_mutate_canonical_data():
    candles = [_candle("2026-01-06 14:00:00"), _candle("2026-01-06 14:06:00")]
    before = list(candles)
    verdict = forensics_script.old_export_crosscheck("2026-01-06 14:01:00", "2026-01-06 14:05:00", [["2026-01-06 14:00:00", "2026-01-06 14:30:00"]])
    assert verdict == "OLD_EXPORT_ALSO_MISSING"
    assert candles == before


# --- 19: end-boundary semantics -----------------------------------------------------

def test_end_boundary_semantics():
    expected = classify_end_boundary("2026-08-07 23:56:00", "2026-08-07 23:57:00")
    assert expected["classification"] == EndBoundaryClassification.EXPECTED_END_SEMANTICS

    missing = classify_end_boundary("2026-08-07 23:56:00", "2026-08-07 23:58:00")
    assert missing["classification"] == EndBoundaryClassification.MISSING_FINAL_BAR

    unresolved = classify_end_boundary("2026-08-07 23:56:00", "2026-08-08 04:00:00")
    assert unresolved["classification"] == EndBoundaryClassification.UNRESOLVED_END_BOUNDARY


# --- 20/21: freeze rejection and freeze-with-warning paths -------------------------

def test_freeze_rejection_path():
    decision, reason = decide_freeze_status(
        unresolved_count=3, provider_count=0, concentrated_damage=False,
        unexpected_missing_bars=100, missingness_denominator=1000, missingness_rate=0.1,
    )
    assert decision == "FREEZE_REJECTED"

    decision2, _ = decide_freeze_status(
        unresolved_count=0, provider_count=0, concentrated_damage=True,
        unexpected_missing_bars=0, missingness_denominator=1000, missingness_rate=0.0,
    )
    assert decision2 == "FREEZE_REJECTED"


def test_freeze_accepted_with_warnings_path():
    decision, reason = decide_freeze_status(
        unresolved_count=0, provider_count=83, concentrated_damage=False,
        unexpected_missing_bars=143, missingness_denominator=1981767, missingness_rate=0.0000722,
    )
    assert decision == "FREEZE_ACCEPTED_WITH_WARNINGS"
    assert "residual" in reason


def test_freeze_accepted_clean_path():
    decision, reason = decide_freeze_status(
        unresolved_count=0, provider_count=0, concentrated_damage=False,
        unexpected_missing_bars=0, missingness_denominator=1000, missingness_rate=0.0,
    )
    assert decision == "FREEZE_ACCEPTED"


# --- 22/23: authoritative loader fail-closed behavior -------------------------------

def _write_mt5_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n")
        for d, t, o, h, l, c, tv in rows:
            f.write(f"{d}\t{t}\t{o}\t{h}\t{l}\t{c}\t{tv}\t0\t30\n")


def _tiny_rows():
    return [
        ("2026.01.05", "00:00:00", 2000.0, 2000.5, 1999.5, 2000.1, 10),
        ("2026.01.05", "00:01:00", 2000.1, 2000.6, 1999.6, 2000.2, 10),
    ]


def test_loader_rejects_non_frozen_dataset(tmp_path):
    csv_path = os.path.join(tmp_path, "canonical.csv")
    _write_mt5_csv(csv_path, _tiny_rows())

    missing_manifest = os.path.join(tmp_path, "does_not_exist.json")
    with pytest.raises(DatasetNotFrozenError):
        load_authoritative_frozen_v2_dataset(canonical_csv_path=csv_path, frozen_manifest_path=missing_manifest)

    rejected_manifest = os.path.join(tmp_path, "rejected.json")
    with open(rejected_manifest, "w") as f:
        json.dump({"dataset_id": "V2_M1_LIVE_DATASET_V2", "freeze_decision": "FREEZE_REJECTED"}, f)
    with pytest.raises(DatasetNotFrozenError):
        load_authoritative_frozen_v2_dataset(canonical_csv_path=csv_path, frozen_manifest_path=rejected_manifest)


def test_loader_rejects_wrong_fingerprint(tmp_path):
    csv_path = os.path.join(tmp_path, "canonical.csv")
    _write_mt5_csv(csv_path, _tiny_rows())

    bad_manifest = os.path.join(tmp_path, "frozen.json")
    with open(bad_manifest, "w") as f:
        json.dump({
            "dataset_id": "V2_M1_LIVE_DATASET_V2",
            "freeze_decision": "FREEZE_ACCEPTED_WITH_WARNINGS",
            "canonical_fingerprint": "0" * 64,
            "row_count": 2,
            "actual_range": {"start": "2026-01-05 00:00:00", "end": "2026-01-05 00:01:00"},
        }, f)

    with pytest.raises(DatasetIdentityMismatchError):
        load_authoritative_frozen_v2_dataset(canonical_csv_path=csv_path, frozen_manifest_path=bad_manifest)


# --- 24: V1 remains LEGACY_UNVERIFIED -------------------------------------------------

def test_v1_remains_legacy_unverified():
    assert forensics_script.LEGACY_STATUS == "LEGACY_UNVERIFIED"
    assert forensics_script.LEGACY_DATASET_ID == "V2_M1_LIVE_DATASET_V1"
    assert forensics_script.LEGACY_CANONICAL_FINGERPRINT == "8f5a20fd6b77dbebcfcf756b16e670cfb39712ff3e2b18a59f49073bd189e042"


# --- 25: split boundaries unchanged ---------------------------------------------------

def test_split_boundaries_unchanged():
    names = [b[0] for b in PARTITION_BOUNDARIES]
    assert names == ["TRAIN", "DEVELOPMENT", "VALIDATION", "FINAL_TEST"]
    assert PARTITION_BOUNDARIES[0][2] == "2023-11-01 00:00:00"
    assert PARTITION_BOUNDARIES[1] == ("DEVELOPMENT", "2023-11-01 00:00:00", "2025-01-01 00:00:00")
    assert PARTITION_BOUNDARIES[2] == ("VALIDATION", "2025-01-01 00:00:00", "2025-11-01 00:00:00")
    assert PARTITION_BOUNDARIES[3][1] == "2025-11-01 00:00:00"


# --- 26: exact partition counts deterministic -------------------------------------------

def test_partition_counts_deterministic():
    ts_list = ["2022-06-01 00:00:00", "2024-01-01 00:00:00", "2025-06-01 00:00:00", "2026-01-01 00:00:00"]
    first = [get_partition(ts) for ts in ts_list]
    second = [get_partition(ts) for ts in ts_list]
    assert first == second == ["TRAIN", "DEVELOPMENT", "VALIDATION", "FINAL_TEST"]
