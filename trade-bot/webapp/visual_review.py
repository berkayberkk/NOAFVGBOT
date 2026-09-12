"""
FAZ A -- Görsel İnceleme Paneli (talep üzerine / canlı hesaplama).

Bu modül NOAFVGBOT'un KENDİ tespit motorunu ve gerçek sinyal/backtest
hattını DOĞRUDAN çağırır -- ayrı/paralel bir tespit veya backtest mantığı
YOK, burada sadece mevcut fonksiyonların çıktısını gruplayıp JSON'a
dönüştüren "görselleştirme kaplaması" var:

- Tespit: strategy/fvg.py, ifvg.py, order_block.py, trendline.py
  (detect_fvgs/detect_all_ifvg_candidates/detect_order_blocks/detect_trendlines)
- Sinyal: strategy/signal_engine.py:generate_signals (TAM production
  pipeline, 4 modül birlikte -- tek backtest geçişi)
- Backtest/sonuç: backtest/engine.py:run_backtest (Trade.won/r_multiple/
  is_breakeven BURADAN okunuyor, ayrı bir R hesabı YAPILMIYOR)

KUTSAL KURAL: SADECE train+val (%80) üzerinde çalışır -- holdout (%20)
hiç kullanılmıyor. Bu aynı zamanda #6'daki tutarlılık kontrolünün elma-
elmayla karşılaştırma olmasını sağlıyor (results/exp005_sr_tp/*.json da
AYNI train+val bölmesiyle üretildi).

Panel SADECE inceleme amaçlıdır -- config.py'ye hiçbir yazma yapmaz,
"canlıya al" gibi bir eylem YOKTUR.
"""

from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from strategy.config import StrategyConfig, MODULE_SL_BUFFER_RATIO
from strategy.signal_engine import generate_signals, SetupType, SignalType
from strategy.fvg import detect_fvgs, mark_filled_fvgs, FVGDirection
from strategy.ifvg import detect_all_ifvg_candidates
from strategy.support_resistance import build_levels, LevelType
from backtest.engine import run_backtest
from backtest.validation import split_chronological
from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "canonical")
NOTES_PATH = os.path.join(PROJECT_ROOT, "results", "visual_review_notes.json")
EXP005_DIR = os.path.join(PROJECT_ROOT, "results", "exp005_sr_tp")

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
MODULE_KEY_BY_SETUP = {
    SetupType.FVG_ONLY: "fvg", SetupType.IFVG_ONLY: "ifvg",
    SetupType.OB_ONLY: "ob", SetupType.TRENDLINE_ONLY: "trendline",
}
MODULE_NAMES = {"fvg": "FVG", "ifvg": "iFVG", "ob": "Order Block", "trendline": "Trendline"}
TIMEFRAMES = {"M5": Timeframe.M5, "M15": Timeframe.M15, "M30": Timeframe.M30,
              "H1": Timeframe.H1, "H4": Timeframe.H4, "D1": Timeframe.D1}
OFFICIAL_TIMEFRAME = "M30"  # results/exp005_sr_tp/ vb. HEP M30'da üretildi -- tutarlılık kontrolü sadece burada mümkün

MAX_SR_LEVELS = 6
PRE_BARS = 40
POST_BARS = 15
MAX_POST_ENTRY_BARS = 200
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def discover_symbols() -> list[str]:
    paths = glob.glob(os.path.join(DATA_DIR, "V2_MULTI_*_M1_canonical.csv"))
    syms = []
    for p in paths:
        m = re.search(r"V2_MULTI_(.+)_M1_canonical\.csv$", os.path.basename(p))
        if m:
            syms.append(m.group(1))
    return sorted(syms)


def _load_candles(symbol: str, timeframe_key: str) -> list[dict]:
    tf = TIMEFRAMES[timeframe_key]
    m1 = load_m1_canonical_as_candlev2(os.path.join(DATA_DIR, f"V2_MULTI_{symbol}_M1_canonical.csv"))
    resampled, _ = resample_m1(m1, tf)
    return [candlev2_to_strategy_dict(c) for c in resampled]


