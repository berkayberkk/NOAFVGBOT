"""
PROTOTIP (scratch, kalici degil): mevcut resmi breakeven-stop esigi
%60'tir (strategy/config.py:BREAKEVEN_TRIGGER_PCT, bkz.
scratch_breakeven_sl_study.py). Kullanici sordu: "yolun YARISINI (%50)
kat ettiyse SL girise cekilirse win rate/kar nasil etkilenir?" -- bu
script tek bir esigi degil, BIRDEN FAZLA esigi (%30/%40/%50/%60/%70/%80)
+ baseline'i (BE yok) ayni pooled tabloda karsilastirir, boylece sadece
"%50 nasil" degil "hangi esik optimal" sorusuna da cevap verir.

Kapsam: strategy/config.py:KEPT_SYMBOLS (GOLD, BTCUSD, EURGBP), M30,
FVG/iFVG/Order Block (Trendline BREAKEVEN_ENABLED_MODULES'ta yok --
orijinal breakeven calismasindaki ayni kapsam, karsilastirilabilirlik
icin korundu).

BREAKEVEN MANTIGI (causal, scratch_breakeven_sl_study.py ile birebir
ayni sira): ONCE eski efektif SL kontrol edilir, SONRA TP, SONRA (ikisi
de olmadiysa) bu barin favorable hareketi esigi gectiyse SL bir SONRAKI
bardan itibaren girise cekilir.
"""

import json
from dataclasses import dataclass

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO, KEPT_SYMBOLS
from strategy.fvg import detect_fvgs, FVGDirection
from strategy.order_block import detect_order_blocks, OBDirection
from scratch_ifvg_tp_sl_study import detect_confirmed_ifvgs

MAX_WAIT_BARS = 3000
TRIGGER_PCTS = [None, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3]  # None = baseline (BE yok) -- ince tarama, ilk turda (0.3-0.8) tepe bulunamadi, asagi devam
OUTPUT_PATH = "breakeven_trigger_sweep_fine_results.json"
CONFIG = StrategyConfig()


@dataclass
class TradeOutcome:
    result: str  # "win" | "loss" | "breakeven"
    r_multiple: float


def _simulate(candles, start_idx, is_bull, entry, sl, tp, r_multiple, trigger_pct: float | None) -> TradeOutcome | None:
    end = min(len(candles), start_idx + MAX_WAIT_BARS)
    fill_index = None
    for i in range(start_idx, end):
        c = candles[i]
        if (is_bull and c["low"] <= entry) or (not is_bull and c["high"] >= entry):
            fill_index = i
            break
    if fill_index is None:
        return None

    use_be = trigger_pct is not None
    if use_be:
        arm_level = entry + trigger_pct * (tp - entry) if is_bull else entry - trigger_pct * (entry - tp)
    effective_sl = sl
    armed = False

    scan_end = min(len(candles), fill_index + MAX_WAIT_BARS)
    for i in range(fill_index, scan_end):
        c = candles[i]
        if is_bull:
            hit_sl = c["low"] <= effective_sl
            hit_tp = c["high"] >= tp
        else:
            hit_sl = c["high"] >= effective_sl
            hit_tp = c["low"] <= tp

        if hit_sl:
            if armed:
                return TradeOutcome(result="breakeven", r_multiple=0.0)
            return TradeOutcome(result="loss", r_multiple=-1.0)
        if hit_tp:
            return TradeOutcome(result="win", r_multiple=r_multiple)

        if use_be and not armed:
            reached_arm = (c["high"] >= arm_level) if is_bull else (c["low"] <= arm_level)
            if reached_arm:
                armed = True
                effective_sl = entry
    return None


def _fvg_events(candles):
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
        out.append((f.end_index + 1, is_bull, entry, sl, tp, r_mult))
    return out


def _ifvg_events(candles):
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
        out.append((e["retest_idx"], is_bull, entry, sl, tp, r_mult))
    return out


