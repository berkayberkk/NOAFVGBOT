"""
PROTOTIP (scratch, kalici degil): FVG/iFVG/OB'nin ayni disiplinli
metodolojisi (RR-TP taramasi, causal simulasyon, checkpoint'li 101
sembol x 6 zaman dilimi tarama) -- Trendline (sekme + kirilim+retest)
icin.

Giris/SL/TP (arastirmadan, bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md
"Trendline TP/SL arastirmasi" + "KRITIK BULGU -- 2 lookahead/optimizm
hatasi" bolumleri, 2026-09-01):
- SEKME (bounce): giris = dokunan mumun KENDI fiyati (wick), SL =
  dokunus fiyati +/- ATR x tampon.
- KIRILIM+RETEST (reversal): giris = retest mumunun KENDI KAPANISI
  (line_price DEGIL -- fiyatin gercekten ulasmadigi bir seviye olabilir),
  SL = retest mumunun kendi fitil ekstremumu +/- ATR x tampon.
- Ikisi de: TP = sabit R katlari.
- SL_BUFFER_RATIO = 0.5 -- GOLD M30 tam gecmiste kalibre edildi
  (0.1/0.25/0.5/0.75/1.0/2.0/3.0 sweep), tepe nokta R=1.5'te exp_r=0.516,
  pf=2.31.

CAUSAL DUZELTME (KRITIK, bkz. NOA doc): `find_swing_points` bir mumun
swing oldugunu ancak SONRASINDAKI `lookback` kadar mum gorulunce
onaylayabiliyor -- bu yuzden trade simulasyonu HICBIR olayi
`tl.known_index`'ten (validated_index + swing_lookback) ONCE kullanmiyor,
ve dokunuslar artik find_swing_points pivotlariyla SINIRLI DEGIL --
known_index'ten kirilmaya kadar HER mum tek tek taraniyor (dokunus
"streak"inin ilk barinda bir olay -- ust uste gelen coklu-bar temaslar
tek islem sayilir).
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, EXCLUDED_SYMBOLS, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO, MODULE_DISABLED_TIMEFRAMES, KEPT_SYMBOLS
from strategy.trendline import detect_trendlines, detect_trendline_reversals, TrendlineDirection
from strategy.fvg import compute_atr_series
from scratch_multi_timeframe_fvg_scan import _aggregate_by_calendar

RESULTS_PATH = Path("trendline_tp_sl_study_results.json")
# Trendline'in kendi R'sinde (asagida) en cok SL yedigi zaman dilimi
# (strategy/config.py:MODULE_DISABLED_TIMEFRAMES) artik TARANMIYOR --
# 2026-09-01 karariyla Trendline bu zaman diliminde islem acmiyor.
TIMEFRAMES = [tf for tf in (Timeframe.M30, Timeframe.H1, Timeframe.H2, Timeframe.H4, Timeframe.D1, Timeframe.W1)
              if tf.name not in MODULE_DISABLED_TIMEFRAMES["trendline"]]
R_MULTIPLES = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
TRENDLINE_OFFICIAL_R_MULTIPLE = MODULE_R_MULTIPLE["trendline"]  # = 2.0 -- profit factor tepe noktasi, resmi TP hedefi
SL_BUFFER_RATIO = MODULE_SL_BUFFER_RATIO["trendline"]  # = 0.5, GOLD'da kalibre edildi
MAX_WAIT_BARS = 3000

# + 2026-09-02, TUR 4 (kullanici karariyla): kapsam GOLD, BTCUSD, EURGBP
# UCLUSUNE daraltildi -- strategy/config.py:KEPT_SYMBOLS. Bkz.
# NOA_KONSEPTI_KAYNAK_ANALIZI.md "Sembol eleme turu 2 ve 3" bolumu.
ALL_SYMBOLS = list(KEPT_SYMBOLS)
assert not (set(ALL_SYMBOLS) & set(EXCLUDED_SYMBOLS)), "EXCLUDED_SYMBOLS listesi ile cakisma var"

CONFIG = StrategyConfig()


@dataclass
class TradeOutcome:
    won: bool
    r_multiple: float


def _bounce_events(candles: list[dict], lines, atr_series) -> list[tuple[int, bool, float, float]]:
    events = []
    for tl in lines:
        is_bull = tl.direction == TrendlineDirection.ASCENDING
        start = tl.known_index + 1
        end = tl.broken_index if tl.broken_index is not None else len(candles)
        was_touching = False
        for k in range(max(start, 0), min(end, len(candles))):
            line_price = tl.price_at(k)
            tol = (atr_series[k] or 0) * CONFIG.trendline_touch_tolerance_atr_ratio
            c = candles[k]
            touched = (c["low"] <= line_price + tol) if is_bull else (c["high"] >= line_price - tol)
            if touched and not was_touching:
                touch_price = c["low"] if is_bull else c["high"]
                buffer = (atr_series[k] or 0) * SL_BUFFER_RATIO
                entry = touch_price
                sl = entry - buffer if is_bull else entry + buffer
                events.append((k, is_bull, entry, sl))
            was_touching = touched
    return events


def _reversal_events(candles: list[dict], reversals, atr_series) -> list[tuple[int, bool, float, float]]:
    events = []
    for r in reversals:
        rc = candles[r.retest_index]
        buffer = (atr_series[r.retest_index] or 0) * SL_BUFFER_RATIO
        entry = rc["close"]  # line_price DEGIL -- gercekten gerceklesmis fiyat (bkz. modul docstring'i)
        sl = (rc["low"] - buffer) if r.is_bullish else (rc["high"] + buffer)
        events.append((r.retest_index, r.is_bullish, entry, sl))
    return events


def simulate_trade(candles: list[dict], trigger_idx: int, is_bull: bool, entry: float, sl: float,
                   r_multiple: float) -> TradeOutcome | None:
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    take_profit = entry + r_multiple * risk if is_bull else entry - r_multiple * risk

    scan_end = min(len(candles), trigger_idx + 1 + MAX_WAIT_BARS)
    for i in range(trigger_idx + 1, scan_end):
        c = candles[i]
        if is_bull:
            hit_sl = c["low"] <= sl
            hit_tp = c["high"] >= take_profit
        else:
            hit_sl = c["high"] >= sl
            hit_tp = c["low"] <= take_profit
        if hit_sl:
            return TradeOutcome(won=False, r_multiple=-1.0)
        if hit_tp:
            return TradeOutcome(won=True, r_multiple=r_multiple)
    return None


def _metrics(outcomes: list[TradeOutcome]) -> dict:
    if not outcomes:
        return {"n": 0}
    wins = [o for o in outcomes if o.won]
    losses = [o for o in outcomes if not o.won]
    win_rate = len(wins) / len(outcomes)
    total_r = sum(o.r_multiple for o in outcomes)
    avg_win = sum(o.r_multiple for o in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(o.r_multiple for o in losses)) / len(losses) if losses else 0.0
    expectancy_r = win_rate * avg_win - (1 - win_rate) * avg_loss
    gross_profit = sum(o.r_multiple for o in wins)
    gross_loss = abs(sum(o.r_multiple for o in losses))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    return {
        "n": len(outcomes), "wins": len(wins), "losses": len(losses),
        "win_rate": win_rate, "total_r": total_r, "expectancy_r": expectancy_r,
        "profit_factor": min(pf, 999.0),
    }


def _process_timeframe(candles: list[dict]) -> dict:
    if len(candles) < 20:
        return {}
    lines = detect_trendlines(candles, config=CONFIG)
    reversals = detect_trendline_reversals(candles, lines, config=CONFIG)
    atr_series = compute_atr_series(candles, CONFIG.atr_period)

    events = _bounce_events(candles, lines, atr_series) + _reversal_events(candles, reversals, atr_series)
    events.sort(key=lambda e: e[0])

    result = {"n_lines": len(lines), "n_reversals": len(reversals), "n_events": len(events)}
    for r in R_MULTIPLES:
        outcomes = []
        for trigger_idx, is_bull, entry, sl in events:
            o = simulate_trade(candles, trigger_idx, is_bull, entry, sl, r)
            if o is not None:
                outcomes.append(o)
        result[str(r)] = _metrics(outcomes)
    return result


def _load_checkpoint() -> dict:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text())
    return {}


def _save_checkpoint(data: dict) -> None:
    tmp = RESULTS_PATH.with_suffix(".tmp")
    for attempt in range(5):
        try:
            tmp.write_text(json.dumps(data, indent=2, default=str))
            tmp.replace(RESULTS_PATH)
            return
        except (PermissionError, FileNotFoundError):
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


def main():
    checkpoint = _load_checkpoint()
    total_units = len(ALL_SYMBOLS) * len(TIMEFRAMES)
    done_units = sum(1 for v in checkpoint.values() if isinstance(v, dict) and "error" not in v for _ in v)

    for symbol in ALL_SYMBOLS:
        sym_result = checkpoint.get(symbol, {})
        if "error" in sym_result:
            continue
        pending_tfs = [tf for tf in TIMEFRAMES if tf.name not in sym_result]
        if not pending_tfs:
            continue

        path = f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv"
        try:
            m1 = load_m1_canonical_as_candlev2(path)
        except FileNotFoundError:
            continue
        if len(m1) < 2000:
            checkpoint[symbol] = {"error": "yetersiz veri"}
            _save_checkpoint(checkpoint)
            continue

        m30_candles = None
        for tf in pending_tfs:
            t0 = time.time()
            if tf in (Timeframe.D1, Timeframe.W1):
                if m30_candles is None:
                    m30_v2, _ = resample_m1(m1, Timeframe.M30)
                    m30_candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
                tf_candles = _aggregate_by_calendar(m30_candles, "day" if tf == Timeframe.D1 else "week")
            else:
                tf_v2, _ = resample_m1(m1, tf)
                tf_candles = [candlev2_to_strategy_dict(c) for c in tf_v2]
                if tf == Timeframe.M30:
                    m30_candles = tf_candles

            sym_result[tf.name] = _process_timeframe(tf_candles)
            checkpoint[symbol] = sym_result
            _save_checkpoint(checkpoint)
            done_units += 1
            print(f"[{done_units}/{total_units}] {symbol}/{tf.name}: {time.time()-t0:.1f}sn -- kaydedildi", flush=True)

    print("\nTUM SEMBOLLER TAMAMLANDI.", flush=True)


if __name__ == "__main__":
    main()
