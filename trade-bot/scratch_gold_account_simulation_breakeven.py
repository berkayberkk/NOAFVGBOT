"""
PROTOTIP (scratch, kalici degil): scratch_gold_account_simulation.py +
scratch_gold_account_equity.py'nin (ORIJINAL, breakeven-stop'suz "ilk
test") AYNI metodolojiyle ("$10.000 hesap, GOLD, 2020-2025, 4 modul,
tek-pozisyon, bilesik %1 + sabit $ risk modelleri") ama GUNCEL resmi
metodolojiyle (breakeven-stop ACIK, esik = strategy/config.py:
BREAKEVEN_TRIGGER_PCT = 0.5) TEKRARLANMIS hali -- "ilk test" ile
DOGRUDAN karsilastirilabilir bir "yeni test" sonucu uretmek icin.

Olay/simulasyon fonksiyonlari scratch_trade_archive.py'den (95-sembol
arsivi icin yazilan, guncel resmi metodolojiyi -- config'ten okunan
BREAKEVEN_TRIGGER_PCT/BREAKEVEN_ENABLED_MODULES dahil -- iceren) AYNEN
tekrar kullaniliyor, kod tekrari yok.
"""

import json
import datetime

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from scratch_trade_archive import _fvg_events, _ifvg_events, _ob_events, _trendline_events, _simulate

SYMBOL = "GOLD"
START_DATE = "2020-01-01"
END_DATE = "2026-01-01"
STARTING_EQUITY = 10_000.0
RISK_PCT = 0.01
OUT_PATH = "gold_account_report_data_breakeven50.json"


