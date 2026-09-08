"""
GLOBAL FORENSIC SUMMARY uretici -- results/holdout_v2_101/*.json'daki
(o ana kadar biten) sembolleri okuyup kullanicinin istedigi ozet
istatistikleri hesaplar. HERHANGI bir asamada (kismi/tam) calistirilabilir
-- coverage HER ZAMAN acikca raporlanir (101/101 tamamlanmadan "final"
diye sunulmaz, "X/101 tamamlandi" seklinde damgalanir).

Hicbir sembol performansina gore evrenden cikarilmaz (frozen universe,
bkz. UNIVERSE_FROZEN.json) -- NOT_TESTED / DATA_INSUFFICIENT olanlar da
sayimda GORUNUR kalir.
"""

import json
import statistics as stats
from pathlib import Path

OUT_DIR = Path("results/holdout_v2_101")

MARKET_FAMILY = {}
for s in ["GOLD", "SILVER", "PLATINUM", "PALLADIUM"]:
    MARKET_FAMILY[s] = "Metals"
for s in ["WTI", "BRENT"]:
    MARKET_FAMILY[s] = "Energy"
for s in ["EURUSD", "GBPUSD", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "USDJPY"]:
    MARKET_FAMILY[s] = "FX_Majors"
for s in ["EURGBP", "EURJPY", "EURCAD", "EURAUD", "EURNZD", "EURCHF", "GBPJPY", "GBPAUD",
          "GBPCAD", "GBPCHF", "GBPNZD", "AUDJPY", "AUDCAD", "AUDCHF", "AUDNZD", "CADJPY",
          "CADCHF", "CHFJPY", "NZDJPY", "NZDCAD", "NZDCHF", "SGDJPY"]:
    MARKET_FAMILY[s] = "FX_Crosses"
for s in ["CHFSGD", "EURDKK", "EURHKD", "EURHUF", "EURNOK", "EURPLN", "EURSEK", "EURSGD",
          "EURTRY", "EURZAR", "GBPDKK", "GBPNOK", "GBPSEK", "GBPSGD", "NZDSGD", "USDCNH",
          "USDDKK", "USDHKD", "USDHUF", "USDMXN", "USDNOK", "USDPLN", "USDSEK", "USDSGD",
          "USDTRY", "USDZAR"]:
    MARKET_FAMILY[s] = "FX_Exotics"
for s in ["NASDAQ", "AUS200", "CA60", "CHN50", "CHINAH", "EU50", "FRA40", "GER40",
          "GERMID50", "GERTECH30", "HK50", "IT40", "JP225", "NETH25", "SA40", "SWI20",
          "SING30", "SPAIN35", "TAIWAN", "UK100", "US2000", "US30", "US500", "USFANG"]:
    MARKET_FAMILY[s] = "Indices"
for s in ["BTCUSD", "ETHUSD", "XRPUSD", "SOLUSD", "DOGEUSD", "ADAUSD", "DOTUSD", "LINKUSD",
          "AVAXUSD", "MATICUSD", "BCHUSD", "LTCUSD", "ATOMUSD", "UNIUSD", "XLMUSD", "ETCUSD"]:
    MARKET_FAMILY[s] = "Crypto"


