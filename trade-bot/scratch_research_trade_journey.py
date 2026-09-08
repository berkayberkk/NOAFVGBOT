"""
NOAFVGBOT RESEARCH LAB -- Faz 1: Trade Journey Dataset + Kayip/Kazanc Taksonomisi
(kullanicinin 52-bolumluk arastirma talimatinin 3/4/5/6/7/8/11/12/15/24/25/34/36
bolumlerinin otomatize edilebilir cekirdegi).

Kapsam: KEPT_SYMBOLS (GOLD/BTCUSD/EURGBP) -- projenin fiilen canli/aday
sembolleri, M30 -- canli botun/EA'nin fiilen calistigi tek zaman dilimi
(coklu-zaman-dilimi arastirmasi ayri, results/fvg|ifvg|ob|trendline/ altinda
zaten 101 sembol x 6 zaman dilimi taranmis durumda -- burada TEKRAR
uretilmiyor). RESMI uretim hattı kullanilir: generate_signals + run_backtest
(bugunku SL tamponu/breakeven/giris-derinligi/hacim-teyidi/market-emri fill
duzeltmesi DAHIL, hicbir parametre bu script icin degistirilmedi).

Uretilen alanlar (Trade Journey, bolum 4):
  MARKET:  symbol, entry_time, day_of_week, session(UTC), atr_at_entry,
           volatility_bucket (sembol-ici percentile), trend_direction/strong
  SIGNAL:  module(setup_type), direction, in_killzone, volume_confirmed
  ENTRY:   signal_entry, executed_entry
  RISK:    stop_loss, risk(price), sl_distance_atr
  TARGET:  take_profit, r_target
  RESULT:  won, is_breakeven, r_multiple, mae_r, mfe_r, time_in_trade_bars
  EXIT:    exit_reason(tp/sl/breakeven_sl), loss_category (sadece kaybedenler)

Uretilen analizler:
  A) Kayip taksonomisi (MFE-tabanli, otomatize edilebilir alt kume --
     bolum 5'teki TAM 14 kategorinin bir kismi nesnel olarak
     otomatize edilemez / manuel/nitel inceleme gerektirir, asagida
     acikca isaretleniyor)
  B) Win vs Loss karsilastirma tablosu (bolum 7)
  C) Session / gun / trend / volatilite / yon kirilimlari (bolum 8/24/25)
  D) "SL vuruldu, sonra fiyat TP'ye gitti" -- gereksiz SL arastirmasi (bolum 11)
  E) Random-entry / falsification benchmark (bolum 34/36) -- gercek islemle
     AYNI risk/R-hedefi dagilimini kullanan, rastgele zamanli/yonlu kontrol

KUTSAL DISIPLIN: bu script HICBIR PARAMETREYI degistirmiyor/onermiyor --
sadece MEVCUT resmi stratejiyi olcuyor. Sonuclar
scratch_research_trade_journey_results.json'a yazilir.
"""

import json
import random
import statistics as stats
from dataclasses import asdict

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, KEPT_SYMBOLS
from strategy.signal_engine import generate_signals
from strategy.fvg import compute_atr_series
from strategy.trend import detect_trend
from backtest.engine import run_backtest

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
RNG_SEED = 20260907

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def session_bucket(hour: int) -> str:
    # Basit UTC saat dilimleri (DST ayarlanmadi -- ayni kisitlama strategy/session.py'de de var)
    if 0 <= hour < 7:
        return "Asian"
    if 7 <= hour < 12:
        return "London"
    if 12 <= hour < 16:
        return "London_NY_Overlap"
    if 16 <= hour < 21:
        return "NewYork"
    return "OffHours"


def volatility_bucket(atr_val, sorted_atrs):
    if atr_val is None or not sorted_atrs:
        return "unknown"
    import bisect
    pos = bisect.bisect_left(sorted_atrs, atr_val) / len(sorted_atrs)
    if pos < 0.25:
        return "low"
    if pos < 0.75:
        return "normal"
    if pos < 0.95:
        return "high"
    return "extreme"


