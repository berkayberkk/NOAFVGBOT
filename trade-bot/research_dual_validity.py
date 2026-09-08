"""
Paylasilan yardimcilar -- STRATEGY VALIDITY / EXECUTION VALIDITY iki eksenli
siniflandirma + spread duyarlilik analizi (2026-09-07, kullanicinin acik
metodoloji duzeltmesi talebi: "spread=0 kullanilan sembollerde EXECUTION
INVALID durumunu strateji basarisizligiyla ayni kategoriye koyma").

ONEMLI DURUSTLUK NOTU: GOLD/BTCUSD/EURGBP'nin SPREAD_BY_SYMBOL degerleri
DE gercek broker'dan kalibre EDILMEDI -- projenin kendi kod yorumlarinda
("temsili, henuz kalibre edilmedi", bkz. scratch_holdout_validation_run.py,
scratch_execution_model_gap_study.py) acikca boyle not dusulmus. Yani bu
3 sembol de "dogrulanmis gercek execution" degil -- SADECE spread=0'dan
daha az kotumser bir TAHMIN. Bu yuzden asagida ne 98 sembol icin
"EXECUTION: VALID" ne de GOLD/BTCUSD/EURGBP icin "EXECUTION: VALID"
kullaniliyor -- ikisi de en iyi ihtimalle "UNCERTAIN", 98'i ise "INVALID"
(spread tam sifir, kesinlikle gercekci degil).

Commission ve slippage HICBIR sembol icin kalibre edilmedi (proje geneli
varsayilan 0.0) -- tick-level execution verisi de YOK (sadece M1 bar).
Bu ikisi TUM 101 sembol icin ayni/sabit.
"""

import hashlib
import json
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from strategy.config import (
    StrategyConfig, MODULE_R_MULTIPLE, MODULE_SL_BUFFER_RATIO,
    MODULE_DISABLED_TIMEFRAMES, BREAKEVEN_TRIGGER_PCT, BREAKEVEN_ENABLED_MODULES,
)
from backtest.validation import split_chronological
from backtest.engine import run_backtest
from strategy.fvg import compute_atr_series

SYNTHETIC_COST_DISCLAIMER = "SYNTHETIC COST SENSITIVITY -- NOT BROKER CALIBRATED (ATR-orantili sentetik stres testi, gercek spread degil)"
UNIVERSE_VERSION = "v1_101_frozen_2026-09-07"
RESEARCH_RUN_ID = "NOA101_2026-09-07"
DATA_DIR = Path("data/canonical")

# ATR-orantili sentetik spread seviyeleri (gercek broker spread'i olmadigi
# icin -- bkz. yukaridaki durustluk notu). "zero" mevcut resmi/varsayilan
# davranisi temsil eder (98 sembolde fiilen kullanilan), digerleri
# "ne kadar maliyet eklenirse sonuc negatife doner" sorusuna cevap arar.
SPREAD_SWEEP_ATR_FRACTIONS = {
    "zero": 0.0,
    "low": 0.01,
    "median": 0.04,
    "high": 0.10,
}


