"""
PROTOTIP (scratch, kalici degil): ob_tp_sl_study_results.json'daki
101 sembol x 6 zaman dilimi ham sonuclarini, ifvg_vs_fvg_report_data.json
ile ayni semaya (overall + per_tf, R-multiple anahtarli) havuzlayip
ob_tp_sl_report_data.json'a yazar.

Havuzlama, oran ortalamasi degil SAYIM TOPLAMI uzerinden yapiliyor
(n/wins/losses/total_r sembol+timeframe birimlerinden toplanip, win_rate/
expectancy_r/profit_factor bu toplamlardan YENIDEN hesaplaniyor) --
kucuk-n birimlerin buyuk-n birimlerle ayni agirlikta sayilmasini onlemek
icin (orn. W1'de birkac yuz OB'ye karsi M30'da on binlerce).
"""

import json
from pathlib import Path

RESULTS_PATH = Path("ob_tp_sl_study_results.json")
OUT_PATH = Path("ob_tp_sl_report_data.json")
R_MULTIPLES = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0", "4.0", "5.0"]
TIMEFRAMES = ["M30", "H1", "H2", "H4", "D1", "W1"]


def main():
    raw = json.loads(RESULTS_PATH.read_text())

    overall_acc = {r: {"n": 0, "wins": 0, "losses": 0, "total_r": 0.0, "gross_profit": 0.0, "gross_loss": 0.0} for r in R_MULTIPLES}
    per_tf_acc = {
        tf: {r: {"n": 0, "wins": 0, "losses": 0, "total_r": 0.0, "gross_profit": 0.0, "gross_loss": 0.0} for r in R_MULTIPLES}
        for tf in TIMEFRAMES
    }
    total_obs = 0
    n_symbols_with_error = 0

    for symbol, sym_result in raw.items():
        if "error" in sym_result:
            n_symbols_with_error += 1
            continue
        for tf in TIMEFRAMES:
            tf_result = sym_result.get(tf)
            if not tf_result:
                continue
            total_obs += tf_result.get("n_obs", 0)
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
                gross_loss = losses * 1.0  # her kayip -1.0R

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
            "total_order_blocks_detected": total_obs,
            "n_symbols": len(raw) - n_symbols_with_error,
            "n_symbols_error": n_symbols_with_error,
            "sl_buffer_ratio": 3.0,
        },
    }

    OUT_PATH.write_text(json.dumps(report, indent=2))
    print(f"Yazildi: {OUT_PATH} ({total_obs} toplam OB, {len(raw) - n_symbols_with_error} sembol)")
    print(json.dumps(report["overall"], indent=2))


if __name__ == "__main__":
    main()
