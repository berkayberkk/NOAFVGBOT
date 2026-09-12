"""
Experiment #004c -- HIPOTEZ TESTI: rejim filtresi (trend.py, NOA'siz)
LONG/SHORT asimetrisini gercekten duzeltiyor mu?

YONTEM: sinyaller BIR KEZ uretilir, backtest BIR KEZ calisir (run_backtest
sinyaller arasinda bagimsizdir -- bir sinyali listeden cikarmak digerlerinin
cozumunu ETKILEMEZ, bkz. backtest/engine.py). Rejim filtresi POST-HOC
uygulanir: her islem icin, sinyalin kendi index'indeki trend.py rejimi
(HH/HL+EMA, jenerik TA -- zone.py/NOA DEGIL) ile sinyalin yonu (BUY/SELL)
karsilastirilir. "REJIM-HIZALI" = trend UP iken BUY, trend DOWN iken SELL.
Boylece TEK bir backtest'ten hem BASELINE (tum islemler) hem FILTRELI
(sadece rejim-hizali islemler) sonucu ayni anda cikariliyor -- ayri ayri
iki backtest calistirmaya (2x maliyet) gerek yok, sonuc MATEMATIKSEL
olarak ayni (backtest engine sinyaller arasinda bagimsiz).

KAPSAM: 101 sembolun TAMAMI (Deney #002/003'un frozen universe'i,
sadece 4 PASS sembolde test etmek SECIM YANLILIGI olurdu -- kullanicinin
acik uyarisi). Checkpoint/resume: her sembolun sonucu KENDI dosyasina.

KUTSAL KURAL: SADECE train+val (%60+%20=%80) kullanilir, holdout (%20)
HIC KULLANILMIYOR -- bu bir HIPOTEZ TARAMASI, nihai karar degil.

ISLEM SAYISI vs EXPECTANCY AYRIMI: filtreli sonucta trade count baseline'a
gore ORANTISIZ dustuyse ("sadece SHORT sayisini azaltip sorunu gizliyor"
riski) bu ACIKCA raporlanir -- filtrenin GERCEKTEN kaliteyi mi arttirdigi
yoksa sadece kotu islemleri mi eledigi (ki bu da mesru bir iyilesme
olabilir, ama "gizleme" ile "gercek iyilesme" ayni sey degil) ayri
metriklerle gosterilir.
"""

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
OUT_DIR = Path("results/exp004c_regime_filter")
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

    result = run_backtest(trainval, signals, config=config)
    if not result.trades:
        return {"symbol": symbol, "status": "no_trades"}

    trend_states = detect_trend(trainval, config=config)

    baseline_trades = result.trades
    aligned_trades = []
    for t in baseline_trades:
        idx = t.signal.index
        if idx >= len(trend_states):
            continue
        ts = trend_states[idx]
        is_buy = t.signal.type.value == "buy"
        aligned = (is_buy and ts.direction == TrendDirection.UP) or ((not is_buy) and ts.direction == TrendDirection.DOWN)
        if aligned:
            aligned_trades.append(t)

    baseline_m = _metrics(baseline_trades)
    filtered_m = _metrics(aligned_trades)

    baseline_buy = [t for t in baseline_trades if t.signal.type.value == "buy"]
    baseline_sell = [t for t in baseline_trades if t.signal.type.value == "sell"]
    filtered_buy = [t for t in aligned_trades if t.signal.type.value == "buy"]
    filtered_sell = [t for t in aligned_trades if t.signal.type.value == "sell"]

    return {
        "symbol": symbol, "status": "ok",
        "baseline": baseline_m, "regime_filtered": filtered_m,
        "baseline_by_direction": {"buy": _metrics(baseline_buy), "sell": _metrics(baseline_sell)},
        "filtered_by_direction": {"buy": _metrics(filtered_buy), "sell": _metrics(filtered_sell)},
        "trade_retention_pct": round(100 * filtered_m["n"] / baseline_m["n"], 1) if baseline_m["n"] else None,
        "expectancy_delta_r": round((filtered_m["expectancy_r"] or 0) - (baseline_m["expectancy_r"] or 0), 4),
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
            b, f = record["baseline"], record["regime_filtered"]
            print(f"[{i}/{len(remaining)}] {symbol}: BASELINE n={b['n']:>5} exp={b['expectancy_r']!s:>8} win={b['win_rate']!s:>7} | "
                  f"FILTRELI n={f['n']:>5} exp={f['expectancy_r']!s:>8} win={f['win_rate']!s:>7} | "
                  f"retention={record['trade_retention_pct']}% delta={record['expectancy_delta_r']:+.4f} ({record['elapsed_sec']}sn)", flush=True)

    print("\nTAMAMLANDI (101/101 hedef).", flush=True)


if __name__ == "__main__":
    main()
