"""
PROTOTIP (scratch, kalici degil): iFVG (kirilma+retest+reddiye onayli)
sinyalleriyle, D1 zaman diliminde, R=1.5'te (en iyi expectancy -- bkz.
scratch_ifvg_tp_sl_study.py sonuclari) tum 101 sembolde GERCEK islem
kayitlarini (entry/SL/TP fiyatlari, tarihler, sembol) toplar.

"En karli" / "en zararli" siralamasi R-multiple'a gore YAPILAMAZ --
sabit R'li bir sistemde her kazanan ayni R'yi (1.5R), her kaybeden ayni
-1R'yi kazaniyor/kaybediyor, R bazinda hepsi esit. Bunun yerine GERCEK
FIYAT HAREKETI YUZDESI (entry'ye gore TP/SL mesafesi, %) kullanilir --
boylece GOLD ile BTCUSD gibi cok farkli fiyat olceklerindeki islemler
adil sekilde karsilastirilir.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig
from scratch_ifvg_tp_sl_study import detect_confirmed_ifvgs, SL_BUFFER_RATIO
from scratch_multi_timeframe_fvg_scan import _aggregate_by_calendar

R_MULTIPLE = 1.5
MAX_WAIT_BARS = 3000
CHECKPOINT_PATH = Path("ifvg_top_trades_checkpoint.json")

ALL_SYMBOLS = [
    "ADAUSD", "ATOMUSD", "AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD", "AUS200", "AVAXUSD",
    "BCHUSD", "BRENT", "BTCUSD", "CA60", "CADCHF", "CADJPY", "CHFJPY", "CHFSGD", "CHINAH", "CHN50",
    "DOGEUSD", "DOTUSD", "ETCUSD", "ETHUSD", "EU50", "EURAUD", "EURCAD", "EURCHF", "EURDKK",
    "EURGBP", "EURHKD", "EURHUF", "EURJPY", "EURNOK", "EURNZD", "EURPLN", "EURSEK", "EURSGD",
    "EURTRY", "EURUSD", "EURZAR", "FRA40", "GBPAUD", "GBPCAD", "GBPCHF", "GBPDKK", "GBPJPY",
    "GBPNOK", "GBPNZD", "GBPSEK", "GBPSGD", "GBPUSD", "GER40", "GERMID50", "GERTECH30", "GOLD",
    "HK50", "IT40", "JP225", "LINKUSD", "LTCUSD", "MATICUSD", "NASDAQ", "NETH25", "NZDCAD",
    "NZDCHF", "NZDJPY", "NZDSGD", "NZDUSD", "PALLADIUM", "PLATINUM", "SA40", "SGDJPY", "SILVER",
    "SING30", "SOLUSD", "SPAIN35", "SWI20", "TAIWAN", "UK100", "UNIUSD", "US2000", "US30", "US500",
    "USDCAD", "USDCHF", "USDCNH", "USDDKK", "USDHKD", "USDHUF", "USDJPY", "USDMXN", "USDNOK",
    "USDPLN", "USDSEK", "USDSGD", "USDTRY", "USDZAR", "USFANG", "WTI", "XLMUSD", "XRPUSD",
]

CONFIG = StrategyConfig()


@dataclass
class TradeRecord:
    symbol: str
    is_bull: bool
    entry: float
    stop_loss: float
    take_profit: float
    entry_index: int
    fill_index: int
    exit_index: int
    won: bool
    pct_move: float  # kazandiysa TP mesafesi, kaybettiyse SL mesafesi -- entry'ye gore %


def simulate_and_record(candles: list[dict], event: dict, symbol: str) -> TradeRecord | None:
    is_bull = event["new_dir"] == "bullish"
    entry = event["consequent_encroachment"]
    gap_size = event["top"] - event["bottom"]
    buffer = gap_size * SL_BUFFER_RATIO
    stop_loss = (event["bottom"] - buffer) if is_bull else (event["top"] + buffer)
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return None
    take_profit = entry + R_MULTIPLE * risk if is_bull else entry - R_MULTIPLE * risk

    start = event["retest_idx"]
    end = min(len(candles), start + MAX_WAIT_BARS)
    fill_index = None
    for i in range(start, end):
        c = candles[i]
        if (is_bull and c["low"] <= entry) or (not is_bull and c["high"] >= entry):
            fill_index = i
            break
    if fill_index is None:
        return None

    scan_end = min(len(candles), fill_index + MAX_WAIT_BARS)
    for i in range(fill_index, scan_end):
        c = candles[i]
        if is_bull:
            hit_sl = c["low"] <= stop_loss
            hit_tp = c["high"] >= take_profit
        else:
            hit_sl = c["high"] >= stop_loss
            hit_tp = c["low"] <= take_profit
        if hit_sl:
            pct = abs(stop_loss - entry) / entry * 100
            return TradeRecord(symbol, is_bull, entry, stop_loss, take_profit,
                                event["broken_idx"], fill_index, i, False, pct)
        if hit_tp:
            pct = abs(take_profit - entry) / entry * 100
            return TradeRecord(symbol, is_bull, entry, stop_loss, take_profit,
                                event["broken_idx"], fill_index, i, True, pct)
    return None


def _load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    return {}


def _save_checkpoint(data: dict) -> None:
    tmp = CHECKPOINT_PATH.with_suffix(".tmp")
    for attempt in range(5):
        try:
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(CHECKPOINT_PATH)
            return
        except (PermissionError, FileNotFoundError):
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


def _load_d1_candles(symbol: str) -> list[dict] | None:
    path = f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv"
    try:
        m1 = load_m1_canonical_as_candlev2(path)
    except FileNotFoundError:
        return None
    if len(m1) < 2000:
        return None
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    m30_candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
    d1_candles = _aggregate_by_calendar(m30_candles, "day")
    return d1_candles if len(d1_candles) >= 20 else None


def main():
    # FAZ 1 (checkpoint'li): her sembol icin hafif islem kayitlarini (mum
    # penceresi OLMADAN -- checkpoint'i kucuk/hizli tutmak icin) topla.
    checkpoint = _load_checkpoint()
    for si, symbol in enumerate(ALL_SYMBOLS, 1):
        if symbol in checkpoint:
            continue
        d1_candles = _load_d1_candles(symbol)
        if d1_candles is None:
            checkpoint[symbol] = []
            _save_checkpoint(checkpoint)
            continue

        events = detect_confirmed_ifvgs(d1_candles)
        records = []
        for e in events:
            rec = simulate_and_record(d1_candles, e, symbol)
            if rec is not None:
                records.append(vars(rec))
        checkpoint[symbol] = records
        _save_checkpoint(checkpoint)
        print(f"[{si}/{len(ALL_SYMBOLS)}] {symbol}: {len(events)} iFVG, {len(records)} trade -- kaydedildi", flush=True)

    print("\nFAZ 1 TAMAMLANDI -- tum semboller tarandi.", flush=True)

    # FAZ 2: en karli/zararli 10'ari bul, SADECE o sembollerin mumlarini
    # (goruntuleme penceresi icin) tekrar yukle.
    all_records = []
    for symbol, records in checkpoint.items():
        for r in records:
            all_records.append(r)

    winners_meta = sorted([r for r in all_records if r["won"]], key=lambda r: -r["pct_move"])[:10]
    losers_meta = sorted([r for r in all_records if not r["won"]], key=lambda r: -r["pct_move"])[:10]

    needed_symbols = {r["symbol"] for r in winners_meta + losers_meta}
    candles_by_symbol = {}
    for symbol in needed_symbols:
        d1 = _load_d1_candles(symbol)
        if d1 is not None:
            candles_by_symbol[symbol] = d1

    def to_trade_tuple(r):
        rec = TradeRecord(**r)
        candles = candles_by_symbol.get(rec.symbol)
        return (rec, candles) if candles is not None else None

    winners = [t for t in (to_trade_tuple(r) for r in winners_meta) if t is not None]
    losers = [t for t in (to_trade_tuple(r) for r in losers_meta) if t is not None]

    def serialize(trade_list):
        out = []
        for rec, candles in trade_list:
            lo = max(0, rec.entry_index - 15)
            hi = min(len(candles), rec.exit_index + 10)
            window = candles[lo:hi]
            out.append({
                "symbol": rec.symbol, "is_bull": rec.is_bull, "entry": rec.entry,
                "stop_loss": rec.stop_loss, "take_profit": rec.take_profit,
                "won": rec.won, "pct_move": rec.pct_move,
                "entry_index_in_window": rec.entry_index - lo,
                "fill_index_in_window": rec.fill_index - lo,
                "exit_index_in_window": rec.exit_index - lo,
                "candles": [{"t": c["time"].isoformat() if hasattr(c["time"], "isoformat") else str(c["time"]),
                             "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]} for c in window],
            })
        return out

    result = {"winners": serialize(winners), "losers": serialize(losers)}
    with open("ifvg_top_trades_data.json", "w") as f:
        json.dump(result, f)

    print("\n=== TOP 10 KARLI ===")
    for rec, _ in winners:
        print(f"{rec.symbol:10} {'BUY' if rec.is_bull else 'SELL':5} pct={rec.pct_move:6.2f}%")
    print("\n=== TOP 10 ZARARLI ===")
    for rec, _ in losers:
        print(f"{rec.symbol:10} {'BUY' if rec.is_bull else 'SELL':5} pct={rec.pct_move:6.2f}%")


if __name__ == "__main__":
    main()
