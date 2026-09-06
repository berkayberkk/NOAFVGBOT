"""
Sinyal motoru.

GÜNCELLEME (2026-09-02): Bu modül önceden A+ (FVG+OB confluence) ve
trend/EMA teyidiyle güven seviyesi belirleyen bir tasarıma sahipti.
Bu, `strategy/signal_engine.py`'nin walk-forward/holdout altyapısıyla
(bkz. `backtest/final_holdout.py`) bağlantılı OLAN ama bu oturumda
kalibre edilen (FVG/iFVG/Order Block/Trendline R-katı hedefleri, SL
tamponları, breakeven-stop eşiği -- hepsi `strategy/config.py`'de)
strateji ile HİÇ BAĞLANTISI OLMAYAN eski bir tasarımdı.

Bu oturumun tüm ampirik çalışması (100'ün üzerinde scratch script,
`results/README.md`'de özetli) şunu gösterdi:
- Dört modül (FVG/iFVG/OB/Trendline) BAĞIMSIZ sinyal üretir -- confluence
  (A+ gibi birden fazla modülün aynı bölgede/yönde çakışması) ayrıca
  test edildi (`results/confluence_and_filters/confluence_study_results.json`)
  ve kaliteyi ARTIRMADIĞI bulundu. Bu yüzden A+ artık ÜRETİLMİYOR.
- Trend/EMA filtresi bu oturumun HİÇBİR kalibrasyon/backtest çalışmasında
  kullanılmadı -- eklemek, kalibre ETMEDİĞİMİZ bir değişkeni sessizce
  strateji tanımına sokmak olurdu. Bu yüzden trend filtresi kaldırıldı.
- Her modülün kendi resmi R-katı hedefi (`MODULE_R_MULTIPLE`), SL
  tamponu (`MODULE_SL_BUFFER_RATIO`) ve (uygunsa) breakeven-stop eşiği
  (`BREAKEVEN_TRIGGER_PCT`/`BREAKEVEN_ENABLED_MODULES`) burada, sinyal
  üretim anında hesaplanıp `Signal.take_profit`/`breakeven_trigger_pct`
  alanlarına yazılıyor -- `backtest/engine.py` artık bunları (varsa)
  doğrudan kullanıyor, kendi Destek/Direnç tabanlı TP arayışına (eski
  davranış, hâlâ `take_profit=None` durumunda devrede) düşmüyor.

KAPSAM NOTU: Aşağıdaki formüller, bu oturumun `scratch_gold_account_simulation.py`/
`scratch_trade_archive.py` gibi scriptlerinde M30 zaman diliminde
doğrulanan AYNI formüllerdir -- burada TEKRAR üretilmedi, birebir
taşındı. `MODULE_DISABLED_TIMEFRAMES` burada UYGULANMIYOR çünkü bu
fonksiyon hangi zaman diliminde çalıştığını bilmiyor (çağıran taraf
karar veriyor) -- tüm bu oturumun doğrulaması zaten sadece M30'da
yapıldı, hiçbir modül M30'da devre dışı değil.

`Confidence` alanı yapısal geriye-dönük uyumluluk için duruyor (bazı
testler/backtest raporlama kodu bunu bekliyor) ama artık ayırt edici
bir sinyal taşımıyor -- trend filtresi kaldırıldığı için her sinyale
sabit `Confidence.MEDIUM` atanıyor.
"""

from dataclasses import dataclass
from enum import Enum

from strategy.fvg import detect_fvgs, FVGDirection, compute_atr_series
from strategy.ifvg import detect_confirmed_ifvgs, IFVGEvent
from strategy.order_block import detect_order_blocks, OBDirection
from strategy.trendline import detect_trendlines, detect_trendline_reversals, TrendlineDirection


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"


class Confidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SetupType(Enum):
    FVG_ONLY = "FVG"
    IFVG_ONLY = "iFVG"
    OB_ONLY = "OB"
    TRENDLINE_ONLY = "Trendline"
    A_PLUS = "A+"       # ARTIK ÜRETİLMİYOR (confluence ablation'da fayda bulunamadı) --
                         # sadece eski testlerin/backtest kodunun enum'u bilmesi için duruyor.


