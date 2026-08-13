"""
NOAFVGBOT V2.10B.1 -- Old-export cross-check and broker M30 cross-check.

Cross-checks the newly canonicalized M1 series (data/canonical/V2_M1_LIVE_DATASET_V1.csv)
against two independent references:

  1. Old MT5 History Center M30 exports already on disk (data/GOLD_M30_2yil.csv,
     data/GOLD_M30_sample.csv), by resampling the new M1 data to M30 and comparing OHLC at
     overlapping open timestamps.
  2. A fresh READ-ONLY M30 pull directly from the connected MT5 terminal for a recent sample
     window, compared the same way.

Read-only. No orders. No strategy evaluation. Reports discrepancies; does not alter data.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from research.v2.data.models import CandleV2, Timeframe
from research.v2.data.resampler import resample_m1
from research.v2.data.live_dataset import parse_mt5_m1_export_csv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CANONICAL_CSV_PATH = os.path.join(REPO_ROOT, "data", "canonical", "V2_M1_LIVE_DATASET_V1.csv")
OLD_EXPORTS = [
    os.path.join(REPO_ROOT, "data", "GOLD_M30_2yil.csv"),
    os.path.join(REPO_ROOT, "data", "GOLD_M30_sample.csv"),
]
EPS = 1e-2


def parse_m30_export(path: str) -> Dict[str, Tuple[float, float, float, float]]:
    out: Dict[str, Tuple[float, float, float, float]] = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader, None)
        for row in reader:
            if len(row) < 6:
                continue
            date_s, time_s, o, h, l, c = row[0:6]
            dt = datetime.strptime(f"{date_s} {time_s}", "%Y.%m.%d %H:%M:%S")
            ts = dt.strftime("%Y-%m-%d %H:%M:%S")
            out[ts] = (float(o), float(h), float(l), float(c))
    return out


def compare(reference: Dict[str, Tuple[float, float, float, float]], resampled: List[CandleV2], label: str) -> Dict:
    resampled_map = {c.timestamp_open_utc: (c.open, c.high, c.low, c.close) for c in resampled}
    overlap_ts = sorted(set(reference.keys()) & set(resampled_map.keys()))

    mismatches = []
    for ts in overlap_ts:
        ref_ohlc = reference[ts]
        new_ohlc = resampled_map[ts]
        if any(abs(a - b) > EPS for a, b in zip(ref_ohlc, new_ohlc)):
            mismatches.append({"timestamp": ts, "reference": ref_ohlc, "new": new_ohlc})

    return {
        "label": label,
        "reference_bar_count": len(reference),
        "new_m30_bar_count": len(resampled_map),
        "overlap_bar_count": len(overlap_ts),
        "mismatch_count": len(mismatches),
        "mismatch_sample": mismatches[:10],
        "overlap_start": overlap_ts[0] if overlap_ts else None,
        "overlap_end": overlap_ts[-1] if overlap_ts else None,
    }


def broker_m30_crosscheck(resampled: List[CandleV2]) -> Dict:
    if os.environ.get("USE_LIVE_MT5") != "1":
        return {"skipped": True, "reason": "USE_LIVE_MT5 not set"}

    import MetaTrader5 as mt5
    if not mt5.initialize():
        return {"skipped": True, "reason": f"mt5.initialize() failed: {mt5.last_error()}"}

    try:
        end = datetime.now(timezone.utc) - timedelta(days=1)
        start = end - timedelta(days=14)
        rates = mt5.copy_rates_range("GOLD", mt5.TIMEFRAME_M30, start, end)
        if rates is None or len(rates) == 0:
            return {"skipped": True, "reason": "no M30 rates returned"}

        broker_map = {}
        for r in rates:
            dt = datetime.fromtimestamp(int(r["time"]), tz=timezone.utc)
            ts = dt.strftime("%Y-%m-%d %H:%M:%S")
            broker_map[ts] = (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))

        return compare(broker_map, resampled, "broker_M30_live_sample_last_14d")
    finally:
        mt5.shutdown()


def run() -> Dict:
    m1 = parse_mt5_m1_export_csv(CANONICAL_CSV_PATH)
    m30, prov = resample_m1(m1, Timeframe.M30)

    results = {
        "new_m1_count": len(m1),
        "new_m30_resampled_count": len(m30),
        "m30_incomplete_buckets": prov.incomplete_bucket_count,
        "old_export_crosschecks": [],
        "broker_m30_crosscheck": None,
    }

    for path in OLD_EXPORTS:
        if not os.path.exists(path):
            results["old_export_crosschecks"].append({"path": path, "skipped": True, "reason": "not found"})
            continue
        ref = parse_m30_export(path)
        cmp = compare(ref, m30, os.path.basename(path))
        cmp["path"] = path
        results["old_export_crosschecks"].append(cmp)

    results["broker_m30_crosscheck"] = broker_m30_crosscheck(m30)
    return results


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
