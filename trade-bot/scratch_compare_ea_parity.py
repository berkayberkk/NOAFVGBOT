"""
PROTOTIP (scratch, kalici degil): mql5/TradeBot_NOA_Recal.mq5'in
Strategy Tester'da LogSignalsOnly=true ile urettigi
NOA_Recal_allsignals_<SEMBOL>.csv dosyasini (MT5'in Common\\Files
klasorunde olusur -- genelde
C:\\Users\\<kullanici>\\AppData\\Roaming\\MetaQuotes\\Terminal\\Common\\Files\\)
Python kaynak-dogrusunun (scratch_dump_signals_for_ea_parity.py --
onceden calistirilmis olmali) urettigi
results/ea_parity/<SEMBOL>_python_signals.json ile karsilastirir.

Eslesme kurali: ayni modul + ayni yon + signal_bar_time (dakika
hassasiyetinde) + entry/sl/tp fiyatlarinin cok kucuk (varsayilan 1e-4
mutlak veya %0.01 bagil, hangisi buyukse) tolerans icinde olmasi.
Fiyat tolerans gerekcesi: MQL5 double yuvarlama / DoubleToString(...,6)
kirpma farklari beklenir, gercek bir mantik hatasi degil.

Kullanim:
    python scratch_compare_ea_parity.py GOLD "C:/Users/.../Common/Files/NOA_Recal_allsignals_GOLD.csv"
    python scratch_compare_ea_parity.py --all-common-dir "C:/Users/.../Common/Files"

Cikti: konsola ozet (kac sinyal Python'da var ama EA'da yok / tam tersi /
esdeger fiyatla eslesti ama SL-TP farkli / vs.) + eslesmeyenlerin ilk 20'si.
"""

import csv
import json
import sys
from datetime import datetime, timedelta

PRICE_ABS_TOL = 1e-4
PRICE_REL_TOL = 0.0001


def close_enough(a: float, b: float) -> bool:
    if a is None or b is None:
        return a == b
    return abs(a - b) <= max(PRICE_ABS_TOL, abs(a) * PRICE_REL_TOL)


def load_python_signals(symbol: str) -> list[dict]:
    path = f"results/ea_parity/{symbol}_python_signals.json"
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    for r in rows:
        r["_time"] = datetime.fromisoformat(r["signal_bar_time_utc"])
    return rows


def load_ea_candidates(csv_path: str) -> list[dict]:
    """NOA_Recal_allsignals_<SYMBOL>.csv: module;direction;signalTime;entry;sl;tp (';' ayracli, basliksiz)."""
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=";")
        for row in reader:
            if len(row) < 6:
                continue
            module, direction, sig_time_str, entry, sl, tp = row[0:6]
            rows.append({
                "module": module,
                "direction": direction,
                "_time": datetime.strptime(sig_time_str.strip(), "%Y.%m.%d %H:%M:%S"),
                "entry": float(entry),
                "sl": float(sl),
                "tp": float(tp),
            })
    return rows


def compare(symbol: str, ea_csv_path: str) -> None:
    py_rows = load_python_signals(symbol)
    ea_rows = load_ea_candidates(ea_csv_path)

    print(f"\n=== {symbol} ===")
    print(f"Python taraf\u0131: {len(py_rows)} sinyal | EA taraf\u0131 (log dosyas\u0131): {len(ea_rows)} aday")

    ea_used = [False] * len(ea_rows)
    matched = 0
    mismatched_price = []
    missing_in_ea = []

    for p in py_rows:
        found = None
        for i, e in enumerate(ea_rows):
            if ea_used[i]:
                continue
            if e["module"] != p["module"] or e["direction"] != p["direction"]:
                continue
            if abs((e["_time"] - p["_time"]).total_seconds()) > 60:
                continue
            found = i
            break
        if found is None:
            missing_in_ea.append(p)
            continue

        e = ea_rows[found]
        ea_used[found] = True
        if close_enough(e["entry"], p["entry"]) and close_enough(e["sl"], p["sl"]) and close_enough(e["tp"], p["tp"]):
            matched += 1
        else:
            mismatched_price.append((p, e))

    extra_in_ea = [ea_rows[i] for i in range(len(ea_rows)) if not ea_used[i]]

    print(f"TAM ESLESTI: {matched}")
    print(f"FIYAT FARKLI (ayni bar/modul/yon ama entry/sl/tp uyusmuyor): {len(mismatched_price)}")
    print(f"Python'da VAR, EA logunda YOK: {len(missing_in_ea)}")
    print(f"EA logunda VAR, Python'da YOK: {len(extra_in_ea)}")

    if mismatched_price:
        print("\n-- Fiyat farkli ornekler (ilk 20) --")
        for p, e in mismatched_price[:20]:
            print(f"  {p['module']} {p['direction']} {p['signal_bar_time_utc']}: "
                  f"PY entry={p['entry']} sl={p['sl']} tp={p['tp']}  |  "
                  f"EA entry={e['entry']} sl={e['sl']} tp={e['tp']}")

    if missing_in_ea:
        print("\n-- Python'da var, EA'da yok (ilk 20) --")
        for p in missing_in_ea[:20]:
            print(f"  {p['module']} {p['direction']} {p['signal_bar_time_utc']} entry={p['entry']}")

    if extra_in_ea:
        print("\n-- EA'da var, Python'da yok (ilk 20) --")
        for e in extra_in_ea[:20]:
            print(f"  {e['module']} {e['direction']} {e['_time']} entry={e['entry']}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    compare(sys.argv[1], sys.argv[2])