def mfe_loss_category(is_breakeven: bool, mfe_r: float) -> str:
    """MFE-tabanli kok-neden siniflandirmasi -- bu oturumun GOLD trade
    gallery calismasinda kurulan AYNI taksonomi (bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md
    "GOLD islem galerisi" bolumu), KEPT_SYMBOLS'un tumune genisletildi."""
    if is_breakeven:
        return "breakeven_then_sl"
    if mfe_r < 0.10:
        return "ani_ters_fakeout"       # <10% -- olasi fakeout, hicbir zaman lehte hareket etmedi
    if mfe_r < 0.40:
        return "erken_basarisiz"        # 10-40%
    if mfe_r < 0.80:
        return "yakin_iskalama"         # 40-80%
    return "cok_yakin_iskalama"         # >80% -- TP'ye COK yakinken kaybetti, en aksiyon-alinabilir


def compute_mae_mfe(candles, entry_idx, exit_idx, entry_price, risk, is_buy):
    mae = 0.0
    mfe = 0.0
    for j in range(entry_idx, exit_idx + 1):
        c = candles[j]
        if is_buy:
            adverse = entry_price - c["low"]
            favorable = c["high"] - entry_price
        else:
            adverse = c["high"] - entry_price
            favorable = entry_price - c["low"]
        mae = max(mae, adverse)
        mfe = max(mfe, favorable)
    return (mae / risk if risk > 0 else 0.0), (mfe / risk if risk > 0 else 0.0)


def build_journey_for_symbol(symbol: str, candles, config: StrategyConfig):
    signals = generate_signals(candles, config=config)
    result = run_backtest(candles, signals, config=config)

    atr_series = compute_atr_series(candles, config.atr_period)
    sorted_atrs = sorted(a for a in atr_series if a is not None)
    trend_states = detect_trend(candles, config=config)

    journey = []
    for t in result.trades:
        sig = t.signal
        is_buy = sig.type.value == "buy"
        risk = abs(t.entry_price - t.stop_loss)
        entry_c = candles[t.entry_fill_index]
        ts = entry_c["time"]
        atr_at_entry = atr_series[sig.index] if sig.index < len(atr_series) else None
        trend_at_signal = trend_states[sig.index] if sig.index < len(trend_states) else None

        mae_r, mfe_r = compute_mae_mfe(candles, t.entry_fill_index, t.exit_index, t.entry_price, risk, is_buy)

        exit_reason = "take_profit" if t.won else ("breakeven_sl" if t.is_breakeven else "stop_loss")
        loss_cat = None if t.won else mfe_loss_category(t.is_breakeven, mfe_r)

        trend_conflict = None
        if trend_at_signal is not None and trend_at_signal.direction.value != "sideways":
            trend_conflict = (is_buy and trend_at_signal.direction.value == "down") or \
                              ((not is_buy) and trend_at_signal.direction.value == "up")

        journey.append({
            "symbol": symbol, "module": sig.setup_type.value if hasattr(sig.setup_type, "value") else str(sig.setup_type),
            "direction": "BUY" if is_buy else "SELL",
            "entry_time": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "day_of_week": DAY_NAMES[ts.weekday()] if hasattr(ts, "weekday") else "UNKNOWN",
            "session": session_bucket(ts.hour) if hasattr(ts, "hour") else "UNKNOWN",
            "atr_at_entry": atr_at_entry,
            "volatility_bucket": volatility_bucket(atr_at_entry, sorted_atrs),
            "trend_direction": trend_at_signal.direction.value if trend_at_signal else "unknown",
            "trend_strong": trend_at_signal.strong if trend_at_signal else False,
            "trend_conflict": trend_conflict,
            "in_killzone": sig.in_killzone, "volume_confirmed": sig.volume_confirmed,
            "signal_entry": t.entry_price, "executed_entry": t.executed_entry,
            "stop_loss": t.stop_loss, "risk_price": risk,
            "sl_distance_atr": (risk / atr_at_entry) if atr_at_entry else None,
            "take_profit": t.take_profit,
            "r_target": (abs(t.take_profit - t.entry_price) / risk) if risk else None,
            "won": t.won, "is_breakeven": t.is_breakeven, "r_multiple": t.r_multiple,
            "mae_r": mae_r, "mfe_r": mfe_r,
            "time_in_trade_bars": t.exit_index - t.entry_fill_index,
            "exit_reason": exit_reason, "loss_category": loss_cat,
            "entry_fill_index": t.entry_fill_index, "exit_index": t.exit_index,
        })
    return journey


