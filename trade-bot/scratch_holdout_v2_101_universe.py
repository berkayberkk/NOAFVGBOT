"""
KUTSAL HOLDOUT V2 -- 101/101 ENSTRUMAN (2026-09-07, kullanicinin acik
talebi: "3 sembol yeterli degil, universe = ALL_SUPPORTED_INSTRUMENTS").

Bu, `scratch_holdout_validation_run_v2_current_config.py`nin (SADECE
KEPT_SYMBOLS=GOLD/BTCUSD/EURGBP) AYNI, DEGISTIRILMEMIS metodolojisini
(split_chronological %60/%20/%20, build_validation_report walk-forward,
run_final_holdout_evaluation tek-atimlik kutsal holdout, block-bootstrap
seed=42/block_size=3/num_resamples=1000) TAM 101 sembole genisletir.

PARAMETRE OPTIMIZASYONU YOK -- bu SADECE olcum. Hicbir sembole/kod yoluna
ozel muamele YOK (if symbol == "GOLD": gibi bir sey bu dosyada olmamali).

CHECKPOINT/RESUME: her sembolun sonucu KENDI dosyasina
(results/holdout_v2_101/{SYMBOL}.json) ATOMIK yazilir -- 101 sembolluk
bu calisma saatler surecegi icin (GOLD/BTCUSD/EURGBP pilotunda sembol
basina ~5-9 dakika, agirlikli olarak M1->M30 resample + train/val/WFA +
1000-resample block-bootstrap), kesintiye ugrarsa TEKRAR CALISTIRILDIGINDA
zaten tamamlanmis sembolleri ATLAR.

SPREAD: KEPT_SYMBOLS (GOLD/BTCUSD/EURGBP) icin bilinen temsili degerler
(projenin 2026-09-02'den beri kullandigi AYNI degerler). Diger 98 sembol
icin GERCEK spread verisi hic kalibre edilmedi -- spread=0.0 kullanilir.

GUNCELLEME (2026-09-07, kullanicinin metodoloji duzeltmesi): STRATEGY
VALIDITY (istatistiksel sonuc) ve EXECUTION VALIDITY (maliyet
gercekciligi) artik IKI BAGIMSIZ EKSEN olarak ayri raporlaniyor --
bkz. `research_dual_validity.py`. Ayrica her sembol icin test
partisyonunda 4 seviyeli (zero/low/median/high, ATR-orantili sentetik)
spread-duyarlilik taramasi yapiliyor: pozitif sonuclarin hangi maliyet
seviyesinde negatife dondugu ACIKCA gosteriliyor. Bu, "strateji
calismiyor" ile "strateji calisiyor olabilir ama execution maliyeti
bilinmedigi icin dogrulanamiyor" ifadelerini ayirt etmek icin.

DATA INSUFFICIENT esigi: M30'a resample sonrasi <2000 mum (kabaca ~42
gun) -- bu esigin altinda 60/20/20 bolme ve anlamli bir holdout ornegi
mumkun degil, deneme yapilmadan E -- DATA INSUFFICIENT olarak isaretlenir.

SIRALAMA: dosya boyutuna (kucukten buyuge) gore islenir -- SADECE
calisma sirasi, sonucu ETKILEMEZ; amac erken asamada cesitli/kismi
sonuclarin gorunur olmasi.
"""

import json
import time
from dataclasses import asdict
from pathlib import Path

from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig, _ALL_101_SYMBOLS
from strategy.signal_engine import generate_signals
from backtest.validation import build_validation_report, split_chronological
from backtest.final_holdout import run_final_holdout_evaluation
from research_dual_validity import spread_sensitivity_sweep, execution_validity, strategy_validity, mae_mfe_summary, provenance

SPREAD_BY_SYMBOL = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
MIN_M30_CANDLES = 2000

OUT_DIR = Path("results/holdout_v2_101")
DATA_DIR = Path("data/canonical")


def _to_jsonable(obj):
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if hasattr(obj, "value"):
        return obj.value
    return obj


def _atomic_write(path: Path, data: dict):
    tmp = path.with_suffix(".tmp")
    for attempt in range(5):
        try:
            tmp.write_text(json.dumps(data, indent=2, default=str))
            tmp.replace(path)
            return
        except (PermissionError, FileNotFoundError):
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


# classify() kaldirildi -- yerine research_dual_validity.strategy_validity /
# execution_validity (iki BAGIMSIZ eksen) kullaniliyor, bkz. process_symbol.


