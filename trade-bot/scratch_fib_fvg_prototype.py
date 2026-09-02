"""
PROTOTIP (scratch, kalici degil): FVG-only sinyallerde giris noktasini gap'in tam
dolumu (mevcut mantik, "1.0" = fvg.entry_price) yerine fib geri cekilme seviyelerinde
(0.382 / 0.5 / 0.618) alsak expectancy/R:R/fill-rate nasil degisir, gercek veriyle olcer.

Geometri: BULLISH FVG icin fvg.top = fiyatin gap'e ILK girdigi kenar (en sig, 0%),
fvg.bottom = mevcut giris (tam dolum, en derin, "1.0"). fib=f icin giris:
  entry(f) = top - f * (top - bottom)   [BULLISH; f=1 -> bottom = mevcut mantik]
BEARISH icin ayna simetrik.

Stop, mevcut mantikla ayni (formasyonun gercek en dusuk/yuksek noktasi) -- boylece
sadece giris seviyesinin etkisini izole ediyoruz.

run_backtest zaten signal.entry'yi bir limit emir gibi ele al覺p (fiyat o seviyeye
dokunana kadar bekliyor) TP'yi de YENI entry'ye gore yeniden hesapl覺yor
(_find_take_profit(signal.entry, ...)) -- yani mevcut, test edilmis motoru
DEGISTIRMEDEN, sadece sinyal listesini fib giris fiyatlariyla besleyerek
kullanabiliyoruz.
"""

from dataclasses import replace

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.fvg import detect_fvgs, mark_filled_fvgs, FVGDirection
from strategy.trend import detect_trend
from strategy.signal_engine import Signal, SignalType, Confidence, SetupType, _trend_confidence
from strategy.config import StrategyConfig
from backtest.engine import run_backtest
from backtest.validation import calculate_metrics, split_chronological


def build_fvg_only_signals(candles, config, fib_fraction: float):
    """fib_fraction=1.0 -> mevcut davranisla birebir ayni (tam dolum)."""
    fvgs = detect_fvgs(candles, config=config)
    mark_filled_fvgs(fvgs, candles)
    trend_states = detect_trend(candles, config=config)

    valid_fvgs = [f for f in fvgs if f.valid and not f.filled]
    signals = []
    for fvg in valid_fvgs:
        fvg_dir = SignalType.BUY if fvg.direction == FVGDirection.BULLISH else SignalType.SELL
        if fvg.end_index >= len(candles):
            continue
        confidence = _trend_confidence(trend_states[fvg.end_index], fvg_dir == SignalType.BUY, cap_medium=True)
        if confidence is None:
            continue

        # fib_fraction=0 -> fvg.top'a (ilk temas, en sig); fib_fraction=1 -> fvg.bottom'a
        # (tam dolum, mevcut/baseline davranis) esdeger BULLISH icin; BEARISH ayna simetrik.
        if fvg_dir == SignalType.BUY:
            entry = fvg.top - fib_fraction * (fvg.top - fvg.bottom)
        else:
            entry = fvg.bottom + fib_fraction * (fvg.top - fvg.bottom)

        formation = candles[fvg.start_index: fvg.end_index + 1]
        if fvg_dir == SignalType.BUY:
            stop_loss = min(c["low"] for c in formation)
        else:
            stop_loss = max(c["high"] for c in formation)

        signals.append(Signal(
            index=fvg.end_index, type=fvg_dir, confidence=confidence, setup_type=SetupType.FVG_ONLY,
            entry=entry, stop_loss=stop_loss, reason=f"fib={fib_fraction} FVG({fvg.direction.value})",
        ))
    signals.sort(key=lambda s: s.index)
    return signals


def run_variant(candles, config, fib_fraction, label):
    signals = build_fvg_only_signals(candles, config, fib_fraction)
    result = run_backtest(candles, signals, config=config)
    m = calculate_metrics(result.trades, total_signals=len(signals),
                           unfilled_orders=result.unfilled_orders, skipped_no_tp=result.skipped_no_tp)
    risk_dists = [abs(t.executed_entry - t.stop_loss) for t in result.trades if t.filled]
    reward_dists = [abs(t.take_profit - t.executed_entry) for t in result.trades if t.filled]
    avg_rr = (sum(r / k for r, k in zip(reward_dists, risk_dists) if k > 0) / len(risk_dists)) if risk_dists else 0.0
    return {
        "label": label, "fib_fraction": fib_fraction,
        "total_signals": len(signals), "filled_trades": m.filled_trades,
        "fill_rate": m.fill_rate, "win_rate": m.win_rate,
        "expectancy_r": m.expectancy_r, "profit_factor": m.profit_factor,
        "avg_rr": avg_rr, "total_net_r": m.total_net_r,
    }


def main():
    for research_symbol, broker_symbol_display in [("GBPJPY", "GBPJPY"), ("EURUSD", "EURUSD")]:
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{research_symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        candles_full = [candlev2_to_strategy_dict(c) for c in m30_v2]
        # Prototip icin son ~3 yila sinirla -- run_backtest'in TP aramasi sinyal basina
        # tum gecmisi (build_levels) yeniden hesapladigi icin O(n^2)'ye yakin, tam 16 yil
        # cok yavas. Yon/buyukluk okumasi icin bu yeterli, tam dogrulama ayri konu.
        candles = candles_full[-35000:]
        config = StrategyConfig()  # spread=0 -- gecerli izole karsilastirma icin oncelik R:R/expectancy YAPISINDA

        print(f"\n=== {research_symbol} (M30, {len(candles)} mum) ===")
        print(f"{'variant':10} {'fib':>5} {'signals':>8} {'filled':>7} {'fill%':>7} {'win%':>7} {'exp_r':>8} {'pf':>7} {'avg_RR':>7} {'total_R':>9}")
        for frac, label in [(1.0, "baseline"), (0.618, "fib618"), (0.5, "fib50"), (0.382, "fib382"), (0.236, "fib236")]:
            r = run_variant(candles, config, frac, label)
            pf = min(r["profit_factor"], 99.9)
            print(f"{r['label']:10} {r['fib_fraction']:5.3f} {r['total_signals']:8d} {r['filled_trades']:7d} "
                  f"{r['fill_rate']:7.1%} {r['win_rate']:7.1%} {r['expectancy_r']:8.4f} {pf:7.2f} {r['avg_rr']:7.3f} {r['total_net_r']:9.2f}")


if __name__ == "__main__":
    main()
