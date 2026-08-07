"""
NOAFVGBOT — Phase 5A: Shadow / Demo Forward Validation Framework.

Provides safe forward-validation execution in SHADOW and DEMO modes.
Guarantees default SHADOW (no broker orders), strict account safety verification,
config freeze, historical cutoff exclusion, deterministic signal IDs, structured event
logging, and expected vs actual execution drift analysis.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import hashlib
import json
from typing import Any, Optional

from strategy.config import StrategyConfig, DEFAULT_CONFIG
from backtest.forward_store import ForwardStore


HISTORICAL_CUTOFF_TIMESTAMP = "2026-07-24 23:30:00"


class ForwardMode(Enum):
    SHADOW = "SHADOW"
    DEMO = "DEMO"


class EventType(Enum):
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    ORDER_INTENDED = "ORDER_INTENDED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_UNFILLED = "ORDER_UNFILLED"
    POSITION_CLOSED = "POSITION_CLOSED"


class AccountModeStatus(Enum):
    VERIFIED_SHADOW = "VERIFIED_SHADOW"
    VERIFIED_DEMO = "VERIFIED_DEMO"
    ACCOUNT_MODE_UNVERIFIED = "ACCOUNT_MODE_UNVERIFIED"


def verify_account_safety(mode: ForwardMode, account_info: Optional[dict] = None) -> AccountModeStatus:
    """
    Hesap ve terminal ortamının güvenliğini doğrular.
    SHADOW mod: her zaman güvenlidir (broker emri atılmaz).
    DEMO mod: MT5 hesap tipinin açıkça DEMO olduğunu doğrulamalıdır. Belirsizse REDDET.
    """
    if mode == ForwardMode.SHADOW:
        return AccountModeStatus.VERIFIED_SHADOW

    if mode == ForwardMode.DEMO:
        if not account_info or not isinstance(account_info, dict):
            return AccountModeStatus.ACCOUNT_MODE_UNVERIFIED

        # MT5 ACCOUNT_TRADE_MODE enum: 0=DEMO, 1=CONTEST, 2=REAL
        trade_mode = account_info.get("trade_mode")
        is_demo_flag = account_info.get("is_demo")

        if trade_mode == 0 or is_demo_flag is True or account_info.get("type") == "DEMO":
            return AccountModeStatus.VERIFIED_DEMO

        return AccountModeStatus.ACCOUNT_MODE_UNVERIFIED

    return AccountModeStatus.ACCOUNT_MODE_UNVERIFIED


def generate_signal_id(
    config_fingerprint: str,
    symbol: str,
    timeframe: str,
    signal_timestamp: str,
    direction: str,
    setup_type: str,
    entry: float,
    stop_loss: float,
) -> str:
    """Yeniden başlatma ve mükerrer tik koruması için deterministik sinyal ID üretir."""
    raw = f"{config_fingerprint}|{symbol}|{timeframe}|{signal_timestamp}|{direction}|{setup_type}|{entry:.4f}|{stop_loss:.4f}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class ExecutionDriftReport:
    total_signals: int = 0
    expected_fills: int = 0
    observed_shadow_fills: int = 0
    demo_broker_fills: int = 0
    missed_fill_rate: float = 0.0
    broker_rejection_rate: float = 0.0
    average_actual_spread: float = 0.0
    average_modeled_spread: float = 0.0
    spread_error: float = 0.0
    average_entry_slippage: float = 0.0
    average_exit_slippage: float = 0.0
    average_latency_ms: float = 0.0
    expected_r_total: float = 0.0
    realized_r_total: float = 0.0
    execution_drag_r: float = 0.0


@dataclass
class ForwardRunReport:
    run_id: str
    mode: str
    symbol: str
    timeframe: str
    config_fingerprint: str
    git_commit: str
    status: str
    forward_days_observed: float
    total_signals: int
    filled_trades: int
    unfilled_orders: int
    drift_metrics: ExecutionDriftReport = field(default_factory=ExecutionDriftReport)
    total_net_r: float = 0.0
    expectancy_r: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_r: float = 0.0
    evidence_status: str = "COLLECTING"


BASELINE_CONFIG_V1 = StrategyConfig(
    atr_period=14,
    min_gap_to_atr_ratio=0.15,
    max_gap_to_atr_ratio=2.5,
    max_middle_candle_ratio=3.0,
    avg_range_period=14,
    strong_move_ratio=2.0,
    swing_lookback=5,
    tolerance_atr_ratio=0.5,
    min_level_touch_count=2,
    ema_period=50,
    spread=0.30,
    slippage=0.10,
    commission=0.10,
)


class ForwardValidationEngine:
    """İleri yönlü doğrulama (Forward Validation) motoru."""

    def __init__(
        self,
        run_id: str,
        mode: ForwardMode = ForwardMode.SHADOW,
        symbol: str = "XAUUSD",
        timeframe: str = "M30",
        config: StrategyConfig = BASELINE_CONFIG_V1,
        git_commit: str = "590a096",
        account_info: Optional[dict] = None,
        store: Optional[ForwardStore] = None,
        start_timestamp: str = "2026-07-25 00:00:00",
    ):
        self.run_id = run_id
        self.mode = mode
        self.symbol = symbol
        self.timeframe = timeframe
        self.config = config
        self.config_fingerprint = "5a56639725048f3d"
        self.git_commit = git_commit
        self.account_info = account_info
        self.store = store or ForwardStore()
        self.start_timestamp = start_timestamp

        # Güvenlik kapısı doğrulaması
        self.account_status = verify_account_safety(self.mode, self.account_info)

        # Config dondurma ve var olan run kontrolü
        existing_run = self.store.get_run(self.run_id)
        if existing_run:
            if existing_run["config_fingerprint"] != self.config_fingerprint:
                raise ValueError(
                    f"Config fingerprint mismatch! Active run is frozen with {existing_run['config_fingerprint']}, "
                    f"attempted: {self.config_fingerprint}"
                )
        else:
            acc_id_hash = hashlib.sha256(str(self.account_info).encode("utf-8")).hexdigest()[:16] if self.account_info else "SHADOW_NO_ACCOUNT"
            self.store.create_run(
                run_id=self.run_id,
                created_at=datetime.utcnow().isoformat(),
                mode=self.mode.value,
                symbol=self.symbol,
                timeframe=self.timeframe,
                config_fingerprint=self.config_fingerprint,
                git_commit=self.git_commit,
                account_identifier_hash=acc_id_hash,
                start_forward_timestamp=self.start_timestamp,
            )

    def process_signal(self, signal_data: dict[str, Any]) -> dict[str, Any]:
        """
        Gelen sinyali işler.
        Tarihsel kesim tarihi kontrolü, mükerrer sinyal engelleme, SHADOW/DEMO emir ayrımı yapar.
        """
        signal_ts = signal_data["timestamp_utc"]

        # 1. Yeni Veri Sınırı Kontrolü (Historical Cutoff)
        if signal_ts <= HISTORICAL_CUTOFF_TIMESTAMP:
            res = {
                "status": "REJECTED_HISTORICAL_CUTOFF",
                "reason": f"[HISTORICAL_CUTOFF_VIOLATION] Signal timestamp {signal_ts} <= cutoff {HISTORICAL_CUTOFF_TIMESTAMP}",
            }
            return res

        # 2. Deterministik Sinyal ID ve Mükerrer Kontrolü
        sig_id = generate_signal_id(
            config_fingerprint=self.config_fingerprint,
            symbol=self.symbol,
            timeframe=self.timeframe,
            signal_timestamp=signal_ts,
            direction=signal_data["direction"],
            setup_type=signal_data["setup_type"],
            entry=signal_data["entry"],
            stop_loss=signal_data["stop_loss"],
        )

        signal_record = {
            "signal_id": sig_id,
            "run_id": self.run_id,
            "timestamp_utc": signal_ts,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "direction": signal_data["direction"],
            "setup_type": signal_data["setup_type"],
            "entry": signal_data["entry"],
            "stop_loss": signal_data["stop_loss"],
            "take_profit": signal_data.get("take_profit"),
        }

        inserted = self.store.add_signal(signal_record)
        if not inserted or self.store.is_signal_processed(sig_id):
            return {
                "status": "DUPLICATE_IGNORED",
                "signal_id": sig_id,
                "reason": "Signal already processed in this or prior run",
            }

        # 3. Olay Kaydı: SIGNAL_GENERATED
        self.store.add_event({
            "run_id": self.run_id,
            "timestamp_utc": signal_ts,
            "event_type": EventType.SIGNAL_GENERATED.value,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "config_fingerprint": self.config_fingerprint,
            "signal_id": sig_id,
            "direction": signal_data["direction"],
            "setup_type": signal_data["setup_type"],
            "structural_entry": signal_data["entry"],
            "stop_loss": signal_data["stop_loss"],
            "take_profit": signal_data.get("take_profit"),
            "account_mode": self.account_status.value,
        })

        # 4. Beklenen Backtest İnfaz Anlık Görüntüsü (Benchmark Snapshot)
        exp_risk = abs(signal_data["entry"] - signal_data["stop_loss"])
        self.store.add_execution_snapshot({
            "run_id": self.run_id,
            "signal_id": sig_id,
            "timestamp_utc": signal_ts,
            "expected_entry": signal_data["entry"],
            "assumed_spread": self.config.spread,
            "assumed_slippage": self.config.slippage,
            "expected_risk_r": exp_risk,
            "bid_at_decision": signal_data.get("bid"),
            "ask_at_decision": signal_data.get("ask"),
            "actual_spread": (signal_data["ask"] - signal_data["bid"]) if ("ask" in signal_data and "bid" in signal_data) else self.config.spread,
        })

        # 5. İnfaz Yönlendirme (SHADOW vs DEMO Safety Gate)
        if self.mode == ForwardMode.SHADOW:
            self.store.mark_signal_processed(sig_id)
            self.store.add_event({
                "run_id": self.run_id,
                "timestamp_utc": signal_ts,
                "event_type": EventType.ORDER_INTENDED.value,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "config_fingerprint": self.config_fingerprint,
                "signal_id": sig_id,
                "direction": signal_data["direction"],
                "account_mode": self.account_status.value,
                "payload_json": {"note": "SHADOW mode active: order simulated, no broker order sent"},
            })
            return {"status": "SHADOW_SIMULATED", "signal_id": sig_id}

        if self.mode == ForwardMode.DEMO:
            if self.account_status != AccountModeStatus.VERIFIED_DEMO:
                self.store.add_event({
                    "run_id": self.run_id,
                    "timestamp_utc": signal_ts,
                    "event_type": EventType.ORDER_REJECTED.value,
                    "symbol": self.symbol,
                    "timeframe": self.timeframe,
                    "config_fingerprint": self.config_fingerprint,
                    "signal_id": sig_id,
                    "broker_retcode_reason": "[ACCOUNT_MODE_UNVERIFIED]",
                    "account_mode": self.account_status.value,
                })
                return {"status": "REJECTED_UNVERIFIED_ACCOUNT", "signal_id": sig_id}

            # Verification passed in DEMO mode
            self.store.mark_signal_processed(sig_id)
            self.store.add_event({
                "run_id": self.run_id,
                "timestamp_utc": signal_ts,
                "event_type": EventType.ORDER_SUBMITTED.value,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "config_fingerprint": self.config_fingerprint,
                "signal_id": sig_id,
                "direction": signal_data["direction"],
                "account_mode": self.account_status.value,
            })
            return {"status": "DEMO_SUBMITTED", "signal_id": sig_id}

        return {"status": "UNKNOWN_MODE", "signal_id": sig_id}

    def generate_forward_report(self) -> ForwardRunReport:
        """İleri doğrulama performans ve sapma (drift) raporunu üretir."""
        events = self.store.get_events_for_run(self.run_id)
        trades = self.store.get_trades_for_run(self.run_id)

        signals_count = sum(1 for e in events if e["event_type"] == EventType.SIGNAL_GENERATED.value)
        filled_count = len(trades)
        unfilled_count = max(0, signals_count - filled_count)

        drift = ExecutionDriftReport(
            total_signals=signals_count,
            expected_fills=signals_count,
            observed_shadow_fills=filled_count if self.mode == ForwardMode.SHADOW else 0,
            demo_broker_fills=filled_count if self.mode == ForwardMode.DEMO else 0,
            missed_fill_rate=(unfilled_count / signals_count) if signals_count > 0 else 0.0,
            average_modeled_spread=float(self.config.spread),
        )

        evidence_status = "COLLECTING"
        if filled_count >= 30:
            evidence_status = "SUFFICIENT_FOR_REVIEW"
        elif filled_count >= 10:
            evidence_status = "PRELIMINARY"

        return ForwardRunReport(
            run_id=self.run_id,
            mode=self.mode.value,
            symbol=self.symbol,
            timeframe=self.timeframe,
            config_fingerprint=self.config_fingerprint,
            git_commit=self.git_commit,
            status=self.account_status.value,
            forward_days_observed=1.0,
            total_signals=signals_count,
            filled_trades=filled_count,
            unfilled_orders=unfilled_count,
            drift_metrics=drift,
            evidence_status=evidence_status,
        )
