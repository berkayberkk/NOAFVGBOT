"""
Alan (Zone) / Katman (Layer) tespit modülü.

Kaynak: kullanıcının kişisel "N/O-A Konsepti" (bkz. proje kökündeki
NOA_KONSEPTI_KAYNAK_ANALIZI.md). Bu modül, strateji ailesindeki en temel
eksik parçayı kapatır -- `strategy/fvg.py`'nin kendi docstring'i bile
"Yüksek Katman FVG" ve "Alanın dibindeki FVG" kurallarının "henüz
kodlamadığımız swing/zone yapısına bağlı" olduğunu zaten not ediyor.

Kurallar:
- N/O Area: fiyatın her leg'i (swing dip -> swing tepe veya tersi) bir
  "Alan"dır. Aktif olan (fiyatın hâlâ genişlettiği) leg "Yeni Alan" (N);
  ondan önceki, artık sabit leg "Eski Alan" (O). Her Alan'ın kendi
  fibonacci'si vardır: 0 = leg'in başladığı (origin) nokta, 1 = leg'in
  ulaştığı en uç nokta -- yön farketmeksizin (bullish'te 0=dip/1=tepe,
  bearish'te 0=tepe/1=dip).
- Yeni Alan onayı (kaynakta 2 kural var, "Kural 1 OR Kural 2"): Kural 1 =
  ters trend, aktif Alan'ın 0.50 seviyesini kırar (fitil teması yeterli,
  kapanış şartı yok). Kural 2 = fiyat "bir modülden" tepki verir --
  kaynak, hangi modülün/ne kadar teyidin sayılacağını hiç netleştirmiyor,
  bu yüzden BU MODÜLDE KURAL 2 IMPLEMENT EDİLMEDİ. Şu an sadece FVG
  modülü kodda var; Wick Imbalance/0.38/R.O.P modülleri eklendiğinde
  Kural 2 ayrı bir işte ele alınacak. Bu, bazı gerçek Alan geçişlerinin
  bu dedektör tarafından kaçırılacağı anlamına gelir (sadece Kural 1
  yakalanır) -- bilinçli bir kapsam kararı, örtük bir eksiklik değil.
- Katman: donmuş (Eski Alan/O) bir Alan'ın fib'i 4 banda bölünür:
  K1 (0-0.25) alınmalı/maksimum reaksiyon, K2 (0.25-0.50) alınabilir/
  ortalama reaksiyon, K3 (0.50-0.75) alınmaz (sadece Kural 1'in "0.50
  kırıldı mı" teyidi için var), K4 (0.75-1) alınmaz/minimal reaksiyon.
  Kaynağın "Ana Kural"ı: fiyat %90-95 oranında Katman 1'den tepki verir.

Diğer strateji modülleriyle aynı desen: `find_swing_points` (bkz.
`strategy/support_resistance.py`) leg sınırlarını (swing pivot'ları)
bulmak için tekrar kullanılıyor -- bu fonksiyon, kod tabanındaki diğer
tüm batch-style modüller (mark_filled_fvgs, mark_mitigated_blocks) gibi
NEDENSEL DEĞİL (ileriye de bakıyor); yani bu modül de bir backtest/
araştırma aracıdır, canlı sinyal üretimi için doğrudan kullanılamaz.
"""

from dataclasses import dataclass
from enum import Enum

from strategy.fvg import compute_atr_series
from strategy.support_resistance import find_swing_points


class ZoneDirection(Enum):
    BULLISH = "bullish"   # start = leg'in dip/origin noktası (0), extreme = leg'in tepesi (1)
    BEARISH = "bearish"   # start = leg'in tepe/origin noktası (0), extreme = leg'in dibi (1)


class ZoneType(Enum):
    N = "yeni_alan"   # aktif, extreme hâlâ genişliyor
    O = "eski_alan"    # donmuş, extreme sabit


class Katman(Enum):
    K1 = 1   # 0.00-0.25 -- tradeable, maksimum reaksiyon, minimum fakeout
    K2 = 2   # 0.25-0.50 -- tradeable, ortalama reaksiyon/fakeout
    K3 = 3   # 0.50-0.75 -- işlem alınmaz, sadece Kural 1 teyidi
    K4 = 4   # 0.75-1.00 -- işlem alınmaz, minimal reaksiyon


