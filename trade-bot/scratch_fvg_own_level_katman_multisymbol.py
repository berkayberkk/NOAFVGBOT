"""
PROTOTIP (scratch, kalici degil): scratch_katman_signal_filter_multisymbol.py'nin
duzeltilmis/daha sadik versiyonu. NOA_KONSEPTI_KAYNAK_ANALIZI.md'de tespit
edildigi gibi, o script sinyalin OLUSTUGU BARDAKI FIYATIN (signal.index'teki
close) katmanini etiketliyordu -- ama kaynagin "Yuksek Katman FVG Tarzi"
("KESINLIKLE islem acmayin, herkesi stop eden FVG bunlardir") ve "Alanin
dibindeki FVG" ("en ideal") kurallari, FVG'NIN KENDI GAP SEVIYESININ
(fvg.entry_price -- traded seviye, bullish icin fvg.bottom / bearish icin
fvg.top) hangi Katman'a dustugune bakiyor.

Bu script, sadece FVG_ONLY sinyalleri (strategy/signal_engine.py'nin
"Tek basina FVG" dalinin BIREBIR ayni mantigini burada yeniden kurup, FVG
nesnesine referansi koruyarak) icin bu daha sadik testi yapar: her FVG_ONLY
sinyalinin ENTRY seviyesini (fvg.entry_price), o barda en son donmus Eski
Alan'a gore Katman'a siniflar, ayni checkpoint'li/havuzlama metodolojisiyle
18 sembolde test eder.

Beklenti: eger kaynagin iddiasi dogruysa, K1 (ozellikle K1'in 0-0.15
alt-bandi, ama bu alt-bolunme henuz kodda yok) etiketli FVG_ONLY
sinyalleri, K3/K4 etiketli olanlardan ACIKCA daha iyi performans
gostermeli (kaynak K3/K4'u "herkesi stop eden" diye tanimliyor).
"""

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from backtest.engine import run_backtest
from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from backtest.validation import calculate_metrics
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig
from strategy.fvg import detect_fvgs, mark_filled_fvgs, FVGDirection
from strategy.signal_engine import Signal, SignalType, SetupType, _trend_confidence
from strategy.trend import detect_trend
from strategy.zone import detect_zones, classify_katman, ZoneType

CANDLE_WINDOW = 10_000
CHECKPOINT_PATH = Path("scratch_fvg_own_level_katman_checkpoint.json")

VALIDATED_SYMBOLS = [
    "GOLD", "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY", "AUDUSD",
    "BTCUSD", "ETHUSD", "XRPUSD",
    "SILVER", "WTI", "BRENT",
    "US500", "US30", "GER40", "JP225", "CHN50",
]


@dataclass
class _MiniTrade:
    net_r_multiple: float
    won: bool


def _zone_as_of(index: int, zones: list) -> object | None:
    """current_katman'daki ayni "en son donmus Alan" secim mantigi -- ama
    burada sinyal anindaki FIYAT yerine, cagiran taraf kendi fiyatini
    classify_katman'a verecek (FVG'nin kendi entry_price'i)."""
    o_zones = [z for z in zones if z.zone_type == ZoneType.O and z.extreme_index <= index]
    if not o_zones:
        return None
    return max(o_zones, key=lambda z: z.extreme_index)


def _build_fvg_only_signals_with_refs(candles: list[dict], config: StrategyConfig):
    """strategy/signal_engine.py'nin 'Tek basina FVG' dalinin birebir ayni
    mantigi -- ama (Signal, FVG) ciftini birlikte dondurur, boylece FVG'nin
    kendi top/bottom/entry_price'ine sinyal uretildikten sonra da erisilebilir."""
    fvgs = detect_fvgs(candles, config=config)
    mark_filled_fvgs(fvgs, candles)
    trend_states = detect_trend(candles, config=config)
    valid_fvgs = [f for f in fvgs if f.valid and not f.filled]

    pairs = []
    for fvg in valid_fvgs:
        fvg_dir = SignalType.BUY if fvg.direction == FVGDirection.BULLISH else SignalType.SELL
        if fvg.end_index >= len(candles):
            continue
        confidence = _trend_confidence(trend_states[fvg.end_index], fvg_dir == SignalType.BUY, cap_medium=True)
        if confidence is None:
            continue
        entry = fvg.entry_price
        formation = candles[fvg.start_index: fvg.end_index + 1]
        stop_loss = min(c["low"] for c in formation) if fvg_dir == SignalType.BUY else max(c["high"] for c in formation)
        signal = Signal(
            index=fvg.end_index, type=fvg_dir, confidence=confidence, setup_type=SetupType.FVG_ONLY,
            entry=entry, stop_loss=stop_loss, reason=f"tek başına FVG({fvg.direction.value})",
        )
        pairs.append((signal, fvg))
    pairs.sort(key=lambda p: p[0].index)
    return pairs


