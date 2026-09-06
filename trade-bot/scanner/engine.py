"""
Tek (sembol, zaman dilimi) analizi -- CANLI MARKET RESEARCH (backtest DEGIL).

Soru: "su an bu sembolde, bu zaman diliminde, fiyatin henuz dokunmadigi
GECERLI (henuz gecersizlesmemis) bir sinyal var mi?"

Strateji mantigi TEKRAR YAZILMADI: strategy/signal_engine.py:generate_signals
DEGISTIRILMEDEN cagriliyor -- bu modul sadece onun ciktisini "hala bekliyor mu
(pending) yoksa zaten dolmus/gecersizlesmis mi" diye SUZUYOR (ayni causal
touch/invalidation mantigi backtest/engine.py'de de var, burada YENIDEN
UYGULANMADI, sadece "resolved mi" sorusuna cevap vermek icin en basit haliyle
kullanildi -- gercek execution/PnL simulasyonu icin hala backtest/engine.py
yetkili kaynak).

Hicbir sembole ozel dal (if symbol == ...) YOK -- tum semboller ayni
fonksiyondan gecer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from strategy.config import StrategyConfig, MODULE_R_MULTIPLE
from strategy.signal_engine import generate_signals, Signal, SignalType
from scanner.data_fetch import fetch_candles, FetchResult

MODULE_LABELS = {"fvg": "FVG", "ifvg": "iFVG", "ob": "Order Block", "trendline": "Trendline"}


@dataclass
class PendingCandidate:
    module: str
    direction: str  # BUY | SELL
    entry: float
    sl: float
    tp: float
    risk: float
    expected_r: float
    signal_time: str
    reason: str


@dataclass
class TimeframeResult:
    symbol: str
    timeframe: str
    status: str  # OK | DATA_INCOMPLETE | SYMBOL_UNAVAILABLE | FETCH_ERROR
    reason: str | None = None
    analyzed_at: str = ""
    data_through: str | None = None
    n_candles: int = 0
    current_price: float | None = None
    module_verdicts: dict = field(default_factory=dict)  # {"fvg": "PASS"/"NONE", ...}
    candidates: list = field(default_factory=list)  # list[PendingCandidate] (dict'e cevrilir)
    verdict: str = "NEUTRAL"  # BUY | SELL | MIXED | NEUTRAL


def _is_still_pending(candles: list[dict], signal: Signal) -> bool:
    """Sinyal, veri penceresinin SONUNA kadar ne dolmus ne de (kaynak bolge
    gecersizlesmesi yuzunden) taranmasi durdurulmus mu -- yani hala 'bekliyor'
    mu? Ayni causal touch/invalid_after_index mantigi (bkz. backtest/engine.py),
    execution maliyeti/PnL hesaplamadan, SADECE durum sorgusu icin."""
    n = len(candles)
    for j in range(signal.index + 1, n):
        if signal.invalid_after_index is not None and j > signal.invalid_after_index:
            return False  # kaynak bolge gecersizlesti, bir daha dolum aranmiyor
        c = candles[j]
        if signal.type == SignalType.BUY:
            if c["low"] <= signal.entry:
                return False  # doldu -- artik "yeni aday" degil
        else:
            if c["high"] >= signal.entry:
                return False
    return True  # taramanin sonuna kadar ne doldu ne gecersizlesti -- hala bekliyor


def analyze_symbol_timeframe(symbol: str, timeframe: str, config: StrategyConfig | None = None, mt5_module=None) -> TimeframeResult:
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    fetch = fetch_candles(symbol, timeframe, mt5_module=mt5_module)

    if fetch.status != "OK":
        return TimeframeResult(
            symbol=symbol, timeframe=timeframe, status=fetch.status, reason=fetch.reason,
            analyzed_at=now_iso, data_through=fetch.data_through, n_candles=fetch.n_candles,
        )

    candles = fetch.candles
    cfg = config or StrategyConfig(spread=0.0)  # 101-sembol evreninde kalibre spread yok -- ayni varsayilan (universe scan'lerle tutarli)
    all_signals = generate_signals(candles, config=cfg)

    module_verdicts = {m: "NONE" for m in MODULE_LABELS}
    candidates: list[PendingCandidate] = []

    for sig in all_signals:
        if not _is_still_pending(candles, sig):
            continue
        module_key = _module_key_for(sig)
        module_verdicts[module_key] = "PASS"
        risk = abs(sig.entry - sig.stop_loss)
        candidates.append(PendingCandidate(
            module=MODULE_LABELS[module_key],
            direction="BUY" if sig.type == SignalType.BUY else "SELL",
            entry=sig.entry, sl=sig.stop_loss, tp=sig.take_profit, risk=risk,
            expected_r=MODULE_R_MULTIPLE[module_key],
            signal_time=candles[sig.index]["time"].isoformat() if sig.index < len(candles) else "",
            reason=sig.reason,
        ))

    buy_n = sum(1 for c in candidates if c.direction == "BUY")
    sell_n = sum(1 for c in candidates if c.direction == "SELL")
    if buy_n and sell_n:
        verdict = "MIXED"
    elif buy_n:
        verdict = "BUY"
    elif sell_n:
        verdict = "SELL"
    else:
        verdict = "NEUTRAL"

    return TimeframeResult(
        symbol=symbol, timeframe=timeframe, status="OK", analyzed_at=now_iso,
        data_through=fetch.data_through, n_candles=fetch.n_candles,
        current_price=candles[-1]["close"], module_verdicts=module_verdicts,
        candidates=[c.__dict__ for c in candidates], verdict=verdict,
    )


def _module_key_for(sig: Signal) -> str:
    reason = sig.reason
    if reason.startswith("FVG"):
        return "fvg"
    if reason.startswith("iFVG"):
        return "ifvg"
    if reason.startswith("OB"):
        return "ob"
    return "trendline"
