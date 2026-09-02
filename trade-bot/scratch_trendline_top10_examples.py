"""
PROTOTIP (scratch, kalici degil): Trendline sekme (bounce) islemleri icin
GERCEK 10 ornek (5 kazanan/5 kaybeden) toplar -- SADECE GOLD'da, tum
paritelere TARAMA YAPILMADAN (kullanici talimati, 2026-08-31).

Giris/SL/TP (arastirmadan -- Monkeytrade, Capital.com, ForTraders; bkz.
NOA_KONSEPTI_KAYNAK_ANALIZI.md "Trendline TP/SL arastirmasi"):
- Giris: dokunus barinin kendi fiyati (swing low/high -- "sekme" ani).
- SL: dokunus fiyatinin ATR x tampon kadar otesi. GECICI deger (henuz
  kalibre edilmedi): 1.0x ATR.
- TP: sabit R kati. GECICI deger: R=1.5 (FVG/iFVG'nin zaten dogrulanmis
  optimal R'si, Trendline'in kendi optimali 101 sembol calismasinda
  ayrica olculecek).
- Oynanabilir dokunus: dogrulama (3.) dokunusu ve kirilana kadar sonraki
  her ek dokunus.

"En karli/en zararli" siralamasi YOK -- kullanici sadece 5 TP + 5 SL
ORNEGI istedi, bulununca DUR.
"""

import json

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.trendline import detect_trendlines, TrendlineDirection
from strategy.fvg import compute_atr_series

SYMBOL = "GOLD"
SL_BUFFER_RATIO = 1.0
R_MULTIPLE = 1.5
MAX_WAIT_BARS = 500
N_WINNERS_WANTED = 5
N_LOSERS_WANTED = 5


def simulate_touch(candles, atr_series, idx, is_bull, price_key):
    touch_price = candles[idx][price_key]
    atr = atr_series[idx] or 0
    buffer = atr * SL_BUFFER_RATIO
    entry = touch_price
    sl = entry - buffer if is_bull else entry + buffer
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
            return {"won": False, "entry": entry, "sl": sl, "tp": tp, "touch_idx": idx, "exit_idx": k}
        if hit_tp:
            return {"won": True, "entry": entry, "sl": sl, "tp": tp, "touch_idx": idx, "exit_idx": k}
    return None


def main():
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{SYMBOL}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]

    lines = detect_trendlines(candles)
    atr_series = compute_atr_series(candles, 14)

    winners, losers = [], []
    for tl in lines:
        is_bull = tl.direction == TrendlineDirection.ASCENDING
        price_key = "low" if is_bull else "high"
        tradeable_touches = tl.anchor_indices[2:]  # 3. dokunus ve sonrasi (ilk 2 henuz dogrulanmamisti)
        for touch_idx in tradeable_touches:
            result = simulate_touch(candles, atr_series, touch_idx, is_bull, price_key)
            if result is None:
                continue
            result["direction"] = tl.direction.value
            result["trendline"] = tl
            if result["won"] and len(winners) < N_WINNERS_WANTED:
                winners.append(result)
            elif not result["won"] and len(losers) < N_LOSERS_WANTED:
                losers.append(result)
        if len(winners) >= N_WINNERS_WANTED and len(losers) >= N_LOSERS_WANTED:
            break

    print(f"kazanan: {len(winners)}, kaybeden: {len(losers)}")

    def serialize(trade_list, won):
        out = []
        for t in trade_list:
            tl = t["trendline"]
            lo = max(0, tl.anchor_indices[0] - 10)
            hi = min(len(candles), t["exit_idx"] + 8)
            window = candles[lo:hi]
            line_prices = [tl.slope * (lo + i) + tl.intercept for i in range(len(window))]
            out.append({
                "direction": t["direction"], "won": won,
                "entry": t["entry"], "stop_loss": t["sl"], "take_profit": t["tp"],
                "touch_index_in_window": t["touch_idx"] - lo,
                "exit_index_in_window": t["exit_idx"] - lo,
                "anchor_indices_in_window": [a - lo for a in tl.anchor_indices],
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
    with open("trendline_top10_examples_data.json", "w") as f:
        json.dump(result, f)
    print("yazildi: trendline_top10_examples_data.json")


if __name__ == "__main__":
    main()
