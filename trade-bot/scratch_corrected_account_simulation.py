"""
PROTOTIP (scratch, kalici degil): "elimizdeki modulleri kullanarak
elimizdeki tum verilerle test et, kar/zarar gorelim" -- ama bu sefer
DUZELTILMIS (causal olarak dogru) motorla: strategy/signal_engine.py +
backtest/engine.py, yani 2026-09-02'deki kritik bulgunun (same-bar
impuls-dolumu + same-bar iyimser-TP) ARTIK ICERMEDIGI yol.

Bu, oturumun EN ILK isteginin ("GOLD'da 10.000 dolarlik hesap
simulasyonu") DOGRU/duzeltilmis versiyonu -- o zamanki sonuc ($25.4M
bilesik) optimist metodolojiyle hesaplanmisti, artik biliyoruz ki
guvenilir degildi. Bu script AYNI $10k/tek-pozisyon/bilesik+sabit-$
modelini kullanir ama ALTTAKI islem sonuclari artik dogru motordan
geliyor.

Kapsam: KEPT_SYMBOLS (GOLD, BTCUSD, EURGBP) -- projenin mevcut resmi
test kapsami (once 101 sembolden bu uce daraltildi, bkz.
strategy/config.py tarihcesi). Spread: temsili degerler (veri
kaynaginda gercek spread hic yok, bkz. onceki spread calismalarindaki
ayni gerekce).
"""

import json
from dataclasses import asdict

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, KEPT_SYMBOLS
from strategy.signal_engine import generate_signals, SetupType
from backtest.engine import run_backtest

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
STARTING_EQUITY = 10_000.0
RISK_PCT = 0.01


def simulate_account(candles, trades):
    """Tek-pozisyon modeli + bilesik %1 / sabit $ risk -- onceki hesap
    simulasyonlariyla AYNI mantik, ama girdi (trades) artik duzeltilmis motordan."""
    ordered = sorted(trades, key=lambda t: t.entry_fill_index if t.entry_fill_index is not None else t.entry_index)
    taken = []
    next_available = -1
    skipped_overlap = 0
    for t in ordered:
        fi = t.entry_fill_index if t.entry_fill_index is not None else t.entry_index
        if fi < next_available:
            skipped_overlap += 1
            continue
        taken.append(t)
        next_available = (t.exit_index if t.exit_index is not None else fi) + 1

    equity = STARTING_EQUITY
    peak = equity
    max_dd_dollar = 0.0
    max_dd_pct = 0.0
    fixed_equity = STARTING_EQUITY
    fixed_risk = STARTING_EQUITY * RISK_PCT
    fixed_peak = fixed_equity
    fixed_max_dd_dollar = 0.0
    fixed_max_dd_pct = 0.0

    module_pnl = {"FVG": 0.0, "iFVG": 0.0, "OB": 0.0, "Trendline": 0.0}
    module_n = {"FVG": 0, "iFVG": 0, "OB": 0, "Trendline": 0}
    module_wins = {"FVG": 0, "iFVG": 0, "OB": 0, "Trendline": 0}
    equity_curve = []
    fixed_curve = []
    wins = 0
    breakevens = 0

    for t in taken:
        r = t.r_multiple
        risk_amount = equity * RISK_PCT
        pnl = risk_amount * r
        equity += pnl
        peak = max(peak, equity)
        dd = peak - equity
        max_dd_dollar = max(max_dd_dollar, dd)
        max_dd_pct = max(max_dd_pct, (dd / peak) if peak > 0 else 0.0)

        fixed_equity += fixed_risk * r
        fixed_peak = max(fixed_peak, fixed_equity)
        fdd = fixed_peak - fixed_equity
        fixed_max_dd_dollar = max(fixed_max_dd_dollar, fdd)
        fixed_max_dd_pct = max(fixed_max_dd_pct, (fdd / fixed_peak) if fixed_peak > 0 else 0.0)

        m = t.signal.setup_type.value
        module_pnl[m] += pnl
        module_n[m] += 1
        if t.won:
            wins += 1
            module_wins[m] += 1
        if t.is_breakeven:
            breakevens += 1

        equity_curve.append(equity)
        fixed_curve.append(fixed_equity)

    n = len(taken)
    return {
        "n_candidate_trades": len(trades), "n_skipped_overlap": skipped_overlap, "n_taken": n,
        "win_rate": (wins / n) if n else 0.0, "breakeven_count": breakevens,
        "final_equity_compound": equity, "net_pnl_pct_compound": (equity - STARTING_EQUITY) / STARTING_EQUITY,
        "max_drawdown_pct_compound": max_dd_pct, "max_drawdown_dollar_compound": max_dd_dollar,
        "final_equity_fixed": fixed_equity, "net_pnl_pct_fixed": (fixed_equity - STARTING_EQUITY) / STARTING_EQUITY,
        "max_drawdown_pct_fixed": fixed_max_dd_pct,
        "module_summary": {
            m: {"n": module_n[m], "pnl": module_pnl[m], "win_rate": (module_wins[m] / module_n[m]) if module_n[m] else 0.0}
            for m in module_pnl
        },
        "equity_curve_compound": equity_curve, "equity_curve_fixed": fixed_curve,
    }


def main():
    results = {}
    for symbol in KEPT_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
        print(f"{len(candles)} M30 mumu, {candles[0]['time']} - {candles[-1]['time']}", flush=True)

        config = StrategyConfig(spread=SPREAD_BY_SYMBOL[symbol])
        signals = generate_signals(candles, config=config)
        print(f"sinyal: {len(signals)}", flush=True)
        result = run_backtest(candles, signals, config=config)
        print(f"islem (dolan): {len(result.trades)}, dolmayan: {result.unfilled_orders}", flush=True)

        acc = simulate_account(candles, result.trades)
        acc["symbol"] = symbol
        results[symbol] = acc
        print(f"  tek-pozisyon: alinan={acc['n_taken']}/{acc['n_candidate_trades']} win={acc['win_rate']:.1%} "
              f"be={acc['breakeven_count']}", flush=True)
        print(f"  bilesik: ${acc['final_equity_compound']:,.2f} ({acc['net_pnl_pct_compound']:+.1%}) "
              f"maxDD={acc['max_drawdown_pct_compound']:.1%}", flush=True)
        print(f"  sabit-$: ${acc['final_equity_fixed']:,.2f} ({acc['net_pnl_pct_fixed']:+.1%})", flush=True)
        for m, v in acc["module_summary"].items():
            print(f"    {m:10} n={v['n']:5} pnl=${v['pnl']:>12,.2f} win={v['win_rate']:.1%}", flush=True)

    with open("corrected_account_simulation_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: corrected_account_simulation_results.json")


if __name__ == "__main__":
    main()
