"""
Experiment #007, ADIM 4 -- Deney #006'nin (confluence-only) pozitif
sonucu, Trendline'in kombinasyonlara dahil olmasindan mi kaynaklaniyor?

YONTEM: #004d/#006 ile AYNI sinyal/backtest gecisi (generate_signals +
run_backtest, TEK backtest, post-hoc ayirma) -- ama confluence bulunan
her islem icin, konfluensi SAGLAYAN ES(LER)IN en az biri Trendline mi
(ya da sinyalin KENDISI Trendline mi) ayrica etiketleniyor. Boylece
confluence_only islemleri iki ayrik kumeye bolunuyor:
  - confluence_with_trendline    (sinyal veya en az bir es Trendline)
  - confluence_without_trendline (FVG/iFVG/OB kombinasyonlari, Trendline YOK)

KUTSAL KURAL: SADECE train+val (%80), holdout HIC KULLANILMADI. 101
sembolun TAMAMI. Checkpoint'li/kesintiye dayanikli (sembol basina atomik
JSON yazimi, exp004d ile AYNI desen).
"""

import bisect
import json
import time
from pathlib import Path

from strategy.config import StrategyConfig, _ALL_101_SYMBOLS
from strategy.signal_engine import generate_signals, SetupType
from backtest.engine import run_backtest
from backtest.validation import split_chronological
from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
MIN_CANDLES = 2000
CONFLUENCE_WINDOW_BARS = 10
OUT_DIR = Path("results/exp007_confluence_trendline_split")
DATA_DIR = Path("data/canonical")

TRENDLINE_KEY = SetupType.TRENDLINE_ONLY.value


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


def _compute_confluence_involves_trendline(signals):
    """Her sinyal icin: (confluence_ok, involves_trendline).
    confluence_ok -- #004d/#006 ile AYNI tanim (herhangi baska bir
    modulden, ayni yonde, +-WINDOW icinde EN AZ 1 sinyal).
    involves_trendline -- sinyalin KENDISI Trendline ise VEYA konfluensi
    saglayan ES(LER)DEN EN AZ BIRI Trendline ise (ORIJINAL algoritmanin
    aksine, ILK bulunan modulde durmuyor -- Trendline'in katilip
    katilmadigini AYRICA, tum modulleri tarayarak kontrol ediyor)."""
    by_module_dir = {}
    for s in signals:
        key = (s.setup_type.value, s.type.value)
        by_module_dir.setdefault(key, []).append(s.index)
    for key in by_module_dir:
        by_module_dir[key].sort()

    result = {}
    for s in signals:
        confluence_ok = False
        involves_trendline = (s.setup_type.value == TRENDLINE_KEY)
        for (mod, direction), idxs in by_module_dir.items():
            if mod == s.setup_type.value or direction != s.type.value:
                continue
            lo = bisect.bisect_left(idxs, s.index - CONFLUENCE_WINDOW_BARS)
            hi = bisect.bisect_right(idxs, s.index + CONFLUENCE_WINDOW_BARS)
            if hi > lo:
                confluence_ok = True
                if mod == TRENDLINE_KEY:
                    involves_trendline = True
        result[id(s)] = (confluence_ok, involves_trendline)
    return result


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

    flags = _compute_confluence_involves_trendline(signals)
    per_signal = {s.index: flags[id(s)] for s in signals}

    result = run_backtest(trainval, signals, config=config)
    if not result.trades:
        return {"symbol": symbol, "status": "no_trades"}

    baseline_trades = result.trades
    confluence_all, with_tl, without_tl = [], [], []
    for t in baseline_trades:
        idx = t.signal.index
        confluence_ok, involves_tl = per_signal.get(idx, (False, False))
        if confluence_ok:
            confluence_all.append(t)
            if involves_tl:
                with_tl.append(t)
            else:
                without_tl.append(t)

    return {
        "symbol": symbol, "status": "ok",
        "baseline": _metrics(baseline_trades),
        "confluence_all": _metrics(confluence_all),
        "confluence_with_trendline": _metrics(with_tl),
        "confluence_without_trendline": _metrics(without_tl),
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
            b, ca, wt, wot = record["baseline"], record["confluence_all"], record["confluence_with_trendline"], record["confluence_without_trendline"]
            print(f"[{i}/{len(remaining)}] {symbol}: BASE n={b['n']:>5} exp={b['expectancy_r']!s:>8} | "
                  f"CONFL_ALL n={ca['n']:>5} exp={ca['expectancy_r']!s:>8} | "
                  f"WITH_TL n={wt['n']:>5} exp={wt['expectancy_r']!s:>8} | "
                  f"WITHOUT_TL n={wot['n']:>5} exp={wot['expectancy_r']!s:>8} ({record['elapsed_sec']}sn)", flush=True)

    print("\nTAMAMLANDI (101/101 hedef).", flush=True)


if __name__ == "__main__":
    main()