def spread_sensitivity_sweep(test_candles, test_signals, base_config: StrategyConfig) -> dict:
    """test partisyonunda AYNI sinyallerle 4 farkli spread seviyesinde
    run_backtest calistirir (sinyal uretimi spread'den etkilenmiyor,
    sadece dolum/cikis maliyeti degisiyor -- bkz. backtest/engine.py).
    """
    atr_series = compute_atr_series(test_candles, base_config.atr_period)
    valid_atrs = [a for a in atr_series if a is not None and a > 0]
    median_atr = sorted(valid_atrs)[len(valid_atrs) // 2] if valid_atrs else 0.0

    out = {}
    flip_level = None
    prev_exp = None
    for name, frac in SPREAD_SWEEP_ATR_FRACTIONS.items():
        spread_price = frac * median_atr
        cfg = replace(base_config, spread=spread_price)
        result = run_backtest(test_candles, test_signals, config=cfg)
        n = len(result.trades)
        total_r = sum(t.r_multiple for t in result.trades) if n else 0.0
        exp_r = total_r / n if n else 0.0
        win_rate = (sum(1 for t in result.trades if t.won) / n) if n else 0.0
        out[name] = {
            "spread_price": spread_price, "atr_fraction": frac,
            "n": n, "expectancy_r": round(exp_r, 4), "total_r": round(total_r, 4),
            "win_rate": round(win_rate, 4),
        }
        if prev_exp is not None and prev_exp > 0 and exp_r <= 0 and flip_level is None:
            flip_level = name
        prev_exp = exp_r

    out["median_atr_used"] = median_atr
    out["flips_negative_at"] = flip_level  # None => hicbir seviyede negatife donmedi (ya da zero'dan itibaren zaten negatif)
    out["already_negative_at_zero_cost"] = out["zero"]["expectancy_r"] <= 0
    out["disclaimer"] = SYNTHETIC_COST_DISCLAIMER
    return out


def _compute_mae_mfe_for_trade(candles, entry_idx, exit_idx, entry_price, risk, is_buy):
    mae = 0.0
    mfe = 0.0
    for j in range(entry_idx, exit_idx + 1):
        c = candles[j]
        if is_buy:
            adverse = entry_price - c["low"]
            favorable = c["high"] - entry_price
        else:
            adverse = c["high"] - entry_price
            favorable = entry_price - c["low"]
        mae = max(mae, adverse)
        mfe = max(mfe, favorable)
    return (mae / risk if risk > 0 else 0.0), (mfe / risk if risk > 0 else 0.0)


def mae_mfe_summary(test_candles, test_signals, config: StrategyConfig) -> dict:
    """Holdout test partisyonunda, RESMI (sweep degil, gercekte kullanilan)
    spread ile calisan run_backtest'in ciktisi uzerinden MAE/MFE ozeti.
    Ayni sinyal+config ile final_holdout'un kendi ic run_backtest cagrisiyla
    BIREBIR ayni islem kumesini uretir (deterministik)."""
    result = run_backtest(test_candles, test_signals, config=config)
    if not result.trades:
        return {"n": 0}

    mae_list, mfe_list = [], []
    mae_wins, mfe_losses = [], []
    for t in result.trades:
        risk = abs(t.entry_price - t.stop_loss)
        is_buy = t.signal.type.value == "buy"
        mae_r, mfe_r = _compute_mae_mfe_for_trade(test_candles, t.entry_fill_index, t.exit_index, t.entry_price, risk, is_buy)
        mae_list.append(mae_r)
        mfe_list.append(mfe_r)
        if t.won:
            mae_wins.append(mae_r)
        else:
            mfe_losses.append(mfe_r)

    def _mean(xs):
        return sum(xs) / len(xs) if xs else None

    def _median(xs):
        if not xs:
            return None
        s = sorted(xs)
        mid = len(s) // 2
        return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2

    return {
        "n": len(result.trades),
        "avg_mae_r": _mean(mae_list), "median_mae_r": _median(mae_list),
        "avg_mfe_r": _mean(mfe_list), "median_mfe_r": _median(mfe_list),
        "avg_mae_r_wins_only": _mean(mae_wins),
        "avg_mfe_r_losses_only": _mean(mfe_losses),
        "pct_losses_with_mfe_over_80pct": (sum(1 for m in mfe_losses if m >= 0.80) / len(mfe_losses)) if mfe_losses else None,
    }


def _git_commit_short() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _parameter_hash() -> str:
    payload = json.dumps({
        "MODULE_R_MULTIPLE": MODULE_R_MULTIPLE,
        "MODULE_SL_BUFFER_RATIO": MODULE_SL_BUFFER_RATIO,
        "MODULE_DISABLED_TIMEFRAMES": MODULE_DISABLED_TIMEFRAMES,
        "BREAKEVEN_TRIGGER_PCT": BREAKEVEN_TRIGGER_PCT,
        "BREAKEVEN_ENABLED_MODULES": BREAKEVEN_ENABLED_MODULES,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _data_version(symbol: str) -> str:
    p = DATA_DIR / f"V2_MULTI_{symbol}_M1_canonical.csv"
    if not p.exists():
        return "missing"
    st = p.stat()
    return f"{st.st_size}_{int(st.st_mtime)}"


def provenance(symbol: str) -> dict:
    """Kullanicinin talebi: her sonuc dosyasinda hangi universe/veri/kod/
    parametre halinin kullanildigi izlenebilir olmali."""
    return {
        "universe_version": UNIVERSE_VERSION,
        "data_version": _data_version(symbol),
        "strategy_version": _git_commit_short(),
        "parameter_hash": _parameter_hash(),
        "research_run_id": RESEARCH_RUN_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def execution_validity(symbol: str, spread_source: str) -> dict:
    """Iki ayri, birbirinden BAGIMSIZ eksen -- STRATEGY sonucunu ETKILEMEZ,
    sadece o sonuca ne kadar guvenilebilecegini nitelendirir."""
    real_spread_calibrated = False  # HICBIR sembolde gercek broker spread'i kalibre edilmedi
    commission_calibrated = False   # proje geneli, hicbir sembolde
    slippage_calibrated = False     # proje geneli, hicbir sembolde
    tick_level_data = False         # sadece M1 bar verisi var, tick yok

    if spread_source == "representative_estimate":
        status = "UNCERTAIN"
        reason = "spread=0 degil (temsili, sifirdan iyimser olmayan bir tahmin kullanildi) ama GERCEK broker spread'inden kalibre EDILMEDI -- proje kod yorumlarinda acikca 'temsili, henuz kalibre edilmedi' olarak isaretli"
    else:
        status = "INVALID"
        reason = "spread=0.0 (hic kalibre edilmedi, gercek maliyet kesinlikle >0) -- bu sembol icin hicbir temsili tahmin bile yok"

    return {
        "status": status, "reason": reason,
        "real_spread_calibrated": real_spread_calibrated,
        "commission_calibrated": commission_calibrated,
        "slippage_calibrated": slippage_calibrated,
        "tick_level_data_available": tick_level_data,
        "spread_source": spread_source,
    }


def strategy_validity(holdout_dict: dict) -> dict:
    """SADECE istatistiksel sonuca bakar -- execution gercekciligi bu
    fonksiyonu HIC ETKILEMEZ (kullanicinin acik talebi)."""
    tm = holdout_dict["test_metrics"]
    ci_lo = holdout_dict["block_bootstrap"]["ci_lower_95"]
    ci_hi = holdout_dict["block_bootstrap"]["ci_upper_95"]
    n = tm["filled_trades"]
    exp = tm["expectancy_r"]

    if ci_hi < 0:
        status, reason = "FAIL", "Bootstrap CI tamamen negatif -- istatistiksel olarak guvenilir sekilde basarisiz"
    elif ci_lo > 0 and n >= 100:
        status, reason = "PASS", "Bootstrap CI tamamen pozitif ve yeterli orneklem (n>=100) -- istatistiksel olarak anlamli pozitif"
    elif exp <= 0:
        status, reason = "FAIL", "Nokta tahmini (holdout expectancy) negatif veya sifir"
    else:
        status, reason = "UNCERTAIN", f"CI sifiri iceriyor ve/veya orneklem kucuk (n={n}) -- yon belirsiz"

    return {"status": status, "reason": reason, "ci_lower_95": ci_lo, "ci_upper_95": ci_hi, "n": n, "expectancy_r": exp}