def sl_recovery_study(candles, journey, lookahead_bars_list=(48, 96)):
    """Bolum 11: SL'e takilan (breakeven degil) islemlerde, SL sonrasi fiyat
    orijinal TP'ye N bar icinde ulasiyor mu? (Ham fiyat, spread'siz -- kaba
    bir 'gereksiz SL' gostergesi, kesin tekrar-islenebilir sinyal degil.)"""
    out = {n: {"checked": 0, "recovered": 0} for n in lookahead_bars_list}
    for rec in journey:
        if rec["exit_reason"] != "stop_loss":
            continue
        exit_idx = rec["exit_index"]
        tp = rec["take_profit"]
        is_buy = rec["direction"] == "BUY"
        for n in lookahead_bars_list:
            end = min(len(candles), exit_idx + 1 + n)
            if end <= exit_idx + 1:
                continue
            out[n]["checked"] += 1
            window = candles[exit_idx + 1:end]
            reached = any((c["high"] >= tp) if is_buy else (c["low"] <= tp) for c in window)
            if reached:
                out[n]["recovered"] += 1
    return {
        str(n): {
            "checked": v["checked"], "recovered": v["recovered"],
            "recovery_rate": (v["recovered"] / v["checked"]) if v["checked"] else 0.0,
        } for n, v in out.items()
    }


def random_entry_benchmark(candles, journey, seed=RNG_SEED):
    """Bolum 34/36: gercek islemlerle AYNI risk(R)/r_target dagilimini
    kullanan, ama rastgele zamanli VE rastgele yonlu bir kontrol grubu.
    Gercek sinyal setinden risk/target COPYlanir (istatistiksel olarak
    karsilastirilabilir olsun diye), sadece giris ZAMANI ve YONU rastgele
    atanir; sonuc AYNI ilk-SL/TP-dokunuru mantigiyla (breakeven'siz, basit)
    simule edilir."""
    rng = random.Random(seed)
    n = len(candles)
    results = []
    for rec in journey:
        risk = rec["risk_price"]
        r_target = rec["r_multiple"] if rec["r_multiple"] is not None else None
        # r_target'i dogrudan kullanmak yerine gercek TP mesafesini risk cinsinden geri turet
        tp_r = abs(rec["take_profit"] - rec["signal_entry"]) / risk if risk else None
        if not risk or not tp_r:
            continue
        idx = rng.randint(50, n - 200)
        is_buy = rng.random() < 0.5
        entry_price = candles[idx]["close"]
        sl = entry_price - risk if is_buy else entry_price + risk
        tp = entry_price + tp_r * risk if is_buy else entry_price - tp_r * risk
        won = None
        for j in range(idx + 1, min(n, idx + 1 + 3000)):
            c = candles[j]
            hit_sl = (c["low"] <= sl) if is_buy else (c["high"] >= sl)
            hit_tp = (c["high"] >= tp) if is_buy else (c["low"] <= tp)
            if hit_sl and hit_tp:
                won = False  # ayni-bar belirsizligi -- kotumser kabul (gercek motorla tutarli)
                break
            if hit_sl:
                won = False
                break
            if hit_tp:
                won = True
                break
        if won is None:
            continue
        results.append(tp_r if won else -1.0)
    if not results:
        return {"n": 0}
    wins = [r for r in results if r > 0]
    return {
        "n": len(results), "win_rate": len(wins) / len(results),
        "expectancy_r": sum(results) / len(results), "total_r": sum(results),
    }


