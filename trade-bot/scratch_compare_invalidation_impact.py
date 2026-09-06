import json

old = json.load(open("module_diagnostic_full_scan_results.PRE_INVALIDATION_BACKUP_2026-09-06.json"))
new = json.load(open("module_diagnostic_full_scan_results.json"))

for sym in ["GOLD", "BTCUSD", "EURGBP"]:
    o = old[sym]["portfolio_level"]
    n = new[sym]["portfolio_level"]
    print(f"=== {sym} (portfoy) ===")
    print(f"  ONCE : n={o['n_taken_into_portfolio']:>4} win={o['portfolio_win_rate']*100:5.1f}% exp={o['portfolio_expectancy_r']:+.4f} total_R={o['portfolio_expectancy_r']*o['n_taken_into_portfolio']:+.2f} PF={o['portfolio_profit_factor']}")
    print(f"  SONRA: n={n['n_taken_into_portfolio']:>4} win={n['portfolio_win_rate']*100:5.1f}% exp={n['portfolio_expectancy_r']:+.4f} total_R={n['portfolio_expectancy_r']*n['n_taken_into_portfolio']:+.2f} PF={n['portfolio_profit_factor']}")
    print()
    for mod in ["fvg", "ifvg", "ob", "trendline"]:
        om = old[sym]["module_level"].get(mod)
        nm = new[sym]["module_level"].get(mod)
        if not om or not nm:
            continue
        print(f"  {mod:10} ONCE : n_sig={om['n_signals']:>5} n_fill={om['n_filled']:>5} win={om['win_rate']*100:5.1f}% exp={om['expectancy_r']:+.4f}")
        print(f"  {mod:10} SONRA: n_sig={nm['n_signals']:>5} n_fill={nm['n_filled']:>5} win={nm['win_rate']*100:5.1f}% exp={nm['expectancy_r']:+.4f}")
    print()
