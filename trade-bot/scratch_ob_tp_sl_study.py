"""
PROTOTIP (scratch, kalici degil): scratch_fvg_tp_sl_study.py'nin Order
Block karsiligi -- ayni disiplinli metodoloji (RR-TP taramasi, SL
kalibrasyonu, causal simulasyon, checkpoint'li 101 sembol x 6 zaman
dilimi tarama), ama sinyal kaynagi duzeltilmis Order Block tanimi
(bkz. strategy/order_block.py, 2026-08-31 duzeltmesi -- OB = son zit
mum, govde bolgesi).

Giris/SL/TP (arastirmadan, ICTKillzone kaynagi): entry = OB govdesinin
%50 orta noktasi ("mean threshold"), SL = OB'nin UZAK kenari (giris
yonunun tersi) + govde boyutunun bir tamponu, TP = sabit R katlari.

FVG calismasindaki AYNI causal hata sinifindan kacinmak icin: sinyal
adaylari, "gelecekte hic mitigated olmayacak mi" diye global bir
on-filtreyle SECILMIYOR -- her OB, KENDI olusum barinda aday sayilir,
fiyatin entry seviyesine (giris) ULASIP ULASMADIGI ileri tarama ile
(lookahead YOK, sadece formasyon sonrasindan itibaren) test edilir.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, MODULE_R_MULTIPLE, MODULE_DISABLED_TIMEFRAMES
from strategy.order_block import detect_order_blocks, OBDirection
from scratch_multi_timeframe_fvg_scan import _aggregate_by_calendar

RESULTS_PATH = Path("ob_tp_sl_study_results.json")
# Order Block'un kendi R'sinde (asagida) en cok SL yedigi zaman dilimi
# (strategy/config.py:MODULE_DISABLED_TIMEFRAMES) artik TARANMIYOR --
# 2026-08-31 karariyla OB bu zaman diliminde islem acmiyor.
TIMEFRAMES = [tf for tf in (Timeframe.M30, Timeframe.H1, Timeframe.H2, Timeframe.H4, Timeframe.D1, Timeframe.W1)
              if tf.name not in MODULE_DISABLED_TIMEFRAMES["ob"]]
R_MULTIPLES = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
OB_OFFICIAL_R_MULTIPLE = MODULE_R_MULTIPLE["ob"]  # = 3.0 -- profit factor tepe noktasi, resmi TP hedefi
SL_BUFFER_RATIO = 3.0  # GOLD M30 tam gecmiste sweep edildi (0.5/1.0/2.0/3.0/4.0/5.0/7.0/10.0):
                        # tepe nokta 3.0-4.0 arasi (R=2.0'da exp_r=0.42, pf=1.79) -- FVG'nin
                        # kendi gap boyutu tamponundan (1.0x) farkli, OB'nin govde boyutu
                        # FVG gap'inden kucuk oldugu icin daha buyuk bir carpan gerekiyor.
MAX_WAIT_BARS = 3000

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
class TradeOutcome:
    won: bool
    r_multiple: float


def simulate_ob_trade(candles: list[dict], ob, r_multiple: float) -> TradeOutcome | None:
    is_bull = ob.direction == OBDirection.BULLISH
    entry = (ob.top + ob.bottom) / 2.0
    body_size = ob.top - ob.bottom
    buffer = body_size * SL_BUFFER_RATIO
    stop_loss = (ob.bottom - buffer) if is_bull else (ob.top + buffer)
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return None
    take_profit = entry + r_multiple * risk if is_bull else entry - r_multiple * risk

    start = ob.impulse_index  # impuls barindan itibaren fiyatin geri donup entry'ye ulasmasini bekle
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
            return TradeOutcome(won=False, r_multiple=-1.0)
        if hit_tp:
            return TradeOutcome(won=True, r_multiple=r_multiple)
    return None


def _metrics(outcomes: list[TradeOutcome]) -> dict:
    if not outcomes:
        return {"n": 0}
    wins = [o for o in outcomes if o.won]
    losses = [o for o in outcomes if not o.won]
    win_rate = len(wins) / len(outcomes)
    total_r = sum(o.r_multiple for o in outcomes)
    avg_win = sum(o.r_multiple for o in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(o.r_multiple for o in losses)) / len(losses) if losses else 0.0
    expectancy_r = win_rate * avg_win - (1 - win_rate) * avg_loss
    gross_profit = sum(o.r_multiple for o in wins)
    gross_loss = abs(sum(o.r_multiple for o in losses))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    return {
        "n": len(outcomes), "wins": len(wins), "losses": len(losses),
        "win_rate": win_rate, "total_r": total_r, "expectancy_r": expectancy_r,
        "profit_factor": min(pf, 999.0),
    }


def _process_timeframe(candles: list[dict]) -> dict:
    if len(candles) < 20:
        return {}
    obs = detect_order_blocks(candles, config=CONFIG)
    result = {"n_obs": len(obs)}
    for r in R_MULTIPLES:
        outcomes = []
        for ob in obs:
            o = simulate_ob_trade(candles, ob, r)
            if o is not None:
                outcomes.append(o)
        result[str(r)] = _metrics(outcomes)
    return result


def _load_checkpoint() -> dict:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text())
    return {}


def _save_checkpoint(data: dict) -> None:
    tmp = RESULTS_PATH.with_suffix(".tmp")
    for attempt in range(5):
        try:
            tmp.write_text(json.dumps(data, indent=2, default=str))
            tmp.replace(RESULTS_PATH)
            return
        except (PermissionError, FileNotFoundError):
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


def main():
    checkpoint = _load_checkpoint()
    total_units = len(ALL_SYMBOLS) * len(TIMEFRAMES)
    done_units = sum(1 for v in checkpoint.values() if isinstance(v, dict) and "error" not in v for _ in v)

    for symbol in ALL_SYMBOLS:
        sym_result = checkpoint.get(symbol, {})
        if "error" in sym_result:
            continue
        pending_tfs = [tf for tf in TIMEFRAMES if tf.name not in sym_result]
        if not pending_tfs:
            continue

        path = f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv"
        try:
            m1 = load_m1_canonical_as_candlev2(path)
        except FileNotFoundError:
            continue
        if len(m1) < 2000:
            checkpoint[symbol] = {"error": "yetersiz veri"}
            _save_checkpoint(checkpoint)
            continue

        m30_candles = None
        for tf in pending_tfs:
            t0 = time.time()
            if tf in (Timeframe.D1, Timeframe.W1):
                if m30_candles is None:
                    m30_v2, _ = resample_m1(m1, Timeframe.M30)
                    m30_candles = [candlev2_to_strategy_dict(c) for c in m30_v2]
                tf_candles = _aggregate_by_calendar(m30_candles, "day" if tf == Timeframe.D1 else "week")
            else:
                tf_v2, _ = resample_m1(m1, tf)
                tf_candles = [candlev2_to_strategy_dict(c) for c in tf_v2]
                if tf == Timeframe.M30:
                    m30_candles = tf_candles

            sym_result[tf.name] = _process_timeframe(tf_candles)
            checkpoint[symbol] = sym_result
            _save_checkpoint(checkpoint)
            done_units += 1
            print(f"[{done_units}/{total_units}] {symbol}/{tf.name}: {time.time()-t0:.1f}sn -- kaydedildi", flush=True)

    print("\nTUM SEMBOLLER TAMAMLANDI.", flush=True)


if __name__ == "__main__":
    main()
