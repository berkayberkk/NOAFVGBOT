"""
NOAFVGBOT V2.DATA.2 — Chronological Dataset Split Preregistration Module.

Defines immutable pre-registered chronological partitions (TRAIN, DEVELOPMENT, VALIDATION, FINAL_TEST)
for V2 research BEFORE any strategy performance evaluation.

INVARIANTS:
- Chronological partitioning with zero overlap and zero shuffling.
- Final Test partition is 100% sacred, unevaluated, and unconsumed.
- No strategy performance metrics, win rates, or PnL values.
- Deterministic split plan fingerprint calculation.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional

from research.v2.data.models import CandleV2


@dataclass(frozen=True)
class PartitionBoundary:
    name: str  # "TRAIN", "DEVELOPMENT", "VALIDATION", "FINAL_TEST"
    start_timestamp_utc: str
    end_timestamp_utc: str
    m1_count: int
    context_start_utc: str
    scoring_start_utc: str


def compute_split_plan_fingerprint(
    canonical_fingerprint: str,
    partitions: List[PartitionBoundary],
    rules: Dict[str, str],
) -> str:
    """Computes a deterministic SHA256 fingerprint for the pre-registered split plan."""
    hasher = hashlib.sha256()
    hasher.update(canonical_fingerprint.encode("utf-8"))

    for p in partitions:
        p_dict = {
            "name": p.name,
            "start": p.start_timestamp_utc,
            "end": p.end_timestamp_utc,
            "m1_count": p.m1_count,
            "context_start": p.context_start_utc,
            "scoring_start": p.scoring_start_utc,
        }
        hasher.update(json.dumps(p_dict, sort_keys=True).encode("utf-8"))

    hasher.update(json.dumps(rules, sort_keys=True).encode("utf-8"))
    return hasher.hexdigest()


@dataclass(frozen=True)
class DatasetSplitPreregistration:
    dataset_id: str
    canonical_fingerprint: str
    partitions: Tuple[PartitionBoundary, ...]
    split_plan_fingerprint: str
    thesis_assignment_rule: str = "THESIS_CREATION_TIMESTAMP"
    child_inheritance_rule: str = "INHERIT_PARENT_THESIS_PARTITION"
    boundary_censoring_rule: str = "CENSOR_AT_PARTITION_END"
    warmup_context_rule: str = "WARMUP_ALLOWED_NO_SCORED_EVIDENCE"
    validation_evaluated: bool = False
    final_test_evaluated: bool = False
    final_test_consumed: bool = False
    schema_version: str = "2.DATA.2"

    def to_json(self) -> str:
        """Serializes preregistration to canonical JSON string."""
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def build_preregistered_v2_split(
    candles: List[CandleV2],
    canonical_fingerprint: str,
) -> DatasetSplitPreregistration:
    """Constructs the canonical pre-registered 4-partition split plan for V2 research."""
    sorted_candles = sorted(candles, key=lambda c: c.timestamp_open_utc)

    # Pre-registered chronological date boundaries
    # TRAIN (~50%): 2021-01-04 to 2023-10-31
    # DEVELOPMENT (~20%): 2023-11-01 to 2024-12-31
    # VALIDATION (~15%): 2025-01-01 to 2025-10-31
    # FINAL_TEST (~15%): 2025-11-01 to 2026-08-07

    train_c = [c for c in sorted_candles if c.timestamp_open_utc < "2023-11-01 00:00:00"]
    dev_c = [c for c in sorted_candles if "2023-11-01 00:00:00" <= c.timestamp_open_utc < "2025-01-01 00:00:00"]
    val_c = [c for c in sorted_candles if "2025-01-01 00:00:00" <= c.timestamp_open_utc < "2025-11-01 00:00:00"]
    test_c = [c for c in sorted_candles if c.timestamp_open_utc >= "2025-11-01 00:00:00"]

    partitions = [
        PartitionBoundary(
            name="TRAIN",
            start_timestamp_utc=train_c[0].timestamp_open_utc if train_c else "2021-01-04 01:00:00",
            end_timestamp_utc=train_c[-1].timestamp_open_utc if train_c else "2023-10-31 23:59:00",
            m1_count=len(train_c),
            context_start_utc=train_c[0].timestamp_open_utc if train_c else "2021-01-04 01:00:00",
            scoring_start_utc=train_c[0].timestamp_open_utc if train_c else "2021-01-04 01:00:00",
        ),
        PartitionBoundary(
            name="DEVELOPMENT",
            start_timestamp_utc=dev_c[0].timestamp_open_utc if dev_c else "2023-11-01 00:00:00",
            end_timestamp_utc=dev_c[-1].timestamp_open_utc if dev_c else "2024-12-31 23:59:00",
            m1_count=len(dev_c),
            context_start_utc="2023-10-15 00:00:00",  # Warmup context start
            scoring_start_utc=dev_c[0].timestamp_open_utc if dev_c else "2023-11-01 00:00:00",
        ),
        PartitionBoundary(
            name="VALIDATION",
            start_timestamp_utc=val_c[0].timestamp_open_utc if val_c else "2025-01-01 00:00:00",
            end_timestamp_utc=val_c[-1].timestamp_open_utc if val_c else "2025-10-31 23:59:00",
            m1_count=len(val_c),
            context_start_utc="2024-12-15 00:00:00",
            scoring_start_utc=val_c[0].timestamp_open_utc if val_c else "2025-01-01 00:00:00",
        ),
        PartitionBoundary(
            name="FINAL_TEST",
            start_timestamp_utc=test_c[0].timestamp_open_utc if test_c else "2025-11-01 00:00:00",
            end_timestamp_utc=test_c[-1].timestamp_open_utc if test_c else "2026-08-07 23:57:00",
            m1_count=len(test_c),
            context_start_utc="2025-10-15 00:00:00",
            scoring_start_utc=test_c[0].timestamp_open_utc if test_c else "2025-11-01 00:00:00",
        ),
    ]

    rules = {
        "thesis_assignment_rule": "THESIS_CREATION_TIMESTAMP",
        "child_inheritance_rule": "INHERIT_PARENT_THESIS_PARTITION",
        "boundary_censoring_rule": "CENSOR_AT_PARTITION_END",
        "warmup_context_rule": "WARMUP_ALLOWED_NO_SCORED_EVIDENCE",
    }

    split_fp = compute_split_plan_fingerprint(canonical_fingerprint, partitions, rules)

    return DatasetSplitPreregistration(
        dataset_id="V2_M1_LIVE_DATASET_V1",
        canonical_fingerprint=canonical_fingerprint,
        partitions=tuple(partitions),
        split_plan_fingerprint=split_fp,
        thesis_assignment_rule=rules["thesis_assignment_rule"],
        child_inheritance_rule=rules["child_inheritance_rule"],
        boundary_censoring_rule=rules["boundary_censoring_rule"],
        warmup_context_rule=rules["warmup_context_rule"],
        validation_evaluated=False,
        final_test_evaluated=False,
        final_test_consumed=False,
    )
