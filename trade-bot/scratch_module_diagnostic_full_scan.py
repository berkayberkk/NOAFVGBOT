"""
PROTOTIP (scratch, kalici degil): kullanicinin sorusuna cevap -- "win rate
neden dusuk, neden cok fazla SL var, neden RR dusuk, zarar yonetimi neden
yetersiz" -- KEPT_SYMBOLS'un (GOLD/BTCUSD/EURGBP) TUM gecmisinde, 4 modulun
(FVG/iFVG/OB/Trendline) HERBIRINI AYRI AYRI (saf/kisitsiz, Aday 6/7/8'in
kendi metodolojisiyle ayni) VE portfoy (tek-pozisyon havuzu, H1 walk-forward
bulgusunun kullandigi ayni `_combined_taken` mantigi) seviyesinde tarayip
somut sayilarla teshis eder.

Iki ayri soruyu ayirt eder:
1. MODUL-SEVIYESI: her modulun kendi R-katina gore GEREKEN basabas kazanma
   oranindan (1/(1+R)) ne kadar UZAK/YAKIN oldugu -- "dusuk win rate" R
   yeterince yuksekse sorun olmayabilir, asil soru expectancy'nin isaretidir.
2. PORTFOY-SEVIYESI: tek-pozisyon havuzunda hangi modulun "slotu" en cok
   isgal ettigi, hangi modulun sinyallerinin en cok REDDEDILDIGI (baska
   bir modul zaten pozisyondayken) -- H1 bulgusundaki "firsat maliyeti"
   mekanizmasinin modul-arasi versiyonu.

Ayrica her modul icin "SL'e ne kadar hizli gidiliyor" (bars-to-exit,
sadece kaybedenler) -- cok hizli/erken SL, "gurultu stopu" (SL cok dar/
entry cok agresif) isareti olabilir.
"""

import json
from collections import Counter, defaultdict

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from backtest.validation import calculate_metrics
from backtest.engine import run_backtest
from strategy.config import StrategyConfig, KEPT_SYMBOLS, MODULE_R_MULTIPLE
from strategy.signal_engine import generate_signals, SetupType

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}

MODULE_KEY_BY_SETUP = {
    SetupType.FVG_ONLY: "fvg",
    SetupType.IFVG_ONLY: "ifvg",
    SetupType.OB_ONLY: "ob",
    SetupType.TRENDLINE_ONLY: "trendline",
}


def load_symbol_m30(symbol: str) -> list[dict]:
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    return [candlev2_to_strategy_dict(c) for c in m30_v2]


def module_level_report(symbol: str, candles: list[dict], config: StrategyConfig, all_signals) -> dict:
    """Her modulu AYRI AYRI, kisitsiz (Aday 6/7/8 metodolojisiyle ayni) calistirir."""
    by_module = defaultdict(list)
    for s in all_signals:
        by_module[MODULE_KEY_BY_SETUP[s.setup_type]].append(s)

    out = {}
    for module_key, sigs in by_module.items():
        result = run_backtest(candles, sigs, config=config)
        m = calculate_metrics(result.trades, total_signals=len(sigs),
                              unfilled_orders=result.unfilled_orders, skipped_no_tp=result.skipped_no_tp)

        losses = [t for t in result.trades if not t.won]
        true_sl_losses = [t for t in losses if not t.is_breakeven]
        breakeven_exits = [t for t in losses if t.is_breakeven]
        wins = [t for t in result.trades if t.won]

        bars_to_sl = []
        for t in true_sl_losses:
            if t.entry_fill_index is not None and t.exit_index is not None:
                bars_to_sl.append(t.exit_index - t.entry_fill_index)
        avg_bars_to_sl = sum(bars_to_sl) / len(bars_to_sl) if bars_to_sl else None

        r_mult = MODULE_R_MULTIPLE[module_key]
        breakeven_wr_required = 1.0 / (1.0 + r_mult)

        out[module_key] = {
            "n_signals": len(sigs),
            "n_filled": m.filled_trades,
            "fill_rate": round(m.fill_rate, 3),
            "win_rate": round(m.win_rate, 4),
            "breakeven_wr_required": round(breakeven_wr_required, 4),
            "win_rate_vs_required": round(m.win_rate - breakeven_wr_required, 4),
            "expectancy_r": round(m.expectancy_r, 4),
            "profit_factor": round(m.profit_factor, 3) if m.profit_factor != float("inf") else None,
            "n_tp_wins": len(wins),
            "n_true_sl_losses": len(true_sl_losses),
            "n_breakeven_exits": len(breakeven_exits),
            "true_sl_loss_rate_of_filled": round(len(true_sl_losses) / m.filled_trades, 4) if m.filled_trades else None,
            "breakeven_rate_of_filled": round(len(breakeven_exits) / m.filled_trades, 4) if m.filled_trades else None,
            "avg_bars_to_sl_hit": round(avg_bars_to_sl, 1) if avg_bars_to_sl is not None else None,
            "r_multiple_target": r_mult,
        }
    return out


