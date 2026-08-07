"""
Sinyal motoru.

Kullanıcının A+ setup tanımı: FVG ve Order Block aynı bölgede üst üste
gelirse ve aynı yöndeyse, bu A+ (en güçlü) setup sayılır.

Sistem gevşetildi: A+ dışında tek başına FVG ya da tek başına OB da
(daha düşük güvenle) sinyal üretebiliyor. Her sinyalin `setup_type`
alanı hangi kategoriden geldiğini gösterir — backtest/kullanım
aşamasında istenirse sadece A+ ile, istenirse hepsiyle çalışılabilir.

Trend, hiçbir zaman sert bir "ya hep ya hiç" filtresi değil (sadece tam
ters yön elenir); yön+EMA teyidi durumuna göre güven seviyesini belirler.
Tek başına (A+ olmayan) sinyallerde güven tavanı bir kademe daha düşük
tutulur, çünkü confluence teyidi eksik.
"""

from dataclasses import dataclass
from enum import Enum

from strategy.fvg import detect_fvgs, mark_filled_fvgs, FVGDirection, FVG
from strategy.order_block import detect_order_blocks, mark_mitigated_blocks, OBDirection, OrderBlock
from strategy.trend import detect_trend, TrendDirection, TrendState


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"


class Confidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SetupType(Enum):
    A_PLUS = "A+"       # FVG + OB confluence
    FVG_ONLY = "FVG"     # sadece FVG
    OB_ONLY = "OB"        # sadece Order Block


@dataclass
class Signal:
    index: int
    type: SignalType
    confidence: Confidence
    setup_type: SetupType
    entry: float
    stop_loss: float
    reason: str


def _zones_overlap(top1: float, bottom1: float, top2: float, bottom2: float) -> bool:
    return min(top1, top2) - max(bottom1, bottom2) > 0


def _trend_confidence(trend: TrendState, wants_up: bool, cap_medium: bool = False) -> Confidence | None:
    """
    Trend durumuna göre güven seviyesini belirler. Tam ters trendse None
    döner (eleme). cap_medium=True ise (tek başına sinyallerde) en
    yüksek seviye HIGH yerine MEDIUM'da tavanlanır.
    """
    opposite = (
        (wants_up and trend.direction == TrendDirection.DOWN) or
        (not wants_up and trend.direction == TrendDirection.UP)
    )
    if opposite:
        return None

    matches = (
        (wants_up and trend.direction == TrendDirection.UP) or
        (not wants_up and trend.direction == TrendDirection.DOWN)
    )

    if matches and trend.strong:
        return Confidence.MEDIUM if cap_medium else Confidence.HIGH
    if matches:
        return Confidence.LOW if cap_medium else Confidence.MEDIUM
    return Confidence.LOW  # sideways


def generate_signals(candles: list[dict]) -> list[Signal]:
    fvgs = detect_fvgs(candles)
    mark_filled_fvgs(fvgs, candles)
    obs = detect_order_blocks(candles)
    mark_mitigated_blocks(obs, candles)
    trend_states = detect_trend(candles)

    valid_fvgs = [f for f in fvgs if f.valid and not f.filled]
    valid_obs = [o for o in obs if not o.mitigated]

    signals: list[Signal] = []

    # --- A+ : FVG + OB confluence ---
    for fvg in valid_fvgs:
        fvg_dir = SignalType.BUY if fvg.direction == FVGDirection.BULLISH else SignalType.SELL
        for ob in valid_obs:
            ob_dir = SignalType.BUY if ob.direction == OBDirection.BULLISH else SignalType.SELL
            if fvg_dir != ob_dir:
                continue
            if not _zones_overlap(fvg.top, fvg.bottom, ob.top, ob.bottom):
                continue

            signal_index = max(fvg.end_index, ob.index)
            if signal_index >= len(candles):
                continue

            confidence = _trend_confidence(trend_states[signal_index], fvg_dir == SignalType.BUY)
            if confidence is None:
                continue

            if fvg_dir == SignalType.BUY:
                entry, stop_loss = max(fvg.bottom, ob.bottom), min(fvg.bottom, ob.bottom)
            else:
                entry, stop_loss = min(fvg.top, ob.top), max(fvg.top, ob.top)

            signals.append(Signal(
                index=signal_index, type=fvg_dir, confidence=confidence, setup_type=SetupType.A_PLUS,
                entry=entry, stop_loss=stop_loss,
                reason=f"A+ FVG({fvg.direction.value})+OB({ob.direction.value})",
            ))

    # --- Tek başına FVG ---
    for fvg in valid_fvgs:
        fvg_dir = SignalType.BUY if fvg.direction == FVGDirection.BULLISH else SignalType.SELL
        if fvg.end_index >= len(candles):
            continue
        confidence = _trend_confidence(trend_states[fvg.end_index], fvg_dir == SignalType.BUY, cap_medium=True)
        if confidence is None:
            continue

        entry = fvg.entry_price
        # Stop, FVG'nin kendi sınırı değil (o zaten entry ile aynı nokta olurdu,
        # risk=0 verirdi) — formasyonu oluşturan 3 mumun gerçek en düşük/yüksek
        # noktası kullanılıyor.
        formation = candles[fvg.start_index: fvg.end_index + 1]
        if fvg_dir == SignalType.BUY:
            stop_loss = min(c["low"] for c in formation)
        else:
            stop_loss = max(c["high"] for c in formation)
        signals.append(Signal(
            index=fvg.end_index, type=fvg_dir, confidence=confidence, setup_type=SetupType.FVG_ONLY,
            entry=entry, stop_loss=stop_loss, reason=f"tek başına FVG({fvg.direction.value})",
        ))

    # --- Tek başına Order Block ---
    for ob in valid_obs:
        ob_dir = SignalType.BUY if ob.direction == OBDirection.BULLISH else SignalType.SELL
        if ob.index >= len(candles):
            continue
        confidence = _trend_confidence(trend_states[ob.index], ob_dir == SignalType.BUY, cap_medium=True)
        if confidence is None:
            continue

        # Entry, bölgenin fiyatın geldiği tarafı (BUY için üst, SELL için alt);
        # stop, bölgenin öbür ucu — böylece stop her zaman entry'nin risk
        # yönünde doğru tarafında kalıyor.
        entry = ob.top if ob_dir == SignalType.BUY else ob.bottom
        stop_loss = ob.bottom if ob_dir == SignalType.BUY else ob.top
        signals.append(Signal(
            index=ob.index, type=ob_dir, confidence=confidence, setup_type=SetupType.OB_ONLY,
            entry=entry, stop_loss=stop_loss, reason=f"tek başına OB({ob.direction.value})",
        ))

    signals.sort(key=lambda s: s.index)
    return signals
