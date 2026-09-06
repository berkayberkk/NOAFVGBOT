"""
PROTOTIP (scratch, kalici degil): web panelindeki "modul ornekleri" sayfalari
icin, GUNCEL resmi kalibrasyonla (strategy/config.py, DEFAULT_CONFIG +
MODULE_R_MULTIPLE/MODULE_SL_BUFFER_RATIO/BREAKEVEN_*) taze ornek islemler
uretir. Proje kokunde Agustos'tan kalma eski *_top_trades_data.json /
trendline_top*_examples_data.json dosyalari, o zamanki (giris-derinligi/SL-
tamponu/hacim-teyidi degisikliklerinden ONCEKI) parametrelerle uretilmisti --
bu script onlarin YERINE gecer, ayni mantikla ama GUNCEL config ile.

2026-09-05: KEPT_SYMBOLS (GOLD/BTCUSD/EURGBP) disindaki 101 sembollik tam
evrene genisletildi (kullanici talebi -- "diger 101 paritenin de islem
ornekleri modul modul cikip feedback verebileyim"). KEPT_SYMBOLS'un kendi
ornek sayisi/derinligi DEGISMEDI (4 kazanan+4 kaybeden+3 breakeven); digger
semboller icin dosya boyutunu makul tutmak icin daha az ornek (2+2+1)
uretiliyor. KEPT_SYMBOLS disindaki semboller icin kalibre spread yok, o
yuzden universe scan'deki gibi spread=0.0 yaklasikligi kullaniliyor --
bu semboller zaten canlida islem gormuyor, sadece feedback/kesif amacli.
Kesinti-dayanikli (incremental resume): islenmis semboller
scratch_module_examples_partial.json'da tutulur, script yeniden
baslatilirsa zaten islenmis semboller ATLANIR.

Her (sembol, modul) icin: kazanan (en yuksek R), kaybeden (gercek SL, en
dusuk R) ve (uygunsa) breakeven ornekleri secilir. Her ornek icin grafik
cizilebilsin diye bir mum penceresi (sinyal barindan ~40 bar once, cikis
barindan ~10 bar sonraya kadar) + zone/entry/sl/tp geometrisi kaydedilir.

Zone (FVG/iFVG/OB gap-bolge) genisligi, Signal nesnesinde ayrica
saklanmadigi icin risk ve MODULE_SL_BUFFER_RATIO'dan geri turetilir:
risk = |entry-sl| = zone_size + zone_size*BUFFER_RATIO = zone_size*(1+BUFFER_RATIO)
=> zone_size = risk / (1+BUFFER_RATIO) -- bu, mql5/TradeBot_NOA_Recal.mq5
parite dogrulamasinda da kullanilan ayni ozdeslik (bkz. o oturumun
formul-tutarliligi kontrolleri).
"""

import glob
import json
import os
import re

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from backtest.engine import run_backtest
from strategy.config import StrategyConfig, KEPT_SYMBOLS, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO
from strategy.signal_engine import generate_signals, SetupType, SignalType
from strategy.support_resistance import build_levels, LevelType

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
MODULE_KEY_BY_SETUP = {
    SetupType.FVG_ONLY: "fvg", SetupType.IFVG_ONLY: "ifvg",
    SetupType.OB_ONLY: "ob", SetupType.TRENDLINE_ONLY: "trendline",
}
N_WINNERS_KEPT = 4
N_LOSERS_KEPT = 4
N_BREAKEVEN_KEPT = 3
N_WINNERS_OTHER = 2
N_LOSERS_OTHER = 2
N_BREAKEVEN_OTHER = 1
PRE_BARS = 40
POST_BARS = 10
MAX_SR_LEVELS = 6  # grafikte gosterilecek en guclu (touch_count'a gore) destek/direnc seviyesi
PARTIAL_PATH = "scratch_module_examples_partial.json"
OUT_PATH = "webapp/data_module_examples.json"


def discover_symbols() -> list[str]:
    paths = glob.glob("data/canonical/V2_MULTI_*_M1_canonical.csv")
    syms = []
    for p in paths:
        m = re.search(r"V2_MULTI_(.+)_M1_canonical\.csv$", os.path.basename(p))
        if m:
            syms.append(m.group(1))
    return sorted(syms)


def load_symbol_m30(symbol: str) -> list[dict]:
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    return [candlev2_to_strategy_dict(c) for c in m30_v2]