@dataclass
class Signal:
    index: int
    type: SignalType
    confidence: Confidence
    setup_type: SetupType
    entry: float
    stop_loss: float
    reason: str
    take_profit: float | None = None
    breakeven_trigger_pct: float | None = None
    # 2026-09-03 eklendi -- win-rate arastirmasi (bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md).
    # Sadece FVG/OB icin doldurulur (kaynak FVG/OrderBlock nesnesinden
    # aktarilir) -- iFVG/Trendline'da karsiligi yok, varsayilan False kalir.
    # Hicbiri generate_signals tarafindan ELEME icin kullanilmiyor.
    in_killzone: bool = False
    volume_confirmed: bool = False


from strategy.config import (
    DEFAULT_CONFIG, StrategyConfig, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO,
    BREAKEVEN_TRIGGER_PCT, BREAKEVEN_ENABLED_MODULES,
)


def _breakeven_pct(module: str) -> float | None:
    return BREAKEVEN_TRIGGER_PCT if module in BREAKEVEN_ENABLED_MODULES else None


def generate_signals(candles: list[dict], config: StrategyConfig = DEFAULT_CONFIG) -> list[Signal]:
    signals: list[Signal] = []

    # --- FVG ---
    # volume_confirmed sarti (2026-09-03 eklendi, bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md
    # "Win rate arastirmasi -- Aday 1 ve 2" + yeni giris temeliyle tekrar
    # dogrulama): displacement (ortadaki) mumun hacmi son 20 mumun
    # ortalamasinin 1.5 katindan azsa sinyal ELENIYOR -- iki ayri
    # KEPT_SYMBOLS calismasinda tutarli, gercek bir iyilesme (win
    # %19.8->%22.6 ilk testte, %23.9->%25.1 giris-derinligi sonrasi
    # ikinci testte). Sadece FVG'de -- OB'de etkisiz/notr cikti,
    # oraya uygulanmadi.
    for f in detect_fvgs(candles, config=config):
        if not f.valid or not f.volume_confirmed:
            continue
        is_bull = f.direction == FVGDirection.BULLISH
        signal_index = f.end_index
        if signal_index >= len(candles):
            continue
        entry = f.entry_price
        buffer = (f.top - f.bottom) * MODULE_SL_BUFFER_RATIO["fvg"]
        stop_loss = f.bottom - buffer if is_bull else f.top + buffer
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        r_mult = MODULE_R_MULTIPLE["fvg"]
        take_profit = entry + r_mult * risk if is_bull else entry - r_mult * risk
        signals.append(Signal(
            index=signal_index, type=SignalType.BUY if is_bull else SignalType.SELL,
            confidence=Confidence.MEDIUM, setup_type=SetupType.FVG_ONLY,
            entry=entry, stop_loss=stop_loss, take_profit=take_profit,
            breakeven_trigger_pct=_breakeven_pct("fvg"),
            in_killzone=f.in_killzone, volume_confirmed=f.volume_confirmed,
            reason=f"FVG({f.direction.value})",
        ))

    # --- iFVG ---
    for e in detect_confirmed_ifvgs(candles, config=config):
        is_bull = e.new_dir == FVGDirection.BULLISH
        signal_index = e.retest_index
        if signal_index >= len(candles):
            continue
        entry = e.consequent_encroachment
        buffer = (e.top - e.bottom) * MODULE_SL_BUFFER_RATIO["ifvg"]
        stop_loss = (e.bottom - buffer) if is_bull else (e.top + buffer)
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        r_mult = MODULE_R_MULTIPLE["ifvg"]
        take_profit = entry + r_mult * risk if is_bull else entry - r_mult * risk
        signals.append(Signal(
            index=signal_index, type=SignalType.BUY if is_bull else SignalType.SELL,
            confidence=Confidence.MEDIUM, setup_type=SetupType.IFVG_ONLY,
            entry=entry, stop_loss=stop_loss, take_profit=take_profit,
            breakeven_trigger_pct=_breakeven_pct("ifvg"),
            reason=f"iFVG({e.new_dir.value})",
        ))

    # --- Order Block ---
    for ob in detect_order_blocks(candles, config=config):
        is_bull = ob.direction == OBDirection.BULLISH
        signal_index = ob.impulse_index
        if signal_index >= len(candles):
            continue
        # Giris, govdenin sig/yakin kenari (bullish->top, bearish->bottom) --
        # 2026-09-03 guncellendi (bkz. FVG.entry_price docstring'i, ayni
        # bulgu OB'de de scratch_ob_entry_depth_study.py ile dogrulandi:
        # govde ortasi (eski varsayilan) yerine sig kenar, KEPT_SYMBOLS'un
        # ucunde de tutarli sekilde daha iyi win rate/beklenti verdi).
        entry = ob.top if is_bull else ob.bottom
        buffer = (ob.top - ob.bottom) * MODULE_SL_BUFFER_RATIO["ob"]
        stop_loss = (ob.bottom - buffer) if is_bull else (ob.top + buffer)
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        r_mult = MODULE_R_MULTIPLE["ob"]
        take_profit = entry + r_mult * risk if is_bull else entry - r_mult * risk
        signals.append(Signal(
            index=signal_index, type=SignalType.BUY if is_bull else SignalType.SELL,
            confidence=Confidence.MEDIUM, setup_type=SetupType.OB_ONLY,
            entry=entry, stop_loss=stop_loss, take_profit=take_profit,
            breakeven_trigger_pct=_breakeven_pct("ob"),
            in_killzone=ob.in_killzone, volume_confirmed=ob.volume_confirmed,
            reason=f"OB({ob.direction.value})",
        ))

    # --- Trendline (sıçrama + kırılım+retest) ---
    # NOT: her iki durumda da entry, TETİKLEME BARININ KENDİ high/low/close'una
    # eşit (dokunuş/reddiye anındaki gerçek fiyat) -- yani dolum KENDİ barında
    # gerçekleşir. `backtest/engine.py`'nin dolum taraması `signal.index+1`'den
    # başladığı için, bu iki durumda `signal_index = tetikleme_bari - 1`
    # kullanılıyor (diğer üç modülde böyle bir kaydırmaya gerek yok, çünkü
    # onların entry seviyesi tetikleme barının KENDİSİNDE değil, SONRAKİ
    # barlarda dolduruluyor -- bkz. bu oturumun scratch script'leri).
    r_mult_tl = MODULE_R_MULTIPLE["trendline"]
    sl_ratio_tl = MODULE_SL_BUFFER_RATIO["trendline"]
    atr_series = compute_atr_series(candles, config.atr_period)
    lines = detect_trendlines(candles, config=config)

    for tl in lines:
        is_bull = tl.direction == TrendlineDirection.ASCENDING
        start = tl.known_index + 1
        end = tl.broken_index if tl.broken_index is not None else len(candles)
        was_touching = False
        for k in range(max(start, 0), min(end, len(candles))):
            line_price = tl.price_at(k)
            tol = (atr_series[k] or 0) * config.trendline_touch_tolerance_atr_ratio
            c = candles[k]
            touched = (c["low"] <= line_price + tol) if is_bull else (c["high"] >= line_price - tol)
            if touched and not was_touching:
                touch_price = c["low"] if is_bull else c["high"]
                buffer = (atr_series[k] or 0) * sl_ratio_tl
                entry = touch_price
                stop_loss = entry - buffer if is_bull else entry + buffer
                risk = abs(entry - stop_loss)
                signal_index = k - 1
                if risk > 0 and signal_index >= 0:
                    take_profit = entry + r_mult_tl * risk if is_bull else entry - r_mult_tl * risk
                    signals.append(Signal(
                        index=signal_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                        confidence=Confidence.MEDIUM, setup_type=SetupType.TRENDLINE_ONLY,
                        entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                        breakeven_trigger_pct=_breakeven_pct("trendline"),
                        reason=f"Trendline-bounce({tl.direction.value})",
                    ))
            was_touching = touched

    reversals = detect_trendline_reversals(candles, lines, config=config)
    for r in reversals:
        rc = candles[r.retest_index]
        buffer = (atr_series[r.retest_index] or 0) * sl_ratio_tl
        entry = rc["close"]
        stop_loss = (rc["low"] - buffer) if r.is_bullish else (rc["high"] + buffer)
        risk = abs(entry - stop_loss)
        signal_index = r.retest_index - 1
        if risk <= 0 or signal_index < 0:
            continue
        take_profit = entry + r_mult_tl * risk if r.is_bullish else entry - r_mult_tl * risk
        signals.append(Signal(
            index=signal_index, type=SignalType.BUY if r.is_bullish else SignalType.SELL,
            confidence=Confidence.MEDIUM, setup_type=SetupType.TRENDLINE_ONLY,
            entry=entry, stop_loss=stop_loss, take_profit=take_profit,
            breakeven_trigger_pct=_breakeven_pct("trendline"),
            reason=f"Trendline-reversal({'bullish' if r.is_bullish else 'bearish'})",
        ))

    signals.sort(key=lambda s: s.index)
    return signals
