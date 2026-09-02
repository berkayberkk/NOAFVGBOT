"""
iFVG Modülü Birim Testleri (Unit Tests for strategy/ifvg.py).
"""

from datetime import datetime, timedelta
import pytest

from strategy.fvg import FVGDirection
from strategy.ifvg import detect_confirmed_ifvgs, IFVGEvent, _mark_chop_clusters


def _make_dummy_candles(ohlc_list: list[tuple[float, float, float, float]]) -> list[dict]:
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    candles = []
    for i, (o, h, l, c) in enumerate(ohlc_list):
        candles.append({
            "time": base_time + timedelta(minutes=30 * i),
            "open": o, "high": h, "low": l, "close": c,
            "tick_volume": 100, "spread": 10,
        })
    return candles


def _bullish_fvg_break_and_reject_candles():
    # test_bullish_fvg_detection ile ayni FVG (top=102.0, bottom=101.0, idx14-16)
    neutral = [(100.0, 101.0, 99.0, 100.0)] * 14
    fvg = [
        (100.0, 101.0, 99.0, 100.5),   # idx14
        (101.0, 103.0, 100.5, 102.8),  # idx15
        (102.8, 104.0, 102.0, 103.5),  # idx16
    ]
    trailing_neutral = [(103.5, 104.0, 103.0, 103.5)] * 2  # idx17-18 -- chop-cluster/broken hesaplarina dokunmuyor
    return neutral, fvg, trailing_neutral


def test_confirmed_ifvg_on_break_and_rejection():
    neutral, fvg, _ = _bullish_fvg_break_and_reject_candles()
    broken = [(100.9, 100.9, 99.5, 100.0)]          # idx17: kapanis 100.0 < bottom(101.0) -- kirilma
    retest = [(100.0, 101.5, 99.8, 100.5)]           # idx18: high=101.5>=101.0 (temas), close=100.5<101.0 (reddiye)
    candles = _make_dummy_candles(neutral + fvg + broken + retest)

    events = detect_confirmed_ifvgs(candles)
    assert len(events) == 1

    e = events[0]
    assert e.top == 102.0
    assert e.bottom == 101.0
    assert e.new_dir == FVGDirection.BEARISH
    assert e.broken_index == 17
    assert e.retest_index == 18
    assert e.consequent_encroachment == 101.5
    assert e.chop_cluster is False


def test_no_ifvg_when_first_touch_does_not_reject():
    neutral, fvg, _ = _bullish_fvg_break_and_reject_candles()
    broken = [(100.9, 100.9, 99.5, 100.0)]           # idx17: kirilma
    no_reject = [(100.0, 101.5, 99.8, 101.3)]         # idx18: high=101.5>=101.0 (temas) ama close=101.3 >= 101.0 -- reddetmiyor
    candles = _make_dummy_candles(neutral + fvg + broken + no_reject)

    events = detect_confirmed_ifvgs(candles)
    assert events == []


def test_no_ifvg_when_fvg_never_breaks():
    neutral, fvg, trailing = _bullish_fvg_break_and_reject_candles()
    candles = _make_dummy_candles(neutral + fvg + trailing)

    events = detect_confirmed_ifvgs(candles)
    assert events == []


def _make_event(top, bottom, new_dir, broken_index):
    return IFVGEvent(top=top, bottom=bottom, new_dir=new_dir, broken_index=broken_index,
                     retest_index=broken_index + 1, consequent_encroachment=(top + bottom) / 2)


def test_chop_cluster_flags_later_opposite_overlapping_event():
    earlier = _make_event(top=100.0, bottom=99.0, new_dir=FVGDirection.BULLISH, broken_index=10)
    later = _make_event(top=99.5, bottom=98.5, new_dir=FVGDirection.BEARISH, broken_index=20)  # 10 bar sonra, cakisiyor, zit yon
    events = [earlier, later]

    _mark_chop_clusters(events, chop_cluster_bars=15)

    assert later.chop_cluster is True
    assert earlier.chop_cluster is False  # sadece GECMISE bakar -- earlier'in kendisinden once event yok


def test_no_chop_cluster_when_same_direction():
    earlier = _make_event(top=100.0, bottom=99.0, new_dir=FVGDirection.BULLISH, broken_index=10)
    later = _make_event(top=99.5, bottom=98.5, new_dir=FVGDirection.BULLISH, broken_index=20)  # cakisiyor ama AYNI yon
    events = [earlier, later]

    _mark_chop_clusters(events, chop_cluster_bars=15)

    assert later.chop_cluster is False


def test_no_chop_cluster_when_zones_dont_overlap():
    earlier = _make_event(top=100.0, bottom=99.0, new_dir=FVGDirection.BULLISH, broken_index=10)
    later = _make_event(top=90.0, bottom=89.0, new_dir=FVGDirection.BEARISH, broken_index=20)  # zit yon ama cakismiyor
    events = [earlier, later]

    _mark_chop_clusters(events, chop_cluster_bars=15)

    assert later.chop_cluster is False


def test_no_chop_cluster_when_outside_bar_window():
    earlier = _make_event(top=100.0, bottom=99.0, new_dir=FVGDirection.BULLISH, broken_index=10)
    later = _make_event(top=99.5, bottom=98.5, new_dir=FVGDirection.BEARISH, broken_index=30)  # 20 bar sonra -- pencere disi (15)
    events = [earlier, later]

    _mark_chop_clusters(events, chop_cluster_bars=15)

    assert later.chop_cluster is False