def zone_bounds(trade, module_key: str):
    """Signal'in entry/sl'inden zone (gap/govde) sinirlarini geri turetir (bkz. modul docstring'i)."""
    entry = trade.entry_price
    sl = trade.stop_loss
    is_buy = trade.signal.type == SignalType.BUY
    risk = abs(entry - sl)
    ratio = MODULE_SL_BUFFER_RATIO[module_key]
    zone_size = risk / (1 + ratio)
    if module_key == "trendline":
        return None  # zone kavrami yok, diyagonal cizgi -- sadece entry seviyesi gosterilecek
    if is_buy:
        # entry = sig kenar (ust), zone: [entry-zone_size, entry]
        return {"top": entry, "bottom": entry - zone_size}
    else:
        return {"top": entry + zone_size, "bottom": entry}


MAX_POST_ENTRY_BARS = 200  # bazi OB/FVG islemleri SL/TP'ye binlerce bar sonra ulasiyor
                            # (bkz. module_diagnostic bulgusu: GOLD OB ort. ~1230 bar) --
                            # grafik/JSON boyutu icin cikis bu kadar bar sonra kirpilir,
                            # gercek cikis zamani/R'si yine de dogru raporlanir (truncated bayragiyla).
                            # 2026-09-05: 101-sembol genislemesiyle dosya boyutu icin 400'den dusuruldu.


def nearby_sr_levels(candles: list[dict], signal_index: int, price_lo: float, price_hi: float) -> list[dict]:
    """Destek/direnc seviyeleri -- CAUSAL (sadece sinyal anina kadarki mumlarla,
    strategy/support_resistance.py:build_levels DEGISTIRILMEDEN), grafikte
    GORUNEN fiyat araligina dusenler, en guclu (touch_count) MAX_SR_LEVELS
    tanesi. Bu sadece gorsel baglam icin -- sinyal uretiminde KULLANILMIYOR
    (FVG/iFVG/OB/Trendline S/R'den bagimsiz, bkz. strategy/signal_engine.py)."""
    causal_candles = candles[:signal_index + 1]
    if len(causal_candles) < 20:
        return []
    levels = build_levels(causal_candles)
    in_range = [lvl for lvl in levels if price_lo <= lvl.price <= price_hi]
    in_range.sort(key=lambda lvl: -lvl.touch_count)
    return [
        {"price": lvl.price, "type": "resistance" if lvl.type == LevelType.RESISTANCE else "support",
         "touch_count": lvl.touch_count}
        for lvl in in_range[:MAX_SR_LEVELS]
    ]


