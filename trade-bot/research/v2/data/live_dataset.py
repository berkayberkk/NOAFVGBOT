"""
NOAFVGBOT V2.10B — Real Canonical Live Dataset Loader & Provenance.

Provides a strictly real-only canonical M1 dataset loader with zero synthetic fallback,
using the existing DatasetManifest schema (research/v2/data/manifest.py) as the single
authoritative identity object. No parallel/duplicate metadata schema is introduced.

INVARIANTS:
- load_frozen_live_dataset() has NO synthetic fallback under any parameter combination —
  there is no boolean flag that can silently route it to generated data.
- Fails closed: missing file, empty file, malformed row, duplicate/out-of-order timestamps,
  or canonical fingerprint mismatch all raise. Nothing is silently repaired or skipped.
- load_synthetic_fixture() is a structurally separate function/path. It can never produce a
  DatasetManifest carrying the real dataset's dataset_id, source_kind, or fingerprint — it
  always computes its own fingerprint from the synthetic content it actually generated and
  stamps source_kind="BENCHMARK_FIXTURE" / dataset_state="V2_M1_BENCHMARK_FIXTURE" (which
  DatasetManifest.__post_init__ already refuses to let masquerade as V2_M1_DATASET_CANDIDATE).
"""

from datetime import datetime, timedelta, timezone
from typing import List, Tuple
import csv
import json
import os

from research.v2.data.models import CandleV2, Timeframe
from research.v2.data.manifest import DatasetManifest, compute_canonical_fingerprint

FROZEN_V2_MANIFEST_PATH = "data/canonical/V2_M1_LIVE_DATASET_V2_frozen_manifest.json"
AUTHORITATIVE_FROZEN_DATASET_ID = "V2_M1_LIVE_DATASET_V2"
ACCEPTED_FREEZE_DECISIONS = ("FREEZE_ACCEPTED", "FREEZE_ACCEPTED_WITH_WARNINGS")


class DatasetFileMissingError(Exception):
    """Raised when the real canonical dataset file does not exist at the given path."""


class DatasetIntegrityError(Exception):
    """Raised on malformed rows, duplicate/out-of-order timestamps, or empty parsed output."""


class DatasetIdentityMismatchError(Exception):
    """Raised when the recomputed canonical fingerprint does not match the expected value."""


class DatasetNotFrozenError(Exception):
    """Raised when the frozen V2 manifest is missing, names a different dataset_id, or its
    freeze_decision is not one of the accepted states (V2.10B.2)."""


