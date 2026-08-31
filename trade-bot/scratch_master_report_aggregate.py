"""
PROTOTIP (scratch, kalici degil): FVG/iFVG/OB uc calismasinin ham
per-sembol/per-timeframe sonuclarini (fvg_tp_sl_study_results.json,
ifvg_tp_sl_study_results.json, ob_tp_sl_study_results.json) tek bir
kapsamli rapor veri blobuna (master_report_data.json) toplar --
kullanicinin istedigi "detayli finansal sunum" artifact'i icin.

Uc katman:
1. overall / per_tf (R-katina gore havuzlanmis) -- zaten var olan
   *_report_data.json dosyalariyla ayni yontem (sayim toplami, oran
   ortalamasi degil).
2. per_symbol_at_r1 -- her sembol icin R=1.0'daki (ortak karsilastirma
   noktasi) win_rate/expectancy_r/pf/n, uc modul icin ayri ayri --
   sembol bazli en iyi/en kotu siralamasi icin.
3. meta -- toplam sinyal sayilari, sembol sayilari.
"""

import json
from pathlib import Path

R_MULTIPLES = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0", "4.0", "5.0"]
TIMEFRAMES = ["M30", "H1", "H2", "H4", "D1", "W1"]

FILES = {
    "fvg": "fvg_tp_sl_study_results.json",
    "ifvg": "ifvg_tp_sl_study_results.json",
    "ob": "ob_tp_sl_study_results.json",
}


def aggregate(raw: dict) -> dict:
    overall_acc = {r: {"n": 0, "wins": 0, "losses": 0, "total_r": 0.0, "gp": 0.0, "gl": 0.0} for r in R_MULTIPLES}
    per_tf_acc = {tf: {r: {"n": 0, "wins": 0, "losses": 0, "total_r": 0.0, "gp": 0.0, "gl": 0.0} for r in R_MULTIPLES} for tf in TIMEFRAMES}

    for symbol, sym_result in raw.items():
        if "error" in sym_result:
            continue
        for tf in TIMEFRAMES:
            tf_result = sym_result.get(tf)
            if not tf_result:
                continue
            for r in R_MULTIPLES:
                unit = tf_result.get(r)
                if not unit or unit.get("n", 0) == 0:
                    continue
                n, wins, losses, total_r = unit["n"], unit["wins"], unit["losses"], unit["total_r"]
                r_mult = float(r)
                gp, gl = wins * r_mult, losses * 1.0
                for acc in (overall_acc[r], per_tf_acc[tf][r]):
                    acc["n"] += n
                    acc["wins"] += wins
                    acc["losses"] += losses
                    acc["total_r"] += total_r
                    acc["gp"] += gp
                    acc["gl"] += gl

    def finalize(acc):
        n = acc["n"]
        if n == 0:
            return {"n": 0, "win_rate": 0.0, "expectancy_r": 0.0, "pf": 0.0, "total_r": 0.0}
        pf = (acc["gp"] / acc["gl"]) if acc["gl"] > 0 else (999.0 if acc["gp"] > 0 else 0.0)
        return {"n": n, "win_rate": acc["wins"] / n, "expectancy_r": acc["total_r"] / n, "pf": min(pf, 999.0), "total_r": acc["total_r"]}

    return {
        "overall": {r: finalize(overall_acc[r]) for r in R_MULTIPLES},
        "per_tf": {tf: {r: finalize(per_tf_acc[tf][r]) for r in R_MULTIPLES} for tf in TIMEFRAMES},
    }


def per_symbol_at_r(raw: dict, r: str) -> dict:
    """Her sembol icin TUM zaman dilimleri havuzlanmis, tek bir R'deki metrikler."""
    out = {}
    for symbol, sym_result in raw.items():
        if "error" in sym_result:
            continue
        n = wins = losses = 0
        total_r = 0.0
        gp = gl = 0.0
        for tf in TIMEFRAMES:
            tf_result = sym_result.get(tf)
            if not tf_result:
                continue
            unit = tf_result.get(r)
            if not unit or unit.get("n", 0) == 0:
                continue
            n += unit["n"]; wins += unit["wins"]; losses += unit["losses"]; total_r += unit["total_r"]
            gp += unit["wins"] * float(r); gl += unit["losses"] * 1.0
        if n == 0:
            continue
        pf = (gp / gl) if gl > 0 else (999.0 if gp > 0 else 0.0)
        out[symbol] = {"n": n, "win_rate": wins / n, "expectancy_r": total_r / n, "pf": min(pf, 999.0)}
    return out


def main():
    master = {"modules": {}, "meta": {}}
    for name, fname in FILES.items():
        path = Path(fname)
        raw = json.loads(path.read_text())
        agg = aggregate(raw)
        agg["per_symbol_r1"] = per_symbol_at_r(raw, "1.0")
        agg["per_symbol_r2"] = per_symbol_at_r(raw, "2.0")
        master["modules"][name] = agg
        master["meta"][name + "_n_symbols"] = sum(1 for v in raw.values() if "error" not in v)

    Path("master_report_data.json").write_text(json.dumps(master))
    for name in FILES:
        ov = master["modules"][name]["overall"]
        print(name, {r: round(v["expectancy_r"], 3) for r, v in ov.items()})


if __name__ == "__main__":
    main()
