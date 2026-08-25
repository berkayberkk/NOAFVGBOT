"""
NOAFVGBOT — Phase 5C: Shadow Runner & Operational Reliability Module.

Provides the long-running operational SHADOW runner for collecting new forward evidence
from the real MT5 terminal without broker execution risk.

INVARIANTS:
- SHADOW mode ONLY (Hard safety boundary, no order_send / order_check reachable).
- Single-instance lock protection with stale lock recovery.
- Transactional bar processing & downtime catch-up (chronological, forming bar excluded).
- Historical cutoff enforcement (bars <= 2026-07-24 23:30:00 treated as CONTEXT ONLY).
- Heartbeat, health tracking (HEALTHY/DEGRADED/DISCONNECTED), and compact daily summary.
- Graceful shutdown on SIGINT/SIGTERM.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any, Optional, List, Dict

from strategy.config import StrategyConfig, DEFAULT_CONFIG
from strategy.signal_engine import generate_signals
from backtest.forward import (
    ForwardValidationEngine,
    ForwardMode,
    HISTORICAL_CUTOFF_TIMESTAMP,
    AccountModeStatus,
    BASELINE_CONFIG_V1,
)
from backtest.forward_store import ForwardStore
from backtest.mt5_shadow import MT5ShadowAdapter
from backtest.telegram_notifier import TelegramNotifier


class SingleInstanceLock:
    """Tekil Çalışma Kilidi (Single-Instance Lock)."""

    def __init__(self, lock_file_path: str | Path):
        self.lock_file = Path(lock_file_path)
        self.acquired = False

    def acquire(self) -> bool:
        if self.lock_file.exists():
            # Bayat kilit (Stale Lock) kontrolü
            try:
                content = self.lock_file.read_text().strip()
                pid = int(content.split(":")[0]) if ":" in content else int(content)
                # PID çalışıyor mu kontrol et (Windows/Unix)
                if not self._is_pid_running(pid):
                    # Bayat kilit temizlenebilir
                    self.lock_file.unlink(missing_ok=True)
                else:
                    return False
            except Exception:
                self.lock_file.unlink(missing_ok=True)

        try:
            self.lock_file.write_text(f"{os.getpid()}:{int(time.time())}")
            self.acquired = True
            return True
        except Exception:
            return False

    def release(self) -> None:
        if self.acquired and self.lock_file.exists():
            try:
                self.lock_file.unlink(missing_ok=True)
            except Exception:
                pass
            self.acquired = False

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            if os.name == "nt":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                SYNCHRONIZE = 0x00100000
                process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
                if process:
                    kernel32.CloseHandle(process)
                    return True
                return False
            else:
                os.kill(pid, 0)
                return True
        except Exception:
            return False


class HealthState(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"


@dataclass
class ShadowRunnerStatus:
    mode: str = "SHADOW"
    health_state: str = "HEALTHY"
    mt5_connected: bool = False
    symbol: str = "XAUUSD"
    run_id: str = ""
    started_at: str = ""
    last_market_bar: str = ""
    last_processed_bar: str = ""
    signals_count: int = 0
    open_shadow_trades: int = 0
    completed_trades: int = 0
    total_net_r: float = 0.0
    uptime_seconds: float = 0.0


@dataclass
class DailySummaryReport:
    date_str: str
    run_id: str
    uptime_hours: float
    new_completed_bars: int
    recovered_bars: int
    signals_generated: int
    filled_shadow_trades: int
    total_net_r: float
    average_observed_spread: float
    stale_ticks_count: int
    reconnect_count: int
    duplicate_bars_ignored: int


class ShadowRunner:
    """Operational SHADOW Runner."""

    def __init__(
        self,
        run_id: str = "shadow_live_run_v1",
        mode: ForwardMode = ForwardMode.SHADOW,
        symbol: str = "XAUUSD",
        broker_symbol: str = "XAUUSD",
        timeframe: str = "M30",
        config: StrategyConfig = BASELINE_CONFIG_V1,
        polling_interval_sec: float = 10.0,
        db_path: str = "forward.db",
        lock_file_path: str = "forward_runner.lock",
        mt5_module: Any = None,
        notifier: Optional[TelegramNotifier] = None,
    ):
        if mode != ForwardMode.SHADOW:
            raise ValueError(f"ShadowRunner ONLY supports SHADOW mode! Requested: {mode}")

        self.mode = mode
        self.symbol = symbol
        self.broker_symbol = broker_symbol
        self.timeframe = timeframe
        self.config = config
        self.config_fingerprint = "5a56639725048f3d"
        self.polling_interval_sec = polling_interval_sec

        self.lock = SingleInstanceLock(lock_file_path)
        if not self.lock.acquire():
            raise RuntimeError(f"Runner locked! Another instance is running for {lock_file_path}")

        self.store = ForwardStore(db_path)
        self.engine = ForwardValidationEngine(
            run_id=run_id,
            mode=self.mode,
            symbol=self.symbol,
            timeframe=self.timeframe,
            config=self.config,
            store=self.store,
        )

        self.notifier = notifier or TelegramNotifier()

        self.adapter = MT5ShadowAdapter(
            engine=self.engine,
            research_symbol=self.symbol,
            broker_symbol=self.broker_symbol,
            mt5_module=mt5_module,
            notifier=self.notifier,
        )

        self.start_time = time.time()
        self.started_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.running = False

        self.reconnect_count = 0
        self.stale_ticks_count = 0
        self.duplicate_bars_count = 0
        self.recovered_bars_count = 0
        self._last_health_state: Optional[HealthState] = None

        self.assert_read_only_safety()

    def assert_read_only_safety(self) -> None:
        """Runner seviyesinde sert okuma-sadece güvenlik doğrulaması."""
        if self.mode != ForwardMode.SHADOW:
            raise RuntimeError("CRITICAL SAFETY VIOLATION: Execution mode is not SHADOW!")
        self.adapter.assert_read_only_boundary()

    def initialize(self) -> bool:
        """Runner ve MT5 adaptörünü başlatır."""
        init_ok = self.adapter.initialize()
        if not init_ok:
            self.reconnect_count += 1
        else:
            self.notifier.notify_runner_started(self.engine.run_id, self.symbol, self.timeframe)
        return init_ok

    def catch_up_missing_bars(self, historical_warmup: Optional[List[Dict[str, Any]]] = None) -> int:
        """
        Kesinti sonrası eksik kalan TÜM TAMAMLANMIŞ M30 barlarını kronolojik olarak işler.
        Oluşan 0. mum KESİNLİKLE EKLENMEZ.
        """
        if not self.adapter.connected:
            return 0

        candles = self.adapter.fetch_completed_candles(count=200)
        if not candles:
            return 0

        # Son işlenen bar zaman damgası
        last_ts = self.adapter.last_processed_timestamp or self.engine.start_timestamp

        # Eksik barları filtrele (last_ts'ten sonra gelenler)
        missing_bars = [c for c in candles if c["time"] > last_ts]
        if not missing_bars:
            return 0

        recovered_count = 0
        context = list(historical_warmup) if historical_warmup else []

        for bar in missing_bars:
            context.append(bar)

            # Tarihsel kesim tarihi sonrasındaki barlar ileri yönlü kanıt olarak işlenir
            if bar["time"] > HISTORICAL_CUTOFF_TIMESTAMP:
                sigs = generate_signals(context, config=self.config)
                for sig in sigs:
                    if sig.index == len(context) - 1:
                        payload = {
                            "timestamp_utc": bar["time"],
                            "direction": sig.type.value,
                            "setup_type": sig.setup_type.value if hasattr(sig.setup_type, "value") else str(sig.setup_type),
                            "entry": sig.entry,
                            "stop_loss": sig.stop_loss,
                            "take_profit": getattr(sig, "take_profit", None),
                            "bid": bar["close"],
                            "ask": bar["close"] + self.config.spread,
                        }
                        self.engine.process_signal(payload)
                        recovered_count += 1

            self.adapter.last_processed_timestamp = bar["time"]

        self.recovered_bars_count += recovered_count
        return recovered_count

    def run_heartbeat(self) -> None:
        """Hafif sıklet periyodik kalp atışı (heartbeat) kaydeder."""
        health = self.get_health_state()
        if health != HealthState.HEALTHY and health != self._last_health_state:
            self.notifier.notify_health_degraded(
                health.value, f"run_id={self.engine.run_id}, symbol={self.symbol}"
            )
        self._last_health_state = health
        self.store.add_event({
            "run_id": self.engine.run_id,
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": "HEARTBEAT",
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "config_fingerprint": self.config_fingerprint,
            "account_mode": self.engine.account_status.value,
            "payload_json": {
                "health_state": health.value,
                "mt5_connected": self.adapter.connected,
                "last_processed_bar": self.adapter.last_processed_timestamp,
                "uptime_seconds": round(time.time() - self.start_time, 1),
            },
        })

    def get_health_state(self) -> HealthState:
        """MT5 bağlantısı ve tik tazeliğine göre sağlık durumunu döner."""
        if not self.adapter.connected:
            return HealthState.DISCONNECTED

        if self.adapter._mt5 and hasattr(self.adapter._mt5, "initialize") and not self.adapter._mt5.initialize():
            self.adapter.connected = False
            return HealthState.DISCONNECTED

        tick = self.adapter.get_current_tick()
        if tick is None:
            return HealthState.DEGRADED

        return HealthState.HEALTHY

    def get_status(self) -> ShadowRunnerStatus:
        """Kapsamlı çalışma durum özeti."""
        rep = self.engine.generate_forward_report()
        tick = self.adapter.get_current_tick()

        return ShadowRunnerStatus(
            mode=self.mode.value,
            health_state=self.get_health_state().value,
            mt5_connected=self.adapter.connected,
            symbol=self.symbol,
            run_id=self.engine.run_id,
            started_at=self.started_at,
            last_market_bar=self.adapter.last_processed_timestamp,
            last_processed_bar=self.adapter.last_processed_timestamp,
            signals_count=rep.total_signals,
            open_shadow_trades=0,
            completed_trades=rep.filled_trades,
            total_net_r=rep.total_net_r,
            uptime_seconds=round(time.time() - self.start_time, 1),
        )

    def generate_daily_summary(self, date_str: str) -> DailySummaryReport:
        """Belirtilen gün için özeti derler."""
        rep = self.engine.generate_forward_report()
        uptime_h = round((time.time() - self.start_time) / 3600.0, 2)

        return DailySummaryReport(
            date_str=date_str,
            run_id=self.engine.run_id,
            uptime_hours=uptime_h,
            new_completed_bars=rep.total_signals,
            recovered_bars=self.recovered_bars_count,
            signals_generated=rep.total_signals,
            filled_shadow_trades=rep.filled_trades,
            total_net_r=rep.total_net_r,
            average_observed_spread=self.config.spread,
            stale_ticks_count=self.stale_ticks_count,
            reconnect_count=self.reconnect_count,
            duplicate_bars_ignored=self.duplicate_bars_count,
        )

    def shutdown(self) -> None:
        """Güvenli kapatma işlemini yürütür."""
        self.running = False
        self.run_heartbeat()
        self.notifier.notify_runner_stopped(self.engine.run_id)
        self.lock.release()
        if hasattr(self.adapter, "shutdown") and callable(self.adapter.shutdown):
            self.adapter.shutdown()


def main():
    """Shadow Runner Komut Satırı Çalıştırma Giriş Noktası."""
    print("Starting NOAFVGBOT Phase 5C Operational SHADOW Runner...")
    runner = ShadowRunner()

    def signal_handler(sig, frame):
        print("\nShutdown signal received! Closing SHADOW runner cleanly...")
        runner.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    if not runner.initialize():
        print("Failed to initialize MT5 adapter. Exiting.")
        runner.shutdown()
        sys.exit(1)

    print(f"Runner Started. Mode: {runner.mode.value} | Run ID: {runner.engine.run_id}")
    runner.running = True

    try:
        while runner.running:
            runner.adapter.poll_shadow_cycle()
            runner.run_heartbeat()
            time.sleep(runner.polling_interval_sec)
    except KeyboardInterrupt:
        runner.shutdown()


if __name__ == "__main__":
    main()
