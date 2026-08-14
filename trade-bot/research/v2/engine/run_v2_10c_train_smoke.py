"""
NOAFVGBOT V2.10C -- TRAIN-only real-data feature-wiring integration smoke runner.

Runs the causally-wired V2MultiTimeframeBacktester over bounded TRAIN-only prefixes of the
authoritative frozen V2_M1_LIVE_DATASET_V2 dataset, and reports ENGINEERING/coverage telemetry
only. This is implementation verification, not research:

- No DEVELOPMENT/VALIDATION/FINAL_TEST timestamp is ever loaded or evaluated.
- No optimization, threshold search, or ML training happens here.
- Any performance/outcome numbers the engine happens to produce are explicitly labeled
  ENGINEERING_SMOKE_ONLY / QUARANTINED / NOT_RESEARCH_EVIDENCE and must not be used to form
  research hypotheses.
- Uses ONLY research.v2.data.live_dataset.load_authoritative_frozen_v2_dataset() -- the
  fail-closed, real-only, non-synthetic-fallback loader. There is no code path here that can
  silently switch to synthetic/fixture data.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from research.v2.data.models import CandleV2
from research.v2.data.manifest import compute_canonical_fingerprint
from research.v2.data.live_dataset import load_authoritative_frozen_v2_dataset
from research.v2.data.gap_forensics import PARTITION_BOUNDARIES
from research.v2.engine.mtf_backtester import V2MultiTimeframeBacktester
from research.v2.strategy.train_policy import V2TrainResearchPolicy

# Authoritative TRAIN boundary -- single source of truth, imported (not duplicated) from the
# same PARTITION_BOUNDARIES table research/v2/data/split_preregistration.py's
# build_preregistered_v2_split() and the V2.10B.2 freeze manifest both derive from.
TRAIN_END_UTC = next(end for name, _start, end in PARTITION_BOUNDARIES if name == "TRAIN")

DEFAULT_SMOKE_SIZES = (500, 5000, 20000)


class TrainBoundaryViolationError(Exception):
    pass


def load_train_only_prefix(candles: List[CandleV2], max_count: int) -> List[CandleV2]:
    """Returns up to `max_count` leading M1 candles, but ALWAYS stops at the TRAIN boundary
    even if max_count would otherwise cross it. Never loads/returns a DEVELOPMENT+ timestamp."""
    out: List[CandleV2] = []
    for c in candles:
        if c.timestamp_open_utc >= TRAIN_END_UTC:
            break
        out.append(c)
        if len(out) >= max_count:
            break
    for c in out:
        if c.timestamp_open_utc >= TRAIN_END_UTC:
            raise TrainBoundaryViolationError(f"TRAIN boundary violated: {c.timestamp_open_utc} >= {TRAIN_END_UTC}")
    return out


def _feature_coverage_report(bt: V2MultiTimeframeBacktester) -> Dict[str, Any]:
    """ENGINEERING_SMOKE_ONLY / QUARANTINED / NOT_RESEARCH_EVIDENCE. Coverage counts only --
    NEVER win rate, expectancy, PF, or any threshold/combination ranking (section 24)."""
    report = {}
    for type_key, t in sorted(bt.feature_type_telemetry.items()):
        report[type_key] = {
            "observations": t["count"],
            "timeframes_represented": sorted(t["timeframes"]),
            "first_availability_timestamp": t["first_known_at"],
            "last_availability_timestamp": t["last_known_at"],
        }
    return report


def run_smoke_slice(all_candles: List[CandleV2], size: int) -> Dict[str, Any]:
    slice_candles = load_train_only_prefix(all_candles, size)
    if not slice_candles:
        return {"size_requested": size, "size_actual": 0, "note": "TRAIN boundary reached before any candle was available"}

    bt = V2MultiTimeframeBacktester(policy=V2TrainResearchPolicy())
    t0 = time.time()
    result = bt.run(slice_candles)
    elapsed = time.time() - t0

    return {
        "quarantine_label": "ENGINEERING_SMOKE_ONLY / QUARANTINED / NOT_RESEARCH_EVIDENCE",
        "size_requested": size,
        "size_actual": len(slice_candles),
        "train_boundary_enforced": all(c.timestamp_open_utc < TRAIN_END_UTC for c in slice_candles),
        "first_timestamp": slice_candles[0].timestamp_open_utc,
        "last_timestamp": slice_candles[-1].timestamp_open_utc,
        "runtime_seconds": elapsed,
        "events_per_second": (bt.total_events / elapsed) if elapsed > 0 else None,
        "total_events": bt.total_events,
        "peak_active_theses": bt.peak_active_theses,
        "peak_active_passports": bt.peak_active_passports,
        "created_theses": bt.created_theses,
        "invalidated_theses": bt.invalidated_theses,
        "expired_theses": bt.expired_theses,
        "passport_count": len(bt.passports),
        "feature_release_stats": dict(bt.feature_release_stats),
        "feature_state_count": sum(bt.feature_release_stats.values()),
        "feature_coverage": _feature_coverage_report(bt),
        "backtest_fingerprint": result.fingerprint,
    }


def run(sizes=DEFAULT_SMOKE_SIZES) -> Dict[str, Any]:
    canonical_csv_path = "data/canonical/V2_M1_LIVE_DATASET_V1.csv"

    candles, manifest = load_authoritative_frozen_v2_dataset(canonical_csv_path=canonical_csv_path)
    fp_before = manifest.canonical_fingerprint
    row_count_before = len(candles)

    slices_report = {}
    for size in sizes:
        slices_report[str(size)] = run_smoke_slice(candles, size)

    fp_after = compute_canonical_fingerprint(candles)
    row_count_after = len(candles)

    return {
        "dataset_identity": {
            "dataset_id": manifest.dataset_name,
            "canonical_fingerprint": fp_before,
            "canonical_row_count": row_count_before,
            "train_end_boundary_utc": TRAIN_END_UTC,
        },
        "smoke_slices": slices_report,
        "dataset_integrity": {
            "canonical_fingerprint_before": fp_before,
            "canonical_fingerprint_after": fp_after,
            "fingerprint_unchanged": fp_before == fp_after,
            "row_count_before": row_count_before,
            "row_count_after": row_count_after,
            "row_count_unchanged": row_count_before == row_count_after == 1981624,
        },
        "protection": {
            "development_evaluated": False,
            "validation_evaluated": False,
            "final_test_evaluated": False,
            "final_test_consumed": False,
            "optimization_performed": False,
            "ml_trained": False,
            "orders_sent": 0,
        },
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, default=str))
