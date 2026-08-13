"""
NOAFVGBOT V2.10B — Real Dataset Loader & Provenance Tests.

Covers: real-loader fail-closed behavior (missing file, wrong fingerprint), structural
separation between the real and synthetic loading paths, synthetic-fingerprint distinctness,
gap-audit materiality now depending on actual counts, unchanged partition boundaries with
deterministic exact counts, and a single authoritative provenance ledger with no duplicate
sources of truth.
"""

import inspect
import json
import os
import tempfile

import pytest

from research.v2.data.models import CandleV2, Timeframe
from research.v2.data.manifest import DatasetManifest, compute_canonical_fingerprint
from research.v2.data.live_dataset import (
    load_frozen_live_dataset,
    load_synthetic_fixture,
    parse_mt5_m1_export_csv,
    DatasetFileMissingError,
    DatasetIntegrityError,
    DatasetIdentityMismatchError,
)
from research.v2.data.gap_audit import audit_dataset_gaps
from research.v2.data.split_preregistration import build_preregistered_v2_split
from research.v2.data.run_data_freeze_and_split import execute_freeze_and_split, EXPECTED_CANONICAL_FINGERPRINT


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write_mt5_csv(tmp_path, rows):
    """rows: list of (date_str, time_str, open, high, low, close, tickvol)."""
    path = os.path.join(tmp_path, "fixture.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n")
        for d, t, o, h, l, c, tv in rows:
            f.write(f"{d}\t{t}\t{o}\t{h}\t{l}\t{c}\t{tv}\t0\t30\n")
    return path


def _make_rows(n, start_price=2000.0):
    rows = []
    dt_date, dt_hour, dt_min = "2026.01.05", 0, 0
    for i in range(n):
        p = start_price + i * 0.1
        hh = f"{dt_hour:02d}:{dt_min:02d}:00"
        rows.append((dt_date, hh, p, p + 0.5, p - 0.5, p + 0.1, 10))
        dt_min += 1
        if dt_min == 60:
            dt_min = 0
            dt_hour += 1
    return rows


# --- 1: real loader rejects missing dataset ---------------------------------

def test_1_real_loader_rejects_missing_dataset():
    with pytest.raises(DatasetFileMissingError):
        load_frozen_live_dataset(
            path="C:/definitely/does/not/exist/dataset.csv",
            expected_dataset_id="V2_M1_LIVE_DATASET_V1",
            expected_canonical_fingerprint="deadbeef",
        )


# --- 2: real loader rejects wrong fingerprint --------------------------------

def test_2_real_loader_rejects_wrong_fingerprint(tmp_path):
    rows = _make_rows(50)
    path = _write_mt5_csv(str(tmp_path), rows)
    with pytest.raises(DatasetIdentityMismatchError):
        load_frozen_live_dataset(
            path=path,
            expected_dataset_id="V2_M1_LIVE_DATASET_V1",
            expected_canonical_fingerprint="0" * 64,
        )


# --- 3: synthetic fixture cannot masquerade as LIVE --------------------------

def test_3_synthetic_fixture_cannot_masquerade_as_live():
    _, manifest = load_synthetic_fixture(count=50)
    assert manifest.source_kind == "BENCHMARK_FIXTURE"
    assert manifest.dataset_state == "V2_M1_BENCHMARK_FIXTURE"
    # DatasetManifest itself refuses this exact contradiction structurally
    with pytest.raises(ValueError):
        DatasetManifest(
            dataset_name="x", research_symbol="XAUUSD", broker_symbol="GOLD", timeframe="M1",
            retrieved_at_utc="2026-01-01 00:00:00", earliest_timestamp="", latest_timestamp="",
            raw_row_count=0, canonical_row_count=0, raw_fingerprint="", canonical_fingerprint="",
            quality_status="PASS", m1_count=0, m3_count=0, m5_count=0, m15_count=0, m30_count=0,
            incomplete_buckets={}, source_kind="BENCHMARK_FIXTURE", dataset_state="V2_M1_DATASET_CANDIDATE",
        )


# --- 4: synthetic fingerprint differs from LIVE fingerprint ------------------

def test_4_synthetic_fingerprint_differs_from_live_fingerprint():
    _, manifest = load_synthetic_fixture(count=50)
    assert manifest.canonical_fingerprint != EXPECTED_CANONICAL_FINGERPRINT


# --- 5: artifact fingerprint matches exact source data -----------------------

