"""
PROTOTIP (scratch, kalici degil): scratch_fvg_tp_sl_study.py'nin (FVG icin
RR-TP calismasi) iFVG karsiligi. Ayni R-katli TP taramasini, ayni SL
tamponu (%100 gap boyutu) mantigiyla, ama FVG yerine iFVG sinyalleri
uzerinde calistirir -- boylece iki modulun karlilik/win-rate'i dogrudan
karsilastirilabilir.

iFVG TANIMI (kullanicinin kendi tanimindan, bu oturumda netlestirildi --
onceki, "her invalidation = iFVG" seklindeki YANLIS/gevsek tanimin
yerine gecti):
  1. KIRILMA: bir FVG'nin kapanisla TAMAMEN gecilmesi (mevcut, test
     edilmis mark_filled_fvgs mantigi ile ayni tetikleyici).
  2. RETEST: kirilmadan SONRA (sure siniri YOK -- kullanicidan teyitli),
     fiyatin geri donup bolgenin YAKIN kenarina (kirilan tarafa) fitille
     dokunmasi VE O MUMUN KAPANISININ disarida kalmasi (reddiye,
     "wick rejection"). Ilk temasta karar verilir -- ilk temas
     reddetmezse (bolgeye kapanirsa) o FVG basarisiz sayilir, iFVG
     olusmaz.
  3. CHOP-CLUSTER filtresi: bu bolge, GECMISTE (nedensel, gelecege
     bakmadan) son 15 bar icinde ZIT yonlu baska bir kirilma/retest ile
     CAKISIYORSA supheli sayilir ve elenir -- ayni bolgenin kisa surede
     iki kez zit yonde "kirilmasi" bir chop/kararsizlik isareti, temiz
     bir yon degisimi degil.

Kullanicinin GOLD D1 grafiginde elle dogruladigi ornekler bu ucuncu
kuralla eslesiyor (bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md) -- ama bir
sirri (2026-03-03 GOLD ornegi) hala aciklanamiyor; bu, tam otomatik
tanimin MUKEMMEL olmadigini, ama en iyi elimizdeki calisir versiyon
oldugunu gosteriyor.

Giris/SL/TP (RR calismasiyla birebir paralel, karsilastirma adil olsun
diye):
  - entry = consequent_encroachment (bolgenin %50 orta noktasi)
  - SL = bolgenin UZAK kenari (entry'nin oldugu tarafin tersi) + bolge
    boyutunun %100'u tampon (RR calismasindaki kalibrasyonla ayni)
  - TP = sabit R katlari (0.5R-5.0R), karsilastirmali

Checkpoint'li (sembol/zaman dilimi ciftinde), kesintiye dayanikli.
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

RESULTS_PATH = Path("ifvg_tp_sl_study_results.json")
TIMEFRAMES = [Timeframe.M30, Timeframe.H1, Timeframe.H2, Timeframe.H4, Timeframe.D1, Timeframe.W1]
R_MULTIPLES = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
SL_BUFFER_RATIO = 1.0
MAX_WAIT_BARS = 3000
CHOP_CLUSTER_BARS = 15

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


def detect_confirmed_ifvgs(candles: list[dict]) -> list[dict]:
    """Kirilma + retest/reddiye + causal chop-cluster filtresiyle onaylanmis iFVG listesi."""
    fvgs = [f for f in detect_fvgs(candles, config=CONFIG) if f.valid]
    n = len(candles)
    events = []

    for f in fvgs:
        broken_idx = None
        new_dir = None
        for i in range(f.end_index + 1, n):
            c = candles[i]
            if f.direction == FVGDirection.BULLISH and c["close"] < f.bottom:
                broken_idx, new_dir = i, "bearish"
                break
            if f.direction == FVGDirection.BEARISH and c["close"] > f.top:
                broken_idx, new_dir = i, "bullish"
                break
        if broken_idx is None:
            continue

        retest_idx = None
        for j in range(broken_idx + 1, n):
            cj = candles[j]
            if new_dir == "bearish":
                touched = cj["high"] >= f.bottom
                rejected = cj["close"] < f.bottom
            else:
                touched = cj["low"] <= f.top
                rejected = cj["close"] > f.top
            if touched:
                if rejected:
                    retest_idx = j
                break
        if retest_idx is None:
            continue

        events.append({
            "top": f.top, "bottom": f.bottom, "new_dir": new_dir,
            "broken_idx": broken_idx, "retest_idx": retest_idx,
            "consequent_encroachment": (f.top + f.bottom) / 2,
        })

    for e in events:
        e["chop_cluster"] = False
        for e2 in events:
            if e2["broken_idx"] >= e["broken_idx"]:
                continue
            if e["broken_idx"] - e2["broken_idx"] > CHOP_CLUSTER_BARS:
                continue
            overlap = min(e["top"], e2["top"]) - max(e["bottom"], e2["bottom"])
            if overlap > 0 and e["new_dir"] != e2["new_dir"]:
                e["chop_cluster"] = True

    return [e for e in events if not e["chop_cluster"]]


def simulate_ifvg_trade(candles: list[dict], event: dict, r_multiple: float) -> TradeOutcome | None:
    is_bull = event["new_dir"] == "bullish"
    entry = event["consequent_encroachment"]
    gap_size = event["top"] - event["bottom"]
    buffer = gap_size * SL_BUFFER_RATIO
    stop_loss = (event["bottom"] - buffer) if is_bull else (event["top"] + buffer)
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return None
    take_profit = entry + r_multiple * risk if is_bull else entry - r_multiple * risk

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
    events = detect_confirmed_ifvgs(candles)
    result = {"n_confirmed_ifvgs": len(events)}
    for r in R_MULTIPLES:
        outcomes = []
        for e in events:
            o = simulate_ifvg_trade(candles, e, r)
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
    payload = json.dumps(data, indent=2, default=str)
    for attempt in range(5):
        try:
            tmp.write_text(payload)
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
