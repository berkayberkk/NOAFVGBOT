"""
PROTOTIP (scratch, kalici degil): strategy/zone.py'nin Alan/Katman dedektorunu
gercek veriyle calistirip kaynagin ("N/O-A Konsepti", bkz.
NOA_KONSEPTI_KAYNAK_ANALIZI.md) "Ana Kural: fiyat %90-95 Katman 1'den tepki
verir" iddiasini sinar. Ayrica zone_min_size_atr_ratio varsayilaninin (3.0)
makul olup olmadigini gozlemlemek icin valid/invalid alan kirilimini da
raporlar -- bu esik kaynakta sayisal olarak verilmiyor, kod tarafinda bir
varsayim, gercek veriyle kalibre edilmesi gerekiyor.

Not: research/v2/data/resampler.py'deki Timeframe enum'u M30'un ustune
cikmiyor (H1/H4/Gunluk/Haftalik yok) -- kaynagin bahsettigi daha yuksek
zaman dilimi olcegi burada test edilemiyor, bu acik bir sinirlama, sessizce
atlanmiyor.

Bu dedektor sadece Kural 1'i (aktif alanin 0.50 seviyesinin kirilmasi)
implement ediyor -- Kural 2 (modulden tepki) kapsam disi (bkz. strategy/zone.py
docstring'i), bu yuzden bazi gercek alan gecisleri burada yakalanmamis olabilir.
"""

from collections import Counter

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig
from strategy.fvg import compute_atr_series
from strategy.zone import detect_zones, ZoneType


def _print_katman_distribution(label: str, zones: list) -> None:
    if not zones:
        print(f"\n--- {label}: yok ---")
        return
    counts = Counter(z.first_reaction_katman.name for z in zones)
    total = len(zones)
    print(f"\n--- {label} (n={total}) ---")
    for k in ["K1", "K2", "K3", "K4"]:
        n = counts.get(k, 0)
        print(f"  {k}: {n:5d}  ({n / total:6.1%})")


def main():
    m1 = load_m1_canonical_as_candlev2("data/canonical/V2_MULTI_GOLD_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles_full = [candlev2_to_strategy_dict(c) for c in m30_v2]
    # scratch_fib_fvg_prototype.py'deki performans notuyla ayni sebep --
    # tam gecmis yerine son bir dilime sinirla (detect_zones tek gecis O(n),
    # ama yine de karsilastirilabilir olmasi icin ayni pencereyi kullaniyoruz).
    candles = candles_full[-35000:]
    config = StrategyConfig()

    zones = detect_zones(candles, config=config)
    atr_series = compute_atr_series(candles, config.atr_period)

    print(f"=== GOLD (M30, {len(candles)} mum) ===")
    print(f"toplam alan: {len(zones)}")

    n_active = sum(1 for z in zones if z.zone_type == ZoneType.N)
    n_frozen = len(zones) - n_active
    print(f"donmus (O): {n_frozen}, seri sonunda hala aktif (N): {n_active}")

    n_valid = sum(1 for z in zones if z.valid)
    print(f"gecerli (valid, genis-yeterli): {n_valid}, gecersiz (dar): {len(zones) - n_valid}")

    durations = [z.extreme_index - z.start_index for z in zones]
    print(f"ortalama alan suresi: {sum(durations) / len(durations):.1f} bar")

    atr_ratios = []
    for z in zones:
        atr = atr_series[z.start_index]
        if atr:
            atr_ratios.append(abs(z.extreme_price - z.start_price) / atr)
    if atr_ratios:
        print(f"ortalama alan boyutu: {sum(atr_ratios) / len(atr_ratios):.2f}x ATR")

    resolved = [z for z in zones if z.zone_type == ZoneType.O and z.first_reaction_katman is not None]
    print(f"\ncozulmus (O, bir sonraki alanin nereye dustugu bilinen) alan: {len(resolved)}")

    if not resolved:
        print("Cozulmus alan yok, katman dagilimi hesaplanamiyor.")
        return

    # -- Ana Kural testi: "%90-95 K1'den tepki" iddiasinin dogrudan testi --
    _print_katman_distribution("Katman dagilimi (tum cozulmus alanlar)", resolved)

    # -- valid/invalid kirilimi: zone_min_size_atr_ratio kalibrasyonu icin --
    _print_katman_distribution("valid (yeterince genis) alanlar", [z for z in resolved if z.valid])
    _print_katman_distribution("invalid (dar) alanlar", [z for z in resolved if not z.valid])

    reason_counts = Counter(z.flip_reason for z in resolved)
    print(f"\nflip_reason dagilimi: {dict(reason_counts)}")


if __name__ == "__main__":
    main()
