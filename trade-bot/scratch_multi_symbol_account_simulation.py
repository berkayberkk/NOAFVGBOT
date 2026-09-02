"""
PROTOTIP (scratch, kalici degil): scratch_gold_account_simulation.py +
scratch_gold_account_equity.py'nin BIRLESTIRILMIS, TUM PARITELER icin
checkpoint'li hali -- kullanici "bu testi tum pariteler icinde yap"
dedi. Her sembol icin BAGIMSIZ bir $10,000 hesap varsayilir (95 sembol
= 95 ayri hesap, birbirini etkilemiyor), 2020-2025 arasi, ayni
metodoloji: 4 modul (FVG, iFVG, OB, Trendline) kendi resmi kalibre
edilmis parametreleriyle M30'da izlenir, tek-pozisyon modeli (bir islem
acikken diger modullerin sinyalleri atlanir), iki risk modeli (bilesik
%1 / sabit $100) paralel hesaplanir.

Checkpoint'li: her sembol tamamlaninca diske yazilir, kesintiye
dayanikli (bu oturumdaki tum buyuk calismalarla ayni desen).
"""

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO, EXCLUDED_SYMBOLS, KEPT_SYMBOLS
from strategy.fvg import detect_fvgs, FVGDirection, compute_atr_series
from strategy.order_block import detect_order_blocks, OBDirection
from strategy.trendline import detect_trendlines, detect_trendline_reversals, TrendlineDirection
from scratch_ifvg_tp_sl_study import detect_confirmed_ifvgs

START_DATE = "2020-01-01"
END_DATE = "2026-01-01"
MAX_WAIT_BARS = 3000
STARTING_EQUITY = 10_000.0
RISK_PCT = 0.01
RESULTS_PATH = Path("multi_symbol_account_results.json")

CONFIG = StrategyConfig()

# + 2026-09-02, TUR 4 (kullanici karariyla): kapsam GOLD, BTCUSD, EURGBP
# UCLUSUNE daraltildi -- strategy/config.py:KEPT_SYMBOLS. Bkz.
# NOA_KONSEPTI_KAYNAK_ANALIZI.md "Sembol eleme turu 2 ve 3" bolumu.
ALL_SYMBOLS = list(KEPT_SYMBOLS)
assert not (set(ALL_SYMBOLS) & set(EXCLUDED_SYMBOLS))


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


