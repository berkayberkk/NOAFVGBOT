"""
Experiment #005 -- HIPOTEZ TEST: sabit R-kati TP yerine Destek/Direnc
tabanli TP, expectancy'yi artiriyor mu? (4 modul AYRI AYRI test edilir)

TASARIM (kullanicinin talimati):
1. Her sinyal icin: signal.index'e kadarki (causal) mumlarla
   support_resistance.build_levels() cagrilir, _find_take_profit
   (backtest/engine.py'de zaten var, min_level_touch_count=2 varsayilan)
   ile sinyal yonunde en yakin seviye TP adayi olarak denenir.
2. Uygun seviye YOKSA, MEVCUT resmi sabit R-kati TP'ye (MODULE_R_MULTIPLE)
   FALLBACK yapilir -- sinyal ASLA iptal edilmez (bu, engine.py'nin
   kendi ic fallback'inden FARKLI -- o SKIP ediyor, biz FALLBACK
   istiyoruz, bu yuzden take_profit BURADA onceden hesaplanip
   run_backtest'e HAZIR gecilir).
3. SL mantigina DOKUNULMADI (resmi ATR/bolge-bazli SL aynen kullanildi).
4. 4 modul AYRI AYRI test edildi -- FVG-only/iFVG-only/OB-only/
   Trendline-only, HERBIRI kendi BASELINE'iyla (ayni modulun mevcut
   sabit-R TP sonucu) karsilastirildi, karisik/toplu raporlama YAPILMADI.

KAPSAM: 101 sembol, SADECE train+val (%80), holdout HIC KULLANILMADI.
Bu, LONG/SHORT rejim-asimetrisi sorununu (Deney #004b) COZMUYOR --
sadece cikis (TP) mantigini, bagimsiz bir hipotez olarak test ediyor.

KUTSAL KURAL: sonuc ne cikarsa ciksin, config.py'ye HICBIR YAZMA
YAPILMAYACAK -- bu SADECE olcum, karar kullaniciya birakiliyor.
"""

import json
import time
from dataclasses import replace as dc_replace
from pathlib import Path

from strategy.config import StrategyConfig, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO, _ALL_101_SYMBOLS
from strategy.fvg import detect_fvgs, mark_filled_fvgs, FVGDirection, compute_atr_series
from strategy.ifvg import detect_confirmed_ifvgs
from strategy.order_block import detect_order_blocks, mark_mitigated_blocks, OBDirection
from strategy.trendline import detect_trendlines, detect_trendline_reversals, TrendlineDirection
from strategy.signal_engine import Signal, SignalType, Confidence, SetupType, _breakeven_pct
from strategy.support_resistance import build_levels, find_swing_points, Level, LevelType
from backtest.engine import run_backtest, _find_take_profit
from backtest.validation import split_chronological
from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
MIN_CANDLES = 2000
OUT_DIR = Path("results/exp005_sr_tp")
DATA_DIR = Path("data/canonical")


def _atomic_write(path: Path, data: dict):
    tmp = path.with_suffix(".tmp")
    for attempt in range(5):
        try:
            tmp.write_text(json.dumps(data, indent=2, default=str))
            tmp.replace(path)
            return
        except (PermissionError, FileNotFoundError):
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


