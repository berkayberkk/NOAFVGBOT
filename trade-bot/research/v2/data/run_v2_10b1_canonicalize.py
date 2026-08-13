"""
NOAFVGBOT V2.10B.1 -- RAW audit, canonicalization, and legacy fingerprint comparison.

Continuation of the V2.10B.1 mission after data/raw/V2_10B1_XAUUSD_GOLD_M1_raw.csv has been
fully acquired by run_chunked_acquisition.py. This script:

  1. RAW audits the raw CSV (strict parseability, chronological ordering, duplicate timestamps,
     OHLC integrity) BEFORE trusting it for anything.
  2. Canonicalizes it (dedupe by timestamp_open_utc keeping first occurrence, sort) via the
     existing research/v2/data/acquisition.py:convert_raw_to_canonical_m1.
  3. Runs the existing gap-classification audit (research/v2/data/gap_audit.py).
  4. Writes the canonical series to data/canonical/V2_M1_LIVE_DATASET_V1.csv in the tab-separated
     MT5-History-Center-export format that research/v2/data/live_dataset.py's
     parse_mt5_m1_export_csv expects.
  5. Computes the canonical fingerprint via BOTH known algorithms in this codebase
     (manifest.py:compute_canonical_fingerprint -- the one live_dataset.py actually uses -- and
     models.py:compute_dataset_fingerprint) and compares both against the LEGACY_UNVERIFIED
     value 8f5a20fd6b77dbebcfcf756b16e670cfb39712ff3e2b18a59f49073bd189e042 already declared in
     data/manifest.json.
  6. NEVER alters the newly acquired real data to force a fingerprint match. If it differs,
     preserves evidence under a V2_M1_LIVE_DATASET_V2 identity manifest without touching
     data/manifest.json or the V1 dataset_id.

No strategy backtesting, no TRAIN/DEV/VAL/FINAL_TEST execution happens here.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from research.v2.data.models import CandleV2, Timeframe, compute_dataset_fingerprint
from research.v2.data.acquisition import convert_raw_to_canonical_m1
from research.v2.data.audit import audit_m1_dataset
from research.v2.data.gap_audit import audit_dataset_gaps
from research.v2.data.manifest import compute_raw_fingerprint, compute_canonical_fingerprint, DatasetManifest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RAW_PATH = os.path.join(REPO_ROOT, "data", "raw", "V2_10B1_XAUUSD_GOLD_M1_raw.csv")
CANONICAL_DIR = os.path.join(REPO_ROOT, "data", "canonical")
CANONICAL_CSV_PATH = os.path.join(CANONICAL_DIR, "V2_M1_LIVE_DATASET_V1.csv")
RESULTS_DIR = os.path.join(REPO_ROOT, "data", "results")

LEGACY_CANONICAL_FINGERPRINT = "8f5a20fd6b77dbebcfcf756b16e670cfb39712ff3e2b18a59f49073bd189e042"
LEGACY_STATUS = "LEGACY_UNVERIFIED"


class RawAuditError(Exception):
    pass


def load_raw_rows(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        raise RawAuditError(f"Raw file not found: {path}")

    rows: List[Dict[str, Any]] = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        expected_fields = {"time", "timestamp_open_utc", "open", "high", "low", "close", "tick_volume", "spread"}
        if set(reader.fieldnames or []) != expected_fields:
            raise RawAuditError(f"Unexpected raw CSV header: {reader.fieldnames}")

        for line_num, row in enumerate(reader, start=2):
            try:
                parsed = {
                    "time": int(row["time"]),
                    "timestamp_open_utc": row["timestamp_open_utc"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "tick_volume": int(row["tick_volume"]),
                    "spread": int(row["spread"]),
                }
                datetime.fromisoformat(parsed["timestamp_open_utc"])
            except (ValueError, TypeError, KeyError) as e:
                raise RawAuditError(f"Strictly-parseable-row violation at raw CSV line {line_num}: {row!r} ({e})")
            rows.append(parsed)

    if not rows:
        raise RawAuditError("Raw CSV parsed to zero rows.")
    return rows


def raw_audit_report(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    ts_list = [r["timestamp_open_utc"] for r in rows]
    is_sorted_as_persisted = all(ts_list[i] <= ts_list[i + 1] for i in range(len(ts_list) - 1))

    seen: Dict[str, Dict[str, Any]] = {}
    exact_dups = 0
    conflicting_dups = 0
    for r in rows:
        ts = r["timestamp_open_utc"]
        if ts in seen:
            prev = seen[ts]
            if (prev["open"], prev["high"], prev["low"], prev["close"]) == (r["open"], r["high"], r["low"], r["close"]):
                exact_dups += 1
            else:
                conflicting_dups += 1
        else:
            seen[ts] = r

    ohlc_violations = 0
    for r in rows:
        max_oc = max(r["open"], r["close"])
        min_oc = min(r["open"], r["close"])
        if r["high"] < max_oc - 1e-9 or r["low"] > min_oc + 1e-9 or r["high"] < r["low"] - 1e-9:
            ohlc_violations += 1

    return {
        "raw_row_count": len(rows),
        "strictly_parseable": True,
        "persisted_order_chronological": is_sorted_as_persisted,
        "earliest_timestamp": min(ts_list),
        "latest_timestamp": max(ts_list),
        "exact_duplicate_timestamps": exact_dups,
        "conflicting_duplicate_timestamps": conflicting_dups,
        "raw_ohlc_violations": ohlc_violations,
    }


def write_canonical_csv(candles: List[CandleV2], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["<DATE>", "<TIME>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>", "<TICKVOL>", "<VOL>", "<SPREAD>"])
        for c in candles:
            dt_open = datetime.fromisoformat(c.timestamp_open_utc)
            w.writerow([
                dt_open.strftime("%Y.%m.%d"),
                dt_open.strftime("%H:%M:%S"),
                f"{c.open:.5f}", f"{c.high:.5f}", f"{c.low:.5f}", f"{c.close:.5f}",
                int(c.volume), 0, 0,
            ])
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def run() -> Dict[str, Any]:
    raw_rows = load_raw_rows(RAW_PATH)
    audit = raw_audit_report(raw_rows)
    if audit["conflicting_duplicate_timestamps"] > 0 or audit["raw_ohlc_violations"] > 0:
        raise RawAuditError(f"RAW audit failed closed: {audit}")

    canonical = convert_raw_to_canonical_m1(raw_rows)
    if not canonical:
        raise RawAuditError("Canonicalization produced zero candles.")

    write_canonical_csv(canonical, CANONICAL_CSV_PATH)

    quality_report = audit_m1_dataset(canonical, raw_row_count=len(raw_rows))
    gap_summary, gap_records = audit_dataset_gaps(canonical, dataset_fingerprint="PENDING")

    raw_fp = compute_raw_fingerprint(raw_rows)
    can_fp_manifest_algo = compute_canonical_fingerprint(canonical)
    can_fp_models_algo = compute_dataset_fingerprint(canonical)

    legacy_match_manifest_algo = (can_fp_manifest_algo == LEGACY_CANONICAL_FINGERPRINT)
    legacy_match_models_algo = (can_fp_models_algo == LEGACY_CANONICAL_FINGERPRINT)
    any_legacy_match = legacy_match_manifest_algo or legacy_match_models_algo

    manifest_json_path = os.path.join(REPO_ROOT, "data", "manifest.json")
    with open(manifest_json_path, "r") as f:
        legacy_manifest = json.load(f)

    real_manifest = DatasetManifest(
        dataset_name="XAUUSD_M1_HISTORICAL",
        research_symbol="XAUUSD",
        broker_symbol="GOLD",
        timeframe="M1",
        retrieved_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        earliest_timestamp=canonical[0].timestamp_open_utc,
        latest_timestamp=canonical[-1].timestamp_open_utc,
        raw_row_count=len(raw_rows),
        canonical_row_count=len(canonical),
        raw_fingerprint=raw_fp,
        canonical_fingerprint=can_fp_manifest_algo,
        quality_status=quality_report.quality_status.value,
        m1_count=len(canonical), m3_count=0, m5_count=0, m15_count=0, m30_count=0,
        incomplete_buckets={},
        source_kind="LIVE_MT5",
        dataset_state="V2_M1_DATASET_CANDIDATE",
    )

    os.makedirs(RESULTS_DIR, exist_ok=True)
    real_manifest_path = os.path.join(CANONICAL_DIR, "V2_M1_LIVE_DATASET_V1_real_manifest.json")
    with open(real_manifest_path, "w") as f:
        f.write(real_manifest.to_json())

    dataset_identity = "V2_M1_LIVE_DATASET_V1"
    if not any_legacy_match:
        # Preserve evidence under a distinct identity; V1's manifest.json / fingerprint is
        # NEVER overwritten and the real data is NEVER altered to force a match.
        dataset_identity = "V2_M1_LIVE_DATASET_V2"
        v2_manifest_path = os.path.join(CANONICAL_DIR, "V2_M1_LIVE_DATASET_V2_real_manifest.json")
        v2_manifest = DatasetManifest(
            dataset_name="V2_M1_LIVE_DATASET_V2",
            research_symbol="XAUUSD",
            broker_symbol="GOLD",
            timeframe="M1",
            retrieved_at_utc=real_manifest.retrieved_at_utc,
            earliest_timestamp=real_manifest.earliest_timestamp,
            latest_timestamp=real_manifest.latest_timestamp,
            raw_row_count=real_manifest.raw_row_count,
            canonical_row_count=real_manifest.canonical_row_count,
            raw_fingerprint=raw_fp,
            canonical_fingerprint=can_fp_manifest_algo,
            quality_status=real_manifest.quality_status,
            m1_count=real_manifest.m1_count, m3_count=0, m5_count=0, m15_count=0, m30_count=0,
            incomplete_buckets={},
            source_kind="LIVE_MT5",
            dataset_state="V2_M1_DATASET_CANDIDATE",
        )
        with open(v2_manifest_path, "w") as f:
            f.write(v2_manifest.to_json())

    return {
        "raw_audit": audit,
        "quality_status": quality_report.quality_status.value,
        "quality_issue_counts": {
            "ohlc_violations": quality_report.ohlc_violations_count,
            "non_finite": quality_report.non_finite_values_count,
            "non_positive": quality_report.non_positive_values_count,
            "exact_duplicates_removed": quality_report.exact_duplicates_removed,
            "conflicting_duplicates": quality_report.conflicting_duplicates_count,
            "weekend_gaps": quality_report.weekend_gaps_count,
            "daily_break_gaps": quality_report.daily_break_gaps_count,
            "suspicious_intraday_gaps": quality_report.suspicious_intraday_gaps_count,
            "extreme_move_warnings": quality_report.extreme_move_warnings_count,
        },
        "gap_audit_summary": {
            "total_gaps": gap_summary.total_gaps,
            "category_counts": gap_summary.category_counts,
            "materiality_conclusion": gap_summary.materiality_conclusion,
            "unresolved_suspicious_gaps": gap_summary.unresolved_suspicious_gaps,
        },
        "canonical_row_count": len(canonical),
        "canonical_first_timestamp": canonical[0].timestamp_open_utc,
        "canonical_last_timestamp": canonical[-1].timestamp_open_utc,
        "raw_fingerprint": raw_fp,
        "canonical_fingerprint_manifest_algo": can_fp_manifest_algo,
        "canonical_fingerprint_models_algo": can_fp_models_algo,
        "legacy_fingerprint": LEGACY_CANONICAL_FINGERPRINT,
        "legacy_status": LEGACY_STATUS,
        "legacy_match_manifest_algo": legacy_match_manifest_algo,
        "legacy_match_models_algo": legacy_match_models_algo,
        "legacy_declared_row_count": legacy_manifest.get("canonical_row_count"),
        "legacy_declared_earliest": legacy_manifest.get("earliest_timestamp"),
        "legacy_declared_latest": legacy_manifest.get("latest_timestamp"),
        "dataset_identity_used": dataset_identity,
        "real_manifest_path": real_manifest_path,
        "canonical_csv_path": CANONICAL_CSV_PATH,
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, default=str))