def _tag_fvg_own_level(fvg, zones: list) -> str:
    zone = _zone_as_of(fvg.end_index, zones)
    if zone is None:
        return "NONE"
    katman = classify_katman(zone, fvg.entry_price)
    return katman.name if katman is not None else "NONE"


def _load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    return {}


def _save_checkpoint(data: dict) -> None:
    tmp = CHECKPOINT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(CHECKPOINT_PATH)


def _process_symbol(symbol: str, config: StrategyConfig) -> dict | None:
    path = f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv"
    try:
        m1 = load_m1_canonical_as_candlev2(path)
    except FileNotFoundError:
        print(f"[atlandi] {symbol}: canonical dosya yok", flush=True)
        return None

    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2][-CANDLE_WINDOW:]
    if len(candles) < 200:
        return None

    zones = detect_zones(candles, config=config)
    pairs = _build_fvg_only_signals_with_refs(candles, config)
    if not pairs:
        return {"tags": {}}

    signals = [p[0] for p in pairs]
    result = run_backtest(candles, signals, config=config)
    trades_by_index = {t.signal.index: t for t in result.trades}

    tags: dict[str, dict] = defaultdict(lambda: {"signal_count": 0, "trades": []})
    for signal, fvg in pairs:
        tag = _tag_fvg_own_level(fvg, zones)
        tags[tag]["signal_count"] += 1
        trade = trades_by_index.get(signal.index)
        if trade is not None and trade.filled:
            tags[tag]["trades"].append({"net_r_multiple": trade.net_r_multiple, "won": trade.won})

    return {"tags": dict(tags)}


def _print_group(label: str, entries: list[dict]) -> None:
    trades = [_MiniTrade(e["net_r_multiple"], e["won"]) for e in entries]
    if not trades:
        print(f"{label:16} n=0")
        return
    m = calculate_metrics(trades, total_signals=len(trades))
    pf = min(m.profit_factor, 99.9)
    print(f"{label:16} filled={m.filled_trades:5d} win%={m.win_rate:6.1%} "
          f"exp_r={m.expectancy_r:7.4f} pf={pf:6.2f} total_R={m.total_net_r:9.2f}")


def report(checkpoint: dict) -> None:
    pooled: dict[str, list] = defaultdict(list)
    for data in checkpoint.values():
        for tag, tag_data in data.get("tags", {}).items():
            pooled[tag].extend(tag_data["trades"])
            pooled["__ALL__"].extend(tag_data["trades"])

    print(f"\n=== FVG'nin KENDI seviyesi ile Katman testi ({len(checkpoint)} sembol, pencere={CANDLE_WINDOW}) ===")
    _print_group("TUMU (baseline)", pooled.get("__ALL__", []))
    for tag in ["K1", "K2", "K3", "K4", "NONE"]:
        _print_group(tag, pooled.get(tag, []))


def main():
    if "--report" in sys.argv:
        report(_load_checkpoint())
        return

    config = StrategyConfig()
    checkpoint = _load_checkpoint()
    remaining = [s for s in VALIDATED_SYMBOLS if s not in checkpoint]
    print(f"Checkpoint'te {len(checkpoint)} sembol var, {len(remaining)} sembol kaldi.", flush=True)

    for symbol in remaining:
        result = _process_symbol(symbol, config)
        if result is not None:
            checkpoint[symbol] = result
            _save_checkpoint(checkpoint)
            n_trades = sum(len(t["trades"]) for t in result["tags"].values())
            print(f"[{len(checkpoint)}/{len(VALIDATED_SYMBOLS)}] {symbol}: {n_trades} filled trade -- kaydedildi", flush=True)

    report(checkpoint)


if __name__ == "__main__":
    main()