def test_5_artifact_fingerprint_matches_exact_source_data(tmp_path):
    rows = _make_rows(30)
    path = _write_mt5_csv(str(tmp_path), rows)
    candles = parse_mt5_m1_export_csv(path)
    independently_computed_fp = compute_canonical_fingerprint(sorted(candles, key=lambda c: c.timestamp_open_utc))

    loaded_candles, manifest = load_frozen_live_dataset(
        path=path, expected_dataset_id="TEST", expected_canonical_fingerprint=independently_computed_fp,
    )
    assert manifest.canonical_fingerprint == independently_computed_fp
    assert manifest.canonical_row_count == len(rows)

    # Perturbing a single price (within valid OHLC bounds) must change the fingerprint
    # (fingerprint truly describes content, not just row count/shape).
    rows_perturbed = list(rows)
    d, t, o, h, l, c, tv = rows_perturbed[10]
    rows_perturbed[10] = (d, t, o, h, l, c + 0.05, tv)
    perturbed_dir = str(tmp_path) + "_perturbed"
    os.makedirs(perturbed_dir, exist_ok=True)
    path2 = _write_mt5_csv(perturbed_dir, rows_perturbed)
    candles2 = parse_mt5_m1_export_csv(path2)
    fp2 = compute_canonical_fingerprint(sorted(candles2, key=lambda c: c.timestamp_open_utc))
    assert fp2 != independently_computed_fp


# --- 6, 7: gap materiality depends on actual counts; not auto-ACCEPTABLE with unresolved gaps --

def test_6_and_7_gap_materiality_depends_on_actual_counts():
    # Case A: clean continuous series -> zero gaps -> ACCEPTABLE_DISCONTINUITIES
    clean_rows = _make_rows(120)
    clean_candles = [
        CandleV2(
            timestamp_open_utc=f"2026-01-05 {h:02d}:{m:02d}:00",
            timestamp_close_utc=f"2026-01-05 {h:02d}:{m+1:02d}:00" if m < 59 else f"2026-01-05 {h+1:02d}:00:00",
            timeframe=Timeframe.M1, open=2000.0, high=2000.5, low=1999.5, close=2000.1,
        )
        for h in range(2) for m in range(60)
    ]
    summary_clean, _ = audit_dataset_gaps(clean_candles, "fp_clean")
    assert summary_clean.unresolved_suspicious_gaps == 0
    assert summary_clean.materiality_conclusion == "ACCEPTABLE_DISCONTINUITIES"

    # Case B: inject one genuinely suspicious mid-session gap. 2026-01-05 is a Monday, hour 0,
    # so this is neither a weekend gap, a 21:00-22:00 daily-session break, nor a holiday date.
    # A 20-minute (1200s) drop exceeds the <=900s "likely provider gap" threshold, so it must
    # land in SUSPICIOUS_INTRASESSION rather than being auto-explained.
    candles_with_gap = clean_candles[:30] + clean_candles[50:]  # drop minutes 30-49 of hour 0
    summary_gap, _ = audit_dataset_gaps(candles_with_gap, "fp_gap")
    assert summary_gap.category_counts["SUSPICIOUS_INTRASESSION"] == 1
    assert summary_gap.unresolved_suspicious_gaps >= 1
    assert summary_gap.materiality_conclusion == "UNRESOLVED_GAPS_REQUIRE_REVIEW"


# --- 8: partition boundaries unchanged ---------------------------------------

def test_8_partition_boundaries_unchanged():
    # A single TRAIN-only candle: TRAIN's reported end_timestamp is data-derived (the last
    # candle actually observed in that partition), but the other three partitions have zero
    # candles here, so they fall back to their fixed pre-registered boundary constants —
    # exactly what this test needs to verify those constants are unchanged.
    candles = [
        CandleV2("2021-01-04 01:00:00", "2021-01-04 01:01:00", Timeframe.M1, 1800.0, 1800.5, 1799.5, 1800.1),
    ]
    plan = build_preregistered_v2_split(candles, "fp_x")
    boundaries = {p.name: (p.start_timestamp_utc, p.end_timestamp_utc) for p in plan.partitions}
    assert boundaries["TRAIN"][0] == "2021-01-04 01:00:00"
    assert boundaries["DEVELOPMENT"] == ("2023-11-01 00:00:00", "2024-12-31 23:59:00")
    assert boundaries["VALIDATION"] == ("2025-01-01 00:00:00", "2025-10-31 23:59:00")
    assert boundaries["FINAL_TEST"] == ("2025-11-01 00:00:00", "2026-08-07 23:57:00")


# --- 9: exact partition counts deterministic ----------------------------------