@dataclass
class Zone:
    start_index: int
    start_price: float             # fib "0" ucu (origin)
    extreme_index: int
    extreme_price: float           # fib "1" ucu (N için genişler, O için sabit)
    direction: ZoneDirection
    zone_type: ZoneType
    flip_reason: str | None = None         # şu an için hep "kural1" ya da None (bootstrap zone)
    valid: bool = True                      # min-zone-size (ATR) kuralını geçti mi
    invalid_reason: str | None = None
    first_reaction_katman: Katman | None = None   # bir sonraki O alanın extreme'i bu katmanda mı düştü
    first_reaction_index: int | None = None
    first_reaction_price: float | None = None

    @property
    def low(self) -> float:
        return min(self.start_price, self.extreme_price)

    @property
    def high(self) -> float:
        return max(self.start_price, self.extreme_price)

    def level(self, fraction: float) -> float:
        """fraction=0 -> start_price, fraction=1 -> extreme_price (yön-agnostik)."""
        return self.start_price + fraction * (self.extreme_price - self.start_price)


from strategy.config import DEFAULT_CONFIG, StrategyConfig

# --- Kalibre edilecek parametreler ---
ZONE_SWING_LOOKBACK = DEFAULT_CONFIG.zone_swing_lookback
ZONE_MIN_SIZE_ATR_RATIO = DEFAULT_CONFIG.zone_min_size_atr_ratio


def _alternating_pivots(candles: list[dict], swing_highs: list[int], swing_lows: list[int]) -> list[tuple[int, str, float]]:
    """
    Swing high/low index'lerini kronolojik sıraya dizip, ardışık aynı-tip
    pivotları (daha ekstrem olanı tutarak) sıkıştırarak kesin HIGH/LOW
    alternasyonu üretir.
    """
    tagged = [(i, "HIGH", candles[i]["high"]) for i in swing_highs]
    tagged += [(i, "LOW", candles[i]["low"]) for i in swing_lows]

    def sort_key(item: tuple[int, str, float]) -> tuple[int, int]:
        idx, typ, _ = item
        # Aynı index'te hem high hem low pivotu varsa (tek barlık spike),
        # mumun kendi yönüne göre sırala: bearish mum önce tepeye sonra
        # dibe uğramış olabilir (HIGH önce), bullish/doji için tersi.
        candle = candles[idx]
        if candle["close"] < candle["open"]:
            tie_rank = 0 if typ == "HIGH" else 1
        else:
            tie_rank = 0 if typ == "LOW" else 1
        return (idx, tie_rank)

    tagged.sort(key=sort_key)

    collapsed: list[tuple[int, str, float]] = []
    for item in tagged:
        idx, typ, price = item
        if collapsed and collapsed[-1][1] == typ:
            _, _, prev_price = collapsed[-1]
            is_more_extreme = price >= prev_price if typ == "HIGH" else price <= prev_price
            if is_more_extreme:
                collapsed[-1] = item
        else:
            collapsed.append(item)
    return collapsed


def _finalize_zone(zone: Zone, atr_series: list[float | None], config: StrategyConfig) -> None:
    """Donan bir Alan'ı min-zone-size (ATR) kuralına göre valid/invalid işaretler."""
    atr = atr_series[zone.start_index]
    if atr is None or atr == 0:
        zone.valid = True
        return
    size = abs(zone.extreme_price - zone.start_price)
    ratio = size / atr
    zone.valid = ratio >= config.zone_min_size_atr_ratio
    if not zone.valid:
        zone.invalid_reason = (
            f"dar alan (boyut/ATR={ratio:.2f} < {config.zone_min_size_atr_ratio})"
        )


