"""
PROTOTIP (scratch, kalici degil): tum sembollerde (Round 3'te toplanan
canonical M1 verisi), 6 zaman diliminde (M30/H1/H2/H4/D1/W1) FVG ve
iFVG (Inverse Fair Value Gap) tarar. Gece boyu, gozetimsiz calismak
uzere checkpoint'li/resumable tasarlandi -- her sembol tamamlandiginda
sonuc diske yazilir, script tekrar calistirildiginda sadece eksik
semboller islenir (kesinti/oldurulme durumunda ilerleme kaybolmaz).

FVG: strategy/fvg.py'deki mevcut, test edilmis detect_fvgs/mark_filled_fvgs
kullanilir (3 mumluk fitil-gap, ATR-bazli mesafe kurali).

iFVG (Inverse FVG) -- internetten derin arastirmayla netlestirilen kurallar
(ICT "Inversion FVG" konsepti):
  - Bir FVG, SONRAKI bir mumun GOVDESI (kapanisi, sadece fitil degil) tum
    gap araligini ters yonde tam gectiginde "invert" olur -- orijinal
    yonun aksine bir mum, boslugun tamamini kapanisla asar.
  - Invert olunca, FVG'nin TUM orijinal araligi (top-bottom, tek bir kenar
    degil) artik TERS roldeki yeni bir bolge sayilir (eski destek -> yeni
    direnc, ya da tam tersi).
  - Giris seviyesi (literatur: "consequent encroachment"), invert eden
    mumun kendisi degil, bolgenin %50 orta noktasi.
  - Stop, bolgenin UZAK kenarinin biraz otesi.
Kaynaklar: fxopen.com, innercircletrader.net, tradingfinder.com (2026-08-29
tarihli arama).

Bu script SADECE TESPIT/KATALOGLAMA yapar -- iFVG icin backtest/sinyal
uretimi YOK (sabah, bulunanlar uzerinde ayri calisilacak).
"""

import json
import sys
import time
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, KEPT_SYMBOLS
from strategy.fvg import detect_fvgs, mark_filled_fvgs, FVGDirection

RESULTS_PATH = Path("fvg_scan_results.json")

TIMEFRAMES = [Timeframe.M30, Timeframe.H1, Timeframe.H2, Timeframe.H4, Timeframe.D1, Timeframe.W1]

# EXCLUDED_SYMBOLS (strategy/config.py): FVG, iFVG ve Order Block'un ucunun de
# aynı anda en kötü 10 sembol arasında bulduğu, yapısal olarak bu stratejiye
# uygun olmayan semboller çıkarıldı (2026-08-31 R-katı çalışması) --
# GERTECH30, NASDAQ, IT40, GERMID50, EURDKK, USFANG.
# + 2026-09-02, TUR 4 (kullanici karariyla): kapsam GOLD, BTCUSD, EURGBP
# UCLUSUNE daraltildi -- strategy/config.py:KEPT_SYMBOLS. Bkz.
# NOA_KONSEPTI_KAYNAK_ANALIZI.md "Sembol eleme turu 2 ve 3" bolumu.
ALL_SYMBOLS = list(KEPT_SYMBOLS)

CONFIG = StrategyConfig()


def _aggregate_by_calendar(m30_candles: list[dict], period: str) -> list[dict]:
    """
    D1/W1 icin: resample_m1'in "eksiksiz bucket" invariant'i (1440/10080 M1
    bar sart kosuyor) forex'in hafta sonu kapanisi yuzunden HICBIR takvim
    gunu/haftasi icin tutmuyor -- 0 mum donuyor. Bu, o siki invariant'i
    (kasitli, V2 research pipeline'inin veri butunlugu icin) gevsetmeden,
    SADECE bu scratch script icin M30 mumlarini UTC takvim gunu/haftasina
    (Pazartesi baslangicli ISO hafta) gore gruplar -- eksik bar olsa da
    ne varsa kullanir (FVG tespiti icin temsili gunluk/haftalik mum
    yeterli, tam eksiksizlik sart degil).
    """
    from datetime import timedelta

    buckets: dict = {}
    for c in m30_candles:
        t = c["time"]
        key = t.date() if period == "day" else (t.date() - timedelta(days=t.weekday()))
        buckets.setdefault(key, []).append(c)

    result = []
    for key in sorted(buckets.keys()):
        group = buckets[key]
        result.append({
            "time": group[0]["time"],
            "open": group[0]["open"], "close": group[-1]["close"],
            "high": max(g["high"] for g in group), "low": min(g["low"] for g in group),
            "tick_volume": sum(g["tick_volume"] for g in group), "spread": group[0]["spread"],
        })
    return result


