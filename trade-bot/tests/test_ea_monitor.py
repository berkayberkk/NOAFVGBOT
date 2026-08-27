"""
EA Monitor Testleri.
Mock MT5 arayuzu ile magic-number filtrelemeyi, portfoy risk hesabini, yeni deal
tespiti/mesaj formatlamayi ve state (last_seen_deal_ticket) devamliligini dogrular.
"""

from types import SimpleNamespace

import pytest

from backtest.ea_monitor import (
    MAGIC_NUMBER, DEAL_ENTRY_IN, DEAL_ENTRY_OUT,
    get_open_positions, calc_portfolio_risk_pct, get_new_deals,
    format_deal_message, format_status_report,
)


class FakeMT5:
    def __init__(self, positions=None, deals=None, balance=10000.0, account_connected=True):
        self._positions = positions or []
        self._deals = deals or []
        self._balance = balance
        self._account_connected = account_connected

    def positions_get(self):
        return self._positions

    def history_deals_get(self, from_dt, to_dt):
        return self._deals

    def account_info(self):
        if not self._account_connected:
            return None
        return SimpleNamespace(balance=self._balance, equity=self._balance, currency="USD")

    def symbol_info(self, symbol):
        return SimpleNamespace(trade_tick_size=0.0001, trade_tick_value=1.0)


def make_position(symbol="EURUSD", magic=MAGIC_NUMBER, ticket=1, type_=0,
                   volume=0.1, price_open=1.1000, sl=1.0950, tp=1.1100,
                   price_current=1.1010, profit=1.0, time=1700000000):
    return SimpleNamespace(
        ticket=ticket, symbol=symbol, magic=magic, type=type_, volume=volume,
        price_open=price_open, sl=sl, tp=tp, price_current=price_current,
        profit=profit, time=time,
    )


def make_deal(ticket=100, magic=MAGIC_NUMBER, symbol="EURUSD", entry=DEAL_ENTRY_IN,
              type_=0, volume=0.1, price=1.1000, profit=0.0, commission=0.0, swap=0.0,
              time=1700000000, order=1, position_id=1, comment="A+"):
    return SimpleNamespace(
        ticket=ticket, order=order, position_id=position_id, symbol=symbol, magic=magic,
        entry=entry, type=type_, volume=volume, price=price, profit=profit,
        commission=commission, swap=swap, time=time, comment=comment,
    )


def test_get_open_positions_filters_by_magic():
    positions = [make_position(ticket=1, magic=MAGIC_NUMBER), make_position(ticket=2, magic=999)]
    mt5 = FakeMT5(positions=positions)
    result = get_open_positions(mt5)
    assert len(result) == 1
    assert result[0]["ticket"] == 1


def test_get_open_positions_empty_when_none():
    mt5 = FakeMT5(positions=None)
    assert get_open_positions(mt5) == []


def test_calc_portfolio_risk_pct_sums_across_positions():
    positions = [make_position(ticket=1, price_open=1.1000, sl=1.0950, volume=0.1),
                 make_position(ticket=2, price_open=1.1000, sl=1.0900, volume=0.2)]
    mt5 = FakeMT5(positions=positions, balance=10000.0)
    pos_dicts = get_open_positions(mt5)
    pct = calc_portfolio_risk_pct(mt5, pos_dicts)
    # pos1: (0.0050/0.0001)*1.0*0.1 = 5.0 ; pos2: (0.0100/0.0001)*1.0*0.2 = 20.0 -> total 25 / 10000 * 100
    assert pct == pytest.approx(0.25, rel=1e-6)


def test_calc_portfolio_risk_pct_skips_positions_without_sl():
    positions = [make_position(ticket=1, sl=0.0)]
    mt5 = FakeMT5(positions=positions, balance=10000.0)
    pos_dicts = get_open_positions(mt5)
    assert calc_portfolio_risk_pct(mt5, pos_dicts) == 0.0


def test_get_new_deals_filters_by_magic_and_ticket_watermark():
    deals = [
        make_deal(ticket=100, magic=MAGIC_NUMBER),
        make_deal(ticket=101, magic=999),  # yabanci magic, dislanmali
        make_deal(ticket=102, magic=MAGIC_NUMBER),
    ]
    mt5 = FakeMT5(deals=deals)
    result = get_new_deals(mt5, last_seen_ticket=100)
    tickets = [d["ticket"] for d in result]
    assert tickets == [102]


def test_get_new_deals_empty_when_none():
    mt5 = FakeMT5(deals=None)
    assert get_new_deals(mt5, last_seen_ticket=0) == []


def test_format_status_report_returns_none_when_mt5_disconnected():
    mt5 = FakeMT5(account_connected=False)
    report = format_status_report(mt5, positions=[], portfolio_risk_pct=0.0)
    assert report is None


def test_format_status_report_returns_text_when_connected():
    mt5 = FakeMT5(balance=9200.0, account_connected=True)
    report = format_status_report(mt5, positions=[], portfolio_risk_pct=1.5)
    assert report is not None
    assert "9200.00" in report


def test_format_deal_message_open_vs_close():
    open_deal = get_new_deals(FakeMT5(deals=[make_deal(ticket=1, entry=DEAL_ENTRY_IN)]), 0)[0]
    close_deal = get_new_deals(FakeMT5(deals=[make_deal(ticket=1, entry=DEAL_ENTRY_OUT, profit=5.0)]), 0)[0]

    open_msg = format_deal_message(open_deal)
    close_msg = format_deal_message(close_deal)

    assert "acildi" in open_msg
    assert "kapandi" in close_msg
    assert "5.00" in close_msg
