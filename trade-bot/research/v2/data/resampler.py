"""
NOAFVGBOT V2.1 — Multi-Timeframe Data Resampler.

Provides deterministic single-pass OHLCV resampling from canonical M1 input into
M3, M5, M15, and M30 timeframes according to UTC wall-clock boundaries.

INVARIANTS:
- Incomplete buckets (missing constituent M1 bars) are NOT emitted.
- Input M1 data must be strictly chronological and unique.
- No synthetic data interpolation or forward-filling.
- Full provenance metadata is returned.
"""

from datetime import datetime, timezone
from typing import List, Tuple, Dict

from research.v2.data.models import (
    CandleV2,
    Timeframe,
    ResamplingProvenance,
    compute_dataset_fingerprint,
)


def validate_m1_input(candles: List[CandleV2]) -> None:
    """Validates that input M1 data is strictly chronological and unique."""
    if not candles:
        return

    seen_timestamps = set()
    prev_dt = None

    for idx, c in enumerate(candles):
        if c.timeframe != Timeframe.M1:
            raise ValueError(f"Resampler input must be Timeframe.M1, got {c.timeframe} at index {idx}")

        ts_open = c.timestamp_open_utc
        if ts_open in seen_timestamps:
            raise ValueError(f"Duplicate M1 timestamp detected: {ts_open} at index {idx}")
        seen_timestamps.add(ts_open)

        curr_dt = datetime.fromisoformat(ts_open)
        if prev_dt is not None and curr_dt <= prev_dt:
            raise ValueError(f"M1 input out of chronological order: {prev_dt} -> {curr_dt} at index {idx}")
        prev_dt = curr_dt


def resample_m1(m1_candles: List[CandleV2], target_timeframe: Timeframe) -> Tuple[List[CandleV2], ResamplingProvenance]:
    """
    Resamples canonical M1 candles into target timeframe.
    Target candle is emitted ONLY if all expected M1 constituent bars exist.
    """
    validate_m1_input(m1_candles)
    source_fingerprint = compute_dataset_fingerprint(m1_candles)

    if target_timeframe == Timeframe.M1:
        prov = ResamplingProvenance(
            source_fingerprint=source_fingerprint,
            source_timeframe="M1",
            target_timeframe="M1",
            candle_count=len(m1_candles),
            first_close_timestamp=m1_candles[0].timestamp_close_utc if m1_candles else "",
            last_close_timestamp=m1_candles[-1].timestamp_close_utc if m1_candles else "",
            incomplete_bucket_count=0,
        )
        return list(m1_candles), prov

    target_sec = target_timeframe.seconds
    required_m1_count = target_sec // 60

    # Group M1 candles by UTC wall-clock target bucket
    buckets: Dict[int, List[CandleV2]] = {}

    for c in m1_candles:
        dt = datetime.fromisoformat(c.timestamp_open_utc).replace(tzinfo=timezone.utc)
        epoch_sec = int(dt.timestamp())
        bucket_open_epoch = (epoch_sec // target_sec) * target_sec

        if bucket_open_epoch not in buckets:
            buckets[bucket_open_epoch] = []
        buckets[bucket_open_epoch].append(c)

    resampled_candles: List[CandleV2] = []
    incomplete_count = 0

    # Sort buckets chronologically
    for b_epoch in sorted(buckets.keys()):
        constituents = buckets[b_epoch]
        if len(constituents) == required_m1_count:
            b_open_dt = datetime.fromtimestamp(b_epoch, tz=timezone.utc)
            b_close_dt = datetime.fromtimestamp(b_epoch + target_sec, tz=timezone.utc)

            open_val = constituents[0].open
            close_val = constituents[-1].close
            high_val = max(c.high for c in constituents)
            low_val = min(c.low for c in constituents)
            vol_val = sum(c.volume for c in constituents)

            derived_candle = CandleV2(
                timestamp_open_utc=b_open_dt.strftime("%Y-%m-%d %H:%M:%S"),
                timestamp_close_utc=b_close_dt.strftime("%Y-%m-%d %H:%M:%S"),
                timeframe=target_timeframe,
                open=open_val,
                high=high_val,
                low=low_val,
                close=close_val,
                volume=vol_val,
            )
            resampled_candles.append(derived_candle)
        else:
            incomplete_count += 1

    prov = ResamplingProvenance(
        source_fingerprint=source_fingerprint,
        source_timeframe="M1",
        target_timeframe=target_timeframe.name,
        resampler_version="2.1",
        candle_count=len(resampled_candles),
        first_close_timestamp=resampled_candles[0].timestamp_close_utc if resampled_candles else "",
        last_close_timestamp=resampled_candles[-1].timestamp_close_utc if resampled_candles else "",
        incomplete_bucket_count=incomplete_count,
    )

    return resampled_candles, prov
