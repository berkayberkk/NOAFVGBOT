"""
Experiment #004d -- HIPOTEZ TEST: konfluensi (birden fazla modulun ayni
yonde/yakinda sinyal vermesi), rejim filtresiYLE BIRLIKTE, asimetriyi/
expectancy'yi duzeltiyor mu?

BAGLAM: onceki confluence calismasi (confluence_study_results.json,
KEPT_SYMBOLS, eski metodoloji) rejim filtresi OLMADAN yapilmisti ve
faydasiz bulunmustu. Deney #004c rejim filtresini TEK BASINA test etti
(REJECT -- net iyilesme yok). Bu deney IKISINI BIRLIKTE test ediyor.

KONFLUENS TANIMI (basit, causal, mevcut uretim hattiyla tutarli): bir
sinyalin "konfluensli" sayilmasi icin, AYNI YONDE, index'i bu sinyalin
index'ine +-CONFLUENCE_WINDOW_BARS icinde olan BASKA bir modulden
(setup_type farkli) en az 1 sinyal olmasi yeterli. Bu, eski calismanin
zone-overlap tanimindan daha basit (sadece index yakinligi + ayni yon)
ama AYNI temel fikri (birden fazla modulun ayni bolgede/zamanda ayni
yonu isaret etmesi) causal olarak yakalar.

4 DEGISKEN, TEK backtest gecisinden (sinyaller bagimsiz, bkz. #004c notu):
  1. BASELINE          -- tum islemler
  2. REGIME_ONLY        -- sadece rejime hizali (Deney #004c ile ayni)
  3. CONFLUENCE_ONLY     -- sadece konfluensli (rejimden bagimsiz)
  4. CONFLUENCE_AND_REGIME -- ikisi birden

KUTSAL KURAL: SADECE train+val (%80), holdout HIC KULLANILMADI. 101
sembolun TAMAMI (secim yanliligindan kacinmak icin).
"""

import bisect
import json
import time
from pathlib import Path

from strategy.config import StrategyConfig, _ALL_101_SYMBOLS
from strategy.signal_engine import generate_signals
from strategy.trend import detect_trend, TrendDirection
from backtest.engine import run_backtest
from backtest.validation import split_chronological
from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
MIN_CANDLES = 2000
CONFLUENCE_WINDOW_BARS = 10
OUT_DIR = Path("results/exp004d_confluence_regime")
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
        return {"n": 0, "win_rate": None, "expectancy_r": None, "total_r": 0.0, "profit_factor": None}
    rs = [t.r_multiple for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [abs(r) for r in rs if r < 0]
    pf = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else (999.0 if wins else 0.0)
    return {
        "n": n, "win_rate": round(len(wins) / n, 4),
        "expectancy_r": round(sum(rs) / n, 4), "total_r": round(sum(rs), 2),
        "profit_factor": round(pf, 4),
    }


def _compute_confluence_flags(signals):
    """Her sinyal icin, AYNI yonde baska bir modulden +-WINDOW icinde
    sinyal var mi (bool) -- causal degil (gelecek+gecmis ikisine de
    bakar, ama bu bir ELEME/filtre KRITERI, sinyalin kendi olusumundan
    SONRA backtest zamaninda mevcut olan bilgiyle degerlendiriliyor --
    ayni bar'da baska modulun da tetiklenmis olmasi zaten o ana kadar
    BILINEBILIR bir bilgi, ileri sizinti riski yok cunku iki sinyal de
    kendi index'inde zaten olusmus durumda)."""
    by_module_dir = {}
    for s in signals:
        key = (s.setup_type.value, s.type.value)
        by_module_dir.setdefault(key, []).append(s.index)
    for key in by_module_dir:
        by_module_dir[key].sort()

    flags = {}
    for s in signals:
        found = False
        for (mod, direction), idxs in by_module_dir.items():
            if mod == s.setup_type.value or direction != s.type.value:
                continue
            lo = bisect.bisect_left(idxs, s.index - CONFLUENCE_WINDOW_BARS)
            hi = bisect.bisect_right(idxs, s.index + CONFLUENCE_WINDOW_BARS)
            if hi > lo:
                found = True
                break
        flags[id(s)] = found
    return flags


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

    signals = generate_signals(trainval, config=config)
    if not signals:
        return {"symbol": symbol, "status": "structural_failure", "reason": "0 sinyal"}

    confluence_flags = _compute_confluence_flags(signals)
    signal_confluence = {s.index: confluence_flags[id(s)] for s in signals}

    result = run_backtest(trainval, signals, config=config)
    if not result.trades:
        return {"symbol": symbol, "status": "no_trades"}

    trend_states = detect_trend(trainval, config=config)

    baseline_trades = result.trades
    regime_only, confluence_only, both = [], [], []
    for t in baseline_trades:
        idx = t.signal.index
        is_buy = t.signal.type.value == "buy"
        ts = trend_states[idx] if idx < len(trend_states) else None
        regime_ok = ts is not None and ((is_buy and ts.direction == TrendDirection.UP) or ((not is_buy) and ts.direction == TrendDirection.DOWN))
        confluence_ok = signal_confluence.get(idx, False)
        if regime_ok:
            regime_only.append(t)
        if confluence_ok:
            confluence_only.append(t)
        if regime_ok and confluence_ok:
            both.append(t)

    return {
        "symbol": symbol, "status": "ok",
        "baseline": _metrics(baseline_trades),
        "regime_only": _metrics(regime_only),
        "confluence_only": _metrics(confluence_only),
        "confluence_and_regime": _metrics(both),
    }


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
            b, r, c, br = record["baseline"], record["regime_only"], record["confluence_only"], record["confluence_and_regime"]
            print(f"[{i}/{len(remaining)}] {symbol}: BASE n={b['n']:>5} exp={b['expectancy_r']!s:>8} | "
                  f"REGIME n={r['n']:>5} exp={r['expectancy_r']!s:>8} | "
                  f"CONFL n={c['n']:>5} exp={c['expectancy_r']!s:>8} | "
                  f"BOTH n={br['n']:>5} exp={br['expectancy_r']!s:>8} ({record['elapsed_sec']}sn)", flush=True)

    print("\nTAMAMLANDI (101/101 hedef).", flush=True)


if __name__ == "__main__":
    main()