def _metrics(trades):
    n = len(trades)
    if n == 0:
        return {"n": 0, "win_rate": None, "expectancy_r": None, "total_r": 0.0, "profit_factor": None, "avg_bars_held": None}
    rs = [t.r_multiple for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [abs(r) for r in rs if r < 0]
    pf = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else (999.0 if wins else 0.0)
    bars_held = [t.exit_index - t.entry_fill_index for t in trades if t.entry_fill_index is not None and t.exit_index is not None]
    return {
        "n": n, "win_rate": round(len(wins) / n, 4),
        "expectancy_r": round(sum(rs) / n, 4), "total_r": round(sum(rs), 2),
        "profit_factor": round(pf, 4),
        "avg_bars_held": round(sum(bars_held) / len(bars_held), 1) if bars_held else None,
    }


# --- Modul bazli "cekirdek olay" ureticileri (entry/SL/breakeven -- signal_engine.py
# ile BIREBIR ayni, SADECE take_profit hesabi degisti/ertelendi) ---

def _fvg_base_signals(candles, config):
    all_fvgs = detect_fvgs(candles, config=config)
    mark_filled_fvgs(all_fvgs, candles)
    out = []
    for f in all_fvgs:
        if not f.valid or not f.volume_confirmed:
            continue
        is_bull = f.direction == FVGDirection.BULLISH
        signal_index = f.end_index
        if signal_index >= len(candles):
            continue
        entry = f.entry_price
        buffer = (f.top - f.bottom) * MODULE_SL_BUFFER_RATIO["fvg"]
        stop_loss = f.bottom - buffer if is_bull else f.top + buffer
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        out.append((signal_index, is_bull, entry, stop_loss, risk, f.filled_at_index, "fvg", SetupType.FVG_ONLY, f"FVG({f.direction.value})"))
    return out


def _ifvg_base_signals(candles, config):
    out = []
    for e in detect_confirmed_ifvgs(candles, config=config):
        is_bull = e.new_dir == FVGDirection.BULLISH
        signal_index = e.retest_index
        if signal_index >= len(candles):
            continue
        entry = e.consequent_encroachment
        buffer = (e.top - e.bottom) * MODULE_SL_BUFFER_RATIO["ifvg"]
        stop_loss = (e.bottom - buffer) if is_bull else (e.top + buffer)
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        out.append((signal_index, is_bull, entry, stop_loss, risk, None, "ifvg", SetupType.IFVG_ONLY, f"iFVG({e.new_dir.value})"))
    return out


def _ob_base_signals(candles, config):
    all_obs = detect_order_blocks(candles, config=config)
    mark_mitigated_blocks(all_obs, candles)
    out = []
    for ob in all_obs:
        is_bull = ob.direction == OBDirection.BULLISH
        signal_index = ob.impulse_index
        if signal_index >= len(candles):
            continue
        entry = ob.top if is_bull else ob.bottom
        buffer = (ob.top - ob.bottom) * MODULE_SL_BUFFER_RATIO["ob"]
        stop_loss = (ob.bottom - buffer) if is_bull else (ob.top + buffer)
        risk = abs(entry - stop_loss)
        if risk <= 0:
            continue
        out.append((signal_index, is_bull, entry, stop_loss, risk, ob.mitigated_index, "ob", SetupType.OB_ONLY, f"OB({ob.direction.value})"))
    return out


def _trendline_base_signals(candles, config):
    atr_series = compute_atr_series(candles, config.atr_period)
    lines = detect_trendlines(candles, config=config)
    sl_ratio_tl = MODULE_SL_BUFFER_RATIO["trendline"]
    out = []
    for tl in lines:
        is_bull = tl.direction == TrendlineDirection.ASCENDING
        start = tl.known_index + 1
        end = tl.broken_index if tl.broken_index is not None else len(candles)
        was_touching = False
        for k in range(max(start, 0), min(end, len(candles))):
            line_price = tl.price_at(k)
            tol = (atr_series[k] or 0) * config.trendline_touch_tolerance_atr_ratio
            c = candles[k]
            touched = (c["low"] <= line_price + tol) if is_bull else (c["high"] >= line_price - tol)
            if touched and not was_touching:
                touch_price = c["low"] if is_bull else c["high"]
                buffer = (atr_series[k] or 0) * sl_ratio_tl
                entry = touch_price
                stop_loss = entry - buffer if is_bull else entry + buffer
                risk = abs(entry - stop_loss)
                signal_index = k - 1
                if risk > 0 and signal_index >= 0:
                    out.append((signal_index, is_bull, entry, stop_loss, risk, None, "trendline", SetupType.TRENDLINE_ONLY, f"Trendline-bounce({tl.direction.value})"))
            was_touching = touched

    reversals = detect_trendline_reversals(candles, lines, config=config)
    for r in reversals:
        rc = candles[r.retest_index]
        buffer = (atr_series[r.retest_index] or 0) * sl_ratio_tl
        entry = rc["close"]
        stop_loss = (rc["low"] - buffer) if r.is_bullish else (rc["high"] + buffer)
        risk = abs(entry - stop_loss)
        signal_index = r.retest_index - 1
        if risk <= 0 or signal_index < 0:
            continue
        out.append((signal_index, r.is_bullish, entry, stop_loss, risk, None, "trendline", SetupType.TRENDLINE_ONLY, f"Trendline-reversal({'bullish' if r.is_bullish else 'bearish'})"))
    return out


MODULE_GENERATORS = {
    "fvg": _fvg_base_signals, "ifvg": _ifvg_base_signals,
    "ob": _ob_base_signals, "trendline": _trendline_base_signals,
}


def _compute_sr_tp_map(base_events, atr_series, swing_highs, swing_lows, candles, config):
    """TEK GECISLI (O(n_swing + n_signal)) causal S/R-TP hesabi.

    ONCEKI yaklasim (her sinyal icin levels'i sifirdan yeniden kumelemek)
    buyuk sembollerde (>>10k mum, binlerce sinyal) O(n_signal * n_swing)
    davranip pratikte kullanilamaz hale geliyordu (GOLD'da 20+ dakikada
    bitmedi). Bu versiyon swing'leri (ONAY zamanlarina -- i+swing_lookback
    -- gore) ve sinyalleri TEK bir zaman ekseninde birlestirip artan
    sirada TARIYOR: her swing sadece BIR KEZ kumeleniyor (levels listesine
    ekleniyor/guncelleniyor), her sinyal o ana kadar biriken (SADECE
    kendi index'ine kadar onaylanmis) levels durumunu SORGULUYOR. Sonuc
    build_levels(candles[:idx+1]) ile MATEMATIKSEL OLARAK AYNI -- SADECE
    tekrar hesaplama israfi kaldirildi (bkz. asagidaki causal not).

    KRITIK (causal): find_swing_points bir swing'i ancak ONDAN SONRAKI
    `swing_lookback` mum da goruldukten sonra onaylayabiliyor -- confirm
    zamani = raw_index + swing_lookback. Bir sinyal SADECE confirm
    zamani <= kendi index'i olan swing'leri gorebilir.
    """
    lb = config.swing_lookback
    tolerance_ratio = config.tolerance_atr_ratio
    min_touch = config.min_level_touch_count

    swing_events = [(i + lb, i, LevelType.RESISTANCE, "high") for i in swing_highs]
    swing_events += [(i + lb, i, LevelType.SUPPORT, "low") for i in swing_lows]
    swing_events.sort(key=lambda x: x[0])

    # ONEMLI: birden fazla olay AYNI index'te olabilir (ayni barda iki
    # ayri modul-ici sinyal) -- tp_map'i SADECE idx'e gore anahtarlamak
    # bu durumda BIRINI diğerinin ustune yazardi (yanlis TP). Orijinal
    # liste sirasini (enumerate) da anahtara katip her olayi BENZERSIZ
    # tutuyoruz.
    queries = sorted(enumerate(base_events), key=lambda p: p[1][0])

    levels: list[Level] = []

    def cluster_one(i, level_type, price_key):
        price = candles[i][price_key]
        atr = atr_series[i] or 0
        tolerance = atr * tolerance_ratio
        matched = None
        for lvl in levels:
            if lvl.type == level_type and abs(lvl.price - price) <= tolerance:
                matched = lvl
                break
        if matched:
            matched.price = (matched.price * matched.touch_count + price) / (matched.touch_count + 1)
            matched.touch_count += 1
            matched.last_index = i
        else:
            levels.append(Level(price=price, type=level_type, touch_count=1, first_index=i, last_index=i))

    swing_ptr = 0
    n_swings = len(swing_events)
    tp_map = {}
    for orig_pos, (idx, is_bull, entry, sl, risk, invalid_after, mod, setup_type, reason) in queries:
        while swing_ptr < n_swings and swing_events[swing_ptr][0] <= idx:
            _, raw_i, ltype, pkey = swing_events[swing_ptr]
            cluster_one(raw_i, ltype, pkey)
            swing_ptr += 1
        direction = SignalType.BUY if is_bull else SignalType.SELL
        tp_map[orig_pos] = _find_take_profit(entry, direction, levels, idx, min_level_touch_count=min_touch)
    return tp_map


def _build_signals(base_events, module, config, candles, use_sr_tp, atr_series=None, swing_highs=None, swing_lows=None):
    """base_events -> Signal listesi. use_sr_tp=True ise S/R TP denenir,
    bulunamazsa sabit-R fallback (SKIP YOK); False ise dogrudan sabit-R
    (mevcut resmi davranis, baseline)."""
    r_mult = MODULE_R_MULTIPLE[module]
    signals = []

    tp_map = None
    if use_sr_tp:
        tp_map = _compute_sr_tp_map(base_events, atr_series, swing_highs, swing_lows, candles, config)

    for pos, (idx, is_bull, entry, sl, risk, invalid_after, mod, setup_type, reason) in enumerate(base_events):
        direction = SignalType.BUY if is_bull else SignalType.SELL
        fixed_tp = entry + r_mult * risk if is_bull else entry - r_mult * risk

        if use_sr_tp:
            sr_tp = tp_map.get(pos)
            take_profit = sr_tp if sr_tp is not None else fixed_tp
        else:
            take_profit = fixed_tp

        signals.append(Signal(
            index=idx, type=direction, confidence=Confidence.MEDIUM, setup_type=setup_type,
            entry=entry, stop_loss=sl, take_profit=take_profit,
            breakeven_trigger_pct=_breakeven_pct(mod),
            invalid_after_index=invalid_after, reason=reason,
        ))
    signals.sort(key=lambda s: s.index)
    return signals


def process_symbol(symbol: str) -> dict:
    path = DATA_DIR / f"V2_MULTI_{symbol}_M1_canonical.csv"
    if not path.exists():
        return {"symbol": symbol, "status": "insufficient", "reason": "csv yok"}

    m1 = load_m1_canonical_as_candlev2(str(path))
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]

    if len(candles) < MIN_CANDLES:
        return {"symbol": symbol, "status": "insufficient", "reason": f"M30 mum sayisi ({len(candles)}) < esik"}

    spread = SPREAD_BY_SYMBOL.get(symbol, 0.0)
    config = StrategyConfig(spread=spread)

    _, (train_candles, val_candles, _) = split_chronological(candles, 0.60, 0.20, 0.20)
    trainval = train_candles + val_candles

    # ATR + swing tespiti sembol basina BIR KEZ (bkz. _cluster_levels_fast notu)
    sr_atr_series = compute_atr_series(trainval, config.atr_period)
    swing_highs, swing_lows = find_swing_points(trainval, config=config)

    per_module = {}
    for module, gen_fn in MODULE_GENERATORS.items():
        base_events = gen_fn(trainval, config)
        if not base_events:
            per_module[module] = {"status": "no_events"}
            continue

        baseline_signals = _build_signals(base_events, module, config, trainval, use_sr_tp=False)
        baseline_result = run_backtest(trainval, baseline_signals, config=config)

        srtp_signals = _build_signals(base_events, module, config, trainval, use_sr_tp=True,
                                       atr_series=sr_atr_series, swing_highs=swing_highs, swing_lows=swing_lows)
        srtp_result = run_backtest(trainval, srtp_signals, config=config)

        per_module[module] = {
            "status": "ok",
            "baseline_fixed_r": _metrics(baseline_result.trades),
            "sr_based_tp": _metrics(srtp_result.trades),
        }

    return {"symbol": symbol, "status": "ok", "modules": per_module}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done = {p.stem for p in OUT_DIR.glob("*.json")}
    remaining = [s for s in _ALL_101_SYMBOLS if s not in done]

    def _size(s):
        p = DATA_DIR / f"V2_MULTI_{s}_M1_canonical.csv"
        return p.stat().st_size if p.exists() else 0
    remaining.sort(key=_size)

    print(f"{len(done)}/101 tamamlanmis, {len(remaining)} kaldi", flush=True)

    for i, symbol in enumerate(remaining, start=1):
        t0 = time.time()
        try:
            record = process_symbol(symbol)
        except Exception as e:
            record = {"symbol": symbol, "status": "insufficient", "reason": f"HATA: {type(e).__name__}: {e}"}
        record["elapsed_sec"] = round(time.time() - t0, 1)
        _atomic_write(OUT_DIR / f"{symbol}.json", record)

        if record["status"] != "ok":
            print(f"[{i}/{len(remaining)}] {symbol}: {record['status']} -- {record.get('reason','')} ({record['elapsed_sec']}sn)", flush=True)
        else:
            parts = []
            for mod, mres in record["modules"].items():
                if mres["status"] != "ok":
                    parts.append(f"{mod}=no_events")
                    continue
                b, s = mres["baseline_fixed_r"], mres["sr_based_tp"]
                parts.append(f"{mod}[base_exp={b['expectancy_r']!s}/sr_exp={s['expectancy_r']!s}]")
            print(f"[{i}/{len(remaining)}] {symbol}: " + " ".join(parts) + f" ({record['elapsed_sec']}sn)", flush=True)

    print("\nTAMAMLANDI (101/101 hedef).", flush=True)


if __name__ == "__main__":
    main()
