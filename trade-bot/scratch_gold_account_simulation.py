"""
PROTOTIP (scratch, kalici degil): "10.000 dolarlik gercek bir hesap
varmis gibi, GOLD'da 2020-2025 arasi, elimizdeki DORT modulu (FVG,
iFVG, Order Block, Trendline) birlikte kullanarak trade et" simulasyonu.

Metodoloji:
- Tek zaman dilimi: M30 (dort modulun de MODULE_DISABLED_TIMEFRAMES'inde
  M30 yok -- hepsi icin kullanilabilir).
- Her modulun KENDI resmi kalibre edilmis parametreleri (strategy/config.py):
  R hedefi (MODULE_R_MULTIPLE) ve SL tamponu (MODULE_SL_BUFFER_RATIO).
- Sinyal TESPITI tum GOLD gecmisinde (2010'dan itibaren) causal olarak
  calisir (soguk baslangic artefaktindan kacinmak icin) -- ama sadece
  GIRISI (fill/trigger barinin tarihi) 2020-01-01 ile 2025-12-31 arasinda
  olan islemler HESAP simulasyonuna dahil edilir.
- Hesap: baslangic $10,000, her islem GUNCEL bakiyenin %1'ini riske eder
  (bilesik/compounding risk -- standart prop-hesap konvansiyonu). Tum
  islemler MODULLER ARASI kronolojik sirayla (giris barina gore) tek
  bir equity egrisine islenir -- ayni anda acik pozisyonlarin gercek
  marj etkilesimi modellenmiyor (bilinen bir basitlestirme, raporda
  belirtiliyor).
"""

import json
from dataclasses import dataclass, asdict

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO
from strategy.fvg import detect_fvgs, FVGDirection
from strategy.order_block import detect_order_blocks, OBDirection
from strategy.trendline import detect_trendlines, detect_trendline_reversals, TrendlineDirection
from strategy.fvg import compute_atr_series
from scratch_ifvg_tp_sl_study import detect_confirmed_ifvgs

SYMBOL = "GOLD"
START_DATE = "2020-01-01"
END_DATE = "2026-01-01"  # ust sinir haric (2025-12-31 dahil son gun)
MAX_WAIT_BARS = 3000
STARTING_EQUITY = 10_000.0
RISK_PCT = 0.01  # islem basina guncel bakiyenin %1'i

CONFIG = StrategyConfig()


@dataclass
class TradeRecord:
    module: str
    is_bull: bool
    entry_index: int
    fill_index: int
    exit_index: int
    entry: float
    stop_loss: float
    take_profit: float
    won: bool
    r_multiple: float


def _scan_fill_and_exit(candles, start_idx, is_bull, entry, sl, tp):
    end = min(len(candles), start_idx + MAX_WAIT_BARS)
    fill_index = None
    for i in range(start_idx, end):
        c = candles[i]
        if (is_bull and c["low"] <= entry) or (not is_bull and c["high"] >= entry):
            fill_index = i
            break
    if fill_index is None:
        return None
    scan_end = min(len(candles), fill_index + MAX_WAIT_BARS)
    for i in range(fill_index, scan_end):
        c = candles[i]
        if is_bull:
            hit_sl = c["low"] <= sl
            hit_tp = c["high"] >= tp
        else:
            hit_sl = c["high"] >= sl
            hit_tp = c["low"] <= tp
        if hit_sl:
            return fill_index, i, False
        if hit_tp:
            return fill_index, i, True
    return None


