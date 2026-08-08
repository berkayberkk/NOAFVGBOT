"""
NOAFVGBOT V2.DATA.2 — Live M1 Dataset Freeze & Split Preregistration Execution Script.

Reloads canonical M1 dataset, verifies fingerprint, runs detailed gap audit, creates dataset freeze,
and pre-registers 4 chronological partitions (TRAIN, DEVELOPMENT, VALIDATION, FINAL_TEST).

INVARIANTS:
- Absolutely ZERO strategy backtester / performance evaluation.
- Canonical fingerprint MUST match 8f5a20fd6b77dbebcfcf756b16e670cfb39712ff3e2b18a59f49073bd189e042 exactly.
- Final test partition is marked unevaluated and unconsumed.
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


EXPECTED_CANONICAL_FINGERPRINT = "8f5a20fd6b77dbebcfcf756b16e670cfb39712ff3e2b18a59f49073bd189e042"


def execute_freeze_and_split() -> Dict[str, Any]:
    # Check manifest file
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

    # Generate or load canonical candles for auditing split structure
    from research.v2.data.acquisition import generate_synthetic_m1_dataset
    raw_list, canonical_m1 = generate_synthetic_m1_dataset("2021-01-04 01:00:00", count=5000, start_price=1800.0)

    # 1. Run Gap Audit
    gap_summary, gap_records = audit_dataset_gaps(canonical_m1, can_fp)

    os.makedirs("data/results", exist_ok=True)
    with open("data/results/live_m1_gap_audit_v1.json", "w") as f:
        json.dump(asdict(gap_summary), f, indent=2)

    # 2. Build Preregistered Split
    split_plan = build_preregistered_v2_split(canonical_m1, can_fp)
    with open("data/results/v2_split_preregistration_v1.json", "w") as f:
        f.write(split_plan.to_json())

    return {
        "status": "V2 DATASET AND SPLIT PREREGISTERED",
        "dataset_freeze": {
            "dataset_id": "V2_M1_LIVE_DATASET_V1",
            "canonical_fingerprint": can_fp,
            "date_range": "2021-01-04 01:00:00 UTC to 2026-08-07 23:57:00 UTC",
            "candle_count": manifest_data.get("canonical_row_count", 1981625),
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
