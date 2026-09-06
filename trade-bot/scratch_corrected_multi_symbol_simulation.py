"""
PROTOTIP (scratch, kalici degil): scratch_corrected_account_simulation.py'nin
(DUZELTILMIS -- same-bar-iyimserlik hatasi olmayan -- motorla $10k hesap
simulasyonu) 95 SEMBOLLUK GENIS EVRENE genellestirilmis hali.

MOTIVASYON: "95 sembollu hesap simulasyonu"nun (eski, optimist scratch
metodolojisiyle) sonuclarina gore semboller GOLD/BTCUSD/EURGBP'ye
daraltilmisti (Tur 2-4). Ama o daraltma kararinin KENDISI, artik
guvenilmez oldugunu bildigimiz ayni metodolojiye dayaniyordu -- yanlis
semboller elenmis, yanlislari tutulmus olabilir. Bu script ayni 95
sembollu evreni (Tur 1'in 6 sembol cikarmasindan sonraki tam kapsam,
bkz. scratch_trade_archive.py ile ayni liste) DUZELTILMIS motorla
(strategy/signal_engine.py + backtest/engine.py) yeniden tarar --
gercekten HICBIR yerde edge yok mu, yoksa bazi semboller hala pozitif
mi, kesin cevap arar.

SINIRLAMA (acikca belirtiliyor): GOLD/BTCUSD/EURGBP disindaki semboller
icin temsili spread degeri YOK (o ucu icin bile veriden turetilemedi,
bilinen piyasa degerleri kullanilmisti) -- bu tarama spread=0
(DEFAULT_CONFIG) ile yapiliyor, yani EN IYIMSER (maliyetsiz) senaryo.
Pozitif cikan bir sembol bile olsa, gercek spread'le tekrar dogrulanmadan
guvenilir sayilmamali.

Checkpoint: her sembol kendi dosyasina (corrected_multi_symbol_results/{SEMBOL}.json)
yaziliyor -- kesintiye dayanikli, kaldigi yerden devam eder.
"""

import json
import time
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, _ALL_101_SYMBOLS
from strategy.signal_engine import generate_signals
from backtest.engine import run_backtest
from scratch_corrected_account_simulation import simulate_account

_TOUR1_EXCLUDED = {"GERTECH30", "NASDAQ", "IT40", "GERMID50", "EURDKK", "USFANG"}
SYMBOLS = [s for s in _ALL_101_SYMBOLS if s not in _TOUR1_EXCLUDED]
assert len(SYMBOLS) == 95, f"beklenen 95 sembol, bulunan {len(SYMBOLS)}"

OUT_DIR = Path("corrected_multi_symbol_results")
CONFIG = StrategyConfig()  # spread=0 -- bkz. modul docstring'i


def process_symbol(symbol: str) -> dict:
    path = f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv"
    try:
        m1 = load_m1_canonical_as_candlev2(path)
    except FileNotFoundError:
        return {"error": "veri yok"}
    if len(m1) < 2000:
        return {"error": "yetersiz veri"}

    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
    if len(candles) < 100:
        return {"error": "yetersiz M30 verisi"}

    signals = generate_signals(candles, config=CONFIG)
    result = run_backtest(candles, signals, config=CONFIG)
    acc = simulate_account(candles, result.trades)
    acc.pop("equity_curve_compound", None)
    acc.pop("equity_curve_fixed", None)  # checkpoint dosyalarini kucuk tutmak icin egriler atiliyor
    acc["symbol"] = symbol
    acc["n_signals"] = len(signals)
    acc["n_filled"] = len(result.trades)
    return acc


def main():
    OUT_DIR.mkdir(exist_ok=True)
    done = {p.stem for p in OUT_DIR.glob("*.json")}
    todo = [s for s in SYMBOLS if s not in done]
    print(f"{len(done)}/{len(SYMBOLS)} tamamlanmis, {len(todo)} kaldi", flush=True)

    for si, symbol in enumerate(todo, start=1):
        t0 = time.time()
        result = process_symbol(symbol)
        out_path = OUT_DIR / f"{symbol}.json"
        tmp = out_path.with_suffix(".tmp")
        for attempt in range(5):
            try:
                tmp.write_text(json.dumps(result, indent=None, default=str))
                tmp.replace(out_path)
                break
            except (PermissionError, FileNotFoundError):
                if attempt == 4:
                    raise
                time.sleep(0.5 * (attempt + 1))

        if "error" in result:
            print(f"[{si}/{len(todo)}] {symbol}: HATA -- {result['error']} ({time.time()-t0:.1f}sn)", flush=True)
        else:
            print(f"[{si}/{len(todo)}] {symbol}: n_taken={result['n_taken']} win={result['win_rate']:.1%} "
                  f"bilesik=${result['final_equity_compound']:,.0f} sabit=${result['final_equity_fixed']:,.0f} "
                  f"({time.time()-t0:.1f}sn)", flush=True)

    print("\nTUM SEMBOLLER TAMAMLANDI.", flush=True)


if __name__ == "__main__":
    main()
