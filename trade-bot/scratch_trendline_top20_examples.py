"""
PROTOTIP (scratch, kalici degil): scratch_trendline_top10_examples.py'nin
genisletilmis hali -- kullanici "kirilim sonrasi reversal (orn. dusus
trendi kirilinca long) de eklensin, 20 islemlik (10 TP + 10 SL) yapalim"
dedi. Sekme (bounce) VE kirilim+retest (reversal, bkz.
strategy/trendline.py:detect_trendline_reversals) islemleri BIRLIKTE,
kronolojik sirayla, SADECE GOLD'da (tum paritelere tarama YOK) taranir.

TP/SL (arastirmadan -- bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md "Trendline
TP/SL arastirmasi" ve "Kirilim+Retest" bolumleri):
- Sekme: giris = dokunus fiyati, SL = dokunus fiyati +/- ATR x tampon.
- Reversal: giris = retest anindaki cizgi fiyati, SL = retest barinin
  KENDI fitil ekstremumu +/- ATR x tampon ("SL beyond the retest
  extreme" -- arastirmadan).
- Ikisi de: TP = sabit R kati (GECICI R=1.5, henuz kalibre edilmedi).
"""

import json

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.trendline import detect_trendlines, detect_trendline_reversals, TrendlineDirection
from strategy.fvg import compute_atr_series

SYMBOL = "GOLD"
SL_BUFFER_RATIO = 1.0
R_MULTIPLE = 1.5
MAX_WAIT_BARS = 500
N_WINNERS_WANTED = 10
N_LOSERS_WANTED = 10


def _simulate(candles, idx, is_bull, entry, sl):
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    tp = entry + R_MULTIPLE * risk if is_bull else entry - R_MULTIPLE * risk

    scan_end = min(len(candles), idx + 1 + MAX_WAIT_BARS)
    for k in range(idx + 1, scan_end):
        c = candles[k]
        if is_bull:
            hit_sl = c["low"] <= sl
            hit_tp = c["high"] >= tp
        else:
            hit_sl = c["high"] >= sl
            hit_tp = c["low"] <= tp
        if hit_sl:
            return {"won": False, "entry": entry, "sl": sl, "tp": tp, "trigger_idx": idx, "exit_idx": k}
        if hit_tp:
            return {"won": True, "entry": entry, "sl": sl, "tp": tp, "trigger_idx": idx, "exit_idx": k}
    return None


def _bounce_events(lines, candles, atr_series):
    events = []
    for tl in lines:
        is_bull = tl.direction == TrendlineDirection.ASCENDING
        price_key = "low" if is_bull else "high"
        for touch_idx in tl.anchor_indices[2:]:
            touch_price = candles[touch_idx][price_key]
            buffer = (atr_series[touch_idx] or 0) * SL_BUFFER_RATIO
            entry = touch_price
            sl = entry - buffer if is_bull else entry + buffer
            events.append({"kind": "bounce", "trigger_idx": touch_idx, "is_bull": is_bull,
                            "entry": entry, "sl": sl, "trendline": tl})
    return events


def _reversal_events(reversals, candles, atr_series):
    events = []
    for r in reversals:
        buffer = (atr_series[r.retest_index] or 0) * SL_BUFFER_RATIO
        retest_candle = candles[r.retest_index]
        if r.is_bullish:
            sl = retest_candle["low"] - buffer
        else:
            sl = retest_candle["high"] + buffer
        events.append({"kind": "reversal", "trigger_idx": r.retest_index, "is_bull": r.is_bullish,
                        "entry": r.entry_price, "sl": sl, "trendline": r.source_trendline})
    return events


def main():
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{SYMBOL}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]

    lines = detect_trendlines(candles)
    reversals = detect_trendline_reversals(candles, lines)
    atr_series = compute_atr_series(candles, 14)

    events = _bounce_events(lines, candles, atr_series) + _reversal_events(reversals, candles, atr_series)
    events.sort(key=lambda e: e["trigger_idx"])

    winners, losers = [], []
    for e in events:
        result = _simulate(candles, e["trigger_idx"], e["is_bull"], e["entry"], e["sl"])
        if result is None:
            continue
        result.update({"kind": e["kind"], "is_bull": e["is_bull"], "trendline": e["trendline"]})
        if result["won"] and len(winners) < N_WINNERS_WANTED:
            winners.append(result)
        elif not result["won"] and len(losers) < N_LOSERS_WANTED:
            losers.append(result)
        if len(winners) >= N_WINNERS_WANTED and len(losers) >= N_LOSERS_WANTED:
            break

    print(f"kazanan: {len(winners)}, kaybeden: {len(losers)}")
    print("kazanan turleri:", [w["kind"] for w in winners])
    print("kaybeden turleri:", [l["kind"] for l in losers])

    def serialize(trade_list, won):
        out = []
        for t in trade_list:
            tl = t["trendline"]
            lo = max(0, tl.anchor_indices[0] - 10)
            hi = min(len(candles), t["exit_idx"] + 8)
            window = candles[lo:hi]
            line_prices = [tl.slope * (lo + i) + tl.intercept for i in range(len(window))]
            out.append({
                "kind": t["kind"], "is_bull": t["is_bull"], "won": won,
                "entry": t["entry"], "stop_loss": t["sl"], "take_profit": t["tp"],
                "trigger_index_in_window": t["trigger_idx"] - lo,
                "exit_index_in_window": t["exit_idx"] - lo,
                "anchor_indices_in_window": [a - lo for a in tl.anchor_indices],
                "broken_index_in_window": (tl.broken_index - lo) if tl.broken_index is not None else None,
                "line_prices": line_prices,
                "candles": [{"t": c["time"].isoformat(), "o": c["open"], "h": c["high"],
                             "l": c["low"], "c": c["close"]} for c in window],
            })
        return out

    result = {
        "symbol": SYMBOL, "timeframe": "M30",
        "params": {"sl_buffer_ratio": SL_BUFFER_RATIO, "r_multiple": R_MULTIPLE},
        "winners": serialize(winners, True),
        "losers": serialize(losers, False),
    }
    with open("trendline_top20_examples_data.json", "w") as f:
        json.dump(result, f)
    print("yazildi: trendline_top20_examples_data.json")


if __name__ == "__main__":
    main()