def _ob_events(candles):
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
        out.append((ob.impulse_index, is_bull, entry, sl, tp, r_mult))
    return out


def _metrics(outcomes: list[TradeOutcome]) -> dict:
    if not outcomes:
        return {"n": 0}
    wins = [o for o in outcomes if o.result == "win"]
    losses = [o for o in outcomes if o.result == "loss"]
    breakevens = [o for o in outcomes if o.result == "breakeven"]
    n = len(outcomes)
    total_r = sum(o.r_multiple for o in outcomes)
    gross_profit = sum(o.r_multiple for o in wins)
    gross_loss = abs(sum(o.r_multiple for o in losses))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    return {
        "n": n, "wins": len(wins), "losses": len(losses), "breakevens": len(breakevens),
        "win_rate": len(wins) / n, "loss_rate": len(losses) / n, "breakeven_rate": len(breakevens) / n,
        "expectancy_r": total_r / n, "profit_factor": min(pf, 999.0), "total_r": total_r,
    }


def _label(pct):
    return "baseline" if pct is None else f"trigger_{int(pct*100)}pct"


def main():
    results = {}
    for symbol in KEPT_SYMBOLS:
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
        print(f"{symbol}: {len(candles)} M30 mumu", flush=True)

        by_module_events = {
            "fvg": _fvg_events(candles), "ifvg": _ifvg_events(candles), "ob": _ob_events(candles),
        }

        sym_result = {}
        for mod_name, events in by_module_events.items():
            mod_result = {}
            for pct in TRIGGER_PCTS:
                outcomes = []
                for start_idx, is_bull, entry, sl, tp, r_mult in events:
                    o = _simulate(candles, start_idx, is_bull, entry, sl, tp, r_mult, pct)
                    if o is not None:
                        outcomes.append(o)
                mod_result[_label(pct)] = _metrics(outcomes)
            sym_result[mod_name] = mod_result
            print(f"  {mod_name:6} " + " | ".join(
                f"{_label(p)}: win={mod_result[_label(p)].get('win_rate',0):.1%} exp={mod_result[_label(p)].get('expectancy_r',0):.3f}"
                for p in TRIGGER_PCTS
            ), flush=True)
        results[symbol] = sym_result

    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nyazildi: {OUTPUT_PATH}")

    print("\n=== HAVUZLANMIS (3 sembol, tum modüller birlikte) ===")
    for pct in TRIGGER_PCTS:
        label = _label(pct)
        n = sum(results[s][m][label].get("n", 0) for s in KEPT_SYMBOLS for m in ["fvg", "ifvg", "ob"])
        if n == 0:
            print(f"{label:14} n=0")
            continue
        total_r = sum(results[s][m][label].get("total_r", 0) for s in KEPT_SYMBOLS for m in ["fvg", "ifvg", "ob"])
        wins = sum(results[s][m][label].get("wins", 0) for s in KEPT_SYMBOLS for m in ["fvg", "ifvg", "ob"])
        breakevens = sum(results[s][m][label].get("breakevens", 0) for s in KEPT_SYMBOLS for m in ["fvg", "ifvg", "ob"])
        print(f"{label:14} n={n:6} win={wins/n:.1%} be={breakevens/n:.1%} exp={total_r/n:.3f}")

    print("\n=== MODUL BAZINDA HAVUZLANMIS ===")
    for m in ["fvg", "ifvg", "ob"]:
        print(f"-- {m} --")
        for pct in TRIGGER_PCTS:
            label = _label(pct)
            n = sum(results[s][m][label].get("n", 0) for s in KEPT_SYMBOLS)
            if n == 0:
                print(f"  {label:14} n=0")
                continue
            total_r = sum(results[s][m][label].get("total_r", 0) for s in KEPT_SYMBOLS)
            wins = sum(results[s][m][label].get("wins", 0) for s in KEPT_SYMBOLS)
            print(f"  {label:14} n={n:6} win={wins/n:.1%} exp={total_r/n:.3f}")


if __name__ == "__main__":
    main()
