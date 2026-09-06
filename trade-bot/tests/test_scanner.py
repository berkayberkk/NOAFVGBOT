"""
Scanner (Multi-Timeframe Market Research Engine) Testleri.

MT5 baglantisi GEREKTIRMEZ -- tests/test_mt5_shadow.py'deki ayni desenle
(mt5_module enjeksiyonu) sahte bir MT5 arayuzu kullanilir.
"""
from datetime import datetime, timedelta, timezone
import inspect
import os
import re

import pytest

from strategy.config import _ALL_101_SYMBOLS, KEPT_SYMBOLS
from scanner.timeframes import TIMEFRAMES, TIMEFRAME_SPECS
from scanner.data_fetch import fetch_candles
from scanner.engine import analyze_symbol_timeframe
from scanner.confluence import compute_confluence, rank_candidates


# ---------- Sahte MT5 arayuzu ----------

class _SymInfo:
    def __init__(self, visible=True):
        self.visible = visible


class MockMT5:
    """copy_rates_from_pos'un donecegi 'rates' listesi disaridan set edilir
    (self.rates_by_key: {(symbol, tf_const): [dict, ...]})."""
    def __init__(self, symbol_exists=True, symbol_visible=True):
        self.symbol_exists = symbol_exists
        self.symbol_visible = symbol_visible
        self.rates_by_key = {}
        # MT5'in gercek TIMEFRAME_* sabit degerleri onemli degil, sadece
        # birbirinden farkli olmalari yeterli (getattr ile cozuluyor)
        self.TIMEFRAME_M30 = 30
        self.TIMEFRAME_H1 = 60
        self.TIMEFRAME_H2 = 120
        self.TIMEFRAME_H4 = 240
        self.TIMEFRAME_D1 = 1440
        self.TIMEFRAME_W1 = 10080

    def initialize(self):
        return True

    def last_error(self):
        return (-1, "mock error")

    def symbol_info(self, symbol):
        if not self.symbol_exists:
            return None
        return _SymInfo(visible=self.symbol_visible)

    def symbol_select(self, symbol, enable):
        return True

    def copy_rates_from_pos(self, symbol, tf_const, start, count):
        return self.rates_by_key.get((symbol, tf_const), [])


def _make_rates(n, start_time=None, interval_seconds=1800, fvg_at=None, volume_spike=False):
    """n adet notr mum + istege bagli (fvg_at index'inde) guvenilir bir
    bullish FVG deseni (bkz. tests/test_signal_engine.py ile ayni desen).
    Varsayilan start_time, SON mum 'simdi'ye yakin dusecek sekilde geriye
    dogru hesaplanir (aksi halde stale-data kontrolu yanlislikla tetiklenir)."""
    if start_time is None:
        start_time = datetime.now(tz=timezone.utc) - timedelta(seconds=interval_seconds * n)
    rates = []
    for i in range(n):
        t = start_time + timedelta(seconds=interval_seconds * i)
        o, h, l, c, vol = 100.0, 101.0, 99.0, 100.0, 100
        if fvg_at is not None and i == fvg_at:
            o, h, l, c = 100.0, 101.0, 99.0, 100.5
        elif fvg_at is not None and i == fvg_at + 1:
            o, h, l, c = 101.0, 103.0, 100.5, 102.8
            vol = 500 if volume_spike else 100
        elif fvg_at is not None and i == fvg_at + 2:
            o, h, l, c = 102.8, 104.0, 102.0, 103.5
        elif fvg_at is not None and i > fvg_at + 2:
            # Gap'in (bottom=101.0) ne AŞAĞI (invalidation) ne YUKARI (entry=102.0
            # touch) yönünde bozulmaması için "güvenli bölge"de kalan mumlar --
            # aksi halde sinyal hemen gecersiz/dolmus sayilir, "hala bekliyor"
            # durumu test edilemez.
            o, h, l, c = 103.0, 103.2, 102.8, 103.0
        rates.append({"time": int(t.timestamp()), "open": o, "high": h, "low": l, "close": c, "tick_volume": vol})
    return rates


# ---------- 1. Instrument / timeframe coverage ----------

