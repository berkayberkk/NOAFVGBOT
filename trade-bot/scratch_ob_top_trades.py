"""
PROTOTIP (scratch, kalici degil): scratch_ifvg_top_trades.py'nin Order
Block karsiligi. Fark: iFVG'de GLOBAL en karli/en zararli 10 isleniyordu
-- burada kullanici "her pariteden en karli islemi" istedi, yani HER
sembol icin (varsa) o sembolun en karli (en yuksek gercek fiyat hareketi
yuzdeli) KAZANAN Order Block islemi ayri ayri secilip goruntuleniyor.

Yontem, iFVG calismasindaki gibi: R sabit oldugu icin (R=2.0, bkz.
scratch_ob_tp_sl_study.py sonuclari -- PF bu R civarinda tepe yapiyor)
"en karli" R'ye gore degil GERCEK FIYAT HAREKETI YUZDESINE gore
sirlaniyor (entry'ye gore TP mesafesi, %) -- GOLD ile XRPUSD gibi cok
farkli fiyat olcekleri adil karsilastirilsin diye.

Zaman dilimi: D1 (gorsellestirme icin okunakli mum sayisi, iFVG
galerisiyle ayni secim).
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, MODULE_R_MULTIPLE
from strategy.order_block import detect_order_blocks, OBDirection
from scratch_multi_timeframe_fvg_scan import _aggregate_by_calendar

R_MULTIPLE = MODULE_R_MULTIPLE["ob"]  # = 3.0, resmi OB TP hedefi (2026-08-31)
SL_BUFFER_RATIO = 3.0  # scratch_ob_tp_sl_study.py'de kalibre edildi
MAX_WAIT_BARS = 3000
CHECKPOINT_PATH = Path("ob_top_trades_checkpoint.json")

# EXCLUDED_SYMBOLS (strategy/config.py): FVG, iFVG ve Order Block'un ucunun de
# aynı anda en kötü 10 sembol arasında bulduğu, yapısal olarak bu stratejiye
# uygun olmayan semboller çıkarıldı (2026-08-31 R-katı çalışması) --
# GERTECH30, NASDAQ, IT40, GERMID50, EURDKK, USFANG.
ALL_SYMBOLS = [
    "ADAUSD", "ATOMUSD", "AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD", "AUS200", "AVAXUSD",
    "BCHUSD", "BRENT", "BTCUSD", "CA60", "CADCHF", "CADJPY", "CHFJPY", "CHFSGD", "CHINAH",
    "CHN50", "DOGEUSD", "DOTUSD", "ETCUSD", "ETHUSD", "EU50", "EURAUD", "EURCAD", "EURCHF",
    "EURGBP", "EURHKD", "EURHUF", "EURJPY", "EURNOK", "EURNZD", "EURPLN", "EURSEK", "EURSGD",
    "EURTRY", "EURUSD", "EURZAR", "FRA40", "GBPAUD", "GBPCAD", "GBPCHF", "GBPDKK", "GBPJPY",
    "GBPNOK", "GBPNZD", "GBPSEK", "GBPSGD", "GBPUSD", "GER40", "GOLD", "HK50", "JP225",
    "LINKUSD", "LTCUSD", "MATICUSD", "NETH25", "NZDCAD", "NZDCHF", "NZDJPY", "NZDSGD", "NZDUSD",
    "PALLADIUM", "PLATINUM", "SA40", "SGDJPY", "SILVER", "SING30", "SOLUSD", "SPAIN35", "SWI20",
    "TAIWAN", "UK100", "UNIUSD", "US2000", "US30", "US500", "USDCAD", "USDCHF", "USDCNH",
    "USDDKK", "USDHKD", "USDHUF", "USDJPY", "USDMXN", "USDNOK", "USDPLN", "USDSEK", "USDSGD",
    "USDTRY", "USDZAR", "WTI", "XLMUSD", "XRPUSD",
]

CONFIG = StrategyConfig()


@dataclass
class TradeRecord:
    symbol: str
    is_bull: bool
    entry: float
    stop_loss: float
    take_profit: float
    ob_index: int          # OB mumunun (son zit mumun) index'i -- pencere baslangici bu
    fill_index: int
    exit_index: int
    won: bool
    pct_move: float  # kazandiysa TP mesafesi, kaybettiyse SL mesafesi -- entry'ye gore %


def simulate_and_record(candles: list[dict], ob, symbol: str) -> TradeRecord | None:
    is_bull = ob.direction == OBDirection.BULLISH
    entry = (ob.top + ob.bottom) / 2.0
    body_size = ob.top - ob.bottom
    buffer = body_size * SL_BUFFER_RATIO
    stop_loss = (ob.bottom - buffer) if is_bull else (ob.top + buffer)
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return None
    take_profit = entry + R_MULTIPLE * risk if is_bull else entry - R_MULTIPLE * risk

    start = ob.impulse_index
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
                                ob.index, fill_index, i, False, pct)
        if hit_tp:
            pct = abs(take_profit - entry) / entry * 100
            return TradeRecord(symbol, is_bull, entry, stop_loss, take_profit,
                                ob.index, fill_index, i, True, pct)
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
    # FAZ 1 (checkpoint'li): her sembol icin, o sembolun EN KARLI (en
    # yuksek pct_move'lu) KAZANAN islemini (varsa) hafif kayit olarak sakla.
    checkpoint = _load_checkpoint()
    for si, symbol in enumerate(ALL_SYMBOLS, 1):
        if symbol in checkpoint:
            continue
        d1_candles = _load_d1_candles(symbol)
        if d1_candles is None:
            checkpoint[symbol] = None
            _save_checkpoint(checkpoint)
            continue

        obs = detect_order_blocks(d1_candles, config=CONFIG)
        best = None
        for ob in obs:
            rec = simulate_and_record(d1_candles, ob, symbol)
            if rec is not None and rec.won:
                if best is None or rec.pct_move > best.pct_move:
                    best = rec
        checkpoint[symbol] = vars(best) if best is not None else None
        _save_checkpoint(checkpoint)
        print(f"[{si}/{len(ALL_SYMBOLS)}] {symbol}: {len(obs)} OB -- "
              f"{'en iyi %.2f%%' % best.pct_move if best else 'kazanan yok'} -- kaydedildi", flush=True)

    print("\nFAZ 1 TAMAMLANDI -- tum semboller tarandi.", flush=True)

    # FAZ 2: her sembolun en karli islemi icin goruntuleme penceresini
    # (mum listesi) tekrar yukle ve tek bir JSON'a serilestir.
    best_records = {sym: rec for sym, rec in checkpoint.items() if rec is not None}

    trades_out = []
    for symbol, rec_dict in sorted(best_records.items(), key=lambda kv: -kv[1]["pct_move"]):
        rec = TradeRecord(**rec_dict)
        candles = _load_d1_candles(symbol)
        if candles is None:
            continue
        lo = max(0, rec.ob_index - 15)
        hi = min(len(candles), rec.exit_index + 10)
        window = candles[lo:hi]
        trades_out.append({
            "symbol": rec.symbol, "is_bull": rec.is_bull, "entry": rec.entry,
            "stop_loss": rec.stop_loss, "take_profit": rec.take_profit,
            "won": rec.won, "pct_move": rec.pct_move,
            "entry_index_in_window": rec.ob_index - lo,
            "fill_index_in_window": rec.fill_index - lo,
            "exit_index_in_window": rec.exit_index - lo,
            "candles": [{"t": c["time"].isoformat() if hasattr(c["time"], "isoformat") else str(c["time"]),
                         "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]} for c in window],
        })
        print(f"pencere hazir: {symbol} (+{rec.pct_move:.2f}%)", flush=True)

    with open("ob_top_trades_data.json", "w") as f:
        json.dump({"trades": trades_out}, f)

    print(f"\n=== {len(trades_out)} SEMBOL, HER BIRININ EN KARLI OB ISLEMI ===")
    for t in trades_out:
        print(f"{t['symbol']:10} {'BUY' if t['is_bull'] else 'SELL':5} pct=+{t['pct_move']:6.2f}%")


if __name__ == "__main__":
    main()
