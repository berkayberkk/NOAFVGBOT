"""
101/101 tamamlandiktan SONRA, GLOBAL FORENSIC SUMMARY'den ONCE calistirilacak
8 bütünlük kontrolü (kullanicinin 2026-09-07 talebi). Herhangi bir kontrol
FAIL ederse rapor bundan sonra da üretilmemeli -- once kok neden bulunmali.
"""

import json
import hashlib
from pathlib import Path

OUT_DIR = Path("results/holdout_v2_101")
PRECOMPUTED = {
    "GOLD": {"n": 2937, "exp": 0.08265241707997006, "pf": 1.1482410875259166, "maxdd": 89.0779996658668},
    "BTCUSD": {"n": 2966, "exp": -0.08172429706592454, "pf": 0.8584825006383395, "maxdd": 288.67188592221976},
    "EURGBP": {"n": 4581, "exp": -0.23753316784892398, "pf": 0.621132452082284, "maxdd": 1096.4970548760018},
}


def main():
    results = {}

    frozen = json.loads((OUT_DIR / "UNIVERSE_FROZEN.json").read_text())
    universe = frozen["symbols_frozen_order"]

    files = {f.stem: f for f in OUT_DIR.glob("*.json") if f.stem != "UNIVERSE_FROZEN"}
    records = {s: json.loads(files[s].read_text()) for s in universe if s in files}

    # 1. Coverage 101/101?
    missing = [s for s in universe if s not in records]
    results["1_coverage_101_101"] = {"pass": len(missing) == 0, "tested": len(records), "missing": missing}

    # 2. Data insufficient semboller
    insufficient = [s for s, r in records.items() if r.get("data_status") == "insufficient"]
    results["2_data_insufficient_symbols"] = insufficient

    # 3. Her sembolde holdout sonucu var mi (ok/structural_failure/insufficient disinda bosluk yok mu)
    no_holdout = [s for s, r in records.items()
                  if r.get("data_status") == "ok" and not r.get("structural_failure") and "holdout" not in r]
    results["3_missing_holdout_despite_ok"] = {"pass": len(no_holdout) == 0, "symbols": no_holdout}

    # 4. Strategy/Execution validity karismis mi -- iki alan da BAGIMSIZ var olmali (ok semboller icin)
    confused = []
    for s, r in records.items():
        if r.get("data_status") == "ok" and not r.get("structural_failure"):
            sv = r.get("strategy_validity")
            ev = r.get("execution_validity")
            if sv is None or ev is None or "status" not in sv or "status" not in ev:
                confused.append(s)
            # execution INVALID/UNCERTAIN strategy sonucunu FAIL'e cevirmemeli -- capraz kontrol
            elif sv["status"] == "PASS" and ev["status"] == "INVALID" and r.get("classification") != f"STRATEGY PASS / EXECUTION INVALID":
                confused.append(s)
    results["4_strategy_execution_not_conflated"] = {"pass": len(confused) == 0, "problem_symbols": confused}

    # 5. Precomputed/imported (GOLD/BTCUSD/EURGBP) orijinal metriklerle birebir ayni mi
    mismatches = []
    for sym, orig in PRECOMPUTED.items():
        r = records.get(sym, {})
        tm = r.get("holdout", {}).get("test_metrics", {})
        ok = (tm.get("filled_trades") == orig["n"]
              and abs(tm.get("expectancy_r", 0) - orig["exp"]) < 1e-9
              and abs(tm.get("profit_factor", 0) - orig["pf"]) < 1e-9
              and abs(tm.get("max_drawdown_r", 0) - orig["maxdd"]) < 1e-6)
        if not ok:
            mismatches.append({"symbol": sym, "expected": orig, "found": tm})
    results["5_precomputed_metrics_unchanged"] = {"pass": len(mismatches) == 0, "mismatches": mismatches}

    # 6. Hicbir sembol evrenden cikarilmis mi (frozen universe ile _ALL_101_SYMBOLS karsilastir)
    from strategy.config import _ALL_101_SYMBOLS
    universe_matches_config = list(universe) == list(_ALL_101_SYMBOLS)
    results["6_universe_not_pruned"] = {"pass": universe_matches_config, "frozen_count": len(universe), "config_count": len(_ALL_101_SYMBOLS)}

    # 7. Parametre degisti mi -- TUM sembollerin parameter_hash'i AYNI olmali
    param_hashes = {r.get("provenance", {}).get("parameter_hash") for r in records.values() if r.get("provenance")}
    results["7_parameters_unchanged_across_run"] = {"pass": len(param_hashes) <= 1, "distinct_hashes": list(param_hashes)}

    # 8. Reproducible metadata var mi (provenance tam mi)
    prov_fields = {"universe_version", "data_version", "strategy_version", "parameter_hash", "research_run_id", "timestamp"}
    missing_prov = [s for s, r in records.items() if not prov_fields.issubset(set((r.get("provenance") or {}).keys()))]
    results["8_provenance_complete"] = {"pass": len(missing_prov) == 0, "symbols_missing_provenance": missing_prov}

    all_pass = all(v.get("pass", True) if isinstance(v, dict) else True for v in results.values())
    print(json.dumps(results, indent=2, default=str))
    print(f"\n{'TUM KONTROLLER GECTI' if all_pass else 'BAZI KONTROLLER BASARISIZ -- rapor uretmeden ONCE bunlari coz'}")
    return results, all_pass


if __name__ == "__main__":
    main()