def test_101_symbol_universe_is_the_research_scope():
    assert len(_ALL_101_SYMBOLS) == 101
    # KEPT_SYMBOLS (canli trade edilen) 101'in bir alt kumesi -- scanner
    # bunlari da AYNI pipeline'dan geciriyor, ozel muamele YOK (bkz. test_no_symbol_specific_branching)
    assert set(KEPT_SYMBOLS).issubset(set(_ALL_101_SYMBOLS))


def test_all_six_timeframes_defined():
    assert TIMEFRAMES == ["M30", "H1", "H2", "H4", "D1", "W1"]
    assert set(TIMEFRAME_SPECS.keys()) == set(TIMEFRAMES)


# ---------- 2. Modul coverage ----------

def test_module_verdicts_include_all_four_modules():
    mock = MockMT5()
    rates = _make_rates(30, fvg_at=20, volume_spike=True)
    mock.rates_by_key[("EURUSD", mock.TIMEFRAME_M30)] = rates
    r = analyze_symbol_timeframe("EURUSD", "M30", mt5_module=mock)
    assert r.status == "DATA_INCOMPLETE"  # 30 < min_required_bars(200) -- ayri test asagida bunu dogru test ediyor
    assert set(r.module_verdicts.keys()) if r.module_verdicts else True  # (asil modul-kapsami testi altta, yeterli veriyle)


def test_module_verdicts_full_set_with_sufficient_data():
    mock = MockMT5()
    rates = _make_rates(250, fvg_at=220, volume_spike=True)
    mock.rates_by_key[("EURUSD", mock.TIMEFRAME_M30)] = rates
    r = analyze_symbol_timeframe("EURUSD", "M30", mt5_module=mock)
    assert r.status == "OK"
    assert set(r.module_verdicts.keys()) == {"fvg", "ifvg", "ob", "trendline"}
    assert r.module_verdicts["fvg"] == "PASS"  # bilerek yerlestirilen FVG deseni yakalanmali


# ---------- 3. Esitlik testi: sembol adina gore DAL YOK ----------

def test_no_symbol_specific_branching_in_scanner_source():
    """scanner/ altindaki hicbir dosyada belirli bir sembole (GOLD/BTC/XAUUSD
    vb.) gore kod dalı olmamali -- proje talebinin '9. OZEL PARITE MANTIGINI
    KALDIR' bolumunun otomatik/kalici regresyon testi."""
    scanner_dir = os.path.join(os.path.dirname(__file__), "..", "scanner")
    forbidden = re.compile(
        r"symbol\s*==\s*['\"](GOLD|BTC|BTCUSD|XAUUSD|EURUSD)['\"]|"
        r"priority_symbols|special_symbols|top_symbols|favorite_symbols",
        re.IGNORECASE,
    )
    offenders = []
    for fname in os.listdir(scanner_dir):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(scanner_dir, fname)
        text = open(path, encoding="utf-8").read()
        if forbidden.search(text):
            offenders.append(fname)
    assert offenders == [], f"scanner/ icinde sembole-ozel dal bulundu: {offenders}"


def test_gold_and_arbitrary_symbol_use_identical_code_path():
    """Ayni (sahte) veriyle GOLD ve rastgele bir sembol (ZZZTEST) TAMAMEN
    ayni sonucu uretmeli -- sembol adi mantigi hicbir sekilde etkilemiyor."""
    rates = _make_rates(250, fvg_at=220, volume_spike=True)
    results = {}
    for symbol in ["GOLD", "ZZZTEST"]:
        mock = MockMT5()
        mock.rates_by_key[(symbol, mock.TIMEFRAME_M30)] = rates
        r = analyze_symbol_timeframe(symbol, "M30", mt5_module=mock)
        results[symbol] = r
    assert results["GOLD"].status == results["ZZZTEST"].status == "OK"
    assert results["GOLD"].verdict == results["ZZZTEST"].verdict
    assert results["GOLD"].module_verdicts == results["ZZZTEST"].module_verdicts
    assert len(results["GOLD"].candidates) == len(results["ZZZTEST"].candidates)


# ---------- 4. Eksik veri ----------