def summarize(journey):
    n = len(journey)
    if n == 0:
        return {"n": 0}
    wins = [r for r in journey if r["won"]]
    losses = [r for r in journey if not r["won"]]
    total_r = sum(r["r_multiple"] for r in journey)
    return {
        "n": n, "win_rate": len(wins) / n, "expectancy_r": total_r / n, "total_r": total_r,
        "avg_win_r": stats.mean([r["r_multiple"] for r in wins]) if wins else 0.0,
        "avg_loss_r": stats.mean([r["r_multiple"] for r in losses]) if losses else 0.0,
        "avg_mae_r": stats.mean([r["mae_r"] for r in journey]),
        "avg_mfe_r": stats.mean([r["mfe_r"] for r in journey]),
        "avg_mae_r_wins": stats.mean([r["mae_r"] for r in wins]) if wins else 0.0,
        "avg_mfe_r_losses": stats.mean([r["mfe_r"] for r in losses]) if losses else 0.0,
        "avg_sl_distance_atr": stats.mean([r["sl_distance_atr"] for r in journey if r["sl_distance_atr"]]),
        "trend_conflict_rate": stats.mean([1.0 if r["trend_conflict"] else 0.0 for r in journey if r["trend_conflict"] is not None]) if any(r["trend_conflict"] is not None for r in journey) else None,
    }


def breakdown_by(journey, key):
    groups = {}
    for r in journey:
        groups.setdefault(r[key], []).append(r)
    return {str(k): summarize(v) for k, v in groups.items()}


def main():
    all_journey = []
    per_symbol_summary = {}
    per_symbol_sl_recovery = {}
    per_symbol_random_bench = {}

    for symbol in KEPT_SYMBOLS:
        print(f"\n=== {symbol} ===", flush=True)
        m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
        m30_v2, _ = resample_m1(m1, Timeframe.M30)
        candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
        print(f"{len(candles)} M30 mumu", flush=True)

        config = StrategyConfig(spread=SPREAD_BY_SYMBOL[symbol])
        journey = build_journey_for_symbol(symbol, candles, config)
        print(f"{len(journey)} gerceklesen islem (tum aday sinyaller, tek-pozisyon SUZGECI YOK -- bu run_backtest'in ham ciktisi)", flush=True)

        all_journey.extend(journey)
        per_symbol_summary[symbol] = summarize(journey)
        per_symbol_sl_recovery[symbol] = sl_recovery_study(candles, journey)
        per_symbol_random_bench[symbol] = random_entry_benchmark(candles, journey)
        print(f"  gercek: {per_symbol_summary[symbol]}", flush=True)
        print(f"  random-entry benchmark: {per_symbol_random_bench[symbol]}", flush=True)

    loss_records = [r for r in all_journey if not r["won"]]
    loss_cat_counts = {}
    loss_cat_r = {}
    for r in loss_records:
        cat = r["loss_category"]
        loss_cat_counts[cat] = loss_cat_counts.get(cat, 0) + 1
        loss_cat_r[cat] = loss_cat_r.get(cat, 0.0) + r["r_multiple"]

    output = {
        "note_scope": "KEPT_SYMBOLS (GOLD/BTCUSD/EURGBP), M30 -- tek-pozisyon suzgeci UYGULANMADI, run_backtest'in ham ciktisi (her modulun butun aday sinyalleri ayri ayri simule edildi)",
        "combined_summary": summarize(all_journey),
        "per_symbol_summary": per_symbol_summary,
        "loss_taxonomy": {
            "counts": loss_cat_counts,
            "total_r_by_category": loss_cat_r,
            "n_losses": len(loss_records),
        },
        "breakdown_by_module": breakdown_by(all_journey, "module"),
        "breakdown_by_direction": breakdown_by(all_journey, "direction"),
        "breakdown_by_session": breakdown_by(all_journey, "session"),
        "breakdown_by_day_of_week": breakdown_by(all_journey, "day_of_week"),
        "breakdown_by_volatility_bucket": breakdown_by(all_journey, "volatility_bucket"),
        "breakdown_by_trend_direction": breakdown_by(all_journey, "trend_direction"),
        "sl_recovery_study": per_symbol_sl_recovery,
        "random_entry_benchmark": per_symbol_random_bench,
        "random_entry_benchmark_seed": RNG_SEED,
    }

    with open("scratch_research_trade_journey_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    with open("scratch_research_trade_journey_full.json", "w") as f:
        json.dump(all_journey, f, indent=None, default=str)

    print("\n=== OZET ===")
    print(json.dumps(output["combined_summary"], indent=2))
    print("\n=== KAYIP TAKSONOMISI ===")
    print(json.dumps(loss_cat_counts, indent=2))
    print("\nyazildi: scratch_research_trade_journey_results.json, scratch_research_trade_journey_full.json")


if __name__ == "__main__":
    main()
