"""
PROTOTIP (scratch, kalici degil): kullanicinin istegi -- her islemin ayni
lot ile acilmamasi, bunun yerine "Setup Kalitesi" (kaynak materyaldeki
S+/S/A+/A/B+/B/C sisteminin basitlestirilmis bir versiyonu, bkz.
NOA_KONSEPTI_KAYNAK_ANALIZI.md) fikrine gore B/A/A+ diye derecelendirilip
lot buyuklugunun buna gore olceklenmesi.

ONEMLI ON-NOT: bu proje AYNI fikri (modul cakismasi = daha kaliteli
islem) daha once test etmisti (results/confluence_and_filters/
confluence_study_results.json) ve "ise yaramadi" sonucuna varmisti --
AMA o test, bu oturumun duzelttigi ESKI (same-bar-iyimser) motorla
yapilmisti (GOLD confluence=0'da bile win %40.2/expectancy +0.41R --
duzeltilmis motorun gercekci sayilariyla hic uyusmuyor). Yani o eski
"ise yaramadi" sonucu da guvenilir degil. Bu script AYNI soruyu
DUZELTILMIS motorla, KEPT_SYMBOLS + gercekci spread ile yeniden soruyor.

GRADE TANIMI (kullanicinin tarifi -- "trend" = Trendline modulunun
yonu, kullanici onayiyla):
  B  : FVG ya da OB sinyali, tek basina (baseline, mevcut davranis)
  A  : sinyalin yonuyle AYNI yonde AKTIF (bilinen, henuz kirilmamis)
       bir Trendline var
  A+ : A + AYRICA diger modulden (FVG sinyaliyse OB, OB sinyaliyse FVG)
       AYNI yonde, fiyat araligi CAKISAN ve o anda hala aktif
       (mitigasyon/dolum olmamis) bir bolge var

Hem FVG-ankorlu hem OB-ankorlu grade'ler ayri ayri raporlaniyor
("varyasyon" -- kullanicinin istedigi gibi).
"""

import json

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, KEPT_SYMBOLS, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO
from strategy.fvg import detect_fvgs, FVGDirection
from strategy.order_block import detect_order_blocks, OBDirection
from strategy.trendline import detect_trendlines, TrendlineDirection
from strategy.signal_engine import Signal, SignalType, Confidence, SetupType
from backtest.engine import run_backtest
from backtest.validation import calculate_metrics

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}


def _trend_active_arrays(candles, lines):
    """Her bar icin, o anda AKTIF (known_index<=i<broken_index) bullish/bearish
    (ascending/descending) trendline var mi -- causal, O(n+lines)."""
    n = len(candles)
    bull = [False] * n
    bear = [False] * n
    for tl in lines:
        start = max(0, tl.known_index)
        end = tl.broken_index if tl.broken_index is not None else n
        end = min(end, n)
        target = bull if tl.direction == TrendlineDirection.ASCENDING else bear
        for i in range(start, end):
            target[i] = True
    return bull, bear


def _ob_active_by_direction(obs, n):
    """Her bar icin, o anda AKTIF (impulse_index<=i, mitigated degil ya da
    mitigated_index>i) bullish/bearish OB araliklarinin listesi."""
    bull_ranges = [[] for _ in range(n)]
    bear_ranges = [[] for _ in range(n)]
    for ob in obs:
        start = ob.impulse_index
        end = ob.mitigated_index if (ob.mitigated and ob.mitigated_index is not None) else n
        end = min(end, n)
        target = bull_ranges if ob.direction == OBDirection.BULLISH else bear_ranges
        for i in range(max(0, start), end):
            target[i].append((ob.bottom, ob.top))
    return bull_ranges, bear_ranges


def _fvg_active_by_direction(fvgs, n):
    bull_ranges = [[] for _ in range(n)]
    bear_ranges = [[] for _ in range(n)]
    for f in fvgs:
        if not f.valid:
            continue
        start = f.end_index
        end = f.filled_at_index if (f.filled and f.filled_at_index is not None) else n
        end = min(end, n)
        target = bull_ranges if f.direction == FVGDirection.BULLISH else bear_ranges
        for i in range(max(0, start), end):
            target[i].append((f.bottom, f.top))
    return bull_ranges, bear_ranges


def _overlaps(a_bottom, a_top, ranges):
    for b_bottom, b_top in ranges:
        if a_bottom <= b_top and b_bottom <= a_top:
            return True
    return False


def _grade(is_bull, index, trend_bull, trend_bear, other_bull_ranges, other_bear_ranges, zone_bottom, zone_top):
    trend_ok = trend_bull[index] if is_bull else trend_bear[index]
    other_ranges = other_bull_ranges[index] if is_bull else other_bear_ranges[index]
    overlap_ok = _overlaps(zone_bottom, zone_top, other_ranges)
    if trend_ok and overlap_ok:
        return "A+"
    if trend_ok:
        return "A"
    return "B"


