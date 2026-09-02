"""
PROTOTIP (scratch, kalici degil): gold_account_simulation_trades.json'daki
kronolojik islem listesini, $10,000 baslangicli, islem basina bakiyenin
%1'ini riske eden bir hesaba uygulayip equity egrisi + max drawdown +
en karli/en zararli islemler cikartir. Rapor artifact'i icin veri
hazirlar.

KRITIK metodoloji karari: 4 modulun BAGIMSIZ tespit ettigi 10.890 aday
islem, GERCEK bir hesapta AYNI ANDA acik olamaz (tek trader, tek hesap,
sinirsiz eszamanli pozisyon+bilesik risk varsayimi ilk denemede
$10^21 gibi anlamsiz bir sonuc verdi -- bu YONTEMSEL bir hata, gercek
bir edge degil). Bunun yerine GERCEKCI tek-pozisyon modeli kullanilir:
bir islem ACIKKEN (fill'den exit'e kadar), o pencerede tetiklenen BASKA
HICBIR modulun sinyali ALINMAZ -- ilk ates eden modul kazanir, pozisyon
kapanana kadar diger sinyaller atlanir (greedy, kronolojik, hangfi modul
once tetiklerse o alinir).
"""

import json

IN_PATH = "gold_account_simulation_trades.json"
OUT_PATH = "gold_account_equity_data.json"


def main():
    d = json.load(open(IN_PATH))
    all_candidates = sorted(d["trades"], key=lambda t: t["fill_index"])

    trades = []
    next_available_index = -1
    skipped_overlap = 0
    for t in all_candidates:
        if t["fill_index"] < next_available_index:
            skipped_overlap += 1
            continue
        trades.append(t)
        next_available_index = t["exit_index"] + 1
    print(f"aday islem: {len(all_candidates)}, cakisma nedeniyle atlanan: {skipped_overlap}, "
          f"gercekten alinan (tek-pozisyon modeli): {len(trades)}")

    equity = d["starting_equity"]
    risk_pct = d["risk_pct"]

    peak = equity
    max_dd_pct = 0.0
    max_dd_dollar = 0.0
    equity_curve = [{"t": trades[0]["fill_time"] if trades else d["start_date"], "equity": equity}]

    # ikinci, daha muhafazakar seri: SABIT dolar riski (her islemde HEP
    # baslangic bakiyesinin %1'i = $100, bilesik degil) -- bilesik riskin
    # ($10k'dan yuz milyonlara/trilyonlara ulasan matematiksel ama
    # gercekci-olmayan buyumesine karsi daha sindirilebilir bir referans.
    fixed_equity = d["starting_equity"]
    fixed_risk_amount = d["starting_equity"] * risk_pct
    fixed_curve = [{"t": trades[0]["fill_time"] if trades else d["start_date"], "equity": fixed_equity}]
    fixed_peak = fixed_equity
    fixed_max_dd_dollar = 0.0
    fixed_max_dd_pct = 0.0

    module_pnl = {"fvg": 0.0, "ifvg": 0.0, "ob": 0.0, "trendline": 0.0}
    module_n = {"fvg": 0, "ifvg": 0, "ob": 0, "trendline": 0}
    module_wins = {"fvg": 0, "ifvg": 0, "ob": 0, "trendline": 0}

    enriched = []
    for t in trades:
        risk_amount = equity * risk_pct
        pnl = risk_amount * t["r_multiple"]
        equity_before = equity
        equity += pnl
        peak = max(peak, equity)
        dd_dollar = peak - equity
        dd_pct = dd_dollar / peak if peak > 0 else 0.0
        max_dd_dollar = max(max_dd_dollar, dd_dollar)
        max_dd_pct = max(max_dd_pct, dd_pct)

        fixed_equity += fixed_risk_amount * t["r_multiple"]
        fixed_peak = max(fixed_peak, fixed_equity)
        fixed_dd_dollar = fixed_peak - fixed_equity
        fixed_max_dd_dollar = max(fixed_max_dd_dollar, fixed_dd_dollar)
        fixed_max_dd_pct = max(fixed_max_dd_pct, (fixed_dd_dollar / fixed_peak) if fixed_peak > 0 else 0.0)

        module_pnl[t["module"]] += pnl
        module_n[t["module"]] += 1
        if t["won"]:
            module_wins[t["module"]] += 1

        rec = dict(t)
        rec["risk_amount"] = risk_amount
        rec["pnl"] = pnl
        rec["equity_before"] = equity_before
        rec["equity_after"] = equity
        enriched.append(rec)
        equity_curve.append({"t": t["exit_time"], "equity": equity})
        fixed_curve.append({"t": t["exit_time"], "equity": fixed_equity})

    final_equity = equity
    net_pnl = final_equity - d["starting_equity"]
    net_pnl_pct = net_pnl / d["starting_equity"]
    fixed_final_equity = fixed_equity
    fixed_net_pnl = fixed_final_equity - d["starting_equity"]
    fixed_net_pnl_pct = fixed_net_pnl / d["starting_equity"]

    wins = [t for t in enriched if t["won"]]
    losses = [t for t in enriched if not t["won"]]
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
        "symbol": d["symbol"], "start_date": d["start_date"], "end_date": d["end_date"],
        "n_candidate_trades": len(all_candidates), "n_skipped_overlap": skipped_overlap,
        "starting_equity": d["starting_equity"], "risk_pct": risk_pct,
        "final_equity": final_equity, "net_pnl": net_pnl, "net_pnl_pct": net_pnl_pct,
        "max_drawdown_pct": max_dd_pct, "max_drawdown_dollar": max_dd_dollar,
        "fixed_final_equity": fixed_final_equity, "fixed_net_pnl": fixed_net_pnl, "fixed_net_pnl_pct": fixed_net_pnl_pct,
        "fixed_risk_amount": fixed_risk_amount,
        "fixed_max_drawdown_dollar": fixed_max_dd_dollar, "fixed_max_drawdown_pct": fixed_max_dd_pct,
        "total_trades": len(enriched), "win_rate": win_rate,
        "module_summary": module_summary,
        "equity_curve": equity_curve,
        "fixed_equity_curve": fixed_curve,
        "top_winners": top_winners,
        "top_losers": top_losers,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f)

    print(f"Baslangic: ${d['starting_equity']:,.2f}")
    print(f"Bitis (bileşik %1):     ${final_equity:,.2f}  ({net_pnl_pct:+.1%})")
    print(f"Bitis (sabit ${fixed_risk_amount:,.0f}/islem): ${fixed_final_equity:,.2f}  ({fixed_net_pnl_pct:+.1%})")
    print(f"Max DD (bileşik):    ${max_dd_dollar:,.2f} ({max_dd_pct:.1%})")
    print(f"Toplam islem: {len(enriched)}, kazanma orani: {win_rate:.1%}")
    print("\nModul bazinda:")
    for m, v in module_summary.items():
        print(f"  {m:10} n={v['n']:5} pnl=${v['pnl']:>12,.2f} win={v['win_rate']:.1%} (net'in %{v['pct_of_net']:.1f}'i)")


if __name__ == "__main__":
    main()
