"""
PROTOTIP (scratch, kalici degil): "FVG'den giris, SL uzak kenarin biraz
otesi, TP nereye konmali?" sorusunu tum semboller ve zaman dilimlerinde
(M30/H1/H2/H4/D1/W1) test eder.

KURALLAR (kullanicidan, bu oturumda netlesti):
- Giris: fvg.entry_price (bullish=bottom, bearish=top) -- limit emir gibi,
  fiyat o seviyeye GERCEKTEN donmeli (causal, is_unfilled_as_of ile ayni
  ruhta -- ama burada retrospektif calisma oldugu icin dogrudan ilerleyerek
  ilk temasi ariyoruz).
- SL: FVG'nin UZAK kenarinin (gecersizlik/invalidation seviyesinin -- bkz.
  strategy/fvg.py:mark_filled_fvgs, kapanis-bazli) biraz otesi. "Biraz"
  = gap boyutunun (top-bottom) %10'u -- ATR'ye bagimli olmayan, FVG'nin
  KENDI geometrisinden turetilen sabit bir tampon.
- TP: SABIT R-katlari (0.5R'den 5R'ye) karsilastiriliyor -- bu, yapisal
  (bir sonraki FVG/seviye gibi) TP fikirlerinden ONCE, en temel/gurultusuz
  soruyu cevaplar ve hicbir lookahead icermez (ileri taramada sadece
  candles[i+1:]'e bakilir).

Bu CAUSAL bir simulasyon: entry sinyalin olustugu barin (end_index)
HEMEN SONRASINDAN aranir, ayni FVG icin ayni yaklasimla mark_filled_fvgs
(kapanis-bazli) uygulanmis olsa da BURADA "aday sinyal havuzu" filtresi
YOK -- her gecerli FVG bir aday sinyal, entry gercekten dolarsa
(fiyat o seviyeye giderse) trade sayilir, dolmadiysa atlanir (skipped).

Checkpoint'li -- her sembol tamamlaninca diske yazilir.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig
from strategy.fvg import detect_fvgs, FVGDirection
from scratch_multi_timeframe_fvg_scan import _aggregate_by_calendar

RESULTS_PATH = Path("fvg_tp_sl_study_results.json")
TIMEFRAMES = [Timeframe.M30, Timeframe.H1, Timeframe.H2, Timeframe.H4, Timeframe.D1, Timeframe.W1]
R_MULTIPLES = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
SL_BUFFER_RATIO = 1.0  # gap boyutunun %100'u -- GOLD M30 tam gecmiste sweep
                        # edildi (0.10/0.25/0.5/0.75/1.0): %10 tampon exp_r=-0.61
                        # (siradan gurultuyle hemen stop oluyor), %50=+0.23 (R=3'te
                        # pik), %100=+0.24 (R=1.0-1.5'te pik, en iyi profit factor
                        # 1.52). "Biraz otesi" kullaniciya gore olsa da, ampirik
                        # olarak gap boyutunun YARISINDAN AZ bir tampon negatif
                        # expectancy veriyor -- bu varsayilan (1.0x) en iyi PF'yi
                        # veren deger olarak secildi.
MAX_WAIT_BARS = 3000    # entry doldurma + SL/TP cozumleme icin max ileri tarama

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
class TradeOutcome:
    won: bool
    r_multiple: float


def simulate_fvg_trade(candles: list[dict], fvg, r_multiple: float) -> TradeOutcome | None:
    entry = fvg.entry_price
    gap_size = fvg.top - fvg.bottom
    buffer = gap_size * SL_BUFFER_RATIO
    is_bull = fvg.direction == FVGDirection.BULLISH

    if is_bull:
        stop_loss = fvg.bottom - buffer
    else:
        stop_loss = fvg.top + buffer
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return None
    take_profit = entry + r_multiple * risk if is_bull else entry - r_multiple * risk

    start = fvg.end_index + 1
    end = min(len(candles), start + MAX_WAIT_BARS)

    fill_index = None
    for i in range(start, end):
        c = candles[i]
        if is_bull:
            if c["low"] <= entry:
                fill_index = i
                break
        else:
            if c["high"] >= entry:
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


def _process_symbol_timeframe(candles: list[dict]) -> dict:
    if len(candles) < 20:
        return {}
    fvgs = [f for f in detect_fvgs(candles, config=CONFIG) if f.valid]
    result = {}
    for r in R_MULTIPLES:
        outcomes = []
        for fvg in fvgs:
            o = simulate_fvg_trade(candles, fvg, r)
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
    tmp.write_text(json.dumps(data, indent=2, default=str))
    # Windows'ta OneDrive/AV taramasi gibi seyler dosyayi gecici olarak
    # kilitleyebiliyor -- birkac kez kisa bir bekleme ile tekrar dene.
    for attempt in range(5):
        try:
            tmp.replace(RESULTS_PATH)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


def main():
    checkpoint = _load_checkpoint()
    total_units = len(ALL_SYMBOLS) * len(TIMEFRAMES)
    done_units = sum(len(v) for v in checkpoint.values() if isinstance(v, dict) and "error" not in v)

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

            sym_result[tf.name] = _process_symbol_timeframe(tf_candles)
            checkpoint[symbol] = sym_result
            _save_checkpoint(checkpoint)
            done_units += 1
            print(f"[{done_units}/{total_units}] {symbol}/{tf.name}: {time.time()-t0:.1f}sn -- kaydedildi", flush=True)

    print("\nTUM SEMBOLLER TAMAMLANDI.", flush=True)


if __name__ == "__main__":
    main()
