"""
PROTOTIP (scratch, kalici degil): trendline_tp_sl_study_results.json'daki
95 sembol x 6 zaman dilimi ham sonuclarini, ob_tp_sl_report_data.json ile
ayni semaya (overall + per_tf, R-multiple anahtarli) havuzlayip
trendline_tp_sl_report_data.json'a yazar. Havuzlama SAYIM TOPLAMI
uzerinden (bkz. scratch_ob_report_aggregate.py docstring'i).
"""

import json
from pathlib import Path

RESULTS_PATH = Path("trendline_tp_sl_study_results.json")
OUT_PATH = Path("trendline_tp_sl_report_data.json")
R_MULTIPLES = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0", "4.0", "5.0"]
TIMEFRAMES = ["M30", "H1", "H2", "H4", "D1", "W1"]


def main():
    raw = json.loads(RESULTS_PATH.read_text())

    overall_acc = {r: {"n": 0, "wins": 0, "losses": 0, "total_r": 0.0, "gross_profit": 0.0, "gross_loss": 0.0} for r in R_MULTIPLES}
    per_tf_acc = {
        tf: {r: {"n": 0, "wins": 0, "losses": 0, "total_r": 0.0, "gross_profit": 0.0, "gross_loss": 0.0} for r in R_MULTIPLES}
        for tf in TIMEFRAMES
    }
    total_lines = 0
    total_reversals = 0
    n_symbols_with_error = 0

    for symbol, sym_result in raw.items():
        if "error" in sym_result:
            n_symbols_with_error += 1
            continue
        for tf in TIMEFRAMES:
            tf_result = sym_result.get(tf)
            if not tf_result:
                continue
            total_lines += tf_result.get("n_lines", 0)
            total_reversals += tf_result.get("n_reversals", 0)
            for r in R_MULTIPLES:
                unit = tf_result.get(r)
                if not unit or unit.get("n", 0) == 0:
                    continue
                n = unit["n"]
                wins = unit["wins"]
                losses = unit["losses"]
                total_r = unit["total_r"]
                r_mult = float(r)
                gross_profit = wins * r_mult
                gross_loss = losses * 1.0

                for acc in (overall_acc[r], per_tf_acc[tf][r]):
                    acc["n"] += n
                    acc["wins"] += wins
                    acc["losses"] += losses
                    acc["total_r"] += total_r
                    acc["gross_profit"] += gross_profit
                    acc["gross_loss"] += gross_loss

    def finalize(acc):
        n = acc["n"]
        if n == 0:
            return {"n": 0, "win_rate": 0.0, "expectancy_r": 0.0, "pf": 0.0, "total_r": 0.0}
        pf = (acc["gross_profit"] / acc["gross_loss"]) if acc["gross_loss"] > 0 else (999.0 if acc["gross_profit"] > 0 else 0.0)
        return {
            "n": n,
            "win_rate": acc["wins"] / n,
            "expectancy_r": acc["total_r"] / n,
            "pf": min(pf, 999.0),
            "total_r": acc["total_r"],
        }

    report = {
        "overall": {r: finalize(overall_acc[r]) for r in R_MULTIPLES},
        "per_tf": {tf: {r: finalize(per_tf_acc[tf][r]) for r in R_MULTIPLES} for tf in TIMEFRAMES},
        "meta": {
            "total_trendlines_detected": total_lines,
            "total_reversals_detected": total_reversals,
            "n_symbols": len(raw) - n_symbols_with_error,
            "n_symbols_error": n_symbols_with_error,
            "sl_buffer_ratio": 0.5,
        },
    }

    OUT_PATH.write_text(json.dumps(report, indent=2))
    print(f"Yazildi: {OUT_PATH} ({total_lines} trendline, {total_reversals} reversal, {len(raw) - n_symbols_with_error} sembol)")
    print(json.dumps(report["overall"], indent=2))


if __name__ == "__main__":
    main()