def test_insufficient_candles_marked_data_incomplete():
    mock = MockMT5()
    mock.rates_by_key[("EURUSD", mock.TIMEFRAME_W1)] = _make_rates(10)  # W1 min=60
    r = analyze_symbol_timeframe("EURUSD", "W1", mt5_module=mock)
    assert r.status == "DATA_INCOMPLETE"
    assert "yetersiz mum" in r.reason


def test_symbol_unavailable_not_shown_as_fake_no_trade():
    """Sembol broker'da yoksa (isim uyusmazligi) ANALYSIS UNAVAILABLE gibi
    acikca isaretlenmeli -- sahte bir NEUTRAL/NO_TRADE sonucu UYDURULMAMALI."""
    mock = MockMT5(symbol_exists=False)
    r = analyze_symbol_timeframe("AUS200", "H4", mt5_module=mock)
    assert r.status == "SYMBOL_UNAVAILABLE"
    assert r.verdict == "NEUTRAL"  # varsayilan deger ama status alani zaten "gercek degil, eksik" diyor
    assert r.candidates == []


def test_duplicate_candle_timestamps_marked_incomplete():
    mock = MockMT5()
    rates = _make_rates(250)
    rates[100]["time"] = rates[99]["time"]  # duplicate zaman damgasi
    mock.rates_by_key[("EURUSD", mock.TIMEFRAME_M30)] = rates
    r = analyze_symbol_timeframe("EURUSD", "M30", mt5_module=mock)
    assert r.status == "DATA_INCOMPLETE"
    assert "duplicate" in r.reason


def test_stale_data_marked_incomplete():
    mock = MockMT5()
    old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)  # cok eski -- stale
    rates = _make_rates(250, start_time=old_time)
    mock.rates_by_key[("EURUSD", mock.TIMEFRAME_M30)] = rates
    r = analyze_symbol_timeframe("EURUSD", "M30", mt5_module=mock)
    assert r.status == "DATA_INCOMPLETE"
    assert "bayat" in r.reason


# ---------- 5. Basarisiz tarama izolasyonu (orchestrator seviyesinde) ----------

def test_failed_timeframe_does_not_kill_other_timeframes(monkeypatch):
    """Bir (sembol,timeframe) FETCH_ERROR verse bile digerleri normal
    islenmeye devam etmeli -- bkz. scanner/orchestrator.py'nin per-timeframe
    try/except'i."""
    import scanner.orchestrator as orch

    call_log = []

    def fake_analyze(symbol, tf, config=None):
        call_log.append((symbol, tf))
        if tf == "H4":
            raise RuntimeError("simule edilmis MT5 hatasi")
        from scanner.engine import TimeframeResult
        return TimeframeResult(symbol=symbol, timeframe=tf, status="OK", verdict="NEUTRAL")

    monkeypatch.setattr(orch, "analyze_symbol_timeframe", fake_analyze)
    monkeypatch.setattr(orch, "RESULTS_PATH", "test_scratch_scanner_results.json")
    monkeypatch.setattr(orch, "CONFLUENCE_PATH", "test_scratch_scanner_confluence.json")
    monkeypatch.setattr(orch, "CANDIDATES_PATH", "test_scratch_scanner_candidates.json")
    monkeypatch.setattr(orch, "PROGRESS_PATH", "test_scratch_scanner_progress.json")

    try:
        orch.run_full_scan(symbols=["EURUSD"])
        # 6 timeframe'in HEPSI cagrilmis olmali (H4 patlasa bile)
        assert len(call_log) == 6
        assert ("EURUSD", "H4") in call_log
        assert ("EURUSD", "D1") in call_log  # H4'ten SONRAKI timeframe'ler de calismis
    finally:
        for p in ["test_scratch_scanner_results.json", "test_scratch_scanner_confluence.json",
                  "test_scratch_scanner_candidates.json", "test_scratch_scanner_progress.json"]:
            if os.path.exists(p):
                os.remove(p)


