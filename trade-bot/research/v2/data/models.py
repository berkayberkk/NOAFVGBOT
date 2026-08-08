"""
NOAFVGBOT V2.1 — Multi-Timeframe Data Core Models.

Defines canonical immutable representations for candles, timeframes, market events,
dataset fingerprints, and resampling provenance metadata.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import math
from typing import Any, List, Optional


class Timeframe(Enum):
    M1 = 60
    M3 = 180
    M5 = 300
    M15 = 900
    M30 = 1800

    @property
    def seconds(self) -> int:
        return self.value


@dataclass(frozen=True)
class CandleV2:
    timestamp_open_utc: str
    timestamp_close_utc: str
    timeframe: Timeframe
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        # 1. Finite and Positive Validation
        for field_name, val in [("open", self.open), ("high", self.high), ("low", self.low), ("close", self.close), ("volume", self.volume)]:
            if not math.isfinite(val):
                raise ValueError(f"Candle {field_name} must be a finite number, got: {val}")
            if field_name != "volume" and val <= 0:
                raise ValueError(f"Candle {field_name} must be positive (> 0), got: {val}")
            if field_name == "volume" and val < 0:
                raise ValueError(f"Candle volume cannot be negative, got: {val}")

        # 2. Structural High/Low Bounds
        max_oc = max(self.open, self.close)
        min_oc = min(self.open, self.close)
        if self.high < max_oc - 1e-9:
            raise ValueError(f"Candle high ({self.high}) cannot be less than max(open, close) ({max_oc})")
        if self.low > min_oc + 1e-9:
            raise ValueError(f"Candle low ({self.low}) cannot be greater than min(open, close) ({min_oc})")

        # 3. Timestamp Ordering
        try:
            t_open = datetime.fromisoformat(self.timestamp_open_utc)
            t_close = datetime.fromisoformat(self.timestamp_close_utc)
        except Exception as e:
            raise ValueError(f"Invalid UTC ISO timestamp format: {e}")

        if t_close <= t_open:
            raise ValueError(f"Candle timestamp_close_utc ({self.timestamp_close_utc}) must be > timestamp_open_utc ({self.timestamp_open_utc})")


@dataclass(frozen=True)
class MarketEvent:
    timestamp_utc: str
    timeframe: Timeframe
    candle: CandleV2


@dataclass(frozen=True)
class ResamplingProvenance:
    source_fingerprint: str
    source_timeframe: str = "M1"
    target_timeframe: str = ""
    resampler_version: str = "2.1"
    candle_count: int = 0
    first_close_timestamp: str = ""
    last_close_timestamp: str = ""
    incomplete_bucket_count: int = 0


def compute_dataset_fingerprint(candles: List[CandleV2]) -> str:
    """Calculates deterministic SHA256 content hash for a sequence of candles."""
    hasher = hashlib.sha256()
    for c in candles:
        item_str = f"{c.timestamp_open_utc}|{c.timestamp_close_utc}|{c.timeframe.name}|{c.open:.4f}|{c.high:.4f}|{c.low:.4f}|{c.close:.4f}|{c.volume:.2f}\n"
        hasher.update(item_str.encode("utf-8"))
    return hasher.hexdigest()
