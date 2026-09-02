"""
PROTOTIP (scratch, kalici degil): "sirasiyla yapalim: OB filtreleri ->
Katman entegrasyonu -> confluence testi" sirasinin 3. ve son adimi.
OB filtreleri (bkz. scratch_ob_filters_study.py) ve Katman entegrasyonu
(bkz. scratch_katman_signal_filter_multisymbol.py, commit cd44e90) ikisi
de negatif sonuc verdi ve benimsenmedi. Bu script son soruyu soruyor:
**4 modulun (FVG, iFVG, Order Block, Trendline) BIRDEN FAZLASI ayni anda
ayni yonde/bolgede sinyal verirse ("confluence"), tek basina bir modulun
sinyaline gore kalite (win rate/beklenti/PF) gercekten artiyor mu?**
`strategy/signal_engine.py`'nin A+ (FVG+OB) fikri burada 4 module
genellenip olcekli test ediliyor -- bu, kullanicinin "A+ setup" fikrinin
ilk kapsamli ampirik testi.

Kapsam: strategy/config.py:KEPT_SYMBOLS (GOLD, BTCUSD, EURGBP), M30, her
modulun kendi resmi R/SL/breakeven parametreleri (strategy/config.py).

MODELLEME BASITLESTIRMESI (acikca belirtiliyor, gizlenmiyor): bir sinyalin
"aktif" (hala geciyerli/tetiklenebilir) sayildigi bar araligi modul
modul FARKLI kesinlikte biliniyor -- FVG (filled_at_index) ve OB
(mitigated_index) icin GERCEK causal invalidation izleniyor, ama iFVG
(detect_confirmed_ifvgs) ve Trendline reversal icin kod tabaninda hic
invalidation/gecersizlik takibi YOK. Bu yuzden TUM modullerde aktiflik
penceresi tek-tip bir ust sinira (MAX_ACTIVE_BARS) sinirlandi -- gercek
invalidation biliniyorsa o kullanilir (daha erken bitebilir), bilinmiyorsa
tetiklenme barindan itibaren MAX_ACTIVE_BARS kadar "hala gecerli"
varsayilir. Bu, "bir bolge sonsuza kadar gecerlidir" gibi yapay bir
varsayimdan kacinmak icin konan MAKUL ama KALIBRE EDILMEMIS bir sinir.

Confluence sayimi: her sinyalin KENDI tetiklenme barinda (causal --
sadece o ana kadarki bilgiyle), AYNI yonde VE bolgesi cakisan, AYNI
zamanda aktif olan BASKA kac modulun sinyali oldugu sayilir (0-3 arasi,
kendi modulu haric). Sonuclar bu sayiya gore bucket'lanir.
"""

import bisect
import json
from dataclasses import dataclass

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO, KEPT_SYMBOLS, BREAKEVEN_TRIGGER_PCT, BREAKEVEN_ENABLED_MODULES
from strategy.fvg import detect_fvgs, mark_filled_fvgs, FVGDirection, compute_atr_series
from strategy.order_block import detect_order_blocks, mark_mitigated_blocks, OBDirection
from strategy.trendline import detect_trendlines, detect_trendline_reversals, TrendlineDirection
from scratch_ifvg_tp_sl_study import detect_confirmed_ifvgs

CONFIG = StrategyConfig()
MAX_WAIT_BARS = 3000
MAX_ACTIVE_BARS = 500  # kalibre edilmedi -- bkz. modul docstring'i


@dataclass
class Event:
    module: str
    trigger_idx: int          # sinyalin tetiklendigi (causal olarak bilindigi) bar
    is_bull: bool
    entry: float
    sl: float
    tp: float
    r_multiple: float
    top: float                 # bolge ust siniri (Trendline icin top==bottom==entry, cizgi bir nokta)
    bottom: float
    active_end: int             # bu bardan SONRA artik "aktif" sayilmaz (dahil degil)
    use_breakeven: bool


def _zones_overlap(top1, bottom1, top2, bottom2) -> bool:
    return min(top1, top2) - max(bottom1, bottom2) >= 0


