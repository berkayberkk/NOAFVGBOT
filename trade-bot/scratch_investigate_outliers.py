"""
PROTOTIP (scratch, kalici degil): module_diagnostic_full_universe_results.json'da
asiri uc deger veren CHFJPY (-9.37R), USDZAR (-3.33R), CHFSGD (-2.88R)
sembollerinin portfoy-seviyesi expectancy'sinin bu kadar asiri cikmasinin
sebebini bulur -- tek bir dejenere R-multiple mi (veri sicramasi/formul
kenar durumu), yoksa gercek/tutarli bir zayiflik mi.
"""

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from backtest.engine import run_backtest
from strategy.config import StrategyConfig
from strategy.signal_engine import generate_signals, SetupType

MODULE_KEY_BY_SETUP = {
    SetupType.FVG_ONLY: "fvg", SetupType.IFVG_ONLY: "ifvg",
    SetupType.OB_ONLY: "ob", SetupType.TRENDLINE_ONLY: "trendline",
}


def load_symbol_m30(symbol: str) -> list[dict]:
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    return [candlev2_to_strategy_dict(c) for c in m30_v2]


def investigate(symbol: str):
    print(f"\n{'='*60}\n{symbol}\n{'='*60}", flush=True)
    candles = load_symbol_m30(symbol)
    config = StrategyConfig(spread=0.0)
    all_signals = generate_signals(candles, config=config)
    result = run_backtest(candles, all_signals, config=config)
    trades = [t for t in result.trades if t.r_multiple is not None]

    r_values = sorted((t.r_multiple for t in trades))
    print(f"toplam islem: {len(trades)}")
    print(f"en dusuk 5 R: {[round(r,2) for r in r_values[:5]]}")
    print(f"en yuksek 5 R: {[round(r,2) for r in r_values[-5:]]}")

    # En asiri (mutlak deger en buyuk) 3 islemi detayli goster
    extreme = sorted(trades, key=lambda t: -abs(t.r_multiple))[:3]
    for t in extreme:
        sig = t.signal
        mod = MODULE_KEY_BY_SETUP[sig.setup_type]
        risk = abs(t.entry_price - t.stop_loss)
        entry_idx = t.entry_fill_index if t.entry_fill_index is not None else t.entry_index
        entry_time = candles[entry_idx]["time"] if entry_idx < len(candles) else None
        print(f"  MODUL={mod} R={t.r_multiple:.2f} entry={t.entry_price} sl={t.stop_loss} "
              f"tp={t.take_profit} risk={risk:.6f} entry_time={entry_time} won={t.won} "
              f"is_breakeven={t.is_breakeven} exit_price={t.exit_price}")


if __name__ == "__main__":
    for sym in ["CHFJPY", "USDZAR", "CHFSGD"]:
        investigate(sym)