def detect_ifvgs(fvgs: list, candles: list[dict]) -> list[dict]:
    """
    Her gecerli FVG icin, sonraki mumlardan biri govde kapanisiyla TUM
    gap araligini ters yonde gectiyse (invert), o olayi kaydeder.
    """
    ifvgs = []
    for fvg in fvgs:
        if not fvg.valid:
            continue
        for i in range(fvg.end_index + 1, len(candles)):
            c = candles[i]
            if fvg.direction == FVGDirection.BULLISH:
                if c["close"] < fvg.bottom:
                    ifvgs.append({
                        "original_direction": "bullish", "inverted_to": "bearish",
                        "top": fvg.top, "bottom": fvg.bottom,
                        "consequent_encroachment": (fvg.top + fvg.bottom) / 2,
                        "fvg_start_index": fvg.start_index, "fvg_end_index": fvg.end_index,
                        "inversion_index": i,
                    })
                    break
            else:
                if c["close"] > fvg.top:
                    ifvgs.append({
                        "original_direction": "bearish", "inverted_to": "bullish",
                        "top": fvg.top, "bottom": fvg.bottom,
                        "consequent_encroachment": (fvg.top + fvg.bottom) / 2,
                        "fvg_start_index": fvg.start_index, "fvg_end_index": fvg.end_index,
                        "inversion_index": i,
                    })
                    break
    return ifvgs


def _scan_timeframe(candles: list[dict]) -> dict:
    if len(candles) < 20:
        return {"candle_count": len(candles), "skipped": "yetersiz mum"}

    fvgs = detect_fvgs(candles, config=CONFIG)
    mark_filled_fvgs(fvgs, candles)
    valid_fvgs = [f for f in fvgs if f.valid]
    bullish = [f for f in valid_fvgs if f.direction == FVGDirection.BULLISH]
    bearish = [f for f in valid_fvgs if f.direction == FVGDirection.BEARISH]
    unfilled = [f for f in valid_fvgs if not f.filled]

    ifvgs = detect_ifvgs(fvgs, candles)

    def _recent_fvg_sample(flist, n=5):
        return [{
            "direction": f.direction.value, "top": f.top, "bottom": f.bottom,
            "entry_price": f.entry_price, "start_index": f.start_index, "end_index": f.end_index,
            "filled": f.filled, "time": candles[f.end_index]["time"].isoformat() if hasattr(candles[f.end_index]["time"], "isoformat") else str(candles[f.end_index]["time"]),
        } for f in flist[-n:]]

    return {
        "candle_count": len(candles),
        "fvg_total": len(fvgs),
        "fvg_valid": len(valid_fvgs),
        "fvg_bullish": len(bullish),
        "fvg_bearish": len(bearish),
        "fvg_unfilled_current": len(unfilled),
        "ifvg_total": len(ifvgs),
        "recent_valid_fvgs": _recent_fvg_sample(valid_fvgs),
        "recent_unfilled_fvgs": _recent_fvg_sample(unfilled),
        "recent_ifvgs": ifvgs[-5:],
    }


def _load_checkpoint() -> dict:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text())
    return {}


def _save_checkpoint(data: dict) -> None:
    tmp = RESULTS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(RESULTS_PATH)


def _process_symbol(symbol: str) -> dict | None:
    path = f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv"
    try:
        m1 = load_m1_canonical_as_candlev2(path)
    except FileNotFoundError:
        return None
    if len(m1) < 2000:
        return {"error": f"yetersiz M1 veri ({len(m1)} satir)"}

    result = {}
    m30_candles: list[dict] | None = None
    for tf in TIMEFRAMES:
        if tf in (Timeframe.D1, Timeframe.W1):
            if m30_candles is None:
                m30_v2, _ = resample_m1(m1, Timeframe.M30)
                m30_candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
            tf_candles = _aggregate_by_calendar(m30_candles, "day" if tf == Timeframe.D1 else "week")
        else:
            tf_candles_v2, _ = resample_m1(m1, tf)
            tf_candles = [candlev2_to_strategy_dict(c) for c in tf_candles_v2]
            if tf == Timeframe.M30:
                m30_candles = tf_candles
        result[tf.name] = _scan_timeframe(tf_candles)
    return result


def main():
    checkpoint = _load_checkpoint()
    remaining = [s for s in ALL_SYMBOLS if s not in checkpoint]
    print(f"Checkpoint'te {len(checkpoint)} sembol var, {len(remaining)} sembol kaldi.", flush=True)

    for symbol in remaining:
        t0 = time.time()
        result = _process_symbol(symbol)
        if result is not None:
            checkpoint[symbol] = result
            _save_checkpoint(checkpoint)
        elapsed = time.time() - t0
        print(f"[{len(checkpoint)}/{len(ALL_SYMBOLS)}] {symbol}: {elapsed:.1f}sn -- kaydedildi", flush=True)

    print("\nTUM SEMBOLLER TAMAMLANDI.", flush=True)


if __name__ == "__main__":
    main()