def _fvg_events(candles) -> list[Event]:
    r_mult = MODULE_R_MULTIPLE["fvg"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["fvg"]
    use_be = "fvg" in BREAKEVEN_ENABLED_MODULES
    fvgs = detect_fvgs(candles, config=CONFIG)
    mark_filled_fvgs(fvgs, candles)
    out = []
    for f in fvgs:
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
        trigger = f.end_index + 1
        active_end = f.filled_at_index if f.filled_at_index is not None else trigger + MAX_ACTIVE_BARS
        active_end = min(active_end, trigger + MAX_ACTIVE_BARS)
        out.append(Event("fvg", trigger, is_bull, entry, sl, tp, r_mult, f.top, f.bottom, active_end, use_be))
    return out


def _ifvg_events(candles) -> list[Event]:
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
        trigger = e["retest_idx"]
        # invalidation izlenmiyor -- MAX_ACTIVE_BARS varsayimi (bkz. modul docstring'i)
        active_end = trigger + MAX_ACTIVE_BARS
        out.append(Event("ifvg", trigger, is_bull, entry, sl, tp, r_mult, e["top"], e["bottom"], active_end, use_be))
    return out


def _ob_events(candles) -> list[Event]:
    r_mult = MODULE_R_MULTIPLE["ob"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["ob"]
    use_be = "ob" in BREAKEVEN_ENABLED_MODULES
    obs = detect_order_blocks(candles, config=CONFIG)
    mark_mitigated_blocks(obs, candles)
    out = []
    for ob in obs:
        is_bull = ob.direction == OBDirection.BULLISH
        entry = (ob.top + ob.bottom) / 2.0
        buffer = (ob.top - ob.bottom) * sl_ratio
        sl = (ob.bottom - buffer) if is_bull else (ob.top + buffer)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        tp = entry + r_mult * risk if is_bull else entry - r_mult * risk
        trigger = ob.impulse_index
        active_end = ob.mitigated_index if ob.mitigated_index is not None else trigger + MAX_ACTIVE_BARS
        active_end = min(active_end, trigger + MAX_ACTIVE_BARS)
        out.append(Event("ob", trigger, is_bull, entry, sl, tp, r_mult, ob.top, ob.bottom, active_end, use_be))
    return out


def _trendline_events(candles) -> list[Event]:
    r_mult = MODULE_R_MULTIPLE["trendline"]
    sl_ratio = MODULE_SL_BUFFER_RATIO["trendline"]
    atr_series = compute_atr_series(candles, CONFIG.atr_period)
    lines = detect_trendlines(candles, config=CONFIG)
    reversals = detect_trendline_reversals(candles, lines, config=CONFIG)
    out = []

    # Sicrama (bounce) sinyalleri -- aktif/dogrulanmis cizgiye ilk temas.
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
                    active_end = min(end, k + MAX_ACTIVE_BARS)
                    out.append(Event("trendline", k, is_bull, entry, sl, tp, r_mult, entry, entry, active_end, False))
            was_touching = touched

    # Kirilim+retest (reversal) sinyalleri.
    for r in reversals:
        rc = candles[r.retest_index]
        buffer = (atr_series[r.retest_index] or 0) * sl_ratio
        entry = rc["close"]
        sl = (rc["low"] - buffer) if r.is_bullish else (rc["high"] + buffer)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        tp = entry + r_mult * risk if r.is_bullish else entry - r_mult * risk
        active_end = r.retest_index + MAX_ACTIVE_BARS  # invalidation izlenmiyor
        out.append(Event("trendline", r.retest_index, r.is_bullish, entry, sl, tp, r_mult, entry, entry, active_end, False))

    return out


def _simulate(candles, ev: Event):
    scan_end = min(len(candles), ev.trigger_idx + 1 + MAX_WAIT_BARS)
    fill_index = None
    for i in range(ev.trigger_idx, scan_end):
        c = candles[i]
        if (ev.is_bull and c["low"] <= ev.entry) or (not ev.is_bull and c["high"] >= ev.entry):
            fill_index = i
            break
    if fill_index is None:
        return None

    arm_level = ev.entry + BREAKEVEN_TRIGGER_PCT * (ev.tp - ev.entry) if ev.is_bull else ev.entry - BREAKEVEN_TRIGGER_PCT * (ev.entry - ev.tp)
    effective_sl = ev.sl
    armed = False

    end2 = min(len(candles), fill_index + MAX_WAIT_BARS)
    for i in range(fill_index, end2):
        c = candles[i]
        if ev.is_bull:
            hit_sl = c["low"] <= effective_sl
            hit_tp = c["high"] >= ev.tp
        else:
            hit_sl = c["high"] >= effective_sl
            hit_tp = c["low"] <= ev.tp
        if hit_sl:
            return {"won": False, "r": 0.0 if armed else -1.0}
        if hit_tp:
            return {"won": True, "r": ev.r_multiple}
        if ev.use_breakeven and not armed:
            reached = (c["high"] >= arm_level) if ev.is_bull else (c["low"] <= arm_level)
            if reached:
                armed = True
                effective_sl = ev.entry
    return None


def _confluence_count(ev: Event, others_by_module: dict[str, tuple[list[int], list[Event]]]) -> int:
    count = 0
    for mod, (starts, events) in others_by_module.items():
        if mod == ev.module:
            continue
        lo = bisect.bisect_left(starts, ev.trigger_idx - MAX_ACTIVE_BARS)
        hi = bisect.bisect_right(starts, ev.trigger_idx)
        found = False
        for k in range(lo, hi):
            other = events[k]
            if other.trigger_idx > ev.trigger_idx or other.active_end < ev.trigger_idx:
                continue
            if other.is_bull != ev.is_bull:
                continue
            if _zones_overlap(ev.top, ev.bottom, other.top, other.bottom):
                found = True
                break
        if found:
            count += 1
    return count


def _metrics(outcomes: list[dict]) -> dict:
    if not outcomes:
        return {"n": 0}
    wins = [o for o in outcomes if o["won"]]
    losses = [o for o in outcomes if not o["won"]]
    n = len(outcomes)
    total_r = sum(o["r"] for o in outcomes)
    gross_profit = sum(o["r"] for o in wins)
    gross_loss = abs(sum(o["r"] for o in losses))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    return {
        "n": n, "wins": len(wins), "win_rate": len(wins) / n,
        "expectancy_r": total_r / n, "profit_factor": min(pf, 999.0), "total_r": total_r,
    }


def main():
    results = {}
    for symbol in KEPT_SYMBOLS:
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
        print(f"{symbol}: {len(candles)} M30 mumu", flush=True)

        by_module = {
            "fvg": _fvg_events(candles),
            "ifvg": _ifvg_events(candles),
            "ob": _ob_events(candles),
            "trendline": _trendline_events(candles),
        }
        for mod, evs in by_module.items():
            print(f"  {mod}: {len(evs)} sinyal", flush=True)

        others_by_module = {}
        for mod, evs in by_module.items():
            sorted_evs = sorted(evs, key=lambda e: e.trigger_idx)
            starts = [e.trigger_idx for e in sorted_evs]
            others_by_module[mod] = (starts, sorted_evs)

        buckets: dict[int, list[dict]] = {0: [], 1: [], 2: [], 3: []}
        all_events = [e for evs in by_module.values() for e in evs]
        for ev in all_events:
            cc = _confluence_count(ev, others_by_module)
            outcome = _simulate(candles, ev)
            if outcome is not None:
                buckets[cc].append(outcome)

        sym_result = {}
        print(f"  --- confluence bucket sonuclari ({symbol}) ---")
        for cc in [0, 1, 2, 3]:
            m = _metrics(buckets[cc])
            sym_result[str(cc)] = m
            print(f"  confluence={cc} (n_other_modules): n={m.get('n',0):5} "
                  f"win={m.get('win_rate',0):.1%} exp={m.get('expectancy_r',0):.3f} pf={m.get('profit_factor',0):.2f}", flush=True)
        results[symbol] = sym_result

    with open("confluence_study_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: confluence_study_results.json")

    print("\n=== HAVUZLANMIS (3 sembol) ===")
    for cc in [0, 1, 2, 3]:
        n = sum(results[s][str(cc)].get("n", 0) for s in KEPT_SYMBOLS)
        if n == 0:
            print(f"confluence={cc}  n=0")
            continue
        total_r = sum(results[s][str(cc)].get("total_r", 0) for s in KEPT_SYMBOLS)
        wins = sum(results[s][str(cc)].get("wins", 0) for s in KEPT_SYMBOLS)
        print(f"confluence={cc}  n={n:6} win={wins/n:.1%} exp={total_r/n:.3f}")


if __name__ == "__main__":
    main()