def _eval_by_grade(candles, signals_with_grade, config):
    """grade -> Signal listesi ayirip her biri icin ayri backtest/metrik."""
    by_grade = {}
    for s, g in signals_with_grade:
        by_grade.setdefault(g, []).append(s)
    out = {}
    for g, sigs in by_grade.items():
        result = run_backtest(candles, sigs, config=config)
        m = calculate_metrics(result.trades, total_signals=len(sigs),
                               unfilled_orders=result.unfilled_orders, skipped_no_tp=result.skipped_no_tp)
        out[g] = {"n_filled": m.filled_trades, "win_rate": m.win_rate,
                  "expectancy_r": m.expectancy_r, "profit_factor": m.profit_factor,
                  "total_net_r": m.total_net_r}
    return out


def main():
    results = {}
    for symbol in KEPT_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
        config = StrategyConfig(spread=SPREAD_BY_SYMBOL[symbol])
        n = len(candles)

        fvgs = detect_fvgs(candles, config=config)
        obs = detect_order_blocks(candles, config=config)
        lines = detect_trendlines(candles, config=config)

        trend_bull, trend_bear = _trend_active_arrays(candles, lines)
        ob_bull_ranges, ob_bear_ranges = _ob_active_by_direction(obs, n)
        fvg_bull_ranges, fvg_bear_ranges = _fvg_active_by_direction(fvgs, n)

        r_fvg = MODULE_R_MULTIPLE["fvg"]
        sl_fvg = MODULE_SL_BUFFER_RATIO["fvg"]
        fvg_signals = []
        for f in fvgs:
            if not f.valid or not f.volume_confirmed or f.end_index >= n:
                continue
            is_bull = f.direction == FVGDirection.BULLISH
            entry = f.entry_price
            buffer = (f.top - f.bottom) * sl_fvg
            stop_loss = f.bottom - buffer if is_bull else f.top + buffer
            risk = abs(entry - stop_loss)
            if risk <= 0:
                continue
            take_profit = entry + r_fvg * risk if is_bull else entry - r_fvg * risk
            s = Signal(index=f.end_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                       confidence=Confidence.MEDIUM, setup_type=SetupType.FVG_ONLY,
                       entry=entry, stop_loss=stop_loss, take_profit=take_profit, reason="fvg-grade")
            grade = _grade(is_bull, f.end_index, trend_bull, trend_bear, ob_bull_ranges, ob_bear_ranges, f.bottom, f.top)
            fvg_signals.append((s, grade))

        r_ob = MODULE_R_MULTIPLE["ob"]
        sl_ob = MODULE_SL_BUFFER_RATIO["ob"]
        ob_signals = []
        for ob in obs:
            if ob.impulse_index >= n:
                continue
            is_bull = ob.direction == OBDirection.BULLISH
            entry = ob.top if is_bull else ob.bottom
            buffer = (ob.top - ob.bottom) * sl_ob
            stop_loss = (ob.bottom - buffer) if is_bull else (ob.top + buffer)
            risk = abs(entry - stop_loss)
            if risk <= 0:
                continue
            take_profit = entry + r_ob * risk if is_bull else entry - r_ob * risk
            s = Signal(index=ob.impulse_index, type=SignalType.BUY if is_bull else SignalType.SELL,
                       confidence=Confidence.MEDIUM, setup_type=SetupType.OB_ONLY,
                       entry=entry, stop_loss=stop_loss, take_profit=take_profit, reason="ob-grade")
            grade = _grade(is_bull, ob.impulse_index, trend_bull, trend_bear, fvg_bull_ranges, fvg_bear_ranges, ob.bottom, ob.top)
            ob_signals.append((s, grade))

        fvg_by_grade = _eval_by_grade(candles, fvg_signals, config)
        ob_by_grade = _eval_by_grade(candles, ob_signals, config)
        results[symbol] = {"fvg": fvg_by_grade, "ob": ob_by_grade}

        print("  FVG-ankorlu:")
        for g in ["B", "A", "A+"]:
            if g in fvg_by_grade:
                v = fvg_by_grade[g]
                print(f"    {g:3} n={v['n_filled']:5} win={v['win_rate']:.1%} exp={v['expectancy_r']:.4f} pf={v['profit_factor']:.2f}", flush=True)
        print("  OB-ankorlu:")
        for g in ["B", "A", "A+"]:
            if g in ob_by_grade:
                v = ob_by_grade[g]
                print(f"    {g:3} n={v['n_filled']:5} win={v['win_rate']:.1%} exp={v['expectancy_r']:.4f} pf={v['profit_factor']:.2f}", flush=True)

    with open("confluence_grade_study_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nyazildi: confluence_grade_study_results.json")

    print("\n=== HAVUZLANMIS (3 sembol) ===")
    for anchor in ["fvg", "ob"]:
        print(f"-- {anchor} --")
        for g in ["B", "A", "A+"]:
            n_total = sum(results[s][anchor].get(g, {}).get("n_filled", 0) for s in KEPT_SYMBOLS)
            if n_total == 0:
                continue
            total_r = sum(results[s][anchor].get(g, {}).get("total_net_r", 0) for s in KEPT_SYMBOLS)
            wins = sum(round(results[s][anchor].get(g, {}).get("win_rate", 0) * results[s][anchor].get(g, {}).get("n_filled", 0)) for s in KEPT_SYMBOLS)
            print(f"  {g:3} n={n_total:6} win={wins/n_total:.1%} exp={total_r/n_total:.4f}")


if __name__ == "__main__":
    main()
