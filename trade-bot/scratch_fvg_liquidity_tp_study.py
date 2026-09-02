"""
PROTOTIP (scratch, kalici degil): scratch_fvg_tp_sl_study.py'nin ("RR TP",
sabit R-kati) yaninda ikinci bir TP yontemini test eder -- "Likidite TP":

- Yukselis (bullish) trade: TP = fiyatin yukarisinda, HENUZ ALINMAMIS
  (kirilmamis) en yakin likidite (swing high).
- Dususte (bearish) trade: TP = fiyatin asagisinda, HENUZ ALINMAMIS en
  yakin likidite (swing low).

"Alinmamis" = o swing noktasi olustuktan sonra (ve giris barina kadar)
hicbir mum fitili o seviyeyi henuz gecmemis. Swing tespiti icin mevcut,
test edilmis `strategy/support_resistance.py:find_swing_points` yeniden
kullanilir (ayni ATR/lookback mantigi, kod tabaninin geri kalaniyla
tutarli).

Causal: bir swing noktasi, kendi lookback penceresi TAMAMLANMADAN (yani
idx+lookback <= entry_fill_index olmadan) "bilinen" sayilmaz -- ileri
tarama yok.

Giris ve SL, RR TP calismasiyla BIREBIR AYNI (karsilastirma adil olsun
diye): entry=fvg.entry_price, SL=uzak kenar + gap boyutunun %100'u
tampon. TEK degisken: TP yontemi.

Checkpoint'li -- her sembol/zaman dilimi ciftinden sonra diske yazilir.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, KEPT_SYMBOLS
from strategy.fvg import detect_fvgs, FVGDirection
from strategy.support_resistance import find_swing_points
from scratch_multi_timeframe_fvg_scan import _aggregate_by_calendar

RESULTS_PATH = Path("fvg_tp_study_liquidity_results.json")
TIMEFRAMES = [Timeframe.M30, Timeframe.H1, Timeframe.H2, Timeframe.H4, Timeframe.D1, Timeframe.W1]
SL_BUFFER_RATIO = 1.0   # RR TP calismasiyla ayni (bkz. o script'in kalibrasyon notu)
MAX_WAIT_BARS = 3000
SWING_LOOKBACK = 5       # strategy/config.py DEFAULT_CONFIG.swing_lookback ile ayni

# EXCLUDED_SYMBOLS (strategy/config.py): FVG, iFVG ve Order Block'un ucunun de
# aynı anda en kötü 10 sembol arasında bulduğu, yapısal olarak bu stratejiye
# uygun olmayan semboller çıkarıldı (2026-08-31 R-katı çalışması) --
# GERTECH30, NASDAQ, IT40, GERMID50, EURDKK, USFANG.
# + 2026-09-02, TUR 4 (kullanici karariyla): kapsam GOLD, BTCUSD, EURGBP
# UCLUSUNE daraltildi -- strategy/config.py:KEPT_SYMBOLS. Bkz.
# NOA_KONSEPTI_KAYNAK_ANALIZI.md "Sembol eleme turu 2 ve 3" bolumu.
ALL_SYMBOLS = list(KEPT_SYMBOLS)

CONFIG = StrategyConfig()


@dataclass
class TradeOutcome:
    won: bool
    r_multiple: float


def _precompute_taken_index(candles: list[dict], indices: list[int], price_key: str, is_high: bool) -> dict[int, int | None]:
    """Her swing noktasi icin, o seviyenin ILK ALINDIGI (fitille gecildigi) bar'i hesaplar."""
    taken = {}
    n = len(candles)
    for idx in indices:
        level = candles[idx][price_key]
        taken_at = None
        for j in range(idx + 1, n):
            v = candles[j][price_key]
            if (is_high and v >= level) or (not is_high and v <= level):
                taken_at = j
                break
        taken[idx] = taken_at
    return taken


