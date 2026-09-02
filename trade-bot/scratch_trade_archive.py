"""
PROTOTIP (scratch, kalici degil): "95 sembollük hesap simülasyonu"nu
("son genel test" -- bkz. scratch_multi_symbol_account_simulation.py)
AYNI sembol evreniyle (Tur 1'in 6 sembol çıkarmasından sonraki 95
sembol -- bkz. aşağıdaki SYMBOLS listesi) yeniden çalıştırır, ama bu
sefer HER GERÇEKLEŞEN İŞLEMİN TAM KAYDINI (sadece tek en iyi/en kötü
değil) + görselleştirme için bir mum penceresini ("chart window")
diske yazar. Amaç: "bu işlem örnekleriyle test yapacağız" -- ileride
herhangi bir alt kümeyi (örn. sadece SL'e takılanlar) tekrar veri
yüklemeden doğrudan JSON'dan grafiğe dökebilmek.

METODOLOJİ FARKI (bilinçli): orijinal 95-sembol testi (2026-09-01)
breakeven-stop EKLENMEDEN ÖNCE çalıştırılmıştı. Bu arşiv, o zamandan
beri resmi hale gelen breakeven-stop'u (strategy/config.py:
BREAKEVEN_ENABLED_MODULES = fvg/ifvg/ob) DAHIL ediyor -- amaç eski
sonucu birebir tekrarlamak değil, "bu işlem örnekleriyle ileride test
yapacağız" dendiği için ŞU ANKİ en iyi/güncel metodolojiyle üretilmiş
gerçek işlem örnekleri toplamak.

Checkpoint: her sembol kendi dosyasına (trade_archive/{SYMBOL}.json)
yazılır -- 95 sembollük tek dev bir JSON yerine, kesintiye karşı daha
dayanıklı ve tekrar-çalıştırmada tamamlanan sembolleri atlıyor.

Mum penceresi: giriş (fill_index) öncesi 20 bar + sonrası en fazla 100
bar (+ 10 bar dolgu) -- işlem bu pencereden uzun sürdüyse (nadir,
MAX_WAIT_BARS=3000'e kadar olabilir) pencere kırpılır ve
`window_truncated=true` ile açıkça işaretlenir, gerçek exit_index/
exit_time her durumda kayıtta duruyor (sadece görsel pencere kırpılıyor).
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import (
    StrategyConfig, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO, _ALL_101_SYMBOLS,
    BREAKEVEN_TRIGGER_PCT, BREAKEVEN_ENABLED_MODULES,
)
from strategy.fvg import detect_fvgs, FVGDirection, compute_atr_series
from strategy.order_block import detect_order_blocks, OBDirection
from strategy.trendline import detect_trendlines, detect_trendline_reversals, TrendlineDirection
from scratch_ifvg_tp_sl_study import detect_confirmed_ifvgs

START_DATE = "2020-01-01"
END_DATE = "2026-01-01"
MAX_WAIT_BARS = 3000
STARTING_EQUITY = 10_000.0
RISK_PCT = 0.01
PRE_BARS = 20
POST_CAP_BARS = 100
TRAIL_PAD_BARS = 10

ARCHIVE_DIR = Path("trade_archive")
CONFIG = StrategyConfig()

# "son genel test"in kullandigi 95 sembol -- Tur 1'de (2026-08-31)
# cikarilan 6 sembol (GERTECH30, NASDAQ, IT40, GERMID50, EURDKK, USFANG)
# disinda, TAM 101 sembolluk kanonik evrenin tamami. SONRAKI turlarda
# (2/3/4) daraltilan KEPT_SYMBOLS'dan BILEREK farkli -- kullanici bu
# arsivde acikca "95 sembollu genel test" kapsamini istedi.
_TOUR1_EXCLUDED = {"GERTECH30", "NASDAQ", "IT40", "GERMID50", "EURDKK", "USFANG"}
SYMBOLS = [s for s in _ALL_101_SYMBOLS if s not in _TOUR1_EXCLUDED]
assert len(SYMBOLS) == 95, f"beklenen 95 sembol, bulunan {len(SYMBOLS)}"


@dataclass
class TradeEvent:
    module: str
    trigger_index: int
    is_bull: bool
    entry: float
    stop_loss: float
    take_profit: float
    r_multiple: float
    use_breakeven: bool


def _fvg_events(candles) -> list[TradeEvent]:
    r_mult = MODULE_R_MULTIPLE["fvg"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["fvg"]
    use_be = "fvg" in BREAKEVEN_ENABLED_MODULES
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
        out.append(TradeEvent("fvg", f.end_index + 1, is_bull, entry, sl, tp, r_mult, use_be))
    return out


def _ifvg_events(candles) -> list[TradeEvent]:
    r_mult = MODULE_R_MULTIPLE["ifvg"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["ifvg"]
    use_be = "ifvg" in BREAKEVEN_ENABLED_MODULES
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
        out.append(TradeEvent("ifvg", e["retest_idx"], is_bull, entry, sl, tp, r_mult, use_be))
    return out


def _ob_events(candles) -> list[TradeEvent]:
    r_mult = MODULE_R_MULTIPLE["ob"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["ob"]
    use_be = "ob" in BREAKEVEN_ENABLED_MODULES
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
        out.append(TradeEvent("ob", ob.impulse_index, is_bull, entry, sl, tp, r_mult, use_be))
    return out


def _trendline_events(candles) -> list[TradeEvent]:
    r_mult = MODULE_R_MULTIPLE["trendline"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["trendline"]
    use_be = "trendline" in BREAKEVEN_ENABLED_MODULES
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
                    out.append(TradeEvent("trendline", k, is_bull, entry, sl, tp, r_mult, use_be))
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
        out.append(TradeEvent("trendline", r.retest_index, r.is_bullish, entry, sl, tp, r_mult, use_be))
    return out


def _simulate(candles, ev: TradeEvent):
    """(fill_index, exit_index, won, r_multiple) doner, doldurulmadi/sonuclanmadiysa None."""
    scan_end = min(len(candles), ev.trigger_index + 1 + MAX_WAIT_BARS)
    fill_index = None
    for i in range(ev.trigger_index, scan_end):
        c = candles[i]
        if (ev.is_bull and c["low"] <= ev.entry) or (not ev.is_bull and c["high"] >= ev.entry):
            fill_index = i
            break
    if fill_index is None:
        return None

    arm_level = ev.entry + BREAKEVEN_TRIGGER_PCT * (ev.take_profit - ev.entry) if ev.is_bull else ev.entry - BREAKEVEN_TRIGGER_PCT * (ev.entry - ev.take_profit)
    effective_sl = ev.stop_loss
    armed = False

    end2 = min(len(candles), fill_index + MAX_WAIT_BARS)
    for i in range(fill_index, end2):
        c = candles[i]
        if ev.is_bull:
            hit_sl = c["low"] <= effective_sl
            hit_tp = c["high"] >= ev.take_profit
        else:
            hit_sl = c["high"] >= effective_sl
            hit_tp = c["low"] <= ev.take_profit
        if hit_sl:
            r = 0.0 if armed else -1.0
            return fill_index, i, False, r
        if hit_tp:
            return fill_index, i, True, ev.r_multiple
        if ev.use_breakeven and not armed:
            reached = (c["high"] >= arm_level) if ev.is_bull else (c["low"] <= arm_level)
            if reached:
                armed = True
                effective_sl = ev.entry
    return None


def _make_window(candles, fill_index: int, exit_index: int):
    lo = max(0, fill_index - PRE_BARS)
    exit_capped = min(exit_index, fill_index + POST_CAP_BARS)
    hi = min(len(candles), exit_capped + TRAIL_PAD_BARS)
    truncated = exit_index > exit_capped
    window = candles[lo:hi]
    compact = [
        [c["time"].isoformat() if hasattr(c["time"], "isoformat") else str(c["time"]),
         round(c["open"], 5), round(c["high"], 5), round(c["low"], 5), round(c["close"], 5)]
        for c in window
    ]
    return lo, compact, truncated


def _archive_symbol(symbol: str) -> dict:
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

    all_events = []
    all_events += _fvg_events(candles)
    all_events += _ifvg_events(candles)
    all_events += _ob_events(candles)
    all_events += _trendline_events(candles)

    import datetime
    start_dt = datetime.datetime.fromisoformat(START_DATE)
    end_dt = datetime.datetime.fromisoformat(END_DATE)

    # her aday icin simule et, doldu/sonuclandi mi diye bak, sonra 2020-2025
    # penceresine (fill_time'a gore) ve tek-pozisyon modeline gore filtrele.
    resolved = []
    for ev in all_events:
        res = _simulate(candles, ev)
        if res is None:
            continue
        fill_idx, exit_idx, won, r_mult = res
        if not (start_dt <= candles[fill_idx]["time"] < end_dt):
            continue
        resolved.append((ev, fill_idx, exit_idx, won, r_mult))

    resolved.sort(key=lambda x: x[1])  # fill_index'e gore kronolojik

    equity = STARTING_EQUITY
    fixed_equity = STARTING_EQUITY
    fixed_risk_amount = STARTING_EQUITY * RISK_PCT
    next_available = -1
    trades_out = []

    for ev, fill_idx, exit_idx, won, r_mult in resolved:
        if fill_idx < next_available:
            continue  # baska bir islem hala acik -- tek-pozisyon modeli
        next_available = exit_idx + 1

        risk_amount = equity * RISK_PCT
        pnl_compound = risk_amount * r_mult
        equity += pnl_compound
        pnl_fixed = fixed_risk_amount * r_mult
        fixed_equity += pnl_fixed

        outcome = "win" if r_mult > 0 else ("breakeven" if r_mult == 0 else "loss")
        lo, window, truncated = _make_window(candles, fill_idx, exit_idx)

        trades_out.append({
            "symbol": symbol, "module": ev.module, "is_bull": ev.is_bull,
            "trigger_index": ev.trigger_index, "fill_index": fill_idx, "exit_index": exit_idx,
            "entry": round(ev.entry, 5), "stop_loss": round(ev.stop_loss, 5), "take_profit": round(ev.take_profit, 5),
            "won": won, "outcome": outcome, "r_multiple": r_mult,
            "fill_time": candles[fill_idx]["time"].isoformat(),
            "exit_time": candles[exit_idx]["time"].isoformat(),
            "pnl_compound": pnl_compound, "equity_after_compound": equity,
            "pnl_fixed": pnl_fixed, "equity_after_fixed": fixed_equity,
            "window_start_index": lo, "window_truncated": truncated,
            "candles": window,
        })

    return {
        "symbol": symbol, "starting_equity": STARTING_EQUITY, "risk_pct": RISK_PCT,
        "n_candidate_trades": len(resolved), "n_realized_trades": len(trades_out),
        "final_equity_compound": equity, "final_equity_fixed": fixed_equity,
        "trades": trades_out,
    }


def main():
    ARCHIVE_DIR.mkdir(exist_ok=True)
    done = {p.stem for p in ARCHIVE_DIR.glob("*.json")}
    todo = [s for s in SYMBOLS if s not in done]
    print(f"{len(done)}/{len(SYMBOLS)} tamamlanmis, {len(todo)} kaldi", flush=True)

    for si, symbol in enumerate(todo, start=1):
        t0 = time.time()
        result = _archive_symbol(symbol)
        out_path = ARCHIVE_DIR / f"{symbol}.json"
        tmp = out_path.with_suffix(".tmp")
        for attempt in range(5):
            try:
                tmp.write_text(json.dumps(result, indent=None))
                tmp.replace(out_path)
                break
            except (PermissionError, FileNotFoundError):
                if attempt == 4:
                    raise
                time.sleep(0.5 * (attempt + 1))

        if "error" in result:
            print(f"[{si}/{len(todo)}] {symbol}: HATA -- {result['error']} ({time.time()-t0:.1f}sn)", flush=True)
        else:
            print(f"[{si}/{len(todo)}] {symbol}: {result['n_realized_trades']} gercek islem, "
                  f"equity_compound=${result['final_equity_compound']:,.0f} ({time.time()-t0:.1f}sn)", flush=True)

    print("\nTUM SEMBOLLER TAMAMLANDI.", flush=True)


if __name__ == "__main__":
    main()
