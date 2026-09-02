"""
PROTOTIP (scratch, kalici degil): gold_account_equity_data.json'daki top
winners/losers icin GOLD M30 mum pencerelerini ekleyip rapor artifact'i
icin nihai veri blobunu (gold_account_report_data.json) hazirlar.
"""

import json

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1

IN_PATH = "gold_account_equity_data.json"
OUT_PATH = "gold_account_report_data.json"


def main():
    d = json.load(open(IN_PATH))

    m1 = load_m1_canonical_as_candlev2("data/canonical/V2_MULTI_GOLD_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]

    def serialize_trade(t):
        lo = max(0, t["entry_index"] - 12)
        hi = min(len(candles), t["exit_index"] + 8)
        window = candles[lo:hi]
        return {
            "module": t["module"], "is_bull": t["is_bull"], "won": t["won"],
            "entry": t["entry"], "stop_loss": t["stop_loss"], "take_profit": t["take_profit"],
            "pnl": t["pnl"], "r_multiple": t["r_multiple"], "fill_time": t["fill_time"], "exit_time": t["exit_time"],
            "entry_index_in_window": t["entry_index"] - lo,
            "fill_index_in_window": t["fill_index"] - lo,
            "exit_index_in_window": t["exit_index"] - lo,
            "candles": [{"t": c["time"].isoformat(), "o": c["open"], "h": c["high"],
                         "l": c["low"], "c": c["close"]} for c in window],
        }

    d["top_winners"] = [serialize_trade(t) for t in d["top_winners"]]
    d["top_losers"] = [serialize_trade(t) for t in d["top_losers"]]

    # equity_curve / fixed_equity_curve buyuk olabilir -- gorsellestirme icin
    # asiri yogunlugu onlemek adina, cok fazla nokta varsa esit araliklarla
    # ornekle (chart okunabilirligi icin, veri kaybı degil sadece cizim
    # cozunurlugu).
    def downsample(curve, max_points=1500):
        if len(curve) <= max_points:
            return curve
        step = len(curve) / max_points
        return [curve[int(i * step)] for i in range(max_points)] + [curve[-1]]

    d["equity_curve"] = downsample(d["equity_curve"])
    d["fixed_equity_curve"] = downsample(d["fixed_equity_curve"])

    with open(OUT_PATH, "w") as f:
        json.dump(d, f)
    print(f"yazildi: {OUT_PATH}")


if __name__ == "__main__":
    main()
