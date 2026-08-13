"""
NOAFVGBOT V2.10B.1 -- Single-Process Chunked MT5 Historical Acquisition Pipeline.

Read-only, resumable, checkpointed acquisition of GOLD/XAUUSD M1 history from MT5 into
data/raw/V2_10B1_XAUUSD_GOLD_M1_raw.csv. Designed so a mid-run interruption (process kill,
machine shutdown) never requires restarting the whole download: progress is recorded as
completed chunk boundaries in an atomically-written checkpoint file, and resuming re-fetches
the last (possibly partial) chunk with a deliberate overlap window rather than trusting the
raw file's last line.

INVARIANTS:
- READ-ONLY: never calls order_send / order_check / any trade execution function.
- Exactly one acquisition process may run at a time (PID lock file, liveness-checked).
- Checkpoint writes are atomic (temp file + os.replace) so a crash mid-write can never leave
  a corrupt/partial checkpoint that looks valid.
- Chunk-level resume, not line-level: on resume, the last completed chunk boundary is re-fetched
  with OVERLAP_WINDOW of look-back, and rows are deduplicated by timestamp_open_utc against
  last_verified_timestamp before being appended. This tolerates a chunk that was only partially
  flushed before an interruption.
- No synthetic fallback of any kind.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

RAW_PATH = os.path.join(REPO_ROOT, "data", "raw", "V2_10B1_XAUUSD_GOLD_M1_raw.csv")
CHECKPOINT_PATH = os.path.join(REPO_ROOT, "data", "raw", "V2_10B1_acquisition_checkpoint.json")
LOCK_PATH = os.path.join(REPO_ROOT, "data", "raw", "V2_10B1_acquisition.lock")

REQUESTED_START_UTC = "2021-01-04 01:00:00"
REQUESTED_END_UTC = "2026-08-07 23:57:00"
CHUNK_DAYS = 30
OVERLAP_WINDOW = timedelta(hours=2)
BROKER_SYMBOL = "GOLD"
RESEARCH_SYMBOL = "XAUUSD"
TIMESTAMP_CONVERSION_POLICY = (
    "MT5 rate['time'] (epoch seconds as returned by the terminal) is interpreted directly as "
    "UTC via datetime.fromtimestamp(t, tz=timezone.utc), with no server/DST offset adjustment. "
    "This matches research/v2/data/acquisition.py:fetch_historical_m1_chunks, the existing "
    "project convention, so timestamps here are comparable to prior manifests."
)

RAW_FIELDS = ["time", "timestamp_open_utc", "open", "high", "low", "close", "tick_volume", "spread"]


class DuplicateAcquisitionProcessError(Exception):
    pass


class AcquisitionAbortedError(Exception):
    pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=10,
        )
        return str(pid) in out.stdout
    except Exception:
        # Fail safe: if we cannot determine liveness, assume alive to avoid a double-run.
        return True


def acquire_lock() -> None:
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    if os.path.exists(LOCK_PATH):
        with open(LOCK_PATH, "r") as f:
            try:
                lock_data = json.load(f)
            except Exception:
                lock_data = {}
        prev_pid = int(lock_data.get("pid", -1))
        if _pid_alive(prev_pid):
            raise DuplicateAcquisitionProcessError(
                f"Lock file {LOCK_PATH} claims live PID {prev_pid}. Refusing to start a second "
                f"acquisition process."
            )
        # Stale lock from a killed/crashed process -- safe to reclaim.

    tmp = LOCK_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"pid": os.getpid(), "started_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, LOCK_PATH)


def release_lock() -> None:
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except OSError:
        pass


@dataclass
class Checkpoint:
    requested_start_utc: str
    requested_end_utc: str
    broker_symbol: str
    research_symbol: str
    timestamp_conversion_policy: str
    raw_file_path: str
    chunk_days: int
    overlap_window_seconds: float
    completed_chunk_boundaries: List[List[str]] = field(default_factory=list)
    rows_persisted: int = 0
    last_verified_timestamp: Optional[str] = None
    orders_sent: int = 0
    status: str = "IN_PROGRESS"
    updated_at_utc: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def load_checkpoint() -> Optional[Checkpoint]:
    if not os.path.exists(CHECKPOINT_PATH):
        return None
    with open(CHECKPOINT_PATH, "r") as f:
        data = json.load(f)
    return Checkpoint(**data)


def save_checkpoint_atomic(cp: Checkpoint) -> None:
    cp.updated_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    tmp = CHECKPOINT_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write(cp.to_json())
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CHECKPOINT_PATH)


def build_chunk_boundaries(start: datetime, end: datetime, chunk_days: int) -> List[tuple]:
    boundaries = []
    curr = start
    while curr < end:
        nxt = min(curr + timedelta(days=chunk_days), end)
        boundaries.append((curr, nxt))
        curr = nxt
    return boundaries


def ensure_raw_header() -> None:
    os.makedirs(os.path.dirname(RAW_PATH), exist_ok=True)
    if not os.path.exists(RAW_PATH):
        with open(RAW_PATH, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=RAW_FIELDS)
            w.writeheader()
            f.flush()
            os.fsync(f.fileno())


def append_rows_atomic(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    with open(RAW_PATH, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RAW_FIELDS)
        for r in rows:
            w.writerow(r)
        f.flush()
        os.fsync(f.fileno())


def fetch_chunk_rows(mt5, symbol: str, chunk_start: datetime, chunk_end: datetime, last_verified_ts: Optional[str], now_utc: datetime) -> List[Dict[str, Any]]:
    request_start = chunk_start - OVERLAP_WINDOW
    if request_start < datetime.fromisoformat(REQUESTED_START_UTC).replace(tzinfo=timezone.utc):
        request_start = datetime.fromisoformat(REQUESTED_START_UTC).replace(tzinfo=timezone.utc)

    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, request_start, chunk_end)
    if rates is None or len(rates) == 0:
        return []

    rows: List[Dict[str, Any]] = []
    seen_ts = set()
    for r in rates:
        dt_open = datetime.fromtimestamp(int(r["time"]), tz=timezone.utc)
        ts_open_str = dt_open.strftime("%Y-%m-%d %H:%M:%S")

        # Never include a forming/incomplete bar.
        if dt_open + timedelta(seconds=60) > now_utc:
            continue
        # Dedup against everything already persisted on disk.
        if last_verified_ts is not None and ts_open_str <= last_verified_ts:
            continue
        # Stay within this chunk's own upper boundary (avoid double-counting into next chunk).
        if dt_open >= chunk_end:
            continue
        if ts_open_str in seen_ts:
            continue
        seen_ts.add(ts_open_str)

        rows.append({
            "time": int(r["time"]),
            "timestamp_open_utc": ts_open_str,
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "tick_volume": int(r["tick_volume"]),
            "spread": int(r["spread"]) if "spread" in r.dtype.names else 0,
        })

    rows.sort(key=lambda x: x["timestamp_open_utc"])
    return rows


def run() -> Dict[str, Any]:
    if os.environ.get("USE_LIVE_MT5") != "1":
        raise AcquisitionAbortedError("USE_LIVE_MT5=1 must be set explicitly to run a real MT5 acquisition.")

    acquire_lock()
    try:
        import MetaTrader5 as mt5

        if not mt5.initialize():
            raise AcquisitionAbortedError(f"mt5.initialize() failed: {mt5.last_error()}")

        try:
            existing_cp = load_checkpoint()
            if existing_cp is not None:
                if (existing_cp.requested_start_utc != REQUESTED_START_UTC
                        or existing_cp.requested_end_utc != REQUESTED_END_UTC
                        or existing_cp.broker_symbol != BROKER_SYMBOL
                        or existing_cp.raw_file_path != RAW_PATH):
                    raise AcquisitionAbortedError(
                        "Existing checkpoint does not match this run's configuration "
                        "(start/end/symbol/path). Refusing to silently resume with mismatched "
                        "parameters -- quarantine the old checkpoint/raw file first."
                    )
                cp = existing_cp
            else:
                cp = Checkpoint(
                    requested_start_utc=REQUESTED_START_UTC,
                    requested_end_utc=REQUESTED_END_UTC,
                    broker_symbol=BROKER_SYMBOL,
                    research_symbol=RESEARCH_SYMBOL,
                    timestamp_conversion_policy=TIMESTAMP_CONVERSION_POLICY,
                    raw_file_path=RAW_PATH,
                    chunk_days=CHUNK_DAYS,
                    overlap_window_seconds=OVERLAP_WINDOW.total_seconds(),
                )
                ensure_raw_header()
                save_checkpoint_atomic(cp)

            start_dt = datetime.fromisoformat(REQUESTED_START_UTC).replace(tzinfo=timezone.utc)
            end_dt = datetime.fromisoformat(REQUESTED_END_UTC).replace(tzinfo=timezone.utc)
            all_boundaries = build_chunk_boundaries(start_dt, end_dt, CHUNK_DAYS)

            done_set = {tuple(b) for b in cp.completed_chunk_boundaries}
            now_utc = datetime.now(timezone.utc)

            for chunk_start, chunk_end in all_boundaries:
                key = (chunk_start.strftime("%Y-%m-%d %H:%M:%S"), chunk_end.strftime("%Y-%m-%d %H:%M:%S"))
                if key in done_set:
                    continue

                rows = fetch_chunk_rows(mt5, BROKER_SYMBOL, chunk_start, chunk_end, cp.last_verified_timestamp, now_utc)
                append_rows_atomic(rows)

                cp.rows_persisted += len(rows)
                if rows:
                    cp.last_verified_timestamp = rows[-1]["timestamp_open_utc"]
                cp.completed_chunk_boundaries.append([key[0], key[1]])
                cp.status = "IN_PROGRESS"
                save_checkpoint_atomic(cp)

                print(f"[chunk {key[0]} .. {key[1]}] +{len(rows)} rows (total {cp.rows_persisted})", file=sys.stderr)

            cp.status = "COMPLETE"
            save_checkpoint_atomic(cp)
        finally:
            mt5.shutdown()
    finally:
        release_lock()

    return asdict(cp)


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, default=str))