def test_9_exact_partition_counts_deterministic():
    candles = [
        CandleV2(f"2021-01-04 01:{m:02d}:00", f"2021-01-04 01:{m+1:02d}:00", Timeframe.M1, 1800.0, 1800.5, 1799.5, 1800.1)
        for m in range(30)
    ]
    plan1 = build_preregistered_v2_split(candles, "fp_x")
    plan2 = build_preregistered_v2_split(candles, "fp_x")
    counts1 = {p.name: p.m1_count for p in plan1.partitions}
    counts2 = {p.name: p.m1_count for p in plan2.partitions}
    assert counts1 == counts2
    assert counts1["TRAIN"] == 30  # exact int, not an approximation


# --- 10: TRAIN exact count persisted (no "~990k" style approximation) --------

def test_10_train_exact_count_is_a_real_integer_not_an_approximation():
    candles = [
        CandleV2(f"2021-01-04 01:{m:02d}:00", f"2021-01-04 01:{m+1:02d}:00", Timeframe.M1, 1800.0, 1800.5, 1799.5, 1800.1)
        for m in range(45)
    ]
    plan = build_preregistered_v2_split(candles, "fp_x")
    train = next(p for p in plan.partitions if p.name == "TRAIN")
    assert isinstance(train.m1_count, int)
    assert train.m1_count == 45


# --- 11, 12, 13: DEVELOPMENT / VALIDATION / FINAL_TEST untouched -------------

def test_11_to_13_development_validation_final_test_untouched():
    candles = [
        CandleV2("2021-01-04 01:00:00", "2021-01-04 01:01:00", Timeframe.M1, 1800.0, 1800.5, 1799.5, 1800.1),
    ]
    plan = build_preregistered_v2_split(candles, "fp_x")
    assert plan.validation_evaluated is False
    assert plan.final_test_evaluated is False
    assert plan.final_test_consumed is False


# --- 14: V1 untouched ----------------------------------------------------------

def test_14_v1_isolation_regression():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1
    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14


# --- 16: no synthetic fallback in real path -----------------------------------

def test_16_no_synthetic_fallback_reachable_from_real_loader():
    params = inspect.signature(load_frozen_live_dataset).parameters
    assert "allow_synthetic" not in params
    # No boolean parameter exists anywhere in the real loader's signature that could route
    # to generated data -- synthetic data requires calling the differently-named function.
    for name, p in params.items():
        assert p.annotation is not bool, f"unexpected boolean parameter on real loader: {name}"
    assert load_frozen_live_dataset is not load_synthetic_fixture

    # And the real path fails closed rather than ever falling back silently
    res = execute_freeze_and_split(live_dataset_path="C:/definitely/does/not/exist.csv")
    assert res["status"] == "REAL DATASET MISSING"
    assert "note" in res and "No synthetic fallback" in res["note"]


# --- 17: duplicate split source-of-truth prevented -----------------------------

def test_17_single_authoritative_source_recorded_in_provenance_ledger():
    ledger_path = os.path.join(REPO_ROOT, "research", "v2", "data", "dataset_provenance_status.json")
    with open(ledger_path, "r", encoding="utf-8") as f:
        ledger = json.load(f)

    classifications = {a["path"]: a["classification"] for a in ledger["artifacts"]}
    assert classifications["research/v2/data/v2_split_preregistration_v1.json"] == "AUTHORITATIVE_FOR_BOUNDARY_POLICY_ONLY"
    assert classifications["data/results/v2_split_preregistration_v1.json"] == "QUARANTINED"
    # Exactly one artifact is treated as authoritative for split-boundary policy
    authoritative = [p for p, c in classifications.items() if c.startswith("AUTHORITATIVE")]
    assert len(authoritative) == 1
    assert ledger["real_dataset_status"] == "MISSING"


# --- 18: repeated audit deterministic -------------------------------------------

def test_18_repeated_gap_audit_deterministic():
    candles = [
        CandleV2(f"2021-01-04 01:{m:02d}:00", f"2021-01-04 01:{m+1:02d}:00", Timeframe.M1, 1800.0, 1800.5, 1799.5, 1800.1)
        for m in range(40)
    ] + [
        CandleV2(f"2021-01-04 03:{m:02d}:00", f"2021-01-04 03:{m+1:02d}:00", Timeframe.M1, 1801.0, 1801.5, 1800.5, 1801.1)
        for m in range(40)
    ]
    s1, r1 = audit_dataset_gaps(candles, "fp_repeat")
    s2, r2 = audit_dataset_gaps(candles, "fp_repeat")
    assert s1.total_gaps == s2.total_gaps
    assert s1.category_counts == s2.category_counts
    assert s1.materiality_conclusion == s2.materiality_conclusion
    assert s1.dataset_fingerprint == s2.dataset_fingerprint
    assert [rec.gap_id for rec in r1] == [rec.gap_id for rec in r2]