def _fvg_trades(candles) -> list[TradeRecord]:
    r_mult = MODULE_R_MULTIPLE["fvg"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["fvg"]
    out = []
    for f in detect_fvgs(candles, config=CONFIG):
        if not f.valid:
            continue
        is_bull = f.direction == FVGDirection.BULLISH
        entry = f.entry_price
        gap = f.top - f.bottom
        buffer = gap * sl_ratio
        sl = f.bottom - buffer if is_bull else f.top + buffer
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        tp = entry + r_mult * risk if is_bull else entry - r_mult * risk
        res = _scan_fill_and_exit(candles, f.end_index + 1, is_bull, entry, sl, tp)
        if res is None:
            continue
        fill_idx, exit_idx, won = res
        out.append(TradeRecord("fvg", is_bull, f.end_index, fill_idx, exit_idx, entry, sl, tp, won,
                                r_mult if won else -1.0))
    return out


def _ifvg_trades(candles) -> list[TradeRecord]:
    r_mult = MODULE_R_MULTIPLE["ifvg"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["ifvg"]
    out = []
    for e in detect_confirmed_ifvgs(candles):
        is_bull = e["new_dir"] == "bullish"
        entry = e["consequent_encroachment"]
        gap = e["top"] - e["bottom"]
        buffer = gap * sl_ratio
        sl = (e["bottom"] - buffer) if is_bull else (e["top"] + buffer)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        tp = entry + r_mult * risk if is_bull else entry - r_mult * risk
        res = _scan_fill_and_exit(candles, e["retest_idx"], is_bull, entry, sl, tp)
        if res is None:
            continue
        fill_idx, exit_idx, won = res
        out.append(TradeRecord("ifvg", is_bull, e["retest_idx"], fill_idx, exit_idx, entry, sl, tp, won,
                                r_mult if won else -1.0))
    return out


def _ob_trades(candles) -> list[TradeRecord]:
    r_mult = MODULE_R_MULTIPLE["ob"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["ob"]
    out = []
    for ob in detect_order_blocks(candles, config=CONFIG):
        is_bull = ob.direction == OBDirection.BULLISH
        entry = (ob.top + ob.bottom) / 2.0
        body = ob.top - ob.bottom
        buffer = body * sl_ratio
        sl = (ob.bottom - buffer) if is_bull else (ob.top + buffer)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        tp = entry + r_mult * risk if is_bull else entry - r_mult * risk
        res = _scan_fill_and_exit(candles, ob.impulse_index, is_bull, entry, sl, tp)
        if res is None:
            continue
        fill_idx, exit_idx, won = res
        out.append(TradeRecord("ob", is_bull, ob.impulse_index, fill_idx, exit_idx, entry, sl, tp, won,
                                r_mult if won else -1.0))
    return out


def _trendline_trades(candles) -> list[TradeRecord]:
    r_mult = MODULE_R_MULTIPLE["trendline"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["trendline"]
    atr_series = compute_atr_series(candles, CONFIG.atr_period)
    lines = detect_trendlines(candles, config=CONFIG)
    reversals = detect_trendline_reversals(candles, lines, config=CONFIG)
    out = []

    for tl in lines:
        is_bull = tl.direction == TrendlineDirection.ASCENDING
        start = tl.known_index + 1
        end = tl.broken_index if tl.broken_index is not None else len(candles)
        was_touching = False
        for k in range(max(start, 0), min(end, len(candles))):
            line_price = tl.price_at(k)
            tol = (atr_series[k] or 0) * CONFIG.trendline_touch_tolerance_atr_ratio
            c = candles[k]
            touched = (c["low"] <= line_price + tol) if is_bull else (c["high"] >= line_price - tol)
            if touched and not was_touching:
                touch_price = c["low"] if is_bull else c["high"]
                buffer = (atr_series[k] or 0) * sl_ratio
                entry = touch_price
                sl = entry - buffer if is_bull else entry + buffer
                risk = abs(entry - sl)
                if risk > 0:
                    tp = entry + r_mult * risk if is_bull else entry - r_mult * risk
                    res = _scan_fill_and_exit(candles, k, is_bull, entry, sl, tp)
                    if res is not None:
                        fill_idx, exit_idx, won = res
                        out.append(TradeRecord("trendline", is_bull, k, fill_idx, exit_idx, entry, sl, tp, won,
                                                r_mult if won else -1.0))
            was_touching = touched

    for r in reversals:
        rc = candles[r.retest_index]
        buffer = (atr_series[r.retest_index] or 0) * sl_ratio
        entry = rc["close"]
        sl = (rc["low"] - buffer) if r.is_bullish else (rc["high"] + buffer)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        tp = entry + r_mult * risk if r.is_bullish else entry - r_mult * risk
        res = _scan_fill_and_exit(candles, r.retest_index, r.is_bullish, entry, sl, tp)
        if res is None:
            continue
        fill_idx, exit_idx, won = res
        out.append(TradeRecord("trendline", r.is_bullish, r.retest_index, fill_idx, exit_idx, entry, sl, tp, won,
                                r_mult if won else -1.0))
    return out


def main():
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{SYMBOL}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
    print(f"toplam {len(candles)} M30 mumu, {candles[0]['time']} - {candles[-1]['time']}", flush=True)

    all_trades: list[TradeRecord] = []
    for name, fn in [("fvg", _fvg_trades), ("ifvg", _ifvg_trades), ("ob", _ob_trades), ("trendline", _trendline_trades)]:
        trades = fn(candles)
        print(f"{name}: {len(trades)} islem tespit edildi (tum tarih araligi)", flush=True)
        all_trades.extend(trades)

    start_dt = __import__("datetime").datetime.fromisoformat(START_DATE)
    end_dt = __import__("datetime").datetime.fromisoformat(END_DATE)
    windowed = [t for t in all_trades if start_dt <= candles[t.fill_index]["time"] < end_dt]
    windowed.sort(key=lambda t: t.fill_index)
    print(f"\n{START_DATE} - {END_DATE} arasinda giris yapan islem sayisi: {len(windowed)}", flush=True)

    out = {
        "symbol": SYMBOL, "timeframe": "M30", "start_date": START_DATE, "end_date": END_DATE,
        "starting_equity": STARTING_EQUITY, "risk_pct": RISK_PCT,
        "trades": [
            {**asdict(t), "fill_time": candles[t.fill_index]["time"].isoformat(),
             "exit_time": candles[t.exit_index]["time"].isoformat()}
            for t in windowed
        ],
    }
    with open("gold_account_simulation_trades.json", "w") as f:
        json.dump(out, f)
    print("yazildi: gold_account_simulation_trades.json", flush=True)


if __name__ == "__main__":
    main()
