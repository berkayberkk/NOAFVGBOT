"""
NOAFVGBOT V2.DATA.1 — Dataset Provenance & Manifest Module.

Provides deterministic SHA256 content hashing for raw broker data and canonical CandleV2 series,
and generates human/machine-readable dataset manifests for historical dataset freeze.

INVARIANTS:
- Fingerprints depend ONLY on canonical data content, never on file paths, retrieval timestamps, or machine names.
- Manifest contains NO strategy performance metrics, win rates, or PnL values.
- Dataset state is V2_M1_DATASET_CANDIDATE.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional

from research.v2.data.models import CandleV2


def compute_raw_fingerprint(raw_rows: List[Dict[str, Any]]) -> str:
    """Computes a deterministic content-based SHA256 fingerprint for raw broker data rows."""
    hasher = hashlib.sha256()
    sorted_rows = sorted(raw_rows, key=lambda r: r.get("time", r.get("timestamp_open_utc", "")))

    for r in sorted_rows:
        row_str = json.dumps(r, sort_keys=True, default=str)
        hasher.update(row_str.encode("utf-8"))

    return hasher.hexdigest()


def compute_canonical_fingerprint(candles: List[CandleV2], schema_version: str = "2.DATA.1") -> str:
    """Computes a deterministic content-based SHA256 fingerprint for canonical CandleV2 series."""
    hasher = hashlib.sha256()
    hasher.update(schema_version.encode("utf-8"))

    sorted_candles = sorted(candles, key=lambda c: (c.timestamp_open_utc, c.timeframe.name))

    for c in sorted_candles:
        c_dict = {
            "timestamp_open_utc": c.timestamp_open_utc,
            "timestamp_close_utc": c.timestamp_close_utc,
            "timeframe": c.timeframe.name,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        hasher.update(json.dumps(c_dict, sort_keys=True).encode("utf-8"))

    return hasher.hexdigest()


@dataclass(frozen=True)
class DatasetManifest:
    dataset_name: str
    research_symbol: str
    broker_symbol: str
    timeframe: str
    retrieved_at_utc: str
    earliest_timestamp: str
    latest_timestamp: str
    raw_row_count: int
    canonical_row_count: int
    raw_fingerprint: str
    canonical_fingerprint: str
    quality_status: str
    m1_count: int
    m3_count: int
    m5_count: int
    m15_count: int
    m30_count: int
    incomplete_buckets: Dict[str, int]
    source_kind: str = "BENCHMARK_FIXTURE"  # "BENCHMARK_FIXTURE" or "LIVE_MT5"
    schema_version: str = "2.DATA.1"
    acquisition_version: str = "2.DATA.1"
    dataset_state: str = "V2_M1_BENCHMARK_FIXTURE"

    def __post_init__(self) -> None:
        # Enforce strict dataset_state namespacing based on source_kind
        if self.source_kind == "BENCHMARK_FIXTURE" and self.dataset_state == "V2_M1_DATASET_CANDIDATE":
            raise ValueError("Fallback BENCHMARK_FIXTURE cannot be promoted to V2_M1_DATASET_CANDIDATE")

    def to_json(self) -> str:
        """Serializes manifest to canonical JSON string."""
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def validate_dataset_for_research(manifest: DatasetManifest, allow_fixture: bool = False) -> None:
    """
    Validates dataset manifest suitability for research backtests.
    Fails closed if source_kind is BENCHMARK_FIXTURE unless allow_fixture is explicitly True.
    """
    if manifest.source_kind == "BENCHMARK_FIXTURE" and not allow_fixture:
        raise ValueError(
            "Cannot run V2 research backtest on BENCHMARK_FIXTURE dataset. "
            "Real LIVE_MT5 dataset candidate required."
        )
    if manifest.quality_status == "FAIL":
        raise ValueError(f"Cannot run V2 research backtest on dataset with quality_status FAIL")
