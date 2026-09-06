"""
101 sembol x 6 zaman dilimi = 606 analiz isini yoneten pipeline.

Sirali calisir (concurrency YOK) -- bilincli tercih: MetaTrader5 Python
paketinin tek bir global terminal baglantisi var, es zamanli cagrilarin
race condition/bozuk veri riski tasidigi bilinen bir kisitlama (bkz. proje
talebi "11. PARALEL TARAMA -- ...MT5 limits... dikkat edilmeli"). Sinirli
pencere (scanner/timeframes.py:fetch_bars, en fazla 2000 bar) sayesinde
sirali calisma bile hizli (~2-4sn/is, tum tarama ~20-40 dakika) -- tonight's
tam-gecmis (137k+ mum) taramalarindan cok daha az veri.

Kesinti-dayanikli (bu oturumdaki kurulmus desen): sonuclar HER SEMBOL
tamamlandiktan sonra diske yazilir, yeniden baslatilirsa zaten tamamlanmis
semboller ATLANIR.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from dataclasses import asdict

from strategy.config import _ALL_101_SYMBOLS, KEPT_SYMBOLS
from scanner.timeframes import TIMEFRAMES
from scanner.engine import analyze_symbol_timeframe, TimeframeResult
from scanner.confluence import compute_confluence, rank_candidates, ConfluenceResult

RESULTS_PATH = "scanner_results.json"
CONFLUENCE_PATH = "scanner_confluence.json"
CANDIDATES_PATH = "scanner_candidates.json"
PROGRESS_PATH = "scanner_progress.json"


def _tf_result_to_dict(r: TimeframeResult) -> dict:
    d = asdict(r)
    return d


def _confluence_to_dict(c: ConfluenceResult) -> dict:
    return asdict(c)


def _load_json(path: str, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def _write_progress(state: dict) -> None:
    state["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def run_full_scan(symbols: list[str] | None = None) -> None:
    symbols = symbols if symbols is not None else sorted(_ALL_101_SYMBOLS)
    total_jobs = len(symbols) * len(TIMEFRAMES)

    results = _load_json(RESULTS_PATH, {})
    confluence = _load_json(CONFLUENCE_PATH, {})
    done_symbols = set(results.keys())

    completed_jobs = sum(len(v) for v in results.values())
    progress = {
        "total_instruments": len(symbols), "total_timeframes": len(TIMEFRAMES),
        "total_jobs": total_jobs, "completed_jobs": completed_jobs,
        "scanned_instruments": len(done_symbols),
        "status": "RUNNING", "current": None,
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
        "kept_symbols_note": "KEPT_SYMBOLS (canli trade edilen) bu taramada OZEL muamele gormuyor -- ayni pipeline",
        "kept_symbols": list(KEPT_SYMBOLS),
        "log": [],
    }
    _write_progress(progress)

    print(f"toplam {len(symbols)} sembol x {len(TIMEFRAMES)} zaman dilimi = {total_jobs} is", flush=True)
    if done_symbols:
        print(f"onceden tamamlanmis {len(done_symbols)} sembol atlanacak", flush=True)

    for i, symbol in enumerate(symbols):
        if symbol in done_symbols:
            continue
        t0 = time.time()
        tf_map_raw = {}
        for tf in TIMEFRAMES:
            progress["current"] = f"{symbol} / {tf}"
            _write_progress(progress)
            try:
                r = analyze_symbol_timeframe(symbol, tf)
            except Exception as e:
                r = TimeframeResult(symbol=symbol, timeframe=tf, status="FETCH_ERROR", reason=f"{type(e).__name__}: {e}")
            tf_map_raw[tf] = r
            progress["completed_jobs"] += 1

        results[symbol] = {tf: _tf_result_to_dict(r) for tf, r in tf_map_raw.items()}
        conf = compute_confluence(symbol, tf_map_raw)
        confluence[symbol] = _confluence_to_dict(conf)
        progress["scanned_instruments"] = len(results)

        elapsed = time.time() - t0
        ok_count = sum(1 for r in tf_map_raw.values() if r.status == "OK")
        log_line = f"[{i+1}/{len(symbols)}] {symbol}: {ok_count}/{len(TIMEFRAMES)} OK ({elapsed:.1f}s)"
        print(log_line, flush=True)
        progress["log"].append(log_line)
        progress["log"] = progress["log"][-30:]  # sadece son 30 satir tut

        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, default=str)
        with open(CONFLUENCE_PATH, "w", encoding="utf-8") as f:
            json.dump(confluence, f, ensure_ascii=False, default=str)
        _write_progress(progress)

    # Tum sembollerin sonuclari elde -- ranking'i hesapla ve yaz
    tf_result_objs = {}
    for symbol, tf_map in results.items():
        tf_result_objs[symbol] = {tf: TimeframeResult(**d) for tf, d in tf_map.items()}
    confluence_objs = {s: ConfluenceResult(**d) for s, d in confluence.items()}
    ranked = rank_candidates(tf_result_objs, confluence_objs)
    with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
        json.dump(ranked, f, ensure_ascii=False, default=str)

    progress["status"] = "COMPLETED"
    progress["current"] = None
    _write_progress(progress)
    print(f"\nTAMAMLANDI. {len(results)} sembol, {progress['completed_jobs']}/{total_jobs} is.", flush=True)


if __name__ == "__main__":
    run_full_scan()