def portfolio_level_report(symbol: str, candles: list[dict], all_signals, config: StrategyConfig) -> dict:
    """Tek-pozisyon havuzu (H1 walk-forward'daki _combined_taken ayni mantik,
    ama burada H1 yok -- sadece 4 modulun M30'da BIRBIRIYLE rekabeti)."""
    result = run_backtest(candles, all_signals, config=config)
    trades_by_index = {id(t.signal): t for t in result.trades}

    records = []
    for s in all_signals:
        t = trades_by_index.get(id(s))
        if t is None or t.r_multiple is None:
            continue
        fi = t.entry_fill_index if t.entry_fill_index is not None else t.entry_index
        ei = t.exit_index if t.exit_index is not None else fi
        records.append({
            "module": MODULE_KEY_BY_SETUP[s.setup_type],
            "fill_time": candles[min(fi, len(candles) - 1)]["time"],
            "exit_time": candles[min(ei, len(candles) - 1)]["time"],
            "trade": t,
        })
    records.sort(key=lambda r: r["fill_time"])

    taken = []
    rejected_by_module = Counter()
    next_available = None
    for rec in records:
        if next_available is not None and rec["fill_time"] < next_available:
            rejected_by_module[rec["module"]] += 1
            continue
        taken.append(rec)
        next_available = rec["exit_time"]

    taken_by_module = Counter(r["module"] for r in taken)
    taken_trades = [r["trade"] for r in taken]
    m = calculate_metrics(taken_trades, total_signals=len(all_signals))

    return {
        "n_signals_total": len(all_signals),
        "n_taken_into_portfolio": len(taken),
        "taken_by_module": dict(taken_by_module),
        "rejected_by_module_due_to_slot_busy": dict(rejected_by_module),
        "portfolio_win_rate": round(m.win_rate, 4),
        "portfolio_expectancy_r": round(m.expectancy_r, 4),
        "portfolio_profit_factor": round(m.profit_factor, 3) if m.profit_factor != float("inf") else None,
        "portfolio_total_net_r": round(m.total_net_r, 2),
    }


def main():
    full_report = {}
    for symbol in KEPT_SYMBOLS:
        print(f"\n{'='*70}\n{symbol}\n{'='*70}", flush=True)
        candles = load_symbol_m30(symbol)
        config = StrategyConfig(spread=SPREAD_BY_SYMBOL[symbol])
        all_signals = generate_signals(candles, config=config)
        print(f"toplam mum: {len(candles)}, toplam sinyal: {len(all_signals)}", flush=True)

        mod_report = module_level_report(symbol, candles, config, all_signals)
        print(f"\n-- MODUL SEVIYESI (kisitsiz, saf) --")
        print(f"{'modul':10} {'n_sig':>6} {'n_fill':>6} {'fill%':>6} {'win%':>7} {'need_win%':>9} "
              f"{'exp_R':>8} {'PF':>6} {'true_SL%':>9} {'BE%':>6} {'bars->SL':>9}")
        for mod_key, r in mod_report.items():
            print(f"{mod_key:10} {r['n_signals']:>6} {r['n_filled']:>6} {r['fill_rate']*100:>5.1f}% "
                  f"{r['win_rate']*100:>6.1f}% {r['breakeven_wr_required']*100:>8.1f}% "
                  f"{r['expectancy_r']:>+8.4f} {str(r['profit_factor']):>6} "
                  f"{(r['true_sl_loss_rate_of_filled'] or 0)*100:>8.1f}% "
                  f"{(r['breakeven_rate_of_filled'] or 0)*100:>5.1f}% "
                  f"{str(r['avg_bars_to_sl_hit']):>9}")

        port_report = portfolio_level_report(symbol, candles, all_signals, config)
        print(f"\n-- PORTFOY SEVIYESI (tek-pozisyon havuzu, 4 modul birlikte) --")
        print(f"toplam sinyal={port_report['n_signals_total']} alinan={port_report['n_taken_into_portfolio']}")
        print(f"alinan (modul basina): {port_report['taken_by_module']}")
        print(f"reddedilen (slot mesgul, modul basina): {port_report['rejected_by_module_due_to_slot_busy']}")
        print(f"portfoy win_rate={port_report['portfolio_win_rate']*100:.1f}% "
              f"exp_R={port_report['portfolio_expectancy_r']:+.4f} "
              f"PF={port_report['portfolio_profit_factor']} "
              f"total_net_R={port_report['portfolio_total_net_r']}")

        full_report[symbol] = {"module_level": mod_report, "portfolio_level": port_report}

    with open("module_diagnostic_full_scan_results.json", "w") as f:
        json.dump(full_report, f, indent=2, default=str)
    print("\n\nyazildi: module_diagnostic_full_scan_results.json")


if __name__ == "__main__":
    main()
