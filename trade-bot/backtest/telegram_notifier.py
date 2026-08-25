"""
Telegram Bildirim Katmanı.

SHADOW runner'da üretilen sinyalleri, günlük özetleri ve bağlantı/sağlık
uyarılarını Telegram'a gönderir. Ek bağımlılık gerektirmez (stdlib
`urllib.request` kullanılır).

Token/chat id verilmezse (ne parametre ne env var) bildirici sessizce
devre dışı kalır — runner'ın bildirim yokluğunda çökmesini önler.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramNotifier:
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout_sec: float = 10.0,
    ):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        self.timeout_sec = timeout_sec
        self.enabled = bool(self.bot_token and self.chat_id)
        self.last_error: Optional[str] = None

    def send(self, text: str) -> bool:
        """Ham metin mesajı gönderir. Hata durumunda False döner, asla exception fırlatmaz."""
        if not self.enabled:
            return False

        url = f"{TELEGRAM_API_BASE}/bot{self.bot_token}/sendMessage"
        payload = json.dumps({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")

        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            self.last_error = str(e)
            return False

    # --- Yüksek seviye formatlanmış bildirimler ---

    def notify_runner_started(self, run_id: str, symbol: str, timeframe: str) -> bool:
        return self.send(
            f"🟢 <b>SHADOW runner başladı</b>\n"
            f"run_id: <code>{run_id}</code>\n"
            f"sembol: {symbol} | zaman dilimi: {timeframe}"
        )

    def notify_runner_stopped(self, run_id: str, reason: str = "") -> bool:
        text = f"🔴 <b>SHADOW runner durdu</b>\nrun_id: <code>{run_id}</code>"
        if reason:
            text += f"\nsebep: {reason}"
        return self.send(text)

    def notify_health_degraded(self, health_state: str, detail: str = "") -> bool:
        text = f"⚠️ <b>Sağlık durumu: {health_state}</b>"
        if detail:
            text += f"\n{detail}"
        return self.send(text)

    def notify_signal(self, signal_data: dict[str, Any], result: dict[str, Any]) -> bool:
        """Yeni bir sinyal SHADOW motoruna işlendiğinde çağrılır."""
        status = result.get("status", "UNKNOWN")
        if status in ("REJECTED_HISTORICAL_CUTOFF", "DUPLICATE_IGNORED"):
            return False  # geçmiş/mükerrer sinyaller için bildirim gerekmez

        direction = signal_data.get("direction", "?").upper()
        emoji = "🟩" if direction == "BUY" else "🟥"
        entry = signal_data.get("entry")
        stop_loss = signal_data.get("stop_loss")
        take_profit = signal_data.get("take_profit")
        risk_distance = abs(entry - stop_loss) if entry is not None and stop_loss is not None else None

        lines = [
            f"{emoji} <b>Yeni sinyal — {direction}</b>",
            f"setup: {signal_data.get('setup_type', '?')}",
            f"zaman: {signal_data.get('timestamp_utc', '?')}",
            f"giriş: {entry}",
            f"stop: {stop_loss}",
        ]
        if take_profit is not None:
            lines.append(f"hedef: {take_profit}")
        if risk_distance is not None:
            lines.append(f"risk mesafesi: {risk_distance:.2f}")
        lines.append(f"durum: {status}")

        return self.send("\n".join(lines))

    def notify_daily_summary(self, summary: Any) -> bool:
        """DailySummaryReport (ya da eşdeğer dict) için günlük özet mesajı."""
        get = (lambda k: getattr(summary, k, None)) if not isinstance(summary, dict) else summary.get

        return self.send(
            f"📊 <b>Günlük özet — {get('date_str')}</b>\n"
            f"run_id: <code>{get('run_id')}</code>\n"
            f"uptime: {get('uptime_hours')} sa\n"
            f"yeni sinyal: {get('signals_generated')}\n"
            f"dolan işlem: {get('filled_shadow_trades')}\n"
            f"toplam net R: {get('total_net_r')}\n"
            f"reconnect: {get('reconnect_count')} | stale tick: {get('stale_ticks_count')}"
        )


class NullNotifier(TelegramNotifier):
    """Testlerde / bildirim istenmediğinde kullanılan no-op bildirici.

    Ortam değişkenleri set edilmiş olsa bile (ör. global TELEGRAM_BOT_TOKEN)
    her zaman devre dışı kalır — base sınıfın env-var fallback'ini bilerek atlar.
    """

    def __init__(self):
        self.bot_token = None
        self.chat_id = None
        self.timeout_sec = 10.0
        self.enabled = False
        self.last_error = None