def detect_zones(candles: list[dict], config: StrategyConfig = DEFAULT_CONFIG) -> list[Zone]:
    """
    Candle serisini baştan sona tarayıp Alan (Zone) listesini üretir.

    Sadece Kural 1 (aktif alanın 0.50 seviyesinin fitille kırılması) zone
    geçişini tetikler -- Kural 2 (modülden tepki) bilinçli olarak dışarıda
    bırakıldı (bkz. modül docstring'i).
    """
    atr_series = compute_atr_series(candles, config.atr_period)
    swing_highs, swing_lows = find_swing_points(candles, lookback=config.zone_swing_lookback)
    pivots = _alternating_pivots(candles, swing_highs, swing_lows)

    if len(pivots) < 2:
        return []

    origin_index, _, origin_price = pivots[0]
    next_index, next_type, next_price = pivots[1]
    direction = ZoneDirection.BULLISH if next_type == "HIGH" else ZoneDirection.BEARISH
    current = Zone(
        start_index=origin_index, start_price=origin_price,
        extreme_index=next_index, extreme_price=next_price,
        direction=direction, zone_type=ZoneType.N,
    )

    zones: list[Zone] = []

    for i in range(next_index + 1, len(candles)):
        candle = candles[i]

        if current.direction == ZoneDirection.BULLISH:
            if candle["high"] > current.extreme_price:
                current.extreme_price = candle["high"]
                current.extreme_index = i
        else:
            if candle["low"] < current.extreme_price:
                current.extreme_price = candle["low"]
                current.extreme_index = i

        level_50 = current.level(0.5)
        if current.direction == ZoneDirection.BULLISH:
            kural1_fires = candle["low"] <= level_50
        else:
            kural1_fires = candle["high"] >= level_50

        if kural1_fires:
            _finalize_zone(current, atr_series, config)
            current.zone_type = ZoneType.O
            current.flip_reason = "kural1"
            zones.append(current)

            new_direction = (
                ZoneDirection.BEARISH if current.direction == ZoneDirection.BULLISH
                else ZoneDirection.BULLISH
            )
            new_extreme_price = candle["low"] if new_direction == ZoneDirection.BEARISH else candle["high"]
            current = Zone(
                start_index=current.extreme_index, start_price=current.extreme_price,
                extreme_index=i, extreme_price=new_extreme_price,
                direction=new_direction, zone_type=ZoneType.N,
            )

    _finalize_zone(current, atr_series, config)
    zones.append(current)

    mark_zone_reactions(zones)
    return zones


def classify_katman(zone: Zone, price: float) -> Katman | None:
    """
    Bir fiyatı, donmuş bir Alan'ın fib aralığına göre Katman'a sınıflar.
    Sadece Eski Alan (O) için anlamlıdır. price, Alan'ın [start, extreme]
    aralığı dışındaysa None döner.
    """
    span = zone.extreme_price - zone.start_price
    if span == 0:
        return None
    fraction = (price - zone.start_price) / span
    if fraction < 0 or fraction > 1:
        return None
    if fraction < 0.25:
        return Katman.K1
    if fraction < 0.50:
        return Katman.K2
    if fraction < 0.75:
        return Katman.K3
    return Katman.K4


def current_katman(index: int, candles: list[dict], zones: list[Zone],
                    price_field: str = "close") -> tuple[Zone, Katman] | None:
    """
    Verilen bardaki fiyatın, o ana kadar donmuş en son Eski Alan'ın (O)
    hangi katmanında olduğunu döner. Henüz hiç Alan donmadıysa None.
    """
    o_zones = [z for z in zones if z.zone_type == ZoneType.O and z.extreme_index <= index]
    if not o_zones:
        return None
    zone = max(o_zones, key=lambda z: z.extreme_index)
    katman = classify_katman(zone, candles[index][price_field])
    if katman is None:
        return None
    return zone, katman


def mark_zone_reactions(zones: list[Zone]) -> list[Zone]:
    """
    Ardışık iki Eski Alan (O) için, birincinin katmanına göre ikincinin
    extreme_price'ini sınıflandırıp first_reaction_* alanlarına yazar.
    Bir sonraki Alan hâlâ Yeni Alan (N, çözülmemiş) ise None bırakılır.
    """
    for i in range(len(zones) - 1):
        zone, nxt = zones[i], zones[i + 1]
        if zone.zone_type != ZoneType.O or nxt.zone_type != ZoneType.O:
            continue
        katman = classify_katman(zone, nxt.extreme_price)
        zone.first_reaction_katman = katman
        zone.first_reaction_index = nxt.extreme_index
        zone.first_reaction_price = nxt.extreme_price
    return zones
