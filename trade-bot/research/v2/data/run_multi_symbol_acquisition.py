"""
NOAFVGBOT -- Multi-Symbol MT5 Historical Acquisition Pipeline.

Extends the V2.10B.1 single-symbol (GOLD) chunked/resumable/checkpointed acquisition
pattern (research/v2/data/run_chunked_acquisition.py) to a configurable list of symbols,
so the data pool can be enriched beyond XAUUSD without touching any frozen V1/V2 GOLD
artifact (data/manifest.json, data/raw/V2_10B1_*, data/canonical/V2_M1_LIVE_DATASET_V1*
are never read or written by this script).

Per symbol, sequentially:
  1. Chunked, checkpointed, resumable RAW M1 acquisition -> data/raw/V2_MULTI_{SYM}_M1_raw.csv
     (interruption-safe: a checkpoint file records completed chunk boundaries; resuming
     re-fetches the last chunk with an overlap window rather than trusting the raw file's
     last line, exactly like the GOLD pipeline).
  2. RAW audit (strict parseability, duplicate/conflicting timestamps, OHLC integrity).
  3. Canonicalization (dedupe + sort) via the existing symbol-agnostic
     research/v2/data/acquisition.py:convert_raw_to_canonical_m1.
  4. Quality audit (research/v2/data/audit.py) + gap audit (research/v2/data/gap_audit.py).
  5. Informational M3/M5/M15/M30 resample counts via research/v2/data/resampler.py
     (matching the existing convention: only M1 is persisted to disk; higher timeframes
     are derived on demand downstream).
  6. Canonical M1 CSV (tab-separated MT5-History-Center-export format, matching
     live_dataset.py's parser) -> data/canonical/V2_MULTI_{SYM}_M1_canonical.csv
  7. Per-symbol manifest -> data/canonical/V2_MULTI_{SYM}_manifest.json
  8. Running pool summary (updated after every symbol) -> data/canonical/V2_MULTI_pool_summary.json

INVARIANTS (mirrors run_chunked_acquisition.py):
- READ-ONLY: never calls order_send / order_check / any trade execution function.
- One symbol's failure (e.g. broker doesn't carry it) is caught, logged into the pool
  summary as FAILED, and the run continues to the next symbol -- it never aborts the batch.
- Chunk-level resume with overlap + dedup by timestamp, per symbol, independent lock files.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from research.v2.data.models import CandleV2, Timeframe, compute_dataset_fingerprint
from research.v2.data.acquisition import convert_raw_to_canonical_m1
from research.v2.data.audit import audit_m1_dataset
from research.v2.data.gap_audit import audit_dataset_gaps
from research.v2.data.manifest import compute_raw_fingerprint, compute_canonical_fingerprint, DatasetManifest
from research.v2.data.resampler import resample_m1

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RAW_DIR = os.path.join(REPO_ROOT, "data", "raw")
CANONICAL_DIR = os.path.join(REPO_ROOT, "data", "canonical")
SUMMARY_PATH = os.path.join(CANONICAL_DIR, "V2_MULTI_pool_summary.json")
LOG_PATH = os.path.join(REPO_ROOT, "data", "raw", "V2_MULTI_acquisition.log")

# (research_symbol, broker_symbol) -- broker names confirmed live against this account's
# symbol universe (XMGlobal-MT5) before this script was written. AUDCNH was requested but
# does not exist on this broker and is intentionally omitted (see final report, not silently
# substituted).
SYMBOLS: List[Tuple[str, str]] = [
    ("EURUSD", "EURUSD"),
    ("GBPUSD", "GBPUSD"),
    ("USDCHF", "USDCHF"),
    ("USDCAD", "USDCAD"),
    ("AUDCAD", "AUDCAD"),
    ("EURGBP", "EURGBP"),
    ("USDJPY", "USDJPY"),
    ("EURJPY", "EURJPY"),
    ("EURCAD", "EURCAD"),
    ("NASDAQ", "Nasdaq"),
    ("SILVER", "SILVER"),
    # Round 2 -- remaining major-currency crosses (full 8-currency 28-pair grid) + top
    # commodities/crypto not yet covered, confirmed present on this broker's symbol list.
    ("AUDUSD", "AUDUSD"),
    ("NZDUSD", "NZDUSD"),
    ("GBPJPY", "GBPJPY"),
    ("AUDJPY", "AUDJPY"),
    ("CADJPY", "CADJPY"),
    ("CHFJPY", "CHFJPY"),
    ("NZDJPY", "NZDJPY"),
    ("EURAUD", "EURAUD"),
    ("EURNZD", "EURNZD"),
    ("EURCHF", "EURCHF"),
    ("GBPAUD", "GBPAUD"),
    ("GBPCAD", "GBPCAD"),
    ("GBPCHF", "GBPCHF"),
    ("GBPNZD", "GBPNZD"),
    ("AUDCHF", "AUDCHF"),
    ("AUDNZD", "AUDNZD"),
    ("CADCHF", "CADCHF"),
    ("NZDCAD", "NZDCAD"),
    ("NZDCHF", "NZDCHF"),
    ("BTCUSD", "BTCUSD"),
    ("WTI", "OILCash"),
    # GOLD refresh -- separate identity from the frozen V2_10B1_XAUUSD_GOLD_M1_raw.csv /
    # data/manifest.json artifacts (never touched). Gives a directly comparable entry in
    # the same 32-symbol validation table using this pipeline's own fresh acquisition.
    ("GOLD", "GOLD"),

    # Round 3 -- maximum breadth pass. Every symbol below was confirmed present via a live
    # mt5.symbols_get() survey. Deliberately excludes: individual Stocks/Turbo Stocks (1381
    # symbols, not suited to this macro FX/commodity strategy), ETF Derivatives (equity-hours,
    # mostly redundant with instruments already covered), Thematic Indices (broker-proprietary
    # synthetic baskets), and every dated/expiring futures contract (symbols with a "-SEP26"/
    # "-OCT26"/"-NOV26"/"-DEC26" suffix -- not continuous, unsuited to a 2010-2026 backtest).

    # Exotic FX crosses (27) -- minor/EM currencies, expect wider spreads than majors.
    ("CHFSGD", "CHFSGD"), ("EURDKK", "EURDKK"), ("EURHKD", "EURHKD"), ("EURHUF", "EURHUF"),
    ("EURNOK", "EURNOK"), ("EURPLN", "EURPLN"), ("EURSEK", "EURSEK"), ("EURSGD", "EURSGD"),
    ("EURTRY", "EURTRY"), ("EURZAR", "EURZAR"), ("GBPDKK", "GBPDKK"), ("GBPNOK", "GBPNOK"),
    ("GBPSEK", "GBPSEK"), ("GBPSGD", "GBPSGD"), ("NZDSGD", "NZDSGD"), ("SGDJPY", "SGDJPY"),
    ("USDCNH", "USDCNH"), ("USDDKK", "USDDKK"), ("USDHKD", "USDHKD"), ("USDHUF", "USDHUF"),
    ("USDMXN", "USDMXN"), ("USDNOK", "USDNOK"), ("USDPLN", "USDPLN"), ("USDSEK", "USDSEK"),
    ("USDSGD", "USDSGD"), ("USDTRY", "USDTRY"), ("USDZAR", "USDZAR"),

    # Global equity indices (23) -- continuous "Cash" contracts only.
    ("AUS200", "AUS200Cash"), ("CA60", "CA60Cash"), ("CHN50", "CHN50Cash"), ("CHINAH", "ChinaHCash"),
    ("EU50", "EU50Cash"), ("FRA40", "FRA40Cash"), ("GER40", "GER40Cash"), ("GERMID50", "GerMid50Cash"),
    ("GERTECH30", "GerTech30Cash"), ("HK50", "HK50Cash"), ("IT40", "IT40Cash"), ("JP225", "JP225Cash"),
    ("NETH25", "NETH25Cash"), ("SA40", "SA40Cash"), ("SWI20", "SWI20Cash"), ("SING30", "Sing30Cash"),
    ("SPAIN35", "SpainCash"), ("TAIWAN", "TaiwanCash"), ("UK100", "UK100Cash"), ("US2000", "US2000Cash"),
    ("US30", "US30Cash"), ("US500", "US500Cash"), ("USFANG", "USFANGCash"),

    # Metals (2) and energy (1) not yet covered.
    ("PLATINUM", "XPTUSD"), ("PALLADIUM", "XPDUSD"), ("BRENT", "BRENTCash"),

    # Major cryptocurrencies (15) -- top of this broker's 60-symbol crypto list by relevance,
    # excluding long-tail low-cap altcoins.
    ("ETHUSD", "ETHUSD"), ("XRPUSD", "XRPUSD"), ("SOLUSD", "SOLUSD"), ("DOGEUSD", "DOGEUSD"),
    ("ADAUSD", "ADAUSD"), ("DOTUSD", "DOTUSD"), ("LINKUSD", "LINKUSD"), ("AVAXUSD", "AVAXUSD"),
    ("MATICUSD", "MATICUSD"), ("BCHUSD", "BCHUSD"), ("LTCUSD", "LTCUSD"), ("ATOMUSD", "ATOMUSD"),
    ("UNIUSD", "UNIUSD"), ("XLMUSD", "XLMUSD"), ("ETCUSD", "ETCUSD"),
]

REQUESTED_START_UTC = "2010-01-01 00:00:00"  # maximum depth this broker offers (verified available for
                                              # EURUSD/GOLD back to late 2009); a symbol with a shorter
                                              # real history simply yields fewer rows, no error.
CHUNK_DAYS = 30
OVERLAP_WINDOW = timedelta(hours=2)
RAW_FIELDS = ["time", "timestamp_open_utc", "open", "high", "low", "close", "tick_volume", "spread"]


def _log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, file=sys.stderr, flush=True)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=10)
        return str(pid) in out.stdout
    except Exception:
        return True


def _paths(research_symbol: str) -> Dict[str, str]:
    return {
        "raw": os.path.join(RAW_DIR, f"V2_MULTI_{research_symbol}_M1_raw.csv"),
        "checkpoint": os.path.join(RAW_DIR, f"V2_MULTI_{research_symbol}_checkpoint.json"),
        "lock": os.path.join(RAW_DIR, f"V2_MULTI_{research_symbol}_acquisition.lock"),
        "canonical": os.path.join(CANONICAL_DIR, f"V2_MULTI_{research_symbol}_M1_canonical.csv"),
        "manifest": os.path.join(CANONICAL_DIR, f"V2_MULTI_{research_symbol}_manifest.json"),
    }


@dataclass
class Checkpoint:
    requested_start_utc: str
    requested_end_utc: str
    broker_symbol: str
    research_symbol: str
    raw_file_path: str
    chunk_days: int
    overlap_window_seconds: float
    completed_chunk_boundaries: List[List[str]] = field(default_factory=list)
    rows_persisted: int = 0
    last_verified_timestamp: Optional[str] = None
    status: str = "IN_PROGRESS"
    updated_at_utc: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def acquire_lock(lock_path: str) -> None:
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    if os.path.exists(lock_path):
        with open(lock_path, "r") as f:
            try:
                lock_data = json.load(f)
            except Exception:
                lock_data = {}
        prev_pid = int(lock_data.get("pid", -1))
        if _pid_alive(prev_pid):
            raise RuntimeError(f"Lock {lock_path} claims live PID {prev_pid}.")
    tmp = lock_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"pid": os.getpid(), "started_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, lock_path)


def release_lock(lock_path: str) -> None:
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except OSError:
        pass


def load_checkpoint(checkpoint_path: str) -> Optional[Checkpoint]:
    if not os.path.exists(checkpoint_path):
        return None
    with open(checkpoint_path, "r") as f:
        return Checkpoint(**json.load(f))


def save_checkpoint_atomic(cp: Checkpoint, checkpoint_path: str) -> None:
    cp.updated_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    tmp = checkpoint_path + ".tmp"
    with open(tmp, "w") as f:
        f.write(cp.to_json())
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, checkpoint_path)


def build_chunk_boundaries(start: datetime, end: datetime, chunk_days: int) -> List[Tuple[datetime, datetime]]:
    boundaries = []
    curr = start
    while curr < end:
        nxt = min(curr + timedelta(days=chunk_days), end)
        boundaries.append((curr, nxt))
        curr = nxt
    return boundaries


def ensure_raw_header(raw_path: str) -> None:
    os.makedirs(os.path.dirname(raw_path), exist_ok=True)
    if not os.path.exists(raw_path):
        with open(raw_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=RAW_FIELDS)
            w.writeheader()
            f.flush()
            os.fsync(f.fileno())


def append_rows_atomic(rows: List[Dict[str, Any]], raw_path: str) -> None:
    if not rows:
        return
    with open(raw_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RAW_FIELDS)
        for r in rows:
            w.writerow(r)
        f.flush()
        os.fsync(f.fileno())


def fetch_chunk_rows(mt5, symbol: str, chunk_start: datetime, chunk_end: datetime,
                      last_verified_ts: Optional[str], now_utc: datetime,
                      floor_dt: datetime) -> List[Dict[str, Any]]:
    request_start = max(chunk_start - OVERLAP_WINDOW, floor_dt)
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, request_start, chunk_end)
    if rates is None or len(rates) == 0:
        return []

    # last_verified_ts is only meaningful as a dedup watermark when it falls inside this
    # chunk's own overlap-lookback window -- i.e. it was set by the chunk immediately
    # preceding this one in the SAME chronological pass. When depth is extended backward
    # (REQUESTED_START_UTC moved earlier than an existing checkpoint's watermark), the
    # stale watermark from the old forward-only run sits far in the future relative to
    # these older chunks; applying it unconditionally silently discarded every row of the
    # 2010-2021 backfill (all timestamps <= a 2026 watermark) while still marking those
    # chunks "complete" with zero rows written. Only trust it inside [request_start, chunk_end).
    request_start_str = request_start.strftime("%Y-%m-%d %H:%M:%S")
    chunk_end_str = chunk_end.strftime("%Y-%m-%d %H:%M:%S")
    watermark_applies = (
        last_verified_ts is not None
        and request_start_str <= last_verified_ts < chunk_end_str
    )

    rows: List[Dict[str, Any]] = []
    seen_ts = set()
    for r in rates:
        dt_open = datetime.fromtimestamp(int(r["time"]), tz=timezone.utc)
        ts_open_str = dt_open.strftime("%Y-%m-%d %H:%M:%S")
        if dt_open + timedelta(seconds=60) > now_utc:
            continue
        if watermark_applies and ts_open_str <= last_verified_ts:
            continue
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


def acquire_symbol_raw(mt5, research_symbol: str, broker_symbol: str, end_utc: datetime) -> Checkpoint:
    paths = _paths(research_symbol)
    acquire_lock(paths["lock"])
    try:
        if not mt5.symbol_select(broker_symbol, True):
            raise RuntimeError(f"symbol_select({broker_symbol}) failed -- symbol not available on this broker")

        end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")
        existing_cp = load_checkpoint(paths["checkpoint"])
        if existing_cp is not None and existing_cp.broker_symbol == broker_symbol and existing_cp.raw_file_path == paths["raw"]:
            cp = existing_cp
            # extend the end boundary forward on resume (this run's "now"), and the start boundary
            # backward if REQUESTED_START_UTC has been moved earlier since the checkpoint was created
            # (e.g. depth-extension re-runs) -- without discarding any already-completed chunk progress.
            cp.requested_end_utc = end_str
            cp.requested_start_utc = REQUESTED_START_UTC
        else:
            cp = Checkpoint(
                requested_start_utc=REQUESTED_START_UTC,
                requested_end_utc=end_str,
                broker_symbol=broker_symbol,
                research_symbol=research_symbol,
                raw_file_path=paths["raw"],
                chunk_days=CHUNK_DAYS,
                overlap_window_seconds=OVERLAP_WINDOW.total_seconds(),
            )
            ensure_raw_header(paths["raw"])
            save_checkpoint_atomic(cp, paths["checkpoint"])

        start_dt = datetime.fromisoformat(REQUESTED_START_UTC).replace(tzinfo=timezone.utc)
        all_boundaries = build_chunk_boundaries(start_dt, end_utc, CHUNK_DAYS)
        done_set = {tuple(b) for b in cp.completed_chunk_boundaries}
        now_utc = datetime.now(timezone.utc)

        for chunk_start, chunk_end in all_boundaries:
            key = (chunk_start.strftime("%Y-%m-%d %H:%M:%S"), chunk_end.strftime("%Y-%m-%d %H:%M:%S"))
            if key in done_set:
                continue
            rows = fetch_chunk_rows(mt5, broker_symbol, chunk_start, chunk_end, cp.last_verified_timestamp, now_utc, start_dt)
            append_rows_atomic(rows, paths["raw"])
            cp.rows_persisted += len(rows)
            if rows:
                cp.last_verified_timestamp = rows[-1]["timestamp_open_utc"]
            cp.completed_chunk_boundaries.append([key[0], key[1]])
            save_checkpoint_atomic(cp, paths["checkpoint"])

        cp.status = "COMPLETE"
        save_checkpoint_atomic(cp, paths["checkpoint"])
        return cp
    finally:
        release_lock(paths["lock"])


def write_canonical_csv(candles: List[CandleV2], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["<DATE>", "<TIME>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>", "<TICKVOL>", "<VOL>", "<SPREAD>"])
        for c in candles:
            dt_open = datetime.fromisoformat(c.timestamp_open_utc)
            w.writerow([
                dt_open.strftime("%Y.%m.%d"), dt_open.strftime("%H:%M:%S"),
                f"{c.open:.5f}", f"{c.high:.5f}", f"{c.low:.5f}", f"{c.close:.5f}",
                int(c.volume), 0, 0,
            ])
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_raw_rows(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "time": int(row["time"]),
                "timestamp_open_utc": row["timestamp_open_utc"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "tick_volume": int(row["tick_volume"]),
                "spread": int(row["spread"]),
            })
    return rows


def canonicalize_symbol(research_symbol: str, broker_symbol: str) -> Dict[str, Any]:
    paths = _paths(research_symbol)
    raw_rows = load_raw_rows(paths["raw"])
    if not raw_rows:
        raise RuntimeError("zero raw rows acquired")

    canonical = convert_raw_to_canonical_m1(raw_rows)
    if not canonical:
        raise RuntimeError("canonicalization produced zero candles")

    write_canonical_csv(canonical, paths["canonical"])

    quality_report = audit_m1_dataset(canonical, raw_row_count=len(raw_rows))
    raw_fp = compute_raw_fingerprint(raw_rows)
    can_fp = compute_canonical_fingerprint(canonical)

    resample_counts = {}
    for tf in (Timeframe.M3, Timeframe.M5, Timeframe.M15, Timeframe.M30):
        try:
            resampled, _prov = resample_m1(canonical, tf)
            resample_counts[tf.name] = len(resampled)
        except Exception as e:
            resample_counts[tf.name] = f"ERROR: {e}"

    manifest = DatasetManifest(
        dataset_name=f"{research_symbol}_M1_LIVE_HISTORICAL",
        research_symbol=research_symbol,
        broker_symbol=broker_symbol,
        timeframe="M1",
        retrieved_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        earliest_timestamp=canonical[0].timestamp_open_utc,
        latest_timestamp=canonical[-1].timestamp_open_utc,
        raw_row_count=len(raw_rows),
        canonical_row_count=len(canonical),
        raw_fingerprint=raw_fp,
        canonical_fingerprint=can_fp,
        quality_status=quality_report.quality_status.value,
        m1_count=len(canonical),
        m3_count=resample_counts.get("M3", 0) if isinstance(resample_counts.get("M3"), int) else 0,
        m5_count=resample_counts.get("M5", 0) if isinstance(resample_counts.get("M5"), int) else 0,
        m15_count=resample_counts.get("M15", 0) if isinstance(resample_counts.get("M15"), int) else 0,
        m30_count=resample_counts.get("M30", 0) if isinstance(resample_counts.get("M30"), int) else 0,
        incomplete_buckets={},
        source_kind="LIVE_MT5",
        dataset_state="V2_MULTI_M1_DATASET_CANDIDATE",
    )
    with open(paths["manifest"], "w") as f:
        f.write(manifest.to_json())

    return {
        "raw_row_count": len(raw_rows),
        "canonical_row_count": len(canonical),
        "earliest_timestamp": canonical[0].timestamp_open_utc,
        "latest_timestamp": canonical[-1].timestamp_open_utc,
        "quality_status": quality_report.quality_status.value,
        "resample_counts": resample_counts,
        "raw_fingerprint": raw_fp,
        "canonical_fingerprint": can_fp,
        "manifest_path": paths["manifest"],
        "canonical_path": paths["canonical"],
    }


def load_summary() -> Dict[str, Any]:
    if os.path.exists(SUMMARY_PATH):
        with open(SUMMARY_PATH, "r") as f:
            return json.load(f)
    return {"started_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "symbols": {}}


def save_summary(summary: Dict[str, Any]) -> None:
    summary["updated_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    tmp = SUMMARY_PATH + ".tmp"
    os.makedirs(os.path.dirname(SUMMARY_PATH), exist_ok=True)
    with open(tmp, "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True, default=str)
    os.replace(tmp, SUMMARY_PATH)


def run() -> Dict[str, Any]:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"mt5.initialize() failed: {mt5.last_error()}")

    summary = load_summary()
    end_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    try:
        for research_symbol, broker_symbol in SYMBOLS:
            if summary["symbols"].get(research_symbol, {}).get("status") == "DONE":
                _log(f"{research_symbol}: already DONE, skipping")
                continue

            _log(f"{research_symbol} ({broker_symbol}): starting RAW acquisition")
            t0 = time.time()
            try:
                cp = acquire_symbol_raw(mt5, research_symbol, broker_symbol, end_utc)
                _log(f"{research_symbol}: RAW acquisition complete, {cp.rows_persisted} new rows this run, "
                     f"{time.time() - t0:.1f}s")

                _log(f"{research_symbol}: canonicalizing + auditing")
                result = canonicalize_symbol(research_symbol, broker_symbol)
                _log(f"{research_symbol}: DONE -- canonical_rows={result['canonical_row_count']} "
                     f"quality={result['quality_status']} range=[{result['earliest_timestamp']} .. {result['latest_timestamp']}]")

                summary["symbols"][research_symbol] = {
                    "status": "DONE",
                    "broker_symbol": broker_symbol,
                    **result,
                }
            except Exception as e:
                tb = traceback.format_exc()
                _log(f"{research_symbol}: FAILED -- {e}\n{tb}")
                summary["symbols"][research_symbol] = {
                    "status": "FAILED",
                    "broker_symbol": broker_symbol,
                    "error": str(e),
                }
            save_summary(summary)
    finally:
        mt5.shutdown()

    return summary


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, default=str))