def process_symbol(symbol: str) -> dict:
    path = DATA_DIR / f"V2_MULTI_{symbol}_M1_canonical.csv"
    if not path.exists():
        return {"symbol": symbol, "data_status": "insufficient", "reason": "csv dosyasi yok (NOT TESTED)"}

    try:
        m1 = load_m1_canonical_as_candlev2(str(path))
    except Exception as e:
        return {"symbol": symbol, "data_status": "insufficient", "reason": f"yukleme hatasi: {e}"}

    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2]

    if len(candles) < MIN_M30_CANDLES:
        return {"symbol": symbol, "data_status": "insufficient",
                "reason": f"M30 mum sayisi ({len(candles)}) < esik ({MIN_M30_CANDLES})",
                "m30_candle_count": len(candles)}

    spread = SPREAD_BY_SYMBOL.get(symbol, 0.0)
    spread_source = "representative_estimate" if symbol in SPREAD_BY_SYMBOL else "uncalibrated_zero"
    config = StrategyConfig(spread=spread)

    # Yapisal uyumsuzluk kontrolu: sinyal hic uretilmiyor mu?
    probe_signals = generate_signals(candles, config=config)
    if len(probe_signals) == 0:
        return {"symbol": symbol, "data_status": "ok", "structural_failure": True,
                "m30_candle_count": len(candles), "spread_used": spread,
                "reason": "generate_signals hic sinyal uretmedi (0 aday) -- FVG/OB/Trendline mantigi bu enstrumanin fiyat olcegi/yapisiyla uyusmuyor olabilir"}

    val_report = build_validation_report(candles, config=config)
    holdout = run_final_holdout_evaluation(candles, config=config, val_metrics=val_report.val_metrics)
    holdout_j = _to_jsonable(holdout)

    _, (_, _, test_candles) = split_chronological(candles, 0.60, 0.20, 0.20)
    test_signals = generate_signals(test_candles, config=config)
    sweep = spread_sensitivity_sweep(test_candles, test_signals, config)
    mae_mfe = mae_mfe_summary(test_candles, test_signals, config)

    sv = strategy_validity(holdout_j)
    ev = execution_validity(symbol, spread_source)

    return {
        "symbol": symbol, "data_status": "ok", "structural_failure": False,
        "m30_candle_count": len(candles),
        "data_start": str(candles[0]["time"]), "data_end": str(candles[-1]["time"]),
        "spread_used": spread,
        "strategy_validity": sv,
        "execution_validity": ev,
        "classification": f"STRATEGY {sv['status']} / EXECUTION {ev['status']}",
        "spread_sensitivity": sweep,
        "mae_mfe": mae_mfe,
        "provenance": provenance(symbol),
        "train_metrics": _to_jsonable(val_report.train_metrics),
        "val_metrics": _to_jsonable(val_report.val_metrics),
        "walk_forward_oos_metrics": _to_jsonable(val_report.oos_val_metrics),
        "holdout": holdout_j,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done = {p.stem for p in OUT_DIR.glob("*.json")}
    remaining = [s for s in _ALL_101_SYMBOLS if s not in done]

    # Kucukten buyuge sirala -- SADECE sira, sonucu etkilemez.
    def _size(s):
        p = DATA_DIR / f"V2_MULTI_{s}_M1_canonical.csv"
        return p.stat().st_size if p.exists() else 0
    remaining.sort(key=_size)

    print(f"{len(done)}/{len(_ALL_101_SYMBOLS)} tamamlanmis, {len(remaining)} kaldi", flush=True)

    for i, symbol in enumerate(remaining, start=1):
        t0 = time.time()
        try:
            record = process_symbol(symbol)
        except Exception as e:
            record = {"symbol": symbol, "data_status": "insufficient", "reason": f"HATA: {type(e).__name__}: {e}"}
        record["elapsed_sec"] = round(time.time() - t0, 1)

        if record["data_status"] == "insufficient":
            record["strategy_validity"] = {"status": "NOT_TESTED", "reason": record.get("reason")}
            record["execution_validity"] = None
            record["spread_sensitivity"] = None
            record["mae_mfe"] = None
            record["classification"] = "STRATEGY NOT_TESTED / EXECUTION N/A"
            record["provenance"] = provenance(symbol)
            _atomic_write(OUT_DIR / f"{symbol}.json", record)
            print(f"[{i}/{len(remaining)}] {symbol}: DATA_INSUFFICIENT -- {record.get('reason')} ({record['elapsed_sec']}sn)", flush=True)
        elif record.get("structural_failure"):
            record["strategy_validity"] = {"status": "FAIL", "reason": record.get("reason")}
            record["execution_validity"] = None
            record["spread_sensitivity"] = None
            record["mae_mfe"] = None
            record["classification"] = "STRATEGY FAIL (structural, 0 signals) / EXECUTION N/A"
            record["provenance"] = provenance(symbol)
            _atomic_write(OUT_DIR / f"{symbol}.json", record)
            print(f"[{i}/{len(remaining)}] {symbol}: STRUCTURAL_FAILURE -- 0 sinyal ({record['elapsed_sec']}sn)", flush=True)
        else:
            _atomic_write(OUT_DIR / f"{symbol}.json", record)
            h = record["holdout"]
            sv, ev = record["strategy_validity"]["status"], record["execution_validity"]["status"]
            flips = record["spread_sensitivity"]["flips_negative_at"]
            print(f"[{i}/{len(remaining)}] {symbol}: STRATEGY={sv:10} EXECUTION={ev:10} "
                  f"exp={h['test_metrics']['expectancy_r']:+.4f} pf={h['test_metrics']['profit_factor']:.2f} "
                  f"win={h['test_metrics']['win_rate']:.1%} n={h['test_metrics']['filled_trades']} "
                  f"maxDD={h['test_metrics']['max_drawdown_r']:.1f}R flips_neg_at={flips} ({record['elapsed_sec']}sn)", flush=True)

    print("\nTUM 101 SEMBOL TAMAMLANDI.", flush=True)


if __name__ == "__main__":
    main()
