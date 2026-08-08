"""
NOAFVGBOT V2.DATA.1 — Historical Data Acquisition & Quality Audit Pipeline.

Executes read-only M1 acquisition (MT5 broker if available, or synthetic benchmark fixture),
audits OHLC invariants, classifies duplicates and gaps, derives resampled M3/M5/M15/M30 series,
computes deterministic SHA256 fingerprints, and exports reproducible dataset manifest.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

from research.v2.data.models import Timeframe, CandleV2
from research.v2.data.acquisition import discover_broker_symbol, fetch_historical_m1_chunks, convert_raw_to_canonical_m1, generate_synthetic_m1_dataset
from research.v2.data.audit import audit_m1_dataset, DataQualityStatus
from research.v2.data.resampler import resample_m1
from research.v2.data.manifest import compute_raw_fingerprint, compute_canonical_fingerprint, DatasetManifest


def run_pipeline() -> Tuple[DatasetManifest, str]:
    research_sym, broker_sym = discover_broker_symbol()

    # Attempt MT5 fetch for up to 3 years
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=365 * 3)

    raw_rates = fetch_historical_m1_chunks(broker_sym, start_dt, end_dt, chunk_days=30)

    if raw_rates and len(raw_rates) > 100:
        source_kind = "LIVE_MT5"
        dataset_state = "V2_M1_DATASET_CANDIDATE"
        source_name = f"MT5_{broker_sym}"
        canonical_m1 = convert_raw_to_canonical_m1(raw_rates)
    else:
        source_kind = "BENCHMARK_FIXTURE"
        dataset_state = "V2_M1_BENCHMARK_FIXTURE"
        source_name = "SYNTHETIC_BENCHMARK_FIXTURE"
        raw_rates, canonical_m1 = generate_synthetic_m1_dataset("2023-01-01 00:00:00", count=5000, start_price=2000.0)

    # 1. Run Data Quality Audit
    audit_report = audit_m1_dataset(canonical_m1, raw_row_count=len(raw_rates))

    # 2. Resample into M3, M5, M15, M30
    m3, prov3 = resample_m1(canonical_m1, Timeframe.M3)
    m5, prov5 = resample_m1(canonical_m1, Timeframe.M5)
    m15, prov15 = resample_m1(canonical_m1, Timeframe.M15)
    m30, prov30 = resample_m1(canonical_m1, Timeframe.M30)

    # 3. Compute Deterministic Fingerprints
    raw_fp = compute_raw_fingerprint(raw_rates)
    can_fp = compute_canonical_fingerprint(canonical_m1)

    # 4. Construct Dataset Manifest
    manifest = DatasetManifest(
        dataset_name=f"{research_sym}_M1_HISTORICAL",
        research_symbol=research_sym,
        broker_symbol=broker_sym,
        timeframe="M1",
        retrieved_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        earliest_timestamp=audit_report.earliest_timestamp,
        latest_timestamp=audit_report.latest_timestamp,
        raw_row_count=len(raw_rates),
        canonical_row_count=len(canonical_m1),
        raw_fingerprint=raw_fp,
        canonical_fingerprint=can_fp,
        quality_status=audit_report.quality_status.value,
        m1_count=len(canonical_m1),
        m3_count=len(m3),
        m5_count=len(m5),
        m15_count=len(m15),
        m30_count=len(m30),
        incomplete_buckets={
            "M3": prov3.incomplete_bucket_count,
            "M5": prov5.incomplete_bucket_count,
            "M15": prov15.incomplete_bucket_count,
            "M30": prov30.incomplete_bucket_count,
        },
        source_kind=source_kind,
        dataset_state=dataset_state,
    )

    return manifest, source_name


if __name__ == "__main__":
    manifest, src = run_pipeline()
    print("=== DATASET MANIFEST ===")
    print(manifest.to_json())
    print(f"Source: {src}")
