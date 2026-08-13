"""
NOAFVGBOT V2.DATA.2 — Live M1 Dataset Freeze & Split Preregistration Execution Script.

Reloads canonical M1 dataset, verifies fingerprint, runs detailed gap audit, creates dataset freeze,
and pre-registers 4 chronological partitions (TRAIN, DEVELOPMENT, VALIDATION, FINAL_TEST).

INVARIANTS:
- Absolutely ZERO strategy backtester / performance evaluation.
- Canonical fingerprint MUST match 8f5a20fd6b77dbebcfcf756b16e670cfb39712ff3e2b18a59f49073bd189e042 exactly.
- Final test partition is marked unevaluated and unconsumed.

V2.10B FIX: this script previously read the REAL fingerprint from data/manifest.json, then
computed the gap audit and split-plan artifacts from 5,000 rows of SYNTHETIC data — stamping
those synthetic-derived statistics with the real dataset's fingerprint (CRITICAL-4 finding).
It now loads the real canonical file via research.v2.data.live_dataset.load_frozen_live_dataset
(no synthetic fallback of any kind) and fails closed with status "REAL DATASET MISSING" if that
file is not present. It will never again stamp the real fingerprint onto synthetic statistics.
"""

from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from typing import Any, Dict, List

from research.v2.data.models import CandleV2, Timeframe
from research.v2.data.gap_audit import audit_dataset_gaps, GapAuditSummary
from research.v2.data.split_preregistration import build_preregistered_v2_split, DatasetSplitPreregistration
from research.v2.data.manifest import compute_canonical_fingerprint, DatasetManifest
from research.v2.data.live_dataset import (
    load_frozen_live_dataset,
    DatasetFileMissingError,
    DatasetIntegrityError,
    DatasetIdentityMismatchError,
)


EXPECTED_DATASET_ID = "V2_M1_LIVE_DATASET_V1"
EXPECTED_CANONICAL_FINGERPRINT = "8f5a20fd6b77dbebcfcf756b16e670cfb39712ff3e2b18a59f49073bd189e042"
DEFAULT_LIVE_DATASET_PATH = "data/canonical/V2_M1_LIVE_DATASET_V1.csv"


def execute_freeze_and_split(live_dataset_path: str = DEFAULT_LIVE_DATASET_PATH) -> Dict[str, Any]:
    # Check manifest file (identity cross-check only; the manifest is NOT itself a data source)
    manifest_path = "data/manifest.json"
    if not os.path.exists(manifest_path):
        return {"status": "DATASET FREEZE BLOCKED", "reason": "data/manifest.json does not exist"}

    with open(manifest_path, "r") as f:
        manifest_data = json.load(f)

    can_fp = manifest_data.get("canonical_fingerprint", "")
    if can_fp != EXPECTED_CANONICAL_FINGERPRINT:
        return {
            "status": "DATASET FREEZE FAILED",
            "reason": f"Fingerprint mismatch. Expected {EXPECTED_CANONICAL_FINGERPRINT}, got {can_fp}",
        }

    # Load the REAL canonical candles. No synthetic fallback exists on this path.
    try:
        canonical_m1, live_manifest = load_frozen_live_dataset(
            path=live_dataset_path,
            expected_dataset_id=EXPECTED_DATASET_ID,
            expected_canonical_fingerprint=can_fp,
        )
    except DatasetFileMissingError as e:
        return {
            "status": "REAL DATASET MISSING",
            "reason": str(e),
            "note": "No synthetic fallback was used. Nothing was written to data/results/.",
        }
    except (DatasetIntegrityError, DatasetIdentityMismatchError) as e:
        return {
            "status": "DATASET FREEZE FAILED",
            "reason": str(e),
            "note": "No synthetic fallback was used. Nothing was written to data/results/.",
        }

    # 1. Run Gap Audit on the real data
    gap_summary, gap_records = audit_dataset_gaps(canonical_m1, can_fp)

    os.makedirs("data/results", exist_ok=True)
    with open("data/results/live_m1_gap_audit_v1.json", "w") as f:
        json.dump(asdict(gap_summary), f, indent=2)

    # 2. Build Preregistered Split from the real data
    split_plan = build_preregistered_v2_split(canonical_m1, can_fp)
    with open("data/results/v2_split_preregistration_v1.json", "w") as f:
        f.write(split_plan.to_json())

    return {
        "status": "V2 DATASET AND SPLIT PREREGISTERED",
        "dataset_freeze": {
            "dataset_id": EXPECTED_DATASET_ID,
            "source_kind": live_manifest.source_kind,
            "canonical_fingerprint": can_fp,
            "first_timestamp": live_manifest.earliest_timestamp,
            "last_timestamp": live_manifest.latest_timestamp,
            "candle_count": live_manifest.canonical_row_count,
            "quality_status": manifest_data.get("quality_status", "WARNING"),
        },
        "gap_audit": {
            "total_gaps": gap_summary.total_gaps,
            "category_counts": gap_summary.category_counts,
            "unresolved_suspicious_gaps": gap_summary.unresolved_suspicious_gaps,
            "materiality_conclusion": gap_summary.materiality_conclusion,
        },
        "splits": {p.name: {"start": p.start_timestamp_utc, "end": p.end_timestamp_utc, "m1_count": p.m1_count} for p in split_plan.partitions},
        "boundary_policy": {
            "thesis_assignment": split_plan.thesis_assignment_rule,
            "child_inheritance": split_plan.child_inheritance_rule,
            "unresolved_candidate_behavior": split_plan.boundary_censoring_rule,
            "warmup_context_behavior": split_plan.warmup_context_rule,
        },
        "fingerprints": {
            "dataset": can_fp,
            "split_plan": split_plan.split_plan_fingerprint,
        },
        "protection": {
            "validation_evaluated": split_plan.validation_evaluated,
            "final_test_evaluated": split_plan.final_test_evaluated,
            "final_test_consumed": split_plan.final_test_consumed,
        },
        "safety": {
            "performance_metrics_calculated": False,
            "strategy_backtest_executed": False,
        },
    }


if __name__ == "__main__":
    res = execute_freeze_and_split()
    print(json.dumps(res, indent=2, default=str))
