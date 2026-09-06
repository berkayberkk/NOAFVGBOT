"""
PROTOTIP (scratch, kalici degil): scratch_module_diagnostic_full_scan.py'nin
KEPT_SYMBOLS (GOLD/BTCUSD/EURGBP) ile sinirli halini, elimizde canonical M1
verisi olan TUM sembol evrenine (data/canonical/V2_MULTI_*_M1_canonical.csv,
~98 sembol) genisletir. Amac: GOLD/BTCUSD/EURGBP'de bulunan "OB, sinyal
sikligi + asiri uzun elde tutma suresiyle tek-pozisyon portfoy slotunu
domine ediyor, en iyi modulu (FVG) ac birakiyor" bulgusunun bu 3 sembole
OZGU mu yoksa GENEL bir mimari sorun mu oldugunu netlestirmek.

Ayni module_level_report/portfolio_level_report fonksiyonlari (DEGISTIRILMEDEN)
import edilip yeniden kullanilir -- sadece sembol listesi genisletildi ve
spread=0.0 (varsayilan, KEPT_SYMBOLS disindaki semboller icin gercekci
spread degeri hic kalibre edilmedigi icin -- bu TAMAMEN ayni notla,
scratch_r_multiple_recalibration_study.py'deki gibi, dogru sekilde
belirtiliyor).

Sonuc her sembol islendikce ANINDA diske yaziliyor (incremental) ki uzun
suren taramanin kismi sonuclari her an okunabilsin.
"""

import glob
import json
import os
import re
import time

from strategy.config import StrategyConfig
from strategy.signal_engine import generate_signals
from scratch_module_diagnostic_full_scan import (
    load_symbol_m30, module_level_report, portfolio_level_report,
)

OUT_PATH = "module_diagnostic_full_universe_results.json"


def discover_symbols() -> list[str]:
    paths = glob.glob("data/canonical/V2_MULTI_*_M1_canonical.csv")
    syms = []
    for p in paths:
        m = re.search(r"V2_MULTI_(.+)_M1_canonical\.csv$", os.path.basename(p))
        if m:
            syms.append(m.group(1))
    return sorted(syms)


def load_existing_results() -> dict:
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def main():
    symbols = discover_symbols()
    print(f"toplam {len(symbols)} sembol bulundu", flush=True)

    results = load_existing_results()
    done = set(results.keys())
    if done:
        print(f"onceden tamamlanmis {len(done)} sembol atlanacak: {sorted(done)}", flush=True)

    config = StrategyConfig(spread=0.0)

    for i, symbol in enumerate(symbols):
        if symbol in done:
            continue
        t0 = time.time()
        try:
            candles = load_symbol_m30(symbol)
            if len(candles) < 500:
                print(f"[{i+1}/{len(symbols)}] {symbol}: cok az mum (n={len(candles)}), atlandi", flush=True)
                results[symbol] = {"error": "insufficient_candles", "n_candles": len(candles)}
            else:
                all_signals = generate_signals(candles, config=config)
                mod_report = module_level_report(symbol, candles, config, all_signals)
                port_report = portfolio_level_report(symbol, candles, all_signals, config)
                results[symbol] = {
                    "n_candles": len(candles), "n_signals": len(all_signals),
                    "module_level": mod_report, "portfolio_level": port_report,
                }
                elapsed = time.time() - t0
                pr = port_report
                print(f"[{i+1}/{len(symbols)}] {symbol}: n_candles={len(candles)} n_sig={len(all_signals)} "
                      f"| portfoy: taken={pr['n_taken_into_portfolio']} win={pr['portfolio_win_rate']*100:.1f}% "
                      f"exp={pr['portfolio_expectancy_r']:+.4f} taken_by_mod={pr['taken_by_module']} "
                      f"({elapsed:.1f}s)", flush=True)
        except Exception as e:
            print(f"[{i+1}/{len(symbols)}] {symbol}: HATA {type(e).__name__}: {e}", flush=True)
            results[symbol] = {"error": str(e)}

        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)

    print(f"\nTAMAMLANDI. {OUT_PATH} yazildi.", flush=True)


if __name__ == "__main__":
    main()