def main():
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{SYMBOL}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
    print(f"toplam {len(candles)} M30 mumu, {candles[0]['time']} - {candles[-1]['time']}", flush=True)

    all_events = []
    all_events += [("fvg", e) for e in _fvg_events(candles)]
    all_events += [("ifvg", e) for e in _ifvg_events(candles)]
    all_events += [("ob", e) for e in _ob_events(candles)]
    all_events += [("trendline", e) for e in _trendline_events(candles)]
    print(f"toplam aday sinyal: {len(all_events)}", flush=True)

    start_dt = datetime.datetime.fromisoformat(START_DATE)
    end_dt = datetime.datetime.fromisoformat(END_DATE)

    resolved = []
    for mod_name, ev in all_events:
        res = _simulate(candles, ev)
        if res is None:
            continue
        fill_idx, exit_idx, won, r_mult = res
        if not (start_dt <= candles[fill_idx]["time"] < end_dt):
            continue
        resolved.append({
            "module": mod_name, "is_bull": ev.is_bull,
            "fill_index": fill_idx, "exit_index": exit_idx,
            "entry": ev.entry, "stop_loss": ev.stop_loss, "take_profit": ev.take_profit,
            "won": won, "r_multiple": r_mult,
            "fill_time": candles[fill_idx]["time"].isoformat(),
            "exit_time": candles[exit_idx]["time"].isoformat(),
        })
    resolved.sort(key=lambda t: t["fill_index"])
    print(f"{START_DATE} - {END_DATE} arasinda cozulmus (sonuclanmis) aday: {len(resolved)}", flush=True)

    # Tek-pozisyon modeli -- ilk test ile AYNI kural.
    trades = []
    next_available_index = -1
    skipped_overlap = 0
    for t in resolved:
        if t["fill_index"] < next_available_index:
            skipped_overlap += 1
            continue
        trades.append(t)
        next_available_index = t["exit_index"] + 1
    print(f"aday: {len(resolved)}, cakisma nedeniyle atlanan: {skipped_overlap}, "
          f"gercekten alinan (tek-pozisyon modeli): {len(trades)}", flush=True)

    equity = STARTING_EQUITY
    peak = equity
    max_dd_pct = 0.0
    max_dd_dollar = 0.0
    equity_curve = [{"t": trades[0]["fill_time"] if trades else START_DATE, "equity": equity}]

    fixed_equity = STARTING_EQUITY
    fixed_risk_amount = STARTING_EQUITY * RISK_PCT
    fixed_curve = [{"t": trades[0]["fill_time"] if trades else START_DATE, "equity": fixed_equity}]
    fixed_peak = fixed_equity
    fixed_max_dd_dollar = 0.0
    fixed_max_dd_pct = 0.0

    module_pnl = {"fvg": 0.0, "ifvg": 0.0, "ob": 0.0, "trendline": 0.0}
    module_n = {"fvg": 0, "ifvg": 0, "ob": 0, "trendline": 0}
    module_wins = {"fvg": 0, "ifvg": 0, "ob": 0, "trendline": 0}
    breakeven_count = 0

    enriched = []
    for t in trades:
        risk_amount = equity * RISK_PCT
        pnl = risk_amount * t["r_multiple"]
        equity_before = equity
        equity += pnl
        peak = max(peak, equity)
        dd_dollar = peak - equity
        max_dd_dollar = max(max_dd_dollar, dd_dollar)
        max_dd_pct = max(max_dd_pct, (dd_dollar / peak) if peak > 0 else 0.0)

        fixed_equity += fixed_risk_amount * t["r_multiple"]
        fixed_peak = max(fixed_peak, fixed_equity)
        fdd = fixed_peak - fixed_equity
        fixed_max_dd_dollar = max(fixed_max_dd_dollar, fdd)
        fixed_max_dd_pct = max(fixed_max_dd_pct, (fdd / fixed_peak) if fixed_peak > 0 else 0.0)

        module_pnl[t["module"]] += pnl
        module_n[t["module"]] += 1
        if t["won"]:
            module_wins[t["module"]] += 1
        if (not t["won"]) and t["r_multiple"] == 0.0:
            breakeven_count += 1

        rec = dict(t)
        rec["risk_amount"] = risk_amount
        rec["pnl"] = pnl
        rec["equity_before"] = equity_before
        rec["equity_after"] = equity
        enriched.append(rec)
        equity_curve.append({"t": t["exit_time"], "equity": equity})
        fixed_curve.append({"t": t["exit_time"], "equity": fixed_equity})

    final_equity = equity
    net_pnl = final_equity - STARTING_EQUITY
    net_pnl_pct = net_pnl / STARTING_EQUITY
    fixed_final_equity = fixed_equity
    fixed_net_pnl_pct = (fixed_final_equity - STARTING_EQUITY) / STARTING_EQUITY

    wins = [t for t in enriched if t["won"]]
    win_rate = len(wins) / len(enriched) if enriched else 0.0

    top_winners = sorted(enriched, key=lambda t: -t["pnl"])[:10]
    top_losers = sorted(enriched, key=lambda t: t["pnl"])[:10]

    module_summary = {}
    for m in module_pnl:
        n = module_n[m]
        module_summary[m] = {
            "n": n, "pnl": module_pnl[m],
            "win_rate": (module_wins[m] / n) if n else 0.0,
            "pct_of_net": (module_pnl[m] / net_pnl * 100) if net_pnl != 0 else 0.0,
        }

    out = {
        "symbol": SYMBOL, "start_date": START_DATE, "end_date": END_DATE,
        "breakeven_trigger_pct": 0.5,
        "n_candidate_trades": len(resolved), "n_skipped_overlap": skipped_overlap,
        "starting_equity": STARTING_EQUITY, "risk_pct": RISK_PCT,
        "final_equity": final_equity, "net_pnl": net_pnl, "net_pnl_pct": net_pnl_pct,
        "max_drawdown_pct": max_dd_pct, "max_drawdown_dollar": max_dd_dollar,
        "fixed_final_equity": fixed_final_equity, "fixed_net_pnl_pct": fixed_net_pnl_pct,
        "fixed_risk_amount": fixed_risk_amount,
        "fixed_max_drawdown_dollar": fixed_max_dd_dollar, "fixed_max_drawdown_pct": fixed_max_dd_pct,
        "total_trades": len(enriched), "win_rate": win_rate, "breakeven_count": breakeven_count,
        "module_summary": module_summary,
        "equity_curve": equity_curve,
        "fixed_equity_curve": fixed_curve,
        "top_winners": top_winners,
        "top_losers": top_losers,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f)
    print(f"yazildi: {OUT_PATH}")

    print(f"\nBaslangic: ${STARTING_EQUITY:,.2f}")
    print(f"Bitis (bileşik %1):     ${final_equity:,.2f}  ({net_pnl_pct:+.1%})")
    print(f"Bitis (sabit ${fixed_risk_amount:,.0f}/islem): ${fixed_final_equity:,.2f}  ({fixed_net_pnl_pct:+.1%})")
    print(f"Max DD (bileşik):    ${max_dd_dollar:,.2f} ({max_dd_pct:.1%})")
    print(f"Toplam islem: {len(enriched)}, kazanma orani: {win_rate:.1%}, breakeven: {breakeven_count}")
    print("\nModul bazinda:")
    for m, v in module_summary.items():
        print(f"  {m:10} n={v['n']:5} pnl=${v['pnl']:>12,.2f} win={v['win_rate']:.1%} (net'in %{v['pct_of_net']:.1f}'i)")


if __name__ == "__main__":
    main()
