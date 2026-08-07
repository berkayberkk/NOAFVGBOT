"""
NOAFVGBOT — Phase 5A: Forward Validation Persistence Store.

Manages SQLite persistence for forward runs, structured append-only event logs,
deterministic signals, expected/actual execution snapshots, and completed trade results.
"""

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Optional


class ForwardStore:
    """SQLite-based persistent transactional store for forward validation data."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return self._conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Forward Runs Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS forward_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    config_fingerprint TEXT NOT NULL,
                    git_commit TEXT NOT NULL,
                    account_identifier_hash TEXT NOT NULL,
                    start_forward_timestamp TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'COLLECTING'
                )
            """)

            # Structured Append-Only Events Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS forward_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    config_fingerprint TEXT NOT NULL,
                    signal_id TEXT,
                    direction TEXT,
                    setup_type TEXT,
                    structural_entry REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    intended_volume REAL,
                    market_bid REAL,
                    market_ask REAL,
                    actual_fill REAL,
                    broker_spread REAL,
                    broker_retcode_reason TEXT,
                    magic_number INTEGER,
                    account_mode TEXT NOT NULL,
                    payload_json TEXT,
                    FOREIGN KEY (run_id) REFERENCES forward_runs(run_id)
                )
            """)

            # Deterministic Signals Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS forward_signals (
                    signal_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    setup_type TEXT NOT NULL,
                    entry REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL,
                    processed INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (run_id) REFERENCES forward_runs(run_id)
                )
            """)

            # Expected vs Actual Execution Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS execution_snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    signal_id TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    expected_entry REAL NOT NULL,
                    assumed_spread REAL NOT NULL,
                    assumed_slippage REAL NOT NULL,
                    expected_risk_r REAL NOT NULL,
                    bid_at_decision REAL,
                    ask_at_decision REAL,
                    actual_spread REAL,
                    actual_fill REAL,
                    entry_slippage REAL,
                    exit_slippage REAL,
                    latency_ms REAL,
                    broker_retcode TEXT,
                    FOREIGN KEY (run_id) REFERENCES forward_runs(run_id),
                    FOREIGN KEY (signal_id) REFERENCES forward_signals(signal_id)
                )
            """)

            # Completed Forward Trades Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS forward_trades (
                    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    signal_id TEXT NOT NULL,
                    entry_timestamp TEXT NOT NULL,
                    exit_timestamp TEXT,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    gross_r REAL,
                    execution_cost_r REAL,
                    net_r REAL,
                    won INTEGER,
                    holding_duration_sec REAL,
                    mae_r REAL,
                    mfe_r REAL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    FOREIGN KEY (run_id) REFERENCES forward_runs(run_id),
                    FOREIGN KEY (signal_id) REFERENCES forward_signals(signal_id)
                )
            """)

            conn.commit()

    def create_run(
        self,
        run_id: str,
        created_at: str,
        mode: str,
        symbol: str,
        timeframe: str,
        config_fingerprint: str,
        git_commit: str,
        account_identifier_hash: str,
        start_forward_timestamp: str,
    ) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO forward_runs (
                    run_id, created_at, mode, symbol, timeframe,
                    config_fingerprint, git_commit, account_identifier_hash,
                    start_forward_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, created_at, mode, symbol, timeframe,
                config_fingerprint, git_commit, account_identifier_hash,
                start_forward_timestamp
            ))
            conn.commit()

    def get_run(self, run_id: str) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM forward_runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_event(self, event_data: dict[str, Any]) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO forward_events (
                    run_id, timestamp_utc, event_type, symbol, timeframe,
                    config_fingerprint, signal_id, direction, setup_type,
                    structural_entry, stop_loss, take_profit, intended_volume,
                    market_bid, market_ask, actual_fill, broker_spread,
                    broker_retcode_reason, magic_number, account_mode, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_data.get("run_id"),
                event_data.get("timestamp_utc"),
                event_data.get("event_type"),
                event_data.get("symbol"),
                event_data.get("timeframe"),
                event_data.get("config_fingerprint"),
                event_data.get("signal_id"),
                event_data.get("direction"),
                event_data.get("setup_type"),
                event_data.get("structural_entry"),
                event_data.get("stop_loss"),
                event_data.get("take_profit"),
                event_data.get("intended_volume"),
                event_data.get("market_bid"),
                event_data.get("market_ask"),
                event_data.get("actual_fill"),
                event_data.get("broker_spread"),
                event_data.get("broker_retcode_reason"),
                event_data.get("magic_number"),
                event_data.get("account_mode"),
                json.dumps(event_data.get("payload_json", {})),
            ))
            conn.commit()
            return cursor.lastrowid

    def add_signal(self, signal_data: dict[str, Any]) -> bool:
        """Deterministik sinyali kaydeder. Eger sinyal daha once kaydedilmisse False doner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO forward_signals (
                        signal_id, run_id, timestamp_utc, symbol, timeframe,
                        direction, setup_type, entry, stop_loss, take_profit
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    signal_data["signal_id"],
                    signal_data["run_id"],
                    signal_data["timestamp_utc"],
                    signal_data["symbol"],
                    signal_data["timeframe"],
                    signal_data["direction"],
                    signal_data["setup_type"],
                    signal_data["entry"],
                    signal_data["stop_loss"],
                    signal_data.get("take_profit"),
                ))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False  # Duplicate signal ID

    def is_signal_processed(self, signal_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT processed FROM forward_signals WHERE signal_id = ?", (signal_id,))
            row = cursor.fetchone()
            return bool(row["processed"]) if row else False

    def mark_signal_processed(self, signal_id: str) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE forward_signals SET processed = 1 WHERE signal_id = ?", (signal_id,))
            conn.commit()

    def add_execution_snapshot(self, snapshot: dict[str, Any]) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO execution_snapshots (
                    run_id, signal_id, timestamp_utc, expected_entry, assumed_spread,
                    assumed_slippage, expected_risk_r, bid_at_decision, ask_at_decision,
                    actual_spread, actual_fill, entry_slippage, exit_slippage,
                    latency_ms, broker_retcode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.get("run_id"),
                snapshot.get("signal_id"),
                snapshot.get("timestamp_utc"),
                snapshot.get("expected_entry"),
                snapshot.get("assumed_spread"),
                snapshot.get("assumed_slippage"),
                snapshot.get("expected_risk_r"),
                snapshot.get("bid_at_decision"),
                snapshot.get("ask_at_decision"),
                snapshot.get("actual_spread"),
                snapshot.get("actual_fill"),
                snapshot.get("entry_slippage"),
                snapshot.get("exit_slippage"),
                snapshot.get("latency_ms"),
                snapshot.get("broker_retcode"),
            ))
            conn.commit()

    def get_events_for_run(self, run_id: str) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM forward_events WHERE run_id = ? ORDER BY event_id ASC", (run_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_trades_for_run(self, run_id: str) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM forward_trades WHERE run_id = ? ORDER BY trade_id ASC", (run_id,))
            return [dict(row) for row in cursor.fetchall()]