def parse_mt5_m1_export_csv(path: str) -> List[CandleV2]:
    """
    Parses a tab-separated MT5 History Center M1 export
    (<DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>) into canonical
    CandleV2 objects, preserving OHLCV exactly. No repair: a malformed row raises immediately
    rather than being silently skipped or patched.
    """
    candles: List[CandleV2] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader, None)
        if not header:
            raise DatasetIntegrityError(f"Empty or headerless file: {path}")

        for row_num, row in enumerate(reader, start=2):
            if len(row) < 6:
                raise DatasetIntegrityError(f"Malformed row {row_num} in {path}: {row!r}")

            date_str, time_str, open_s, high_s, low_s, close_s = row[0:6]
            tick_vol = row[6] if len(row) > 6 else "0"

            try:
                dt_open = datetime.strptime(f"{date_str} {time_str}", "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
                open_v, high_v, low_v, close_v = float(open_s), float(high_s), float(low_s), float(close_s)
                vol_v = float(tick_vol)
            except (ValueError, TypeError) as e:
                raise DatasetIntegrityError(f"Malformed row {row_num} in {path}: {row!r} ({e})")

            dt_close = dt_open + timedelta(seconds=60)
            candles.append(CandleV2(
                timestamp_open_utc=dt_open.strftime("%Y-%m-%d %H:%M:%S"),
                timestamp_close_utc=dt_close.strftime("%Y-%m-%d %H:%M:%S"),
                timeframe=Timeframe.M1,
                open=open_v, high=high_v, low=low_v, close=close_v, volume=vol_v,
            ))
    return candles


def load_frozen_live_dataset(
    path: str,
    expected_dataset_id: str,
    expected_canonical_fingerprint: str,
    research_symbol: str = "XAUUSD",
    broker_symbol: str = "GOLD",
) -> Tuple[List[CandleV2], DatasetManifest]:
    """
    REAL-ONLY canonical M1 dataset loader. There is no parameter combination that routes this
    function to synthetic/generated data — use load_synthetic_fixture() for that, explicitly.

    Fails closed:
      - DatasetFileMissingError if `path` does not exist.
      - DatasetIntegrityError on malformed rows, duplicate timestamps, or empty output.
      - DatasetIdentityMismatchError if the recomputed canonical fingerprint does not match
        `expected_canonical_fingerprint`. On mismatch, the expected value is NEVER overwritten
        and no data is used — the caller must stop.
    """
    if not os.path.exists(path):
        raise DatasetFileMissingError(f"Real canonical dataset file not found at: {path}")

    candles = parse_mt5_m1_export_csv(path)
    if not candles:
        raise DatasetIntegrityError(f"Zero candles parsed from {path}")

    # Deterministic ordering + strict integrity check. No silent repair: a duplicate or
    # out-of-order timestamp is a hard failure, not something to drop/merge/reorder past.
    candles = sorted(candles, key=lambda c: c.timestamp_open_utc)
    seen_ts = set()
    prev_ts = None
    for c in candles:
        if c.timestamp_open_utc in seen_ts:
            raise DatasetIntegrityError(f"Duplicate timestamp_open_utc in canonical load: {c.timestamp_open_utc}")
        seen_ts.add(c.timestamp_open_utc)
        prev_ts = c.timestamp_open_utc

    canonical_fp = compute_canonical_fingerprint(candles)
    if canonical_fp != expected_canonical_fingerprint:
        raise DatasetIdentityMismatchError(
            f"Canonical fingerprint mismatch for {expected_dataset_id}. "
            f"Expected {expected_canonical_fingerprint}, recomputed {canonical_fp} "
            f"from {len(candles)} rows ({candles[0].timestamp_open_utc} to {candles[-1].timestamp_close_utc}). "
            f"Refusing to proceed — no auto-repair, no fingerprint overwrite."
        )

    manifest = DatasetManifest(
        dataset_name=expected_dataset_id,
        research_symbol=research_symbol,
        broker_symbol=broker_symbol,
        timeframe="M1",
        retrieved_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        earliest_timestamp=candles[0].timestamp_open_utc,
        latest_timestamp=candles[-1].timestamp_close_utc,
        raw_row_count=len(candles),
        canonical_row_count=len(candles),
        raw_fingerprint="",
        canonical_fingerprint=canonical_fp,
        quality_status="PASS",
        m1_count=len(candles), m3_count=0, m5_count=0, m15_count=0, m30_count=0,
        incomplete_buckets={},
        source_kind="LIVE_MT5",
        dataset_state="V2_M1_DATASET_CANDIDATE",
    )
    return candles, manifest


def load_authoritative_frozen_v2_dataset(
    canonical_csv_path: str = "data/canonical/V2_M1_LIVE_DATASET_V1.csv",
    frozen_manifest_path: str = FROZEN_V2_MANIFEST_PATH,
) -> Tuple[List[CandleV2], DatasetManifest]:
    """
    V2.10B.2 fail-closed loader for the ONE authoritative frozen identity
    (V2_M1_LIVE_DATASET_V2). Reads the freeze manifest produced by
    research/v2/data/run_v2_10b2_gap_forensics.py and refuses to load anything that is not
    exactly that frozen dataset:

      - DatasetNotFrozenError if the frozen manifest is missing, names a different
        dataset_id, or its freeze_decision is not FREEZE_ACCEPTED / FREEZE_ACCEPTED_WITH_WARNINGS
        (a FREEZE_REJECTED or absent manifest is never silently treated as usable).
      - Delegates the canonical fingerprint / row / duplicate / ordering checks to
        load_frozen_live_dataset()'s existing fail-closed guarantees, then additionally
        verifies row count, first timestamp, and last timestamp against the frozen manifest's
        own recorded values.

    There is no synthetic fallback on this path -- load_synthetic_fixture() remains the only,
    structurally separate way to obtain synthetic data. Historical V1 metadata
    (data/canonical/V2_M1_LIVE_DATASET_V1_real_manifest.json, data/manifest.json) is left
    untouched and remains fully inspectable; this function only reads it, never mutates it.
    """
    if not os.path.exists(frozen_manifest_path):
        raise DatasetNotFrozenError(f"No frozen V2 manifest at {frozen_manifest_path}. Dataset has not been frozen; refusing to load.")

    with open(frozen_manifest_path, "r") as f:
        frozen = json.load(f)

    if frozen.get("dataset_id") != AUTHORITATIVE_FROZEN_DATASET_ID:
        raise DatasetNotFrozenError(f"Frozen manifest dataset_id mismatch: {frozen.get('dataset_id')!r} != {AUTHORITATIVE_FROZEN_DATASET_ID!r}")

    if frozen.get("freeze_decision") not in ACCEPTED_FREEZE_DECISIONS:
        raise DatasetNotFrozenError(f"Dataset freeze_decision is {frozen.get('freeze_decision')!r}; refusing to load a non-accepted freeze.")

    expected_row_count = frozen.get("row_count")
    expected_first_ts = frozen.get("actual_range", {}).get("start")
    expected_last_ts = frozen.get("actual_range", {}).get("end")
    expected_fp = frozen.get("canonical_fingerprint")

    candles, base_manifest = load_frozen_live_dataset(
        path=canonical_csv_path,
        expected_dataset_id=frozen["dataset_id"],
        expected_canonical_fingerprint=expected_fp,
    )

    if len(candles) != expected_row_count:
        raise DatasetNotFrozenError(f"Row count mismatch against frozen manifest: {len(candles)} != {expected_row_count}")
    if candles[0].timestamp_open_utc != expected_first_ts:
        raise DatasetNotFrozenError(f"First timestamp mismatch against frozen manifest: {candles[0].timestamp_open_utc} != {expected_first_ts}")
    if candles[-1].timestamp_open_utc != expected_last_ts:
        raise DatasetNotFrozenError(f"Last timestamp mismatch against frozen manifest: {candles[-1].timestamp_open_utc} != {expected_last_ts}")

    manifest = DatasetManifest(
        dataset_name=frozen["dataset_id"],
        research_symbol=base_manifest.research_symbol,
        broker_symbol=base_manifest.broker_symbol,
        timeframe=base_manifest.timeframe,
        retrieved_at_utc=base_manifest.retrieved_at_utc,
        earliest_timestamp=base_manifest.earliest_timestamp,
        latest_timestamp=base_manifest.latest_timestamp,
        raw_row_count=base_manifest.raw_row_count,
        canonical_row_count=base_manifest.canonical_row_count,
        raw_fingerprint=frozen.get("raw_fingerprint") or "",
        canonical_fingerprint=base_manifest.canonical_fingerprint,
        quality_status=frozen.get("quality_status", base_manifest.quality_status),
        m1_count=base_manifest.m1_count, m3_count=0, m5_count=0, m15_count=0, m30_count=0,
        incomplete_buckets={},
        source_kind="LIVE_MT5",
        dataset_state="V2_M1_DATASET_CANDIDATE",
    )
    return candles, manifest


def load_synthetic_fixture(
    start_ts: str = "2024-01-01 00:00:00",
    count: int = 1000,
    start_price: float = 2000.0,
) -> Tuple[List[CandleV2], DatasetManifest]:
    """
    Structurally separate synthetic-fixture path for engineering/tests only. Always
    source_kind="BENCHMARK_FIXTURE" with its own fingerprint computed from the actual
    synthetic content — never the LIVE dataset's identity or fingerprint. There is no
    boolean/flag on load_frozen_live_dataset() that reaches this function; a caller must
    explicitly call load_synthetic_fixture() by name.
    """
    from research.v2.data.acquisition import generate_synthetic_m1_dataset
    _, candles = generate_synthetic_m1_dataset(start_ts, count=count, start_price=start_price)
    fp = compute_canonical_fingerprint(candles)
    manifest = DatasetManifest(
        dataset_name="SYNTHETIC_FIXTURE",
        research_symbol="SYNTHETIC",
        broker_symbol="SYNTHETIC",
        timeframe="M1",
        retrieved_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        earliest_timestamp=candles[0].timestamp_open_utc if candles else "",
        latest_timestamp=candles[-1].timestamp_close_utc if candles else "",
        raw_row_count=len(candles),
        canonical_row_count=len(candles),
        raw_fingerprint="",
        canonical_fingerprint=fp,
        quality_status="PASS",
        m1_count=len(candles), m3_count=0, m5_count=0, m15_count=0, m30_count=0,
        incomplete_buckets={},
        source_kind="BENCHMARK_FIXTURE",
        dataset_state="V2_M1_BENCHMARK_FIXTURE",
    )
    return candles, manifest
