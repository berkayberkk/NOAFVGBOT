"""
Experiment #004b -- TESHIS: LONG/SHORT asimetrisi REJIM/DONEM etkisi mi,
yoksa modullerin (FVG/iFVG/OB/Trendline) BULLISH/BEARISH tespit
mantiginda YAPISAL bir asimetri mi?

YONTEM: fiyat serisini DIKEY olarak aynalayip (her mumun open/close/high/
low'u sabit bir eksene gore ters cevrilir -- yukselen trend dusen trend
olur, bullish mum bearish mum olur, TUM gecmis TP/SL/ATR/gap buyuklukleri
MUTLAK deger olarak AYNEN korunur) AYNI sinyal motorunu/backtest'i
calistiriyoruz.

MANTIK: eger modullerin bullish/bearish tespit kodu TAM SIMETRIKSE,
orijinal LONG performansi ~ aynali dunyanin SHORT performansina, orijinal
SHORT performansi ~ aynali dunyanin LONG performansina esit olmali (cunku
eskiden bullish olan bir formasyon simdi AYNI sekilli bir bearish
formasyon oldu). Eger bu esitlik BOZULUYORSA (ozellikle: aynali dunyada
da LONG hala iyi, SHORT hala kotu -- yani "hangi yon iyi" veri
donusumunden ETKILENMIYORSA), bu KODDA (ATR esik karsilastirmalari,
govde/fitil olcumleri, giris derinligi vb.) bullish'i kayiran YAPISAL
bir asimetri oldugunun kaniti olur.

KUTSAL KURAL: bu test SADECE train+val (%80) uzerinde calisir, holdout
(%20) HIC KULLANILMIYOR -- bu bir parametre secimi degil ama proje
disiplinine tam uyum icin muhafazakar davranildi.
"""

import json
from dataclasses import replace as dc_replace
from strategy.config import StrategyConfig
from strategy.signal_engine import generate_signals
from backtest.engine import run_backtest
from backtest.validation import split_chronological
from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
TEST_SYMBOLS = ["GOLD", "UK100", "USDTRY", "EURTRY", "BTCUSD", "EURGBP"]


def mirror_candles(candles: list[dict]) -> list[dict]:
    """Fiyati sabit bir A eksenine gore dikey aynalar: new_p = 2A - p,
    high/low YER DEGISTIRIR (kucuk oldugu icin negasyonla en buyuk olur).
    Zaman/hacim degismez. A = ilk mumun close'u (herhangi bir sabit olur,
    sadece hesap kolayligi icin)."""
    if not candles:
        return []
    A = candles[0]["close"]
    mirrored = []
    for c in candles:
        nc = dict(c)
        nc["open"] = 2 * A - c["open"]
        nc["close"] = 2 * A - c["close"]
        nc["high"] = 2 * A - c["low"]
        nc["low"] = 2 * A - c["high"]
        mirrored.append(nc)
    return mirrored


def direction_breakdown(trades):
    buckets = {"buy": [], "sell": []}
    for t in trades:
        buckets[t.signal.type.value].append(t.r_multiple)
    out = {}
    for d, rs in buckets.items():
        n = len(rs)
        wins = sum(1 for r in rs if r > 0)
        out[d] = {
            "n": n, "win_rate": round(wins / n, 4) if n else None,
            "expectancy_r": round(sum(rs) / n, 4) if n else None,
        }
    return out


def analyze_symbol(symbol):
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]

    spread = SPREAD_BY_SYMBOL.get(symbol, 0.0)
    config = StrategyConfig(spread=spread)

    _, (train_candles, val_candles, _) = split_chronological(candles, 0.60, 0.20, 0.20)
    trainval = train_candles + val_candles  # holdout'a HIC dokunulmuyor

    # ORIJINAL
    orig_signals = generate_signals(trainval, config=config)
    orig_result = run_backtest(trainval, orig_signals, config=config)
    orig_breakdown = direction_breakdown(orig_result.trades)

    # AYNALI
    mirrored = mirror_candles(trainval)
    mir_signals = generate_signals(mirrored, config=config)
    mir_result = run_backtest(mirrored, mir_signals, config=config)
    mir_breakdown = direction_breakdown(mir_result.trades)

    return {"original": orig_breakdown, "mirrored": mir_breakdown}


def main():
    all_results = {}
    for symbol in TEST_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        res = analyze_symbol(symbol)
        all_results[symbol] = res
        o, m = res["original"], res["mirrored"]
        print(f"  ORIJINAL  LONG:  n={o['buy']['n']:>5} win={o['buy']['win_rate']!s:>7} exp={o['buy']['expectancy_r']!s:>8}", flush=True)
        print(f"  ORIJINAL  SHORT: n={o['sell']['n']:>5} win={o['sell']['win_rate']!s:>7} exp={o['sell']['expectancy_r']!s:>8}", flush=True)
        print(f"  AYNALI    LONG:  n={m['buy']['n']:>5} win={m['buy']['win_rate']!s:>7} exp={m['buy']['expectancy_r']!s:>8}", flush=True)
        print(f"  AYNALI    SHORT: n={m['sell']['n']:>5} win={m['sell']['win_rate']!s:>7} exp={m['sell']['expectancy_r']!s:>8}", flush=True)
        # Simetri kontrolu: orijinal LONG ~ aynali SHORT, orijinal SHORT ~ aynali LONG mu?
        print(f"  [orijinal LONG exp={o['buy']['expectancy_r']} vs aynali SHORT exp={m['sell']['expectancy_r']}] -- yakinsa SIMETRIK (rejim etkisi)", flush=True)
        print(f"  [orijinal SHORT exp={o['sell']['expectancy_r']} vs aynali LONG exp={m['buy']['expectancy_r']}] -- yakinsa SIMETRIK (rejim etkisi)", flush=True)

    with open("scratch_exp004b_mirror_symmetry_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print("\nyazildi: scratch_exp004b_mirror_symmetry_results.json")


if __name__ == "__main__":
    main()
