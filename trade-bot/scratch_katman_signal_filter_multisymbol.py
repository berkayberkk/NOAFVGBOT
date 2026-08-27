"""
PROTOTIP (scratch, kalici degil): scratch_katman_signal_filter_validation.py'nin
tek-sembol (GOLD) sonucu istatistiksel olarak anlamsizdi (katman basina 2-7
filled trade). Bu script ayni katman-etiketleme mantigini Round 3'te
dogrulanmis sembollere uygulayip TUM sembollerin trade'lerini ayni katman
kovasinda BIRLESTIREREK (pool ederek) ornek boyutunu buyutur.

Sembol basina son 10.000 M30 mumu kullanilir -- ama asil maliyet resample_m1'in
TUM M1 gecmisini islemesinden geliyor (~110sn/sembol, pencere kucultmek bunu
hizlandirmiyor), bu yuzden CHECKPOINT'li calisiyor: her sembol islendikten
hemen sonra sonuc diske yazilir (scratch_katman_pool_checkpoint.json), boylece
uzun surus bir sekilde kesintiye ugrarsa (arka plan surec sonlandirmasi vb.)
zaten islenmis semboller kaybolmaz -- script tekrar calistirildiginda sadece
eksik sembolleri isler. `--report` ile mevcut checkpoint'ten pooled sonucu
yazdirir (hicbir sembol islemeden).
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
from strategy.signal_engine import generate_signals
from strategy.zone import detect_zones, current_katman

CANDLE_WINDOW = 10_000
CHECKPOINT_PATH = Path("scratch_katman_pool_checkpoint.json")

ALL_VALIDATED_SYMBOLS = [
    "ADAUSD", "AUDCAD", "AUDJPY", "AUDNZD", "AUDUSD", "AUS200", "AVAXUSD", "BRENT", "BTCUSD",
    "CA60", "CADJPY", "CHFJPY", "CHINAH", "CHN50", "DOTUSD", "ETHUSD", "EU50", "EURAUD",
    "EURCAD", "EURCHF", "EURJPY", "EURNZD", "EURUSD", "FRA40", "GBPAUD", "GBPCAD", "GBPJPY",
    "GBPNZD", "GBPUSD", "GER40", "GOLD", "HK50", "IT40", "JP225", "NETH25", "NZDCAD", "NZDUSD",
    "PALLADIUM", "PLATINUM", "SILVER", "SING30", "SPAIN35", "SWI20", "TAIWAN", "UK100", "US2000",
    "US30", "US500", "USDCAD", "USDCHF", "USDJPY", "USFANG", "WTI", "XRPUSD",
]

# Cesitli varlik siniflarindan (FX majör, endeks, kripto, metal/enerji) temsili
# bir alt kume -- 54 sembolun tamami ~1.5-2 saat surer, bu ~18 sembol ~30-35dk.
VALIDATED_SYMBOLS = [
    "GOLD", "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY", "AUDUSD",
    "BTCUSD", "ETHUSD", "XRPUSD",
    "SILVER", "WTI", "BRENT",
    "US500", "US30", "GER40", "JP225", "CHN50",
]


@dataclass
class _MiniTrade:
    """calculate_metrics'in ihtiyac duydugu iki alanla checkpoint'ten yeniden kurulan trade."""
    net_r_multiple: float
    won: bool


def _tag_katman(signal, candles: list[dict], zones: list) -> str:
    result = current_katman(signal.index, candles, zones)
    return result[1].name if result else "NONE"


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
        print(f"[atlandi] {symbol}: canonical dosya yok ({path})", flush=True)
        return None

    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2][-CANDLE_WINDOW:]
    if len(candles) < 200:
        print(f"[atlandi] {symbol}: yetersiz mum ({len(candles)})", flush=True)
        return None

    zones = detect_zones(candles, config=config)
    signals = generate_signals(candles, config=config)
    if not signals:
        return {"tags": {}}

    result = run_backtest(candles, signals, config=config)
    trades_by_index = {t.signal.index: t for t in result.trades}

    tags: dict[str, dict] = defaultdict(lambda: {"signal_count": 0, "trades": []})
    for s in signals:
        tag = _tag_katman(s, candles, zones)
        tags[tag]["signal_count"] += 1
        trade = trades_by_index.get(s.index)
        if trade is not None and trade.filled:
            tags[tag]["trades"].append({
                "net_r_multiple": trade.net_r_multiple,
                "won": trade.won,
            })

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
    for symbol, data in checkpoint.items():
        for tag, tag_data in data.get("tags", {}).items():
            pooled[tag].extend(tag_data["trades"])
            pooled["__ALL__"].extend(tag_data["trades"])

    print(f"\n=== Havuzlanmis sonuc ({len(checkpoint)} sembol, pencere={CANDLE_WINDOW} mum) ===")
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
            print(f"[{len(checkpoint)}/{len(VALIDATED_SYMBOLS)}] {symbol}: "
                  f"{sum(t['signal_count'] for t in result['tags'].values())} sinyal, "
                  f"{n_trades} filled trade -- checkpoint kaydedildi", flush=True)

    report(checkpoint)


if __name__ == "__main__":
    main()