def find_liquidity_tp(swing_indices: list[int], candles: list[dict], price_key: str,
                       taken_at: dict[int, int | None], entry_price: float,
                       fill_index: int, is_bull: bool) -> float | None:
    best = None
    for idx in swing_indices:
        if idx + SWING_LOOKBACK > fill_index:
            continue  # bu swing, fill aninda henuz "bilinir" degil (kendi penceresi tamamlanmadi)
        t = taken_at[idx]
        if t is not None and t <= fill_index:
            continue  # zaten alinmis
        level = candles[idx][price_key]
        if is_bull and level <= entry_price:
            continue
        if not is_bull and level >= entry_price:
            continue
        if best is None or (is_bull and level < best) or (not is_bull and level > best):
            best = level
    return best


def simulate_fvg_trade_liquidity_tp(candles, fvg, swing_highs, swing_lows,
                                     highs_taken, lows_taken) -> TradeOutcome | None:
    entry = fvg.entry_price
    gap_size = fvg.top - fvg.bottom
    buffer = gap_size * SL_BUFFER_RATIO
    is_bull = fvg.direction == FVGDirection.BULLISH
    stop_loss = (fvg.bottom - buffer) if is_bull else (fvg.top + buffer)
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return None

    start = fvg.end_index + 1
    end = min(len(candles), start + MAX_WAIT_BARS)
    fill_index = None
    for i in range(start, end):
        c = candles[i]
        if (is_bull and c["low"] <= entry) or (not is_bull and c["high"] >= entry):
            fill_index = i
            break
    if fill_index is None:
        return None

    if is_bull:
        take_profit = find_liquidity_tp(swing_highs, candles, "high", highs_taken, entry, fill_index, True)
    else:
        take_profit = find_liquidity_tp(swing_lows, candles, "low", lows_taken, entry, fill_index, False)
    if take_profit is None:
        return None  # alinmamis likidite yok -- bu trade test edilemez, atla

    r_multiple = abs(take_profit - entry) / risk
    scan_end = min(len(candles), fill_index + MAX_WAIT_BARS)
    for i in range(fill_index, scan_end):
        c = candles[i]
        if is_bull:
            hit_sl = c["low"] <= stop_loss
            hit_tp = c["high"] >= take_profit
        else:
            hit_sl = c["high"] >= stop_loss
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


def _process_symbol_timeframe(candles: list[dict]) -> dict:
    if len(candles) < 20:
        return {}
    fvgs = [f for f in detect_fvgs(candles, config=CONFIG) if f.valid]
    swing_highs, swing_lows = find_swing_points(candles, lookback=SWING_LOOKBACK)
    highs_taken = _precompute_taken_index(candles, swing_highs, "high", is_high=True)
    lows_taken = _precompute_taken_index(candles, swing_lows, "low", is_high=False)

    outcomes = []
    avg_target_r_list = []
    for fvg in fvgs:
        o = simulate_fvg_trade_liquidity_tp(candles, fvg, swing_highs, swing_lows, highs_taken, lows_taken)
        if o is not None:
            outcomes.append(o)
            avg_target_r_list.append(o.r_multiple if o.won else None)

    m = _metrics(outcomes)
    m["avg_target_r"] = (sum(r for r in avg_target_r_list if r) / len([r for r in avg_target_r_list if r])) if any(avg_target_r_list) else None
    m["n_skipped_no_liquidity"] = len(fvgs) - len(outcomes)
    return m


def _load_checkpoint() -> dict:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text())
    return {}


def _save_checkpoint(data: dict) -> None:
    tmp = RESULTS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    for attempt in range(5):
        try:
            tmp.replace(RESULTS_PATH)
            return
        except PermissionError:
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

            sym_result[tf.name] = _process_symbol_timeframe(tf_candles)
            checkpoint[symbol] = sym_result
            _save_checkpoint(checkpoint)
            done_units += 1
            print(f"[{done_units}/{total_units}] {symbol}/{tf.name}: {time.time()-t0:.1f}sn -- kaydedildi", flush=True)

    print("\nTUM SEMBOLLER TAMAMLANDI.", flush=True)


if __name__ == "__main__":
    main()
