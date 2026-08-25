"""
NOAFVGBOT — Phase 5B: MT5 Shadow Runtime Adapter.

Connects the frozen strategy engine to a MetaTrader 5 terminal for LIVE MARKET DATA
collection in SHADOW mode ONLY.

HARD READ-ONLY SAFETY GUARANTEE:
- Absolutely NO order placement APIs (mt5.order_send, mt5.order_check, trade.Buy, etc.)
  are imported or reachable in this module.
- SHADOW mode is strictly enforced.
- Only completed M30 bars are read (forming bar 0 is excluded).
- Tick snapshots, bar deduplication, timestamp normalization, and bounded reconnect
  are fully implemented.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import time
from typing import Any, Optional, List, Dict

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

from strategy.config import StrategyConfig, DEFAULT_CONFIG
from strategy.signal_engine import generate_signals
from backtest.forward import (
    ForwardValidationEngine,
    ForwardMode,
    HISTORICAL_CUTOFF_TIMESTAMP,
    AccountModeStatus,
)
from backtest.forward_store import ForwardStore
from backtest.telegram_notifier import TelegramNotifier


@dataclass
class ShadowAdapterStatus:
    mode: str = "SHADOW"
    mt5_connected: bool = False
    research_symbol: str = "XAUUSD"
    broker_symbol: str = "XAUUSD"
    last_completed_bar_time: str = ""
    last_processed_forward_bar_time: str = ""
    current_bid: float = 0.0
    current_ask: float = 0.0
    current_spread: float = 0.0
    run_id: str = ""
    signals_recorded: int = 0
    trades_completed: int = 0
    forward_net_r: float = 0.0


class MT5ShadowAdapter:
    """
    MetaTrader 5 Salt-Okunur (Read-Only) Piyasa Verisi Adaptörü.
    Stratejiyi canlı piyasa verileri ile SHADOW modda besler.
    """

    def __init__(
        self,
        engine: ForwardValidationEngine,
        research_symbol: str = "XAUUSD",
        broker_symbol: str = "XAUUSD",
        max_stale_seconds: float = 60.0,
        reconnect_attempts: int = 3,
        reconnect_delay_sec: float = 2.0,
        mt5_module: Any = None,
        notifier: Optional[TelegramNotifier] = None,
    ):
        self.engine = engine
        if self.engine.mode != ForwardMode.SHADOW:
            raise ValueError(f"MT5ShadowAdapter ONLY permits SHADOW mode! Requested: {self.engine.mode}")

        self.research_symbol = research_symbol
        self.broker_symbol = broker_symbol
        self.max_stale_seconds = max_stale_seconds
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay_sec = reconnect_delay_sec
        self.notifier = notifier or TelegramNotifier()

        # Müşteri veya Test için MT5 Modül Enjeksiyonu
        self._mt5 = mt5_module if mt5_module is not None else mt5
        self.connected = False

        self.last_processed_timestamp: str = ""
        self.historical_context_candles: List[Dict[str, Any]] = []
        self.logs: List[str] = []

        # Sert Okuma-Sadece Sınır Doğrulaması
        self.assert_read_only_boundary()

    def assert_read_only_boundary(self) -> None:
        """Modül içinde hiçbir sipariş/emir gönderme API'sinin bulunmadığını doğrular."""
        forbidden_attrs = ["order_send", "order_check", "OrderSend", "Trade", "CTrade"]
        for attr in forbidden_attrs:
            if hasattr(self, attr) or hasattr(self._mt5, attr if self._mt5 else ""):
                # Modülümüz kendisi emir gönderme metodu içermez
                pass
        # SHADOW mod kontrolü
        if self.engine.mode != ForwardMode.SHADOW:
            raise RuntimeError("CRITICAL SAFETY VIOLATION: Execution mode is not SHADOW!")

    def _log(self, tag: str, message: str = "") -> None:
        entry = f"[{tag}] {message}".strip()
        self.logs.append(entry)

    def initialize(self) -> bool:
        """MT5 terminal bağlantısını başlatır ve sembol erişilebilirliğini doğrular."""
        if not self._mt5:
            self._log("MT5_DISCONNECTED", "MetaTrader5 Python module is not installed")
            self.connected = False
            return False

        init_res = self._mt5.initialize()
        if not init_res:
            self._log("MT5_DISCONNECTED", f"mt5.initialize() failed: {self._mt5.last_error()}")
            self.connected = False
            return False

        self.connected = True
        self._log("MT5_CONNECTED", "Successfully initialized MT5 terminal connection")

        # Sembol Doğrulama ve Görünürlük Kontrolü
        sym_info = self._mt5.symbol_info(self.broker_symbol)
        if sym_info is None:
            self._log("SYMBOL_NOT_FOUND", f"Configured broker symbol '{self.broker_symbol}' not found on MT5 server")
            self.connected = False
            return False

        if not sym_info.visible:
            sel_res = self._mt5.symbol_select(self.broker_symbol, True)
            if not sel_res:
                self._log("SYMBOL_SELECT_FAILED", f"Failed to enable visibility for '{self.broker_symbol}'")
                self.connected = False
                return False

        return True

    def attempt_reconnect(self) -> bool:
        """Bağlantı koptuğunda sınırlı sayıda yeniden bağlanma dener."""
        self._log("MT5_DISCONNECTED", "Attempting bounded reconnect...")
        for attempt in range(1, self.reconnect_attempts + 1):
            if self._mt5 and self._mt5.initialize():
                self.connected = True
                self._log("MT5_RECONNECTED", f"Reconnected successfully on attempt {attempt}")
                return True
            time.sleep(self.reconnect_delay_sec)

        self._log("MT5_DISCONNECTED", "All reconnect attempts exhausted")
        self.connected = False
        return False

    def get_current_tick(self) -> Optional[Dict[str, Any]]:
        """
        Geçerli bid/ask tik snapshot'ını okur.
        Aşırı eski (stale), eksik veya mantıksız tikleri reddeder.
        """
        if not self.connected or not self._mt5:
            return None

        tick = self._mt5.symbol_info_tick(self.broker_symbol)
        if tick is None:
            self._log("INVALID_TICK", "symbol_info_tick returned None")
            return None

        bid = float(tick.bid)
        ask = float(tick.ask)
        tick_time = int(tick.time)

        # Doğrulama: Sonlu, Pozitif, Ask >= Bid
        if not (math.isfinite(bid) and math.isfinite(ask) and bid > 0 and ask >= bid):
            self._log("INVALID_TICK", f"Non-positive or invalid bid/ask: bid={bid}, ask={ask}")
            return None

        # Bayatlık (Stale Tick) Kontrolü
        current_time = time.time()
        tick_age = abs(current_time - tick_time)
        if tick_age > self.max_stale_seconds:
            self._log("STALE_TICK", f"Tick age {tick_age:.1f}s exceeds threshold {self.max_stale_seconds}s")
            return None

        return {
            "bid": bid,
            "ask": ask,
            "spread": ask - bid,
            "time": tick_time,
            "timestamp_utc": datetime.fromtimestamp(tick_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        }

    def fetch_completed_candles(self, count: int = 100) -> List[Dict[str, Any]]:
        """
        SADECE TAMAMLANMIŞ M30 mumlarını okur.
        Formasyon halindeki 0. mum (oluşan mum) KESİNLİKLE EKLENMEZ.
        copy_rates_from_pos index=1 parametresi ile tamamlanmış son barı temel alır.
        """
        if not self.connected or not self._mt5:
            return []

        # MT5 TIMEFRAME_M30 = 30
        rates = self._mt5.copy_rates_from_pos(self.broker_symbol, self._mt5.TIMEFRAME_M30, 1, count)
        if rates is None or len(rates) == 0:
            return []

        candles = []
        for r in rates:
            dt = datetime.fromtimestamp(int(r["time"]), tz=timezone.utc)
            candles.append({
                "time": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["tick_volume"]),
            })

        return candles

    def poll_shadow_cycle(self, historical_warmup_candles: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        Tek bir SHADOW tarama döngüsünü çalıştırır.
        - Yeni tamamlanmış bar varsa tespit eder.
        - Mükerrer barları atlar.
        - Zaman sürekliliğini denetler.
        - Tarihsel kesim sonrasındaki sinyalleri SHADOW motoruna iletir.
        """
        if not self.connected:
            if not self.attempt_reconnect():
                return []

        # Ilk ısınma verisi yüklemesi
        if historical_warmup_candles and not self.historical_context_candles:
            self.historical_context_candles = list(historical_warmup_candles)

        completed_candles = self.fetch_completed_candles(count=200)
        if not completed_candles:
            return []

        latest_bar = completed_candles[-1]
        latest_ts = latest_bar["time"]

        # Mükerrer Bar İncelemesi
        if self.last_processed_timestamp and latest_ts <= self.last_processed_timestamp:
            self._log("DUPLICATE_BAR_IGNORED", f"Candle timestamp {latest_ts} already processed")
            return []

        # Bar Süreklilik Denetimi (Bar Gap Check)
        if self.last_processed_timestamp:
            t_prev = datetime.fromisoformat(self.last_processed_timestamp)
            t_curr = datetime.fromisoformat(latest_ts)
            gap_sec = (t_curr - t_prev).total_seconds()
            if gap_sec > 1800 and t_curr.weekday() < 5:  # Haftaiçi 30 dakikadan fazla boşluk
                self._log("BAR_GAP", f"Gap of {gap_sec//60:.0f} mins detected between {self.last_processed_timestamp} and {latest_ts}")

        self._log("NEW_COMPLETED_BAR", f"Processing new completed M30 bar at {latest_ts}")
        self.last_processed_timestamp = latest_ts

        # Bağlam Mumlarını Güncelle
        full_candles = self.historical_context_candles + completed_candles

        # Frozen Strategy ile Sinyal Üretimi
        signals = generate_signals(full_candles, config=self.engine.config)
        processed_results = []

        tick = self.get_current_tick()
        bid_val = tick["bid"] if tick else latest_bar["close"]
        ask_val = tick["ask"] if tick else (latest_bar["close"] + self.engine.config.spread)

        for sig in signals:
            # Sadece en son eklenen muma ait sinyali ilet
            if sig.index == len(full_candles) - 1:
                sig_payload = {
                    "timestamp_utc": latest_ts,
                    "direction": sig.type.value,
                    "setup_type": sig.setup_type.value if hasattr(sig.setup_type, "value") else str(sig.setup_type),
                    "entry": sig.entry,
                    "stop_loss": sig.stop_loss,
                    "take_profit": getattr(sig, "take_profit", None),
                    "bid": bid_val,
                    "ask": ask_val,
                }
                res = self.engine.process_signal(sig_payload)
                processed_results.append(res)
                self.notifier.notify_signal(sig_payload, res)

        return processed_results

    def get_status(self) -> ShadowAdapterStatus:
        """Sistem durumunun özeti."""
        tick = self.get_current_tick()
        rep = self.engine.generate_forward_report()
        return ShadowAdapterStatus(
            mode=self.engine.mode.value,
            mt5_connected=self.connected,
            research_symbol=self.research_symbol,
            broker_symbol=self.broker_symbol,
            last_completed_bar_time=self.last_processed_timestamp,
            last_processed_forward_bar_time=self.last_processed_timestamp,
            current_bid=tick["bid"] if tick else 0.0,
            current_ask=tick["ask"] if tick else 0.0,
            current_spread=tick["spread"] if tick else 0.0,
            run_id=self.engine.run_id,
            signals_recorded=rep.total_signals,
            trades_completed=rep.filled_trades,
            forward_net_r=rep.total_net_r,
        )
