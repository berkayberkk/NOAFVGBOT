"""
Chunked TRAIN-partition ENGINEERING coverage run.

WHY THIS EXISTS: V2MultiTimeframeBacktester keeps terminal_theses, passports, and
path_observations fully in memory for the whole run, never pruned (deliberate --
the domain model docs require full replay/provenance). Measured: ~8.5GB+ RSS at
40,000 M1 candles, ~11GB at 100,000, still not finished after 48+ minutes. The
TRAIN partition is roughly 1,000,000 M1 candles -- running it in one process is
not feasible on commodity hardware with this persistence model.

This script works around that WITHOUT touching the backtester's persistence
model or any of its provenance invariants: it splits TRAIN into independent
chunks, runs each chunk in its own fresh V2MultiTimeframeBacktester instance
(so memory is freed between chunks via gc.collect()), and merges only the
ENGINEERING/coverage telemetry (counts, coverage, timing) across chunks --
never win-rate/expectancy/PF, matching the exact quarantine discipline of
research/v2/engine/run_v2_10c_train_smoke.py.

CAVEAT (documented, not hidden): a thesis or candidate whose lifecycle would
span a chunk boundary is NOT carried over -- each chunk starts with empty
backtester state. Thesis lifetime is capped at
REFERENCE_ENGINEERING_LIFETIME_M30_BARS (24 M30 bars = 720 M1 candles), so for
a chunk_size of 20,000 this boundary effect touches at most ~3.6% of each
chunk's candles. This is an engineering-coverage approximation, not research
evidence, same as the existing smoke runner.

Status/quarantine labels are inherited unchanged: ENGINEERING_SMOKE_ONLY /
QUARANTINED / NOT_RESEARCH_EVIDENCE.
"""

from __future__ import annotations

import gc
import json
import time
from typing import Any, Dict, List

from research.v2.data.live_dataset import load_authoritative_frozen_v2_dataset
from research.v2.data.gap_forensics import PARTITION_BOUNDARIES
from research.v2.engine.mtf_backtester import V2MultiTimeframeBacktester
from research.v2.engine.run_v2_10c_train_smoke import (
    load_train_only_prefix, _feature_coverage_report, TRAIN_END_UTC,
)
from research.v2.strategy.train_policy import V2TrainResearchPolicy

DEFAULT_CHUNK_SIZE = 20000


def _log(msg: str) -> None:
    print(f"[chunked_train] {msg}", flush=True)


def run_chunk(chunk_candles: List[Any]) -> Dict[str, Any]:
    """Runs one chunk in a fresh backtester instance and returns ENGINEERING telemetry only."""
    bt = V2MultiTimeframeBacktester(policy=V2TrainResearchPolicy())
    t0 = time.time()
    result = bt.run(chunk_candles)
    elapsed = time.time() - t0

    report = {
        "size_actual": len(chunk_candles),
        "first_timestamp": chunk_candles[0].timestamp_open_utc,
        "last_timestamp": chunk_candles[-1].timestamp_open_utc,
        "runtime_seconds": elapsed,
        "total_events": bt.total_events,
        "peak_active_theses": bt.peak_active_theses,
        "peak_active_passports": bt.peak_active_passports,
        "created_theses": bt.created_theses,
        "invalidated_theses": bt.invalidated_theses,
        "expired_theses": bt.expired_theses,
        "passport_count": len(bt.passports),
        "feature_release_stats": dict(bt.feature_release_stats),
        "feature_coverage": _feature_coverage_report(bt),
        "backtest_fingerprint": result.fingerprint,
    }

    # Explicitly drop references before returning so gc.collect() in the caller
    # can actually reclaim terminal_theses/passports/path_observations.
    del bt, result
    return report