def _fvg_trades(candles):
    r_mult = MODULE_R_MULTIPLE["fvg"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["fvg"]
    out = []
    for f in detect_fvgs(candles, config=CONFIG):
        if not f.valid:
            continue
        is_bull = f.direction == FVGDirection.BULLISH
        entry = f.entry_price
        buffer = (f.top - f.bottom) * sl_ratio
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


def _ifvg_trades(candles):
    r_mult = MODULE_R_MULTIPLE["ifvg"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["ifvg"]
    out = []
    for e in detect_confirmed_ifvgs(candles):
        is_bull = e["new_dir"] == "bullish"
        entry = e["consequent_encroachment"]
        buffer = (e["top"] - e["bottom"]) * sl_ratio
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


def _ob_trades(candles):
    r_mult = MODULE_R_MULTIPLE["ob"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["ob"]
    out = []
    for ob in detect_order_blocks(candles, config=CONFIG):
        is_bull = ob.direction == OBDirection.BULLISH
        entry = (ob.top + ob.bottom) / 2.0
        buffer = (ob.top - ob.bottom) * sl_ratio
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


def _trendline_trades(candles):
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


def simulate_account(candles, windowed_trades):
    windowed_trades = sorted(windowed_trades, key=lambda t: t.fill_index)
    trades = []
    next_available = -1
    skipped = 0
    for t in windowed_trades:
        if t.fill_index < next_available:
            skipped += 1
            continue
        trades.append(t)
        next_available = t.exit_index + 1

    equity = STARTING_EQUITY
    peak = equity
    max_dd_pct = 0.0
    max_dd_dollar = 0.0
    fixed_equity = STARTING_EQUITY
    fixed_risk_amount = STARTING_EQUITY * RISK_PCT
    fixed_peak = fixed_equity
    fixed_max_dd_pct = 0.0
    fixed_max_dd_dollar = 0.0

    module_pnl = {"fvg": 0.0, "ifvg": 0.0, "ob": 0.0, "trendline": 0.0}
    module_n = {"fvg": 0, "ifvg": 0, "ob": 0, "trendline": 0}
    module_wins = {"fvg": 0, "ifvg": 0, "ob": 0, "trendline": 0}
    wins_n = 0
    best_trade = None
    worst_trade = None

    for t in trades:
        risk_amount = equity * RISK_PCT
        pnl = risk_amount * t.r_multiple
        equity += pnl
        peak = max(peak, equity)
        dd_dollar = peak - equity
        max_dd_dollar = max(max_dd_dollar, dd_dollar)
        max_dd_pct = max(max_dd_pct, (dd_dollar / peak) if peak > 0 else 0.0)

        fixed_equity += fixed_risk_amount * t.r_multiple
        fixed_peak = max(fixed_peak, fixed_equity)
        fdd = fixed_peak - fixed_equity
        fixed_max_dd_dollar = max(fixed_max_dd_dollar, fdd)
        fixed_max_dd_pct = max(fixed_max_dd_pct, (fdd / fixed_peak) if fixed_peak > 0 else 0.0)

        module_pnl[t.module] += pnl
        module_n[t.module] += 1
        if t.won:
            module_wins[t.module] += 1
            wins_n += 1

        if best_trade is None or pnl > best_trade["pnl"]:
            best_trade = {"module": t.module, "pnl": pnl, "r_multiple": t.r_multiple,
                          "fill_time": candles[t.fill_index]["time"].isoformat()}
        if worst_trade is None or pnl < worst_trade["pnl"]:
            worst_trade = {"module": t.module, "pnl": pnl, "r_multiple": t.r_multiple,
                           "fill_time": candles[t.fill_index]["time"].isoformat()}

    n = len(trades)
    return {
        "n_candidate_trades": len(windowed_trades), "n_skipped_overlap": skipped,
        "total_trades": n, "win_rate": (wins_n / n) if n else 0.0,
        "final_equity": equity, "net_pnl": equity - STARTING_EQUITY,
        "net_pnl_pct": (equity - STARTING_EQUITY) / STARTING_EQUITY if STARTING_EQUITY else 0.0,
        "max_drawdown_pct": max_dd_pct, "max_drawdown_dollar": max_dd_dollar,
        "fixed_final_equity": fixed_equity, "fixed_net_pnl": fixed_equity - STARTING_EQUITY,
        "fixed_net_pnl_pct": (fixed_equity - STARTING_EQUITY) / STARTING_EQUITY if STARTING_EQUITY else 0.0,
        "fixed_max_drawdown_pct": fixed_max_dd_pct, "fixed_max_drawdown_dollar": fixed_max_dd_dollar,
        "module_summary": {
            m: {"n": module_n[m], "pnl": module_pnl[m],
                "win_rate": (module_wins[m] / module_n[m]) if module_n[m] else 0.0}
            for m in module_pnl
        },
        "best_trade": best_trade, "worst_trade": worst_trade,
    }


def process_symbol(symbol: str) -> dict:
    path = f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv"
    try:
        m1 = load_m1_canonical_as_candlev2(path)
    except FileNotFoundError:
        return {"error": "veri yok"}
    if len(m1) < 2000:
        return {"error": "yetersiz veri"}

    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
    if len(candles) < 100:
        return {"error": "yetersiz M30 verisi"}

    all_trades = []
    all_trades += _fvg_trades(candles)
    all_trades += _ifvg_trades(candles)
    all_trades += _ob_trades(candles)
    all_trades += _trendline_trades(candles)

    import datetime
    start_dt = datetime.datetime.fromisoformat(START_DATE)
    end_dt = datetime.datetime.fromisoformat(END_DATE)
    windowed = [t for t in all_trades if start_dt <= candles[t.fill_index]["time"] < end_dt]

    if not windowed:
        return {"error": "2020-2025 araliginda islem yok"}

    return simulate_account(candles, windowed)


def _load_checkpoint() -> dict:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text())
    return {}


def _save_checkpoint(data: dict) -> None:
    tmp = RESULTS_PATH.with_suffix(".tmp")
    for attempt in range(5):
        try:
            tmp.write_text(json.dumps(data, indent=2, default=str))
            tmp.replace(RESULTS_PATH)
            return
        except (PermissionError, FileNotFoundError):
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


def main():
    checkpoint = _load_checkpoint()
    for i, symbol in enumerate(ALL_SYMBOLS, 1):
        if symbol in checkpoint:
            continue
        t0 = time.time()
        result = process_symbol(symbol)
        checkpoint[symbol] = result
        _save_checkpoint(checkpoint)
        if "error" in result:
            print(f"[{i}/{len(ALL_SYMBOLS)}] {symbol}: HATA -- {result['error']} ({time.time()-t0:.1f}sn)", flush=True)
        else:
            print(f"[{i}/{len(ALL_SYMBOLS)}] {symbol}: net=${result['net_pnl']:,.0f} "
                  f"({result['net_pnl_pct']:+.1%}) n={result['total_trades']} "
                  f"win={result['win_rate']:.1%} ({time.time()-t0:.1f}sn)", flush=True)

    print("\nTUM SEMBOLLER TAMAMLANDI.", flush=True)


if __name__ == "__main__":
    main()
