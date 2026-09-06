"""
Multi-timeframe confluence/conflict + OBJEKTIF ranking.

Onemli: bu katman mevcut strateji kurallarinin YERINE GECMEZ (bkz. proje
talebi "6. MULTI-TIMEFRAME CONFLUENCE") -- sadece scanner/engine.py'nin
urettigi 6 bagimsiz zaman dilimi sonucunu yorumlayan AYRI bir analitik
katmandir.

Ranking KESINLIKLE sembol adina gore degil, objektif kriterlere gore yapilir:
multi-timeframe alignment, expected R, risk (bkz. proje talebi "9. OZEL
PARITE MANTIGINI KALDIR"). Ayni skorda alfabetik sembol sirasi SADECE
deterministik bir tie-break'tir, bir tercih degil.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from scanner.timeframes import TIMEFRAMES, SHORT_TERM, HIGHER_TIMEFRAME


@dataclass
class ConfluenceResult:
    symbol: str
    per_timeframe_verdict: dict = field(default_factory=dict)   # tf -> "BUY"/"SELL"/"MIXED"/"NEUTRAL"/"DATA_INCOMPLETE"/...
    analyzable_timeframes: int = 0
    buy_count: int = 0
    sell_count: int = 0
    neutral_count: int = 0
    dominant_direction: str | None = None
    alignment_score: int = 0          # dominant yonle ayni fikirde olan tf sayisi
    alignment_label: str = "0/0"      # "5/6" gibi
    conflict: bool = False
    conflict_detail: str | None = None


def compute_confluence(symbol: str, tf_results: dict) -> ConfluenceResult:
    """tf_results: {"M30": TimeframeResult, "H1": TimeframeResult, ...}"""
    per_tf = {}
    buy_n = sell_n = neutral_n = analyzable = 0
    for tf in TIMEFRAMES:
        r = tf_results.get(tf)
        if r is None:
            per_tf[tf] = "NOT_SCANNED"
            continue
        if r.status != "OK":
            per_tf[tf] = r.status
            continue
        analyzable += 1
        per_tf[tf] = r.verdict
        if r.verdict == "BUY":
            buy_n += 1
        elif r.verdict == "SELL":
            sell_n += 1
        else:
            neutral_n += 1  # NEUTRAL veya MIXED tek bir tf icinde -- yon belirsiz sayilir

    dominant = None
    alignment = 0
    if buy_n > sell_n:
        dominant, alignment = "BUY", buy_n
    elif sell_n > buy_n:
        dominant, alignment = "SELL", sell_n

    conflict = False
    conflict_detail = None
    short_dirs = {per_tf[tf] for tf in SHORT_TERM if per_tf.get(tf) in ("BUY", "SELL")}
    higher_dirs = {per_tf[tf] for tf in HIGHER_TIMEFRAME if per_tf.get(tf) in ("BUY", "SELL")}
    if short_dirs and higher_dirs and not (short_dirs & higher_dirs):
        conflict = True
        conflict_detail = (
            f"Short-term {'/'.join(sorted(short_dirs))} -- "
            f"Higher-timeframe {'/'.join(sorted(higher_dirs))}"
        )

    return ConfluenceResult(
        symbol=symbol, per_timeframe_verdict=per_tf, analyzable_timeframes=analyzable,
        buy_count=buy_n, sell_count=sell_n, neutral_count=neutral_n,
        dominant_direction=dominant, alignment_score=alignment,
        alignment_label=f"{alignment}/{analyzable}" if analyzable else "0/0",
        conflict=conflict, conflict_detail=conflict_detail,
    )


def rank_candidates(all_results: dict, confluence_by_symbol: dict) -> list[dict]:
    """Tum (sembol, timeframe, aday) uclulerini TEK bir objektif skorla
    siralar: (1) o sembolun MTF alignment_score'u, (2) adayin expected_r'i,
    (3) risk (kucuk risk daha iyi -- normalize edilmis risk yerine ham deger,
    tum semboller ayni R-katli sistemle uretildigi icin karsilastirilabilir).
    Sembol adi SADECE (4). tie-break olarak, alfabetik, tercih degil.
    """
    flat = []
    for symbol, tf_map in all_results.items():
        conf = confluence_by_symbol.get(symbol)
        alignment_score = conf.alignment_score if conf else 0
        alignment_label = conf.alignment_label if conf else "0/0"
        for tf, result in tf_map.items():
            if result.status != "OK":
                continue
            for cand in result.candidates:
                flat.append({
                    "symbol": symbol, "timeframe": tf, **cand,
                    "mtf_alignment_score": alignment_score,
                    "mtf_alignment_label": alignment_label,
                    "conflict": conf.conflict if conf else False,
                })
    flat.sort(key=lambda c: (-c["mtf_alignment_score"], -c["expected_r"], c["risk"], c["symbol"], c["timeframe"]))
    return flat