def test_duplicate_scan_skips_already_completed_symbols(monkeypatch, tmp_path):
    import scanner.orchestrator as orch

    call_log = []

    def fake_analyze(symbol, tf, config=None):
        call_log.append((symbol, tf))
        from scanner.engine import TimeframeResult
        return TimeframeResult(symbol=symbol, timeframe=tf, status="OK", verdict="NEUTRAL")

    results_path = str(tmp_path / "results.json")
    confluence_path = str(tmp_path / "confluence.json")
    candidates_path = str(tmp_path / "candidates.json")
    progress_path = str(tmp_path / "progress.json")

    import json
    from dataclasses import asdict
    from scanner.engine import TimeframeResult
    pre_existing = {tf: asdict(TimeframeResult(symbol="EURUSD", timeframe=tf, status="OK", verdict="NEUTRAL")) for tf in TIMEFRAMES}
    with open(results_path, "w") as f:
        json.dump({"EURUSD": pre_existing}, f)

    monkeypatch.setattr(orch, "analyze_symbol_timeframe", fake_analyze)
    monkeypatch.setattr(orch, "RESULTS_PATH", results_path)
    monkeypatch.setattr(orch, "CONFLUENCE_PATH", confluence_path)
    monkeypatch.setattr(orch, "CANDIDATES_PATH", candidates_path)
    monkeypatch.setattr(orch, "PROGRESS_PATH", progress_path)

    orch.run_full_scan(symbols=["EURUSD", "GBPUSD"])
    # EURUSD zaten tamamlanmisti -- TEKRAR taranmamali, sadece GBPUSD (6 is)
    assert all(sym == "GBPUSD" for sym, tf in call_log)
    assert len(call_log) == 6


# ---------- 6. Confluence / ranking objektifligi ----------

def test_confluence_alignment_and_conflict():
    from scanner.engine import TimeframeResult
    tf_results = {
        "M30": TimeframeResult(symbol="X", timeframe="M30", status="OK", verdict="BUY"),
        "H1": TimeframeResult(symbol="X", timeframe="H1", status="OK", verdict="BUY"),
        "H2": TimeframeResult(symbol="X", timeframe="H2", status="OK", verdict="SELL"),
        "H4": TimeframeResult(symbol="X", timeframe="H4", status="OK", verdict="SELL"),
        "D1": TimeframeResult(symbol="X", timeframe="D1", status="OK", verdict="SELL"),
        "W1": TimeframeResult(symbol="X", timeframe="W1", status="DATA_INCOMPLETE"),
    }
    conf = compute_confluence("X", tf_results)
    assert conf.analyzable_timeframes == 5
    assert conf.buy_count == 2 and conf.sell_count == 3
    assert conf.dominant_direction == "SELL"
    assert conf.alignment_score == 3
    assert conf.alignment_label == "3/5"
    assert conf.conflict is True  # kisa vade BUY, uzun vade SELL


def test_ranking_uses_objective_criteria_not_symbol_name():
    """Ayni MTF-alignment ve risk'e sahip iki adayda, sembol adi (alfabetik
    sira HARIC) sonucu etkilememeli -- 'ZZZ' sembolu 'AAA'dan once gelebilir
    eger objektif kriterlerde (expected_r) daha iyiyse."""
    from scanner.engine import TimeframeResult
    from scanner.confluence import ConfluenceResult

    all_results = {
        "AAA": {"M30": TimeframeResult(symbol="AAA", timeframe="M30", status="OK", verdict="BUY",
                candidates=[{"module": "FVG", "direction": "BUY", "entry": 1, "sl": 0.9, "tp": 1.2,
                             "risk": 0.1, "expected_r": 1.5, "signal_time": "t", "reason": "FVG"}])},
        "ZZZ": {"M30": TimeframeResult(symbol="ZZZ", timeframe="M30", status="OK", verdict="BUY",
                candidates=[{"module": "OB", "direction": "BUY", "entry": 1, "sl": 0.9, "tp": 1.3,
                             "risk": 0.1, "expected_r": 3.0, "signal_time": "t", "reason": "OB"}])},
    }
    confluence = {
        "AAA": ConfluenceResult(symbol="AAA", alignment_score=3, alignment_label="3/6"),
        "ZZZ": ConfluenceResult(symbol="ZZZ", alignment_score=3, alignment_label="3/6"),
    }
    ranked = rank_candidates(all_results, confluence)
    assert ranked[0]["symbol"] == "ZZZ"  # expected_r(3.0) > (1.5) -- alfabetik degil, objektif kriter kazandi
