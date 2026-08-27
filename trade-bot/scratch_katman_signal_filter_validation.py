"""
PROTOTIP (scratch, kalici degil): strategy/zone.py'nin pratik degerini test
eder -- mevcut V1 sinyallerini (generate_signals: A+/FVG_ONLY/OB_ONLY),
sinyalin olustugu bardaki fiyatin hangi Katman'da oldugu (en son donmus
Eski Alan'a gore) etiketiyle gruplandirip backtest metriklerini (expectancy_r,
win_rate, profit_factor) karsilastirir.

Amac: zone_katman_validation.py'nin bulgusu ("first_reaction_katman"
metrigi Ana Kural'i temiz test edemiyor, yapisal olarak K3/K4 gosteremiyor)
ile ayni tuzaga dusmeden, dogrudan ACTIONABLE bir soruyu yanitlamak --
"Katman 1/2'den gelen sinyaller, hicbir katman etiketi olmayan ya da
K3/K4'ten gelenlere gore V1 stratejisinde gercekten daha iyi mi calisiyor?"
Bu, mevcut ve zaten dogrulanmis backtest motorunu (run_backtest) degistirmeden
kullanir -- sadece sinyal listesini katmana gore filtreler.
"""

from collections import defaultdict

from backtest.engine import run_backtest
from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from backtest.validation import calculate_metrics
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig
from strategy.signal_engine import generate_signals
from strategy.zone import detect_zones, current_katman


def _tag_katman(signal, candles: list[dict], zones: list) -> str:
    result = current_katman(signal.index, candles, zones)
    return result[1].name if result else "NONE"


def _run_group(label: str, signals: list, candles: list[dict], config: StrategyConfig) -> None:
    if not signals:
        print(f"{label:16} n=0")
        return
    result = run_backtest(candles, signals, config=config)
    m = calculate_metrics(result.trades, total_signals=len(signals),
                           unfilled_orders=result.unfilled_orders, skipped_no_tp=result.skipped_no_tp)
    pf = min(m.profit_factor, 99.9)
    print(f"{label:16} signals={len(signals):4d} filled={m.filled_trades:4d} fill%={m.fill_rate:6.1%} "
          f"win%={m.win_rate:6.1%} exp_r={m.expectancy_r:7.4f} pf={pf:6.2f} total_R={m.total_net_r:8.2f}")


def main():
    m1 = load_m1_canonical_as_candlev2("data/canonical/V2_MULTI_GOLD_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2][-35000:]
    config = StrategyConfig()

    zones = detect_zones(candles, config=config)
    signals = generate_signals(candles, config=config)

    groups: dict[str, list] = defaultdict(list)
    for s in signals:
        groups[_tag_katman(s, candles, zones)].append(s)

    print(f"=== GOLD (M30, {len(candles)} mum), toplam sinyal={len(signals)} ===")
    _run_group("TUMU (baseline)", signals, candles, config)
    for tag in ["K1", "K2", "K3", "K4", "NONE"]:
        _run_group(tag, groups.get(tag, []), candles, config)


if __name__ == "__main__":
    main()