def candle_window(candles: list[dict], signal_index: int, exit_index: int | None):
    start = max(0, signal_index - PRE_BARS)
    natural_end = (exit_index if exit_index is not None else signal_index) + POST_BARS + 1
    capped_end = signal_index + MAX_POST_ENTRY_BARS
    end = min(len(candles), natural_end, capped_end)
    truncated = natural_end > capped_end
    window = candles[start:end]
    return truncated, [
        {"t": c["time"].isoformat(), "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]}
        for c in window
    ], start


def build_example(symbol: str, module_key: str, trade, candles: list[dict]) -> dict:
    signal_index = trade.signal.index
    exit_idx = trade.exit_index
    truncated, window, window_start = candle_window(candles, signal_index, exit_idx)
    zone = zone_bounds(trade, module_key)
    bars_held = (exit_idx - signal_index) if exit_idx is not None else None

    outcome = "breakeven" if trade.is_breakeven else ("win" if trade.won else "loss")

    price_lo = min(c["l"] for c in window)
    price_hi = max(c["h"] for c in window)
    for v in (trade.entry_price, trade.stop_loss, trade.take_profit):
        price_lo, price_hi = min(price_lo, v), max(price_hi, v)
    sr_levels = nearby_sr_levels(candles, signal_index, price_lo, price_hi)

    return {
        "symbol": symbol,
        "module": module_key,
        "direction": "BUY" if trade.signal.type == SignalType.BUY else "SELL",
        "entry": trade.entry_price,
        "sl": trade.stop_loss,
        "tp": trade.take_profit,
        "r_multiple": round(trade.r_multiple, 4) if trade.r_multiple is not None else None,
        "outcome": outcome,
        "zone": zone,
        "sr_levels": sr_levels,
        "signal_time": candles[signal_index]["time"].isoformat() if signal_index < len(candles) else None,
        "entry_fill_time": candles[trade.entry_fill_index]["time"].isoformat() if trade.entry_fill_index is not None and trade.entry_fill_index < len(candles) else None,
        "exit_time": candles[exit_idx]["time"].isoformat() if exit_idx is not None and exit_idx < len(candles) else None,
        "candles": window,
        "window_start_index": window_start,
        "reason": trade.signal.reason,
        "bars_held": bars_held,
        "chart_truncated": truncated,
    }


def load_partial() -> dict:
    if os.path.exists(PARTIAL_PATH):
        with open(PARTIAL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def write_outputs(by_symbol: dict) -> None:
    merged = {"fvg": [], "ifvg": [], "ob": [], "trendline": []}
    for symbol_examples in by_symbol.values():
        for module_key, examples in symbol_examples.items():
            merged[module_key].extend(examples)
    with open(PARTIAL_PATH, "w", encoding="utf-8") as f:
        json.dump(by_symbol, f, ensure_ascii=False)
    os.makedirs("webapp", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)


def process_symbol(symbol: str) -> dict:
    is_kept = symbol in KEPT_SYMBOLS
    n_winners = N_WINNERS_KEPT if is_kept else N_WINNERS_OTHER
    n_losers = N_LOSERS_KEPT if is_kept else N_LOSERS_OTHER
    n_breakeven = N_BREAKEVEN_KEPT if is_kept else N_BREAKEVEN_OTHER
    spread = SPREAD_BY_SYMBOL.get(symbol, 0.0)

    candles = load_symbol_m30(symbol)
    if len(candles) < 500:
        print(f"  cok az mum (n={len(candles)}), atlandi", flush=True)
        return {"fvg": [], "ifvg": [], "ob": [], "trendline": []}

    config = StrategyConfig(spread=spread)
    all_signals = generate_signals(candles, config=config)

    by_module_sigs = {}
    for s in all_signals:
        by_module_sigs.setdefault(MODULE_KEY_BY_SETUP[s.setup_type], []).append(s)

    result_by_module = {"fvg": [], "ifvg": [], "ob": [], "trendline": []}
    for module_key, sigs in by_module_sigs.items():
        result = run_backtest(candles, sigs, config=config)
        trades = [t for t in result.trades if t.r_multiple is not None]

        winners = sorted([t for t in trades if t.won], key=lambda t: -t.r_multiple)[:n_winners]
        true_losers = sorted([t for t in trades if not t.won and not t.is_breakeven],
                             key=lambda t: t.r_multiple)[:n_losers]
        breakevens = [t for t in trades if t.is_breakeven][:n_breakeven]

        picked = winners + true_losers + breakevens
        result_by_module[module_key] = [build_example(symbol, module_key, t, candles) for t in picked]

        print(f"  {module_key:10}: {len(winners)} kazanan + {len(true_losers)} kaybeden + "
              f"{len(breakevens)} breakeven ornegi secildi (toplam {len(trades)} islemden)", flush=True)

    return result_by_module


def main():
    symbols = discover_symbols()
    print(f"toplam {len(symbols)} sembol bulundu", flush=True)

    by_symbol = load_partial()
    done = set(by_symbol.keys())
    if done:
        print(f"onceden tamamlanmis {len(done)} sembol atlanacak", flush=True)

    for i, symbol in enumerate(symbols):
        if symbol in done:
            continue
        print(f"\n=== [{i + 1}/{len(symbols)}] {symbol} ===", flush=True)
        try:
            by_symbol[symbol] = process_symbol(symbol)
        except Exception as e:
            print(f"  HATA {type(e).__name__}: {e}", flush=True)
            by_symbol[symbol] = {"fvg": [], "ifvg": [], "ob": [], "trendline": []}
        write_outputs(by_symbol)

    print(f"\nTAMAMLANDI. {OUT_PATH} yazildi.")
    merged = {"fvg": [], "ifvg": [], "ob": [], "trendline": []}
    for symbol_examples in by_symbol.values():
        for module_key, examples in symbol_examples.items():
            merged[module_key].extend(examples)
    for k, v in merged.items():
        print(f"  {k}: {len(v)} ornek")


if __name__ == "__main__":
    main()
