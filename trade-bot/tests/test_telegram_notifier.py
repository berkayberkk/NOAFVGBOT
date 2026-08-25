"""
Telegram Bildirim Katmanı Testleri.
Token/chat_id yokken sessiz no-op davranışını, mesaj formatlamayı ve
sendMessage çağrısının urlopen seviyesinde doğru tetiklendiğini doğrular.
"""

import json
import urllib.error

import pytest

from backtest.telegram_notifier import TelegramNotifier, NullNotifier


def test_disabled_without_token_and_chat_id(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    n = TelegramNotifier()
    assert n.enabled is False
    assert n.send("test") is False


def test_disabled_send_never_calls_urlopen(monkeypatch):
    n = TelegramNotifier(bot_token=None, chat_id=None)
    called = {"n": 0}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    n.send("hello")
    assert called["n"] == 0


def test_enabled_when_token_and_chat_id_present():
    n = TelegramNotifier(bot_token="abc123", chat_id="999")
    assert n.enabled is True


def test_send_success_calls_urlopen_with_expected_url(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    n = TelegramNotifier(bot_token="TOKEN", chat_id="42")
    ok = n.send("merhaba")

    assert ok is True
    assert captured["url"] == "https://api.telegram.org/botTOKEN/sendMessage"
    assert captured["body"]["chat_id"] == "42"
    assert captured["body"]["text"] == "merhaba"


def test_send_failure_returns_false_and_records_last_error(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    n = TelegramNotifier(bot_token="TOKEN", chat_id="42")
    ok = n.send("merhaba")

    assert ok is False
    assert "connection refused" in n.last_error


def test_notify_signal_skips_historical_cutoff_and_duplicate(monkeypatch):
    sent = []
    monkeypatch.setattr(TelegramNotifier, "send", lambda self, text: sent.append(text) or True)

    n = TelegramNotifier(bot_token="TOKEN", chat_id="42")
    sig = {"direction": "buy", "setup_type": "A_PLUS", "entry": 2000.0, "stop_loss": 1990.0,
           "timestamp_utc": "2026-07-25 10:00:00"}

    assert n.notify_signal(sig, {"status": "REJECTED_HISTORICAL_CUTOFF"}) is False
    assert n.notify_signal(sig, {"status": "DUPLICATE_IGNORED"}) is False
    assert sent == []


def test_notify_signal_sends_for_shadow_simulated(monkeypatch):
    sent = []
    monkeypatch.setattr(TelegramNotifier, "send", lambda self, text: sent.append(text) or True)

    n = TelegramNotifier(bot_token="TOKEN", chat_id="42")
    sig = {"direction": "buy", "setup_type": "A_PLUS", "entry": 2000.0, "stop_loss": 1990.0,
           "take_profit": 2020.0, "timestamp_utc": "2026-07-25 10:00:00"}

    assert n.notify_signal(sig, {"status": "SHADOW_SIMULATED"}) is True
    assert len(sent) == 1
    assert "BUY" in sent[0]
    assert "SHADOW_SIMULATED" in sent[0]


def test_null_notifier_is_always_disabled(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "some-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "some-chat")
    n = NullNotifier()
    assert n.enabled is False
    assert n.send("x") is False
