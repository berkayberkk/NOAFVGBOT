"""
PROTOTIP (scratch, kalici degil): scratch_causal_fix_revalidation.py'nin
GOLD-tek-sembol kapsamini genisletir -- ayni disiplinli metodolojiyi
(train/val/holdout %60/20/20 + block-bootstrap + evidence classification)
farkli varlik siniflarindan birkac sembole (FX majör, kripto, endeks)
uygulayip, causal-filled duzeltmesinin sonucunun GOLD'a ozgu bir tesadüf
mu yoksa stratejinin genelinde mi gecerli oldugunu gorur.

Checkpoint'li (kesintiye dayanikli) -- her sembol islendikten hemen sonra
sonuc diske yazilir.
"""

import json
from dataclasses import asdict
from pathlib import Path

from backtest.engine import run_backtest
from backtest.final_holdout import ValidationComparison, classify_holdout_evidence
from backtest.regime import extract_enriched_oos_trades, compute_block_bootstrap
from backtest.run_multi_symbol_validation import load_m1_canonical_as_candlev2, candlev2_to_strategy_dict
from backtest.validation import calculate_metrics, split_chronological, WalkForwardWindowResult
from research.v2.data.models import Timeframe
from research.v2.data.resampler import resample_m1
from strategy.config import StrategyConfig
from strategy.signal_engine import generate_signals

CANDLE_WINDOW = 20_000
CHECKPOINT_PATH = Path("scratch_causal_fix_revalidation_multisymbol_checkpoint.json")

# (symbol, spread, slippage) -- backtest/results/V2_MULTI_<SYM>_validation.json'daki
# gercek/kayitli config degerleri (canli MT5 baglantisi gerektirmeden).
SYMBOLS = [
    ("GOLD", 0.55, 0.01),
    ("EURUSD", 0.0002, 1e-05),
    ("BTCUSD", 40.0, 0.01),
    ("US500", 0.75, 0.01),
    ("GBPJPY", None, None),  # asagida otomatik cekilecek
]


def _resolve_config(symbol: str, spread, slippage) -> StrategyConfig:
    if spread is None:
        with open(f"backtest/results/V2_MULTI_{symbol}_validation.json") as f:
            d = json.load(f)
        return StrategyConfig(spread=d["config"]["spread"], slippage=d["config"]["slippage"], commission=0.0)
    return StrategyConfig(spread=spread, slippage=slippage, commission=0.0)


def _part_metrics(part_candles, config):
    sigs = generate_signals(part_candles, config=config)
    res = run_backtest(part_candles, sigs, config=config)
    return calculate_metrics(res.trades, total_signals=len(sigs),
                              unfilled_orders=res.unfilled_orders, skipped_no_tp=res.skipped_no_tp), sigs, res


def _load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    return {}


def _save_checkpoint(data: dict) -> None:
    tmp = CHECKPOINT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(CHECKPOINT_PATH)


def _process_symbol(symbol: str, spread, slippage) -> dict:
    config = _resolve_config(symbol, spread, slippage)
    m1 = load_m1_canonical_as_candlev2(f"data/canonical/V2_MULTI_{symbol}_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2][-CANDLE_WINDOW:]

    _, (train_c, val_c, test_c) = split_chronological(candles, 0.60, 0.20, 0.20)
    train_metrics, _, _ = _part_metrics(train_c, config)
    val_metrics, _, _ = _part_metrics(val_c, config)
    test_metrics, _, test_result = _part_metrics(test_c, config)

    val_comp = ValidationComparison(
        val_expectancy_r=round(val_metrics.expectancy_r, 4),
        val_total_net_r=round(val_metrics.total_net_r, 4),
        val_profit_factor=round(val_metrics.profit_factor, 4) if val_metrics.profit_factor != float("inf") else 999.0,
        val_win_rate=round(val_metrics.win_rate, 4),
        val_max_drawdown_r=round(val_metrics.max_drawdown_r, 4),
        test_expectancy_r=round(test_metrics.expectancy_r, 4),
        test_total_net_r=round(test_metrics.total_net_r, 4),
        test_profit_factor=round(test_metrics.profit_factor, 4) if test_metrics.profit_factor != float("inf") else 999.0,
        test_win_rate=round(test_metrics.win_rate, 4),
        test_max_drawdown_r=round(test_metrics.max_drawdown_r, 4),
        expectancy_delta_r=round(test_metrics.expectancy_r - val_metrics.expectancy_r, 4),
        pf_delta=0.0, win_rate_delta=round(test_metrics.win_rate - val_metrics.win_rate, 4),
        max_dd_delta_r=round(test_metrics.max_drawdown_r - val_metrics.max_drawdown_r, 4),
    )
    classification, reason = classify_holdout_evidence(test_metrics, val_comp)

    dummy_wres = [WalkForwardWindowResult(0, 0, 0, 0, len(test_c), test_metrics, test_result.trades)]
    enriched = extract_enriched_oos_trades(test_c, dummy_wres, config=config)
    boot_m = compute_block_bootstrap(enriched, seed=42, block_size=3, num_resamples=1000) if enriched else None

    return {
        "train_metrics": asdict(train_metrics),
        "val_metrics": asdict(val_metrics),
        "test_metrics": asdict(test_metrics),
        "evidence_classification": classification,
        "evidence_reason": reason,
        "block_bootstrap": asdict(boot_m) if boot_m else None,
    }


def report(checkpoint: dict) -> None:
    print(f"\n{'sembol':10} {'classification':22} {'test_win%':>10} {'test_exp_r':>11} {'ci_95%':>22}")
    for symbol, data in checkpoint.items():
        tm = data["test_metrics"]
        boot = data.get("block_bootstrap")
        ci = f"[{boot['ci_lower_95']:.3f}, {boot['ci_upper_95']:.3f}]" if boot else "n/a"
        print(f"{symbol:10} {data['evidence_classification']:22} {tm['win_rate']:10.1%} {tm['expectancy_r']:11.4f} {ci:>22}")


def main():
    checkpoint = _load_checkpoint()
    remaining = [(s, sp, sl) for s, sp, sl in SYMBOLS if s not in checkpoint]
    print(f"Checkpoint'te {len(checkpoint)} sembol var, {len(remaining)} sembol kaldi.", flush=True)

    for symbol, spread, slippage in remaining:
        print(f"-- {symbol} işleniyor --", flush=True)
        result = _process_symbol(symbol, spread, slippage)
        checkpoint[symbol] = result
        _save_checkpoint(checkpoint)
        print(f"{symbol}: {result['evidence_classification']}", flush=True)

    report(checkpoint)


if __name__ == "__main__":
    main()
