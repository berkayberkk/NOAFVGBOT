"""
Multi-Symbol Acquisition Testleri.
fetch_chunk_rows'un watermark (last_verified_ts) mantigini test eder -- ozellikle
geriye donuk derinlik genisletmesi (backward depth extension) sirasinda eski/uzak bir
watermark'in, o an cekilen (kronolojik olarak cok daha erken) chunk'in TUM satirlarini
yanlislikla "zaten var" sayip silmemesi gerektigini dogrular (regresyon: EURGBP 2010-2021
backfill'i sirinde tum satirlar filtrelenip chunk yine de 'tamamlandi' isaretlenmisti).
"""

from datetime import datetime, timezone
import numpy as np

from research.v2.data.run_multi_symbol_acquisition import fetch_chunk_rows


class FakeRatesArray(list):
    """MT5'in numpy structured array donusune benzer sekilde davranan liste sarmalayici."""
    pass


def make_rate(ts: str, o=1.0, h=1.01, l=0.99, c=1.0, vol=10, spread=5):
    dt = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
    return {"time": int(dt.timestamp()), "open": o, "high": h, "low": l, "close": c,
            "tick_volume": vol, "spread": spread}


class FakeMT5ForFetch:
    def __init__(self, rates):
        self._rates = rates

    def copy_rates_range(self, symbol, timeframe, start, end):
        arr = np.array(
            [(r["time"], r["open"], r["high"], r["low"], r["close"], r["tick_volume"], r["spread"])
             for r in self._rates],
            dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
                   ("close", "f8"), ("tick_volume", "i8"), ("spread", "i4")],
        )
        return arr

    TIMEFRAME_M1 = 1


def test_stale_far_future_watermark_does_not_erase_early_backfill_chunk():
    """Regresyon: last_verified_ts eski (2026) bir kosudan kalma, ama su an 2010 chunk'i
    cekiliyor -- watermark bu chunk icin gecersiz sayilmali, satirlar SILINMEMELI."""
    chunk_start = datetime(2010, 2, 1, tzinfo=timezone.utc)
    chunk_end = datetime(2010, 3, 3, tzinfo=timezone.utc)
    floor_dt = datetime(2010, 1, 1, tzinfo=timezone.utc)
    now_utc = datetime(2026, 8, 26, tzinfo=timezone.utc)
    stale_watermark = "2026-08-24 21:51:00"  # eski, uzak-gelecekteki bir kosudan kalma

    rates = [make_rate("2010-02-05 10:00:00"), make_rate("2010-02-10 12:00:00")]
    mt5 = FakeMT5ForFetch(rates)

    rows = fetch_chunk_rows(mt5, "EURGBP", chunk_start, chunk_end, stale_watermark, now_utc, floor_dt)

    assert len(rows) == 2, "eski/uzak watermark, bu erken chunk'in satirlarini silmemeli"


def test_adjacent_watermark_still_dedupes_overlap_window():
    """Watermark, chunk'in kendi overlap-lookback penceresi icindeyse (yani hemen onceki
    chunk'tan kalmaysa) hala dogru sekilde dedup yapmali."""
    chunk_start = datetime(2021, 2, 3, tzinfo=timezone.utc)
    chunk_end = datetime(2021, 3, 5, tzinfo=timezone.utc)
    floor_dt = datetime(2010, 1, 1, tzinfo=timezone.utc)
    now_utc = datetime(2026, 8, 26, tzinfo=timezone.utc)
    adjacent_watermark = "2021-02-03 01:30:00"  # hemen onceki chunk'in son satirindan

    rates = [
        make_rate("2021-02-03 01:00:00"),  # watermark'tan once -> dedup edilmeli
        make_rate("2021-02-03 02:00:00"),  # watermark'tan sonra -> kalmali
    ]
    mt5 = FakeMT5ForFetch(rates)

    rows = fetch_chunk_rows(mt5, "EURGBP", chunk_start, chunk_end, adjacent_watermark, now_utc, floor_dt)

    assert len(rows) == 1
    assert rows[0]["timestamp_open_utc"] == "2021-02-03 02:00:00"


def test_no_watermark_keeps_all_rows_within_chunk():
    chunk_start = datetime(2010, 1, 1, tzinfo=timezone.utc)
    chunk_end = datetime(2010, 1, 31, tzinfo=timezone.utc)
    floor_dt = datetime(2010, 1, 1, tzinfo=timezone.utc)
    now_utc = datetime(2026, 8, 26, tzinfo=timezone.utc)

    rates = [make_rate("2010-01-05 00:00:00"), make_rate("2010-01-10 00:00:00")]
    mt5 = FakeMT5ForFetch(rates)

    rows = fetch_chunk_rows(mt5, "EURGBP", chunk_start, chunk_end, None, now_utc, floor_dt)

    assert len(rows) == 2
