"""
PROTOTIP (scratch, kalici degil): "OB, tek-pozisyon portfoy slotunu en sik +
en zayif modul olarak domine ediyor, en iyi modulu (FVG) ac birakiyor"
bulgusunu (module_diagnostic_full_scan/universe_scan) somut bir karsi-ornekle
test eder -- AYNI sinyaller, AYNI backtest motoru, SADECE portfoy
kurgusu degisiyor:

  A) MEVCUT: 4 modul (FVG+iFVG+OB+Trendline) TEK ortak slotu paylasiyor.
  B) OB HARIC: sadece FVG+iFVG+Trendline ortak slotu paylasiyor (OB'nin
     sinyalleri havuza hic girmiyor).
  C) OB AYRI SLOT: FVG+iFVG+Trendline kendi ortak slotunu paylasiyor, OB
     kendi BAGIMSIZ ikinci bir slotta (ayni anda iki pozisyon olabilir --
     biri "non-OB" havuzundan, biri OB'den). Toplam sonuc = iki havuzun
     toplami.

Eger B veya C, A'dan belirgin sekilde iyiyse, bu OB'nin GERCEKTEN
portfoyu bogdugunu (formul/kalite sorunu degil, KAYNAK PAYLASIMI sorunu
oldugunu) dogrular -- somut bir duzeltme onerisi (OB'ye ayri slot vermek)
icin sayisal gerekce olur.
"""

import json
from collections import Counter

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from backtest.validation import calculate_metrics
from backtest.engine import run_backtest
from strategy.config import StrategyConfig, KEPT_SYMBOLS
from strategy.signal_engine import generate_signals, SetupType

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
MODULE_KEY_BY_SETUP = {
    SetupType.FVG_ONLY: "fvg", SetupType.IFVG_ONLY: "ifvg",
    SetupType.OB_ONLY: "ob", SetupType.TRENDLINE_ONLY: "trendline",
}


def load_symbol_m30(symbol: str) -> list[dict]:
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    return [candlev2_to_strategy_dict(c) for c in m30_v2]


def pool_result(candles: list[dict], signals: list, config: StrategyConfig) -> dict:
    """Tek-pozisyon havuzu simulasyonu -- module_diagnostic_full_scan.py:portfolio_level_report
    ile AYNI mantik (ilk dolan sinyal slotu alir, cikana kadar baskasi giremez)."""
    if not signals:
        return {"n_taken": 0, "win_rate": 0.0, "expectancy_r": 0.0, "profit_factor": None, "total_net_r": 0.0,
                "taken_by_module": {}}

    result = run_backtest(candles, signals, config=config)
    trades_by_id = {id(t.signal): t for t in result.trades}

    records = []
    for s in signals:
        t = trades_by_id.get(id(s))
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
    next_available = None
    for rec in records:
        if next_available is not None and rec["fill_time"] < next_available:
            continue
        taken.append(rec)
        next_available = rec["exit_time"]

    taken_trades = [r["trade"] for r in taken]
    m = calculate_metrics(taken_trades, total_signals=len(signals))
    return {
        "n_taken": len(taken),
        "win_rate": round(m.win_rate, 4),
        "expectancy_r": round(m.expectancy_r, 4),
        "profit_factor": round(m.profit_factor, 3) if m.profit_factor != float("inf") else None,
        "total_net_r": round(m.total_net_r, 2),
        "taken_by_module": dict(Counter(r["module"] for r in taken)),
    }


def combine_two_pools(pool_a: dict, pool_b: dict) -> dict:
    """Iki BAGIMSIZ (paralel) havuzun toplam sonucunu hesaplar -- basit
    toplama (n_taken, total_net_r) + agirlikli ortalama (win_rate)."""
    n = pool_a["n_taken"] + pool_b["n_taken"]
    total_r = pool_a["total_net_r"] + pool_b["total_net_r"]
    win_rate = (
        (pool_a["win_rate"] * pool_a["n_taken"] + pool_b["win_rate"] * pool_b["n_taken"]) / n
        if n else 0.0
    )
    return {
        "n_taken": n,
        "win_rate": round(win_rate, 4),
        "expectancy_r": round(total_r / n, 4) if n else 0.0,
        "total_net_r": round(total_r, 2),
    }


def main():
    results = {}
    for symbol in KEPT_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        candles = load_symbol_m30(symbol)
        config = StrategyConfig(spread=SPREAD_BY_SYMBOL[symbol])
        all_signals = generate_signals(candles, config=config)

        ob_signals = [s for s in all_signals if MODULE_KEY_BY_SETUP[s.setup_type] == "ob"]
        non_ob_signals = [s for s in all_signals if MODULE_KEY_BY_SETUP[s.setup_type] != "ob"]

        A_current = pool_result(candles, all_signals, config)
        B_no_ob = pool_result(candles, non_ob_signals, config)
        ob_alone = pool_result(candles, ob_signals, config)
        C_separate = combine_two_pools(B_no_ob, ob_alone)

        print(f"  A) MEVCUT (4 modul birlikte):     n={A_current['n_taken']:4} win={A_current['win_rate']*100:5.1f}% "
              f"exp={A_current['expectancy_r']:+.4f} total_R={A_current['total_net_r']:+.2f} "
              f"dagilim={A_current['taken_by_module']}", flush=True)
        print(f"  B) OB HARIC (sadece FVG+iFVG+TL): n={B_no_ob['n_taken']:4} win={B_no_ob['win_rate']*100:5.1f}% "
              f"exp={B_no_ob['expectancy_r']:+.4f} total_R={B_no_ob['total_net_r']:+.2f}", flush=True)
        print(f"  OB tek basina (referans):         n={ob_alone['n_taken']:4} win={ob_alone['win_rate']*100:5.1f}% "
              f"exp={ob_alone['expectancy_r']:+.4f} total_R={ob_alone['total_net_r']:+.2f}", flush=True)
        print(f"  C) OB AYRI SLOT (B + OB paralel):  n={C_separate['n_taken']:4} win={C_separate['win_rate']*100:5.1f}% "
              f"exp={C_separate['expectancy_r']:+.4f} total_R={C_separate['total_net_r']:+.2f}", flush=True)

        winner = max([("A_mevcut", A_current["total_net_r"]), ("B_ob_haric", B_no_ob["total_net_r"]),
                      ("C_ob_ayri_slot", C_separate["total_net_r"])], key=lambda x: x[1])
        print(f"  >>> EN IYI total_net_R: {winner[0]} ({winner[1]:+.2f}R)", flush=True)

        results[symbol] = {"A_current": A_current, "B_no_ob": B_no_ob, "ob_alone": ob_alone, "C_separate": C_separate}

    with open("ob_crowding_deepdive_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: ob_crowding_deepdive_results.json")


if __name__ == "__main__":
    main()
