"""
NOAFVGBOT V2.10B.1 -- Reproducibility, exact partition counts, and authoritative loader
verification (final phase before pytest / git diff --check).

No strategy performance evaluation. No TRAIN/DEV/VAL/FINAL_TEST execution -- only pre-registered
chronological partition boundary counts, which is explicitly policy, not evaluation.
"""

from __future__ import annotations

import json
import os
from typing import Dict

from research.v2.data.live_dataset import (
    load_frozen_live_dataset,
    DatasetFileMissingError,
    DatasetIntegrityError,
    DatasetIdentityMismatchError,
)
from research.v2.data.manifest import compute_canonical_fingerprint
from research.v2.data.split_preregistration import build_preregistered_v2_split
from research.v2.data.run_data_freeze_and_split import execute_freeze_and_split, EXPECTED_CANONICAL_FINGERPRINT

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CANONICAL_CSV_PATH = os.path.join(REPO_ROOT, "data", "canonical", "V2_M1_LIVE_DATASET_V1.csv")


def run() -> Dict:
    from research.v2.data.live_dataset import parse_mt5_m1_export_csv

    candles = parse_mt5_m1_export_csv(CANONICAL_CSV_PATH)
    candles_sorted = sorted(candles, key=lambda c: c.timestamp_open_utc)

    fp1 = compute_canonical_fingerprint(candles_sorted)
    fp2 = compute_canonical_fingerprint(candles_sorted)
    fp3 = compute_canonical_fingerprint(list(reversed(candles_sorted)))  # order-independence check

    reproducibility = {
        "fingerprint_run_1": fp1,
        "fingerprint_run_2": fp2,
        "fingerprint_run_3_reversed_input_order": fp3,
        "deterministic": (fp1 == fp2 == fp3),
    }

    split_plan = build_preregistered_v2_split(candles_sorted, fp1)
    partition_counts = {
        p.name: {"start": p.start_timestamp_utc, "end": p.end_timestamp_utc, "m1_count": p.m1_count}
        for p in split_plan.partitions
    }
    total_partitioned = sum(p.m1_count for p in split_plan.partitions)

    # Authoritative loader verification: confirm load_frozen_live_dataset's fail-closed
    # guarantee holds correctly against the LEGACY_UNVERIFIED expected fingerprint.
    loader_result: Dict = {}
    try:
        _, manifest = load_frozen_live_dataset(
            path=CANONICAL_CSV_PATH,
            expected_dataset_id="V2_M1_LIVE_DATASET_V1",
            expected_canonical_fingerprint=EXPECTED_CANONICAL_FINGERPRINT,
        )
        loader_result = {"outcome": "SUCCEEDED_UNEXPECTEDLY", "manifest": json.loads(manifest.to_json())}
    except DatasetIdentityMismatchError as e:
        loader_result = {"outcome": "CORRECTLY_FAILED_CLOSED_ON_FINGERPRINT_MISMATCH", "detail": str(e)}
    except (DatasetFileMissingError, DatasetIntegrityError) as e:
        loader_result = {"outcome": "UNEXPECTED_FAILURE", "detail": str(e)}

    freeze_and_split_result = execute_freeze_and_split(live_dataset_path=CANONICAL_CSV_PATH)

    return {
        "reproducibility": reproducibility,
        "exact_partition_counts": partition_counts,
        "total_partitioned_m1_count": total_partitioned,
        "canonical_row_count": len(candles_sorted),
        "partition_count_matches_canonical": (total_partitioned == len(candles_sorted)),
        "authoritative_loader_verification": loader_result,
        "execute_freeze_and_split_result": freeze_and_split_result,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
