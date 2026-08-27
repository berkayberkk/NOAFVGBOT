"""
EA Izleme + Telegram Bildirim Paneli.

mql5/TradeBot_NOA_MultiSymbol.mq5'in (MagicNumber ile) actigi/kapattigi islemleri
MT5 uzerinden salt-okunur izler: acik pozisyonlarin ozetini ve portfoy risk yuzdesini
hesaplar, yeni acilan/kapanan islemler icin Telegram bildirimi gonderir.

INVARIANTLAR:
- READ-ONLY: mt5.order_send / order_check / trade execution fonksiyonlarina hic
  erisilmiyor -- sadece positions_get / history_deals_get okuyor.
- Daha once bildirilmis deal'lar bir state dosyasinda (last_seen_deal_ticket) takip
  edilir, boylece script yeniden baslatildiginda eski islemler tekrar bildirilmez.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backtest.telegram_notifier import TelegramNotifier

MAGIC_NUMBER = 20260826
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(REPO_ROOT, "backtest", "results", "ea_monitor_state.json")

DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_OUT_BY = 3  # netting close-by-opposite


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    return {"last_seen_deal_ticket": 0}


def save_state(state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def get_open_positions(mt5) -> List[Dict[str, Any]]:
    positions = mt5.positions_get()
    if not positions:
        return []
    out = []
    for p in positions:
        if p.magic != MAGIC_NUMBER:
            continue
        out.append({
            "ticket": p.ticket, "symbol": p.symbol,
            "type": "BUY" if p.type == 0 else "SELL",
            "volume": p.volume, "price_open": p.price_open,
            "sl": p.sl, "tp": p.tp, "price_current": p.price_current,
            "profit": p.profit, "time": datetime.fromtimestamp(p.time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return out


def calc_portfolio_risk_pct(mt5, positions: List[Dict[str, Any]]) -> float:
    balance = mt5.account_info().balance if mt5.account_info() else 0.0
    if balance <= 0:
        return 0.0
    total_risk_amount = 0.0
    for p in positions:
        if p["sl"] <= 0:
            continue
        info = mt5.symbol_info(p["symbol"])
        if info is None or info.trade_tick_size <= 0:
            continue
        sl_distance = abs(p["price_open"] - p["sl"])
        risk_amount = (sl_distance / info.trade_tick_size) * info.trade_tick_value * p["volume"]
        total_risk_amount += risk_amount
    return (total_risk_amount / balance) * 100.0


def get_new_deals(mt5, last_seen_ticket: int) -> List[Dict[str, Any]]:
    # NOTE: the broker/terminal clock can run hours ahead of this process's local clock
    # (observed ~3h skew against the MT5 server). Using local "now" as the upper bound
    # silently hid deals that were, in server time, already in the past but still after
    # a too-tight to_dt -- a real deal (EURJPY, 2026-08-26) was missed this way. The
    # last_seen_ticket watermark below is what actually prevents re-notifying old deals,
    # so the date window just needs to be wide enough to never clip real activity --
    # there is no cost to requesting a generous future bound.
    from_dt = datetime.now(timezone.utc) - timedelta(days=30)
    to_dt = datetime.now(timezone.utc) + timedelta(days=1)
    deals = mt5.history_deals_get(from_dt, to_dt)
    if not deals:
        return []
    out = []
    for d in deals:
        if d.magic != MAGIC_NUMBER:
            continue
        if d.ticket <= last_seen_ticket:
            continue
        out.append({
            "ticket": d.ticket, "order": d.order, "position_id": d.position_id,
            "symbol": d.symbol, "type": d.type, "entry": d.entry,
            "volume": d.volume, "price": d.price, "profit": d.profit,
            "commission": d.commission, "swap": d.swap,
            "time": datetime.fromtimestamp(d.time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "comment": d.comment,
        })
    out.sort(key=lambda x: x["ticket"])
    return out


def format_deal_message(deal: Dict[str, Any]) -> str:
    if deal["entry"] == DEAL_ENTRY_IN:
        side = "BUY" if deal["type"] == 0 else "SELL"
        return (
            f"\U0001F7E2 <b>Islem acildi -- {deal['symbol']}</b>\n"
            f"yon: {side} | hacim: {deal['volume']}\n"
            f"fiyat: {deal['price']}\n"
            f"zaman: {deal['time']}"
        )
    else:
        net = deal["profit"] + deal["commission"] + deal["swap"]
        emoji = "\U0001F4B0" if net >= 0 else "\U0001F53B"
        return (
            f"{emoji} <b>Islem kapandi -- {deal['symbol']}</b>\n"
            f"net P/L: {net:.2f}\n"
            f"fiyat: {deal['price']}\n"
            f"zaman: {deal['time']}"
        )


def format_status_report(mt5, positions: List[Dict[str, Any]], portfolio_risk_pct: float) -> Optional[str]:
    account = mt5.account_info()
    if account is None:
        return None  # MT5 terminal disconnected -- skip this report rather than crash
    lines = [
        f"\U0001F4CA <b>EA Durum Raporu</b>",
        f"bakiye: {account.balance:.2f} {account.currency} | equity: {account.equity:.2f}",
        f"portfoy riski: %{portfolio_risk_pct:.2f}",
        f"acik pozisyon: {len(positions)}",
    ]
    for p in positions:
        lines.append(f"  {p['symbol']} {p['type']} vol={p['volume']} P/L={p['profit']:.2f}")
    return "\n".join(lines)


def run_once(mt5, notifier: TelegramNotifier, send_status: bool = False) -> Dict[str, Any]:
    state = load_state()
    positions = get_open_positions(mt5)
    portfolio_risk_pct = calc_portfolio_risk_pct(mt5, positions)

    new_deals = get_new_deals(mt5, state.get("last_seen_deal_ticket", 0))
    for deal in new_deals:
        notifier.send(format_deal_message(deal))
        _log(f"deal notified: ticket={deal['ticket']} symbol={deal['symbol']} entry={deal['entry']}")

    if new_deals:
        state["last_seen_deal_ticket"] = max(d["ticket"] for d in new_deals)
        save_state(state)

    if send_status:
        report = format_status_report(mt5, positions, portfolio_risk_pct)
        if report is not None:
            notifier.send(report)

    return {
        "open_positions": len(positions),
        "portfolio_risk_pct": portfolio_risk_pct,
        "new_deals": len(new_deals),
    }


def run_loop(poll_seconds: int = 30, status_every_n_polls: int = 120) -> None:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"mt5.initialize() failed: {mt5.last_error()}")

    notifier = TelegramNotifier()
    _log(f"EA monitor started. telegram_enabled={notifier.enabled} magic={MAGIC_NUMBER}")

    poll_count = 0
    consecutive_errors = 0
    try:
        while True:
            try:
                send_status = (poll_count % status_every_n_polls == 0)
                result = run_once(mt5, notifier, send_status=send_status)
                _log(f"poll={poll_count} open={result['open_positions']} "
                     f"risk_pct={result['portfolio_risk_pct']:.2f} new_deals={result['new_deals']}")
                consecutive_errors = 0
            except KeyboardInterrupt:
                raise
            except Exception as e:
                # Never let a transient MT5/network hiccup (e.g. terminal closed and
                # reopened by the user) kill the whole monitor -- log and keep polling.
                consecutive_errors += 1
                _log(f"poll={poll_count} ERROR (consecutive={consecutive_errors}): {e}")
                if consecutive_errors >= 10:
                    _log("10 consecutive errors -- attempting mt5.initialize() reconnect")
                    mt5.initialize()
                    consecutive_errors = 0
            poll_count += 1
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        _log("EA monitor stopped by user.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    if "--once" in sys.argv:
        import MetaTrader5 as mt5
        mt5.initialize()
        notifier = TelegramNotifier()
        result = run_once(mt5, notifier, send_status=True)
        print(json.dumps(result, indent=2))
        mt5.shutdown()
    else:
        run_loop()