def _pctile(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def main():
    frozen = json.loads((OUT_DIR / "UNIVERSE_FROZEN.json").read_text())
    universe = frozen["symbols_frozen_order"]

    records = {}
    for sym in universe:
        p = OUT_DIR / f"{sym}.json"
        if p.exists():
            records[sym] = json.loads(p.read_text())

    tested = list(records.keys())
    not_tested = [s for s in universe if s not in records]

    ok_records = {s: r for s, r in records.items() if r.get("data_status") == "ok" and not r.get("structural_failure")}
    insufficient = {s: r for s, r in records.items() if r.get("data_status") == "insufficient"}
    structural_fail = {s: r for s, r in records.items() if r.get("structural_failure")}

    exp_values = {s: r["holdout"]["test_metrics"]["expectancy_r"] for s, r in ok_records.items()}
    pf_values = {s: r["holdout"]["test_metrics"]["profit_factor"] for s, r in ok_records.items()}
    win_values = {s: r["holdout"]["test_metrics"]["win_rate"] for s, r in ok_records.items()}

    sv_counts = {}
    ev_counts = {}
    for r in records.values():
        sv = r.get("strategy_validity", {}).get("status", "UNKNOWN") if r.get("strategy_validity") else "UNKNOWN"
        sv_counts[sv] = sv_counts.get(sv, 0) + 1
        ev = r.get("execution_validity", {}).get("status") if r.get("execution_validity") else "N/A"
        ev_counts[ev] = ev_counts.get(ev, 0) + 1

    exp_list = list(exp_values.values())
    positive = [s for s, v in exp_values.items() if v > 0]
    negative = [s for s, v in exp_values.items() if v <= 0]

    ranked = sorted(exp_values.items(), key=lambda kv: kv[1], reverse=True)
    best10 = ranked[:10]
    worst10 = ranked[-10:]

    def rank_of(sym):
        if sym not in exp_values:
            return None
        for i, (s, _) in enumerate(ranked, start=1):
            if s == sym:
                return {"rank": i, "of": len(ranked), "percentile": round(100 * (1 - (i - 1) / len(ranked)), 1)}
        return None

    family_stats = {}
    for fam in set(MARKET_FAMILY.values()):
        fam_syms = [s for s in ok_records if MARKET_FAMILY.get(s) == fam]
        fam_exp = [exp_values[s] for s in fam_syms]
        if fam_exp:
            family_stats[fam] = {
                "n_symbols": len(fam_syms), "mean_expectancy_r": round(stats.mean(fam_exp), 4),
                "median_expectancy_r": round(stats.median(fam_exp), 4),
                "pct_positive": round(100 * sum(1 for e in fam_exp if e > 0) / len(fam_exp), 1),
            }

    summary = {
        "coverage": {
            "universe_total": len(universe), "tested": len(tested), "not_tested": len(not_tested),
            "not_tested_symbols": not_tested,
            "ok_evaluated": len(ok_records), "data_insufficient": len(insufficient),
            "structural_failure": len(structural_fail),
        },
        "strategy_validity_counts": sv_counts,
        "execution_validity_counts": ev_counts,
        "expectancy_distribution": {
            "n": len(exp_list),
            "mean": round(stats.mean(exp_list), 4) if exp_list else None,
            "median": round(stats.median(exp_list), 4) if exp_list else None,
            "p25": round(_pctile(exp_list, 0.25), 4) if exp_list else None,
            "p75": round(_pctile(exp_list, 0.75), 4) if exp_list else None,
            "pct_positive": round(100 * len(positive) / len(exp_list), 1) if exp_list else None,
            "pct_negative": round(100 * len(negative) / len(exp_list), 1) if exp_list else None,
        },
        "pf_distribution": {
            "median": round(stats.median(pf_values.values()), 4) if pf_values else None,
        },
        "win_rate_distribution": {
            "median": round(stats.median(win_values.values()), 4) if win_values else None,
        },
        "best_10": [{"symbol": s, "expectancy_r": round(v, 4)} for s, v in best10],
        "worst_10": [{"symbol": s, "expectancy_r": round(v, 4)} for s, v in worst10],
        "market_family_stats": family_stats,
        "pilot_symbols_rank": {
            "GOLD": rank_of("GOLD"), "BTCUSD": rank_of("BTCUSD"), "EURGBP": rank_of("EURGBP"),
        },
    }

    out_path = OUT_DIR / "GLOBAL_FORENSIC_SUMMARY.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))

    print(f"=== GLOBAL FORENSIC SUMMARY ({len(tested)}/{len(universe)} tested) ===")
    print(json.dumps(summary["coverage"], indent=2))
    print("\nSTRATEGY VALIDITY:", sv_counts)
    print("EXECUTION VALIDITY:", ev_counts)
    print("\nEXPECTANCY DIST:", json.dumps(summary["expectancy_distribution"], indent=2))
    print("\nBEST 10:", summary["best_10"])
    print("WORST 10:", summary["worst_10"])
    print("\nPILOT RANKS:", summary["pilot_symbols_rank"])
    print(f"\nyazildi: {out_path}")

    if not_tested:
        print(f"\n[!] {len(not_tested)} sembol HENUZ TEST EDILMEDI (sessizce atlanmiyor): {not_tested}")


if __name__ == "__main__":
    main()
