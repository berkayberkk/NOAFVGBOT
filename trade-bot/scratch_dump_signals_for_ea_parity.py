"""
PROTOTIP (scratch, kalici degil): mql5/TradeBot_NOA_Recal.mq5 port'unun
Python kaynak-dogrusuyla (strategy/signal_engine.py) BIREBIR AYNI
sinyalleri urettigini dogrulamak icin kullanilan parite testinin Python
tarafi.

Hicbir strateji mantigi burada TEKRAR YAZILMIYOR -- generate_signals()
DEGISTIRILMEDEN cagriliyor, sadece cikti EA'nin Strategy Tester'da
LogSignalsOnly=true ile urettigi NOA_Recal_signals_<SEMBOL>.csv
dosyasiyla karsilastirilabilecek bir JSON'a donusturuluyor.

Kullanim:
    python scratch_dump_signals_for_ea_parity.py

Cikti: results/ea_parity/<SEMBOL>_python_signals.json (her biri icin
modul, yon, bar zamani (UTC ISO), entry/sl/tp, breakeven uygunlugu).
"""

import json
import os

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import KEPT_SYMBOLS, DEFAULT_CONFIG
from strategy.signal_engine import generate_signals, SignalType

OUT_DIR = "results/ea_parity"


def dump_symbol(symbol: str) -> str:
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]

    signals = generate_signals(candles, config=DEFAULT_CONFIG)

    rows = []
    for s in signals:
        bar_time = candles[s.index]["time"]
        rows.append({
            "module": s.setup_type.value,
            "direction": "BUY" if s.type == SignalType.BUY else "SELL",
            "signal_bar_time_utc": bar_time.isoformat(),
            "entry": round(s.entry, 6),
            "sl": round(s.stop_loss, 6),
            "tp": round(s.take_profit, 6) if s.take_profit is not None else None,
            "breakeven_trigger_pct": s.breakeven_trigger_pct,
        })

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{symbol}_python_signals.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    print(f"{symbol}: {len(rows)} sinyal -> {out_path}")
    return out_path


if __name__ == "__main__":
    for sym in KEPT_SYMBOLS:
        dump_symbol(sym)
