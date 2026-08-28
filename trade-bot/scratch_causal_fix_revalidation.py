"""
PROTOTIP (scratch, kalici degil): strategy/fvg.py + strategy/signal_engine.py'ye
uygulanan causal-filled duzeltmesinin (bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md,
"Kritik bulgu" bolumu) gercek etkisini, backtest/run_multi_symbol_validation.py'nin
RESMI metodolojisiyle (train/val/holdout %60/20/20 + block-bootstrap +
evidence classification) ama pratik bir sure icinde olcer.

Neden tam 137K mumluk GOLD gecmisi degil: duzeltme sonrasi sinyal sayisi
~35-40x artti (eskiden cogu FVG/OB "gelecekte hic kirilmiyor mu" diye
gelecege bakan bir on-filtreyle elenip sinyal havuzuna hic girmiyordu).
Bu, run_backtest'in sinyal basina build_levels'i yeniden hesaplayan
O(n)-per-signal maliyetiyle birlesince, tam gecmis kosusu bu oturumda
pratik olmayan bir sureye (muhtemelen saatler) cikiyor. Bunun yerine son
20.000 M30 mumu (train=12000/val=4000/test=4000, ayni %60/20/20 oran)
kullanarak AYNI DISIPLINLI metodolojiyi (kronolojik split + block-bootstrap
+ holdout classification) makul surede calistiriyoruz.

Config, gercek/mevcut GOLD sonucunda kayitli bilinen degerlerle
(backtest/results/V2_MULTI_GOLD_validation.json: spread=0.55, slippage=0.01)
sabitlendi -- resolve_symbol_config'in gerektirdigi canli MT5 baglantisina
ihtiyac duymadan ayni degerleri kullaniyoruz.
"""

from dataclasses import asdict

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
KNOWN_GOLD_CONFIG = StrategyConfig(spread=0.55, slippage=0.01, commission=0.0)


def _part_metrics(part_candles, config):
    sigs = generate_signals(part_candles, config=config)
    res = run_backtest(part_candles, sigs, config=config)
    return calculate_metrics(res.trades, total_signals=len(sigs),
                              unfilled_orders=res.unfilled_orders, skipped_no_tp=res.skipped_no_tp), sigs, res


def main():
    m1 = load_m1_canonical_as_candlev2("data/canonical/V2_MULTI_GOLD_M1_canonical.csv")
    m30_v2, _ = resample_m1(m1, Timeframe.M30)
    candles = [candlev2_to_strategy_dict(c) for c in m30_v2][-CANDLE_WINDOW:]
    print(f"pencere: son {len(candles)} M30 mum (tam gecmis {len(m30_v2)} mum)", flush=True)

    config = KNOWN_GOLD_CONFIG
    split_def, (train_c, val_c, test_c) = split_chronological(candles, 0.60, 0.20, 0.20)
    print(f"split: train={len(train_c)} val={len(val_c)} test={len(test_c)}", flush=True)

    train_metrics, _, _ = _part_metrics(train_c, config)
    print("train tamam", flush=True)
    val_metrics, _, _ = _part_metrics(val_c, config)
    print("val tamam", flush=True)
    test_metrics, test_signals, test_result = _part_metrics(test_c, config)
    print("test tamam", flush=True)

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

    print("\n=== TRAIN ===")
    print(asdict(train_metrics))
    print("\n=== VAL ===")
    print(asdict(val_metrics))
    print("\n=== TEST (holdout) ===")
    print(asdict(test_metrics))
    print("\n=== evidence_classification ===")
    print(classification, "--", reason)
    print("\n=== block_bootstrap ===")
    print(asdict(boot_m) if boot_m else None)


if __name__ == "__main__":
    main()
