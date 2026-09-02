"""
PROTOTIP (scratch, kalici degil): "TP'ye giderken %60'ini kat ettiyse SL'i
girise cek (breakeven), islem donerse zarar etmeyelim" -- FVG, iFVG, Order
Block icin BASELINE (mevcut sabit-SL) ile BREAKEVEN-STOP varyantini
KARSILASTIRIR. Kapsam: strategy/config.py:KEPT_SYMBOLS (GOLD, BTCUSD,
EURGBP), M30, her modulun kendi resmi R/SL parametreleri.

BREAKEVEN MANTIGI (causal, ayni-bar belirsizligini onlemek icin
muhafazakar sirayla):
  Her barda ONCE mevcut (henuz o barin hareketinden ETKILENMEMIS,
  onceki bardan kalma) efektif SL kontrol edilir -- vurulduysa cikis.
  SONRA TP kontrol edilir -- vurulduysa kazanc. SONRA (bu iki cikis da
  olmadiysa) bu barin HIGH'i (bull icin) "%60 esigini" gectiyse SL bir
  SONRAKI bardan itibaren girise (entry) cekilir -- yani bu barin
  KENDI SL kontrolu hala ESKI SL ile yapildi (geriye donuk/lookahead
  degil).
  Boylece SL'e "girise cekildikten sonra" takilan islemler -1R yerine
  0R (breakeven) sayilir -- ne kazanc ne zarar.
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
BREAKEVEN_TRIGGER_PCT = 0.6  # TP mesafesinin bu orani kat edilince SL girise cekilir
CONFIG = StrategyConfig()


@dataclass
class TradeOutcome:
    result: str  # "win" | "loss" | "breakeven"
    r_multiple: float


def _simulate(candles, start_idx, is_bull, entry, sl, tp, r_multiple, use_breakeven: bool) -> TradeOutcome | None:
    end = min(len(candles), start_idx + MAX_WAIT_BARS)
    fill_index = None
    for i in range(start_idx, end):
        c = candles[i]
        if (is_bull and c["low"] <= entry) or (not is_bull and c["high"] >= entry):
            fill_index = i
            break
    if fill_index is None:
        return None

    arm_level = entry + BREAKEVEN_TRIGGER_PCT * (tp - entry) if is_bull else entry - BREAKEVEN_TRIGGER_PCT * (entry - tp)
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

        if use_breakeven and not armed:
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


def main():
    results = {}
    for symbol in KEPT_SYMBOLS:
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
        print(f"{symbol}: {len(candles)} M30 mumu", flush=True)

        for mod_name, events_fn in [("fvg", _fvg_events), ("ifvg", _ifvg_events), ("ob", _ob_events)]:
            events = events_fn(candles)
            baseline_outcomes = []
            breakeven_outcomes = []
            for start_idx, is_bull, entry, sl, tp, r_mult in events:
                o1 = _simulate(candles, start_idx, is_bull, entry, sl, tp, r_mult, use_breakeven=False)
                if o1 is not None:
                    baseline_outcomes.append(o1)
                o2 = _simulate(candles, start_idx, is_bull, entry, sl, tp, r_mult, use_breakeven=True)
                if o2 is not None:
                    breakeven_outcomes.append(o2)

            key = f"{symbol}_{mod_name}"
            results[key] = {
                "symbol": symbol, "module": mod_name,
                "n_events": len(events),
                "baseline": _metrics(baseline_outcomes),
                "breakeven": _metrics(breakeven_outcomes),
            }
            b = results[key]["baseline"]
            e = results[key]["breakeven"]
            print(f"  {mod_name:10} baseline: n={b.get('n',0):5} win={b.get('win_rate',0):.1%} exp={b.get('expectancy_r',0):.3f} pf={b.get('profit_factor',0):.2f}"
                  f"   |  breakeven: n={e.get('n',0):5} win={e.get('win_rate',0):.1%} be={e.get('breakeven_rate',0):.1%} exp={e.get('expectancy_r',0):.3f} pf={e.get('profit_factor',0):.2f}",
                  flush=True)

    with open("breakeven_sl_study_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nyazildi: breakeven_sl_study_results.json")

    # havuzlanmis (3 sembol) modul bazinda ozet
    print("\n=== HAVUZLANMIS (3 sembol) ===")
    for mod_name in ["fvg", "ifvg", "ob"]:
        base_all = []
        be_all = []
        for symbol in KEPT_SYMBOLS:
            r = results[f"{symbol}_{mod_name}"]
            base_all.append(r["baseline"])
            be_all.append(r["breakeven"])

        def pool(metrics_list):
            n = sum(m.get("n", 0) for m in metrics_list)
            if n == 0:
                return {"n": 0}
            total_r = sum(m.get("total_r", 0) for m in metrics_list)
            wins = sum(m.get("wins", 0) for m in metrics_list)
            return {"n": n, "win_rate": wins / n, "expectancy_r": total_r / n}

        pb = pool(base_all)
        pe = pool(be_all)
        print(f"{mod_name:10} baseline: n={pb.get('n',0)} win={pb.get('win_rate',0):.1%} exp={pb.get('expectancy_r',0):.3f}"
              f"   |  breakeven: n={pe.get('n',0)} win={pe.get('win_rate',0):.1%} exp={pe.get('expectancy_r',0):.3f}")


if __name__ == "__main__":
    main()