def merge_chunk_reports(chunk_reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged_feature_coverage: Dict[str, Dict[str, Any]] = {}
    for rep in chunk_reports:
        for feat_type, cov in rep["feature_coverage"].items():
            if feat_type not in merged_feature_coverage:
                merged_feature_coverage[feat_type] = {
                    "observations": 0, "timeframes_represented": set(),
                    "first_availability_timestamp": cov["first_availability_timestamp"],
                    "last_availability_timestamp": cov["last_availability_timestamp"],
                }
            m = merged_feature_coverage[feat_type]
            m["observations"] += cov["observations"]
            m["timeframes_represented"] = set(m["timeframes_represented"]) | set(cov["timeframes_represented"])
            if cov["first_availability_timestamp"] < m["first_availability_timestamp"]:
                m["first_availability_timestamp"] = cov["first_availability_timestamp"]
            if cov["last_availability_timestamp"] > m["last_availability_timestamp"]:
                m["last_availability_timestamp"] = cov["last_availability_timestamp"]

    for m in merged_feature_coverage.values():
        m["timeframes_represented"] = sorted(m["timeframes_represented"])

    return {
        "chunk_count": len(chunk_reports),
        "size_actual_total": sum(r["size_actual"] for r in chunk_reports),
        "first_timestamp": chunk_reports[0]["first_timestamp"] if chunk_reports else None,
        "last_timestamp": chunk_reports[-1]["last_timestamp"] if chunk_reports else None,
        "runtime_seconds_total": sum(r["runtime_seconds"] for r in chunk_reports),
        "total_events": sum(r["total_events"] for r in chunk_reports),
        "peak_active_theses_max_across_chunks": max((r["peak_active_theses"] for r in chunk_reports), default=0),
        "peak_active_passports_max_across_chunks": max((r["peak_active_passports"] for r in chunk_reports), default=0),
        "created_theses_total": sum(r["created_theses"] for r in chunk_reports),
        "invalidated_theses_total": sum(r["invalidated_theses"] for r in chunk_reports),
        "expired_theses_total": sum(r["expired_theses"] for r in chunk_reports),
        "passport_count_total": sum(r["passport_count"] for r in chunk_reports),
        "feature_coverage_merged": merged_feature_coverage,
        "per_chunk_reports": chunk_reports,
    }


def run(chunk_size: int = DEFAULT_CHUNK_SIZE, max_chunks: "int | None" = None) -> Dict[str, Any]:
    canonical_csv_path = "data/canonical/V2_M1_LIVE_DATASET_V1.csv"
    candles, manifest = load_authoritative_frozen_v2_dataset(canonical_csv_path=canonical_csv_path)

    train_candles = load_train_only_prefix(candles, len(candles))  # full TRAIN prefix
    del candles
    gc.collect()

    n_chunks_total = (len(train_candles) + chunk_size - 1) // chunk_size
    n_chunks_to_run = min(max_chunks, n_chunks_total) if max_chunks else n_chunks_total

    _log(f"TRAIN candles={len(train_candles)}, chunk_size={chunk_size}, "
         f"chunks_total={n_chunks_total}, chunks_to_run={n_chunks_to_run}")

    chunk_reports = []
    for i in range(n_chunks_to_run):
        start = i * chunk_size
        end = min(start + chunk_size, len(train_candles))
        chunk = train_candles[start:end]

        t0 = time.time()
        rep = run_chunk(chunk)
        gc.collect()
        _log(f"chunk {i+1}/{n_chunks_to_run}: [{rep['first_timestamp']} .. {rep['last_timestamp']}] "
             f"events={rep['total_events']} theses={rep['created_theses']} "
             f"passports={rep['passport_count']} elapsed={time.time()-t0:.1f}s")
        chunk_reports.append(rep)

    merged = merge_chunk_reports(chunk_reports)
    merged["quarantine_label"] = "ENGINEERING_SMOKE_ONLY / QUARANTINED / NOT_RESEARCH_EVIDENCE"
    merged["chunking_caveat"] = (
        "Theses/candidates spanning a chunk boundary are dropped, not carried over. "
        f"Thesis lifetime cap is 720 M1 candles vs chunk_size={chunk_size}, "
        f"so boundary effect is bounded to ~{720/chunk_size:.1%} of each chunk."
    )
    merged["train_end_boundary_utc"] = TRAIN_END_UTC
    merged["dataset_fingerprint"] = manifest.canonical_fingerprint
    merged["full_train_run"] = (n_chunks_to_run == n_chunks_total)
    return merged


if __name__ == "__main__":
    import sys
    chunk_size = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CHUNK_SIZE
    max_chunks = int(sys.argv[2]) if len(sys.argv) > 2 else None
    result = run(chunk_size=chunk_size, max_chunks=max_chunks)
    out_path = "research/v2/results/v2_train_chunked_coverage.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"Wrote {out_path}")
    print(json.dumps({k: v for k, v in result.items() if k != "per_chunk_reports"}, indent=2, default=str))