def _candles_json(candles: list[dict]) -> list[dict]:
    return [{"t": c["time"].isoformat(), "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]} for c in candles]


def _window(candles: list[dict], center_index: int, exit_index: int | None):
    start = max(0, center_index - PRE_BARS)
    natural_end = (exit_index if exit_index is not None else center_index) + POST_BARS + 1
    capped_end = center_index + MAX_POST_ENTRY_BARS
    end = min(len(candles), natural_end, capped_end)
    truncated = natural_end > capped_end
    return truncated, _candles_json(candles[start:end]), start


def _nearby_sr_levels(candles: list[dict], signal_index: int, price_lo: float, price_hi: float) -> list[dict]:
    causal = candles[:signal_index + 1]
    if len(causal) < 20:
        return []
    levels = build_levels(causal)
    in_range = [lvl for lvl in levels if price_lo <= lvl.price <= price_hi]
    in_range.sort(key=lambda lvl: -lvl.touch_count)
    return [{"price": lvl.price, "type": "resistance" if lvl.type == LevelType.RESISTANCE else "support",
             "touch_count": lvl.touch_count} for lvl in in_range[:MAX_SR_LEVELS]]


def _zone_bounds(entry: float, sl: float, is_buy: bool, module_key: str):
    """Signal'in entry/sl'inden zone (gap/gövde) sınırlarını geri türetir --
    scratch_generate_module_examples.py:zone_bounds ile AYNI özdeşlik."""
    if module_key == "trendline":
        return None
    risk = abs(entry - sl)
    ratio = MODULE_SL_BUFFER_RATIO[module_key]
    zone_size = risk / (1 + ratio)
    if is_buy:
        return {"top": entry, "bottom": entry - zone_size}
    return {"top": entry + zone_size, "bottom": entry}


def _traded_example(symbol: str, module_key: str, trade, candles: list[dict]) -> dict:
    signal_index = trade.signal.index
    exit_idx = trade.exit_index
    truncated, window, window_start = _window(candles, signal_index, exit_idx)
    is_buy = trade.signal.type == SignalType.BUY
    zone = _zone_bounds(trade.entry_price, trade.stop_loss, is_buy, module_key)
    bars_held = (exit_idx - signal_index) if exit_idx is not None else None
    outcome = "breakeven" if trade.is_breakeven else ("win" if trade.won else "loss")

    price_lo = min((c["l"] for c in window), default=trade.entry_price)
    price_hi = max((c["h"] for c in window), default=trade.entry_price)
    for v in (trade.entry_price, trade.stop_loss, trade.take_profit):
        price_lo, price_hi = min(price_lo, v), max(price_hi, v)
    sr_levels = _nearby_sr_levels(candles, signal_index, price_lo, price_hi)

    return {
        "symbol": symbol, "module": module_key, "valid": True, "signal_index": signal_index,
        "direction": "BUY" if is_buy else "SELL",
        "entry": trade.entry_price, "sl": trade.stop_loss, "tp": trade.take_profit,
        "r_multiple": round(trade.r_multiple, 4) if trade.r_multiple is not None else None,
        "outcome": outcome, "zone": zone, "sr_levels": sr_levels,
        "signal_time": candles[signal_index]["time"].isoformat() if signal_index < len(candles) else None,
        "entry_fill_time": candles[trade.entry_fill_index]["time"].isoformat() if trade.entry_fill_index is not None and trade.entry_fill_index < len(candles) else None,
        "exit_time": candles[exit_idx]["time"].isoformat() if exit_idx is not None and exit_idx < len(candles) else None,
        "candles": window, "window_start_index": window_start,
        "reason": trade.signal.reason, "bars_held": bars_held, "chart_truncated": truncated,
        "invalid_reason": None,
    }


def _invalid_example(symbol: str, module_key: str, signal_index: int, direction: str, zone, reason: str, candles: list[dict]) -> dict:
    truncated, window, window_start = _window(candles, signal_index, None)
    return {
        "symbol": symbol, "module": module_key, "valid": False, "signal_index": signal_index,
        "direction": direction, "entry": None, "sl": None, "tp": None, "r_multiple": None,
        "outcome": "invalid", "zone": zone, "sr_levels": [],
        "signal_time": candles[signal_index]["time"].isoformat() if signal_index < len(candles) else None,
        "entry_fill_time": None, "exit_time": None,
        "candles": window, "window_start_index": window_start,
        "reason": None, "bars_held": None, "chart_truncated": truncated,
        "invalid_reason": reason,
    }


def _collect_invalid_candidates(module_key: str, candles: list[dict], config: StrategyConfig) -> list[dict]:
    """Sinyale DÖNÜŞMEYEN (geçersiz/filtrelenmiş) tespit adaylarının HAFİF
    (mum penceresi OLMADAN) listesi -- FVG/iFVG için gerçek invalid_reason/
    chop_cluster bilgisiyle; OB/Trendline'da bu kavram KODDA YOK (bkz. modül
    docstring'leri, `strategy/order_block.py` ve `strategy/trendline.py`
    hiçbir tespiti eleyen bir 'valid' alanı taşımıyor) -- bu yüzden bu iki
    modülde liste her zaman BOŞ döner, bu bir eksiklik değil koddaki
    gerçeği yansıtıyor."""
    out = []
    if module_key == "fvg":
        all_fvgs = detect_fvgs(candles, config=config)
        mark_filled_fvgs(all_fvgs, candles)
        for f in all_fvgs:
            if f.valid and f.volume_confirmed:
                continue  # bu zaten traded (gecerli) sinyal -- burada tekrar gosterilmiyor
            reason = f.invalid_reason if not f.valid else "hacim teyidi yok (volume_confirmed=False)"
            direction = "BUY" if f.direction == FVGDirection.BULLISH else "SELL"
            out.append({"signal_index": f.end_index, "direction": direction,
                        "zone": {"top": f.top, "bottom": f.bottom}, "reason": reason})
    elif module_key == "ifvg":
        events = detect_all_ifvg_candidates(candles, config=config)
        for e in events:
            if not e.chop_cluster:
                continue  # confirmed -- traded'de
            direction = "BUY" if e.new_dir == FVGDirection.BULLISH else "SELL"
            out.append({"signal_index": e.retest_index, "direction": direction,
                        "zone": {"top": e.top, "bottom": e.bottom},
                        "reason": "chop-cluster (yakın zamanlı zıt yönlü çakışma ile elendi)"})
    return out


def _consistency_check(symbol: str, module_key: str, timeframe_key: str,
                       computed_n: int, computed_exp: float | None, computed_win_rate: float | None) -> dict:
    if timeframe_key != OFFICIAL_TIMEFRAME:
        return {"checked": False, "match": None,
                "message": f"sadece {OFFICIAL_TIMEFRAME} zaman diliminde resmi backtest sonucu mevcut -- "
                           f"{timeframe_key} için karşılaştırma yapılmadı."}
    path = os.path.join(EXP005_DIR, f"{symbol}.json")
    if not os.path.exists(path):
        return {"checked": False, "match": None,
                "message": f"{symbol} için results/exp005_sr_tp/ sonucu bulunamadı -- karşılaştırma yapılamadı."}
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError:
        return {"checked": False, "match": None, "message": "results/exp005_sr_tp/ dosyası bozuk -- karşılaştırma yapılamadı."}
    if data.get("status") != "ok":
        return {"checked": False, "match": None,
                "message": f"resmi sonuç status={data.get('status')!r} -- karşılaştırma yapılamadı."}
    mres = (data.get("modules") or {}).get(module_key)
    if not mres or mres.get("status") != "ok":
        return {"checked": False, "match": None,
                "message": f"{module_key} için resmi sonuç yok (no_events olabilir) -- karşılaştırma yapılamadı."}
    official = mres["baseline_fixed_r"]
    off_n, off_exp, off_wr = official["n"], official["expectancy_r"], official["win_rate"]
    n_match = (computed_n == off_n)
    exp_match = (computed_exp is not None and off_exp is not None and abs(computed_exp - off_exp) < 0.001)
    ok = n_match and exp_match
    return {
        "checked": True,
        "official": {"n": off_n, "expectancy_r": off_exp, "win_rate": off_wr},
        "computed": {"n": computed_n, "expectancy_r": computed_exp, "win_rate": computed_win_rate},
        "match": ok,
        "message": ("resmi backtest sonucuyla (results/exp005_sr_tp/) EŞLEŞİYOR" if ok else
                    "UYUŞMAZLIK: panelin şimdi hesapladığı sonuç results/exp005_sr_tp/ ile FARKLI -- "
                    "olası neden: strategy/ kodu bu deneyden sonra değişti, veri güncellendi, ya da "
                    "farklı bir spread varsayımı kullanılıyor. Aşağıdaki sinyalleri buna göre değerlendirin."),
    }


def build_review(symbol: str, timeframe_key: str, module_key: str,
                 outcome_filter: str | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> dict:
    if module_key not in MODULE_NAMES:
        return {"error": f"bilinmeyen modül: {module_key}"}
    if timeframe_key not in TIMEFRAMES:
        return {"error": f"bilinmeyen zaman dilimi: {timeframe_key}"}
    csv_path = os.path.join(DATA_DIR, f"V2_MULTI_{symbol}_M1_canonical.csv")
    if not os.path.exists(csv_path):
        return {"error": f"{symbol} için veri dosyası yok"}
    limit = max(1, min(MAX_LIMIT, limit))
    offset = max(0, offset)

    candles = _load_candles(symbol, timeframe_key)
    if len(candles) < 200:
        return {"error": f"{timeframe_key} zaman diliminde yeterli mum yok (n={len(candles)})"}

    config = StrategyConfig(spread=SPREAD_BY_SYMBOL.get(symbol, 0.0))
    _, (train_candles, val_candles, _) = split_chronological(candles, 0.60, 0.20, 0.20)
    trainval = train_candles + val_candles  # KUTSAL KURAL: holdout hiç kullanılmıyor

    all_signals = generate_signals(trainval, config=config)
    module_signal_ids = {id(s) for s in all_signals if MODULE_KEY_BY_SETUP.get(s.setup_type) == module_key}
    result = run_backtest(trainval, all_signals, config=config)  # TEK, TAM production backtest geçişi
    module_trades = [t for t in result.trades if id(t.signal) in module_signal_ids]

    valid_trades = [t for t in module_trades if t.r_multiple is not None]
    computed_n = len(valid_trades)
    computed_exp = round(sum(t.r_multiple for t in valid_trades) / computed_n, 4) if computed_n else None
    computed_wins = sum(1 for t in valid_trades if t.r_multiple > 0)
    computed_win_rate = round(computed_wins / computed_n, 4) if computed_n else None

    invalid_candidates = _collect_invalid_candidates(module_key, trainval, config)

    # Hafif tanımlayıcılar (mum penceresi henüz YOK) -- sıralama/filtre/sayfalama
    # BUNLAR üzerinden yapılır, pahalı mum-penceresi cizimi SADECE gösterilecek
    # sayfa için (asagida) hesaplanir.
    descriptors = []
    for t in module_trades:
        idx = t.signal.index
        outcome = "breakeven" if t.is_breakeven else ("win" if t.won else "loss")
        descriptors.append({"kind": "traded", "ref": t, "signal_index": idx,
                            "signal_time": trainval[idx]["time"] if idx < len(trainval) else datetime.min,
                            "outcome": outcome})
    for cand in invalid_candidates:
        idx = cand["signal_index"]
        descriptors.append({"kind": "invalid", "ref": cand, "signal_index": idx,
                            "signal_time": trainval[idx]["time"] if idx < len(trainval) else datetime.min,
                            "outcome": "invalid"})

    if outcome_filter:
        descriptors = [d for d in descriptors if d["outcome"] == outcome_filter]
    descriptors.sort(key=lambda d: d["signal_time"], reverse=True)
    total = len(descriptors)
    page = descriptors[offset:offset + limit]

    examples = []
    for d in page:
        if d["kind"] == "traded":
            examples.append(_traded_example(symbol, module_key, d["ref"], trainval))
        else:
            c = d["ref"]
            examples.append(_invalid_example(symbol, module_key, c["signal_index"], c["direction"], c["zone"], c["reason"], trainval))

    consistency = _consistency_check(symbol, module_key, timeframe_key, computed_n, computed_exp, computed_win_rate)

    return {
        "symbol": symbol, "timeframe": timeframe_key, "module": module_key,
        "total_candles": len(candles), "trainval_candles": len(trainval),
        "total_traded": len(module_trades), "total_invalid": len(invalid_candidates),
        "total_filtered": total, "shown": len(examples), "offset": offset, "limit": limit,
        "aggregate": {"n": computed_n, "expectancy_r": computed_exp, "win_rate": computed_win_rate},
        "consistency": consistency,
        "examples": examples,
    }


def append_note(payload: dict) -> dict:
    os.makedirs(os.path.dirname(NOTES_PATH), exist_ok=True)
    notes = []
    if os.path.exists(NOTES_PATH):
        try:
            notes = json.loads(Path(NOTES_PATH).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            notes = []
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": payload.get("symbol"), "module": payload.get("module"),
        "timeframe": payload.get("timeframe"), "signal_index": payload.get("signal_index"),
        "signal_time": payload.get("signal_time"), "text": (payload.get("text") or "").strip(),
    }
    notes.append(entry)
    tmp = NOTES_PATH + ".tmp"
    Path(tmp).write_text(json.dumps(notes, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, NOTES_PATH)
    return entry


def list_notes(symbol: str | None = None, module: str | None = None) -> list[dict]:
    if not os.path.exists(NOTES_PATH):
        return []
    try:
        notes = json.loads(Path(NOTES_PATH).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if symbol:
        notes = [n for n in notes if n.get("symbol") == symbol]
    if module:
        notes = [n for n in notes if n.get("module") == module]
    return notes
