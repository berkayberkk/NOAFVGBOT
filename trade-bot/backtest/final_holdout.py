"""
NOAFVGBOT — Phase 4F: Final Sacred Holdout Evaluation Module.

Executes a single, scientifically controlled, one-shot out-of-sample (OOS) evaluation
on the final 20% sacred holdout partition (candles[18813:]).
"""

from dataclasses import dataclass, field, asdict
import json
from pathlib import Path
from typing import Any
import numpy as np

from data.loader import load_candles_from_csv
from backtest.data_quality import audit_dataset
from backtest.validation import split_chronological, calculate_metrics, BacktestMetrics
from backtest.engine import run_backtest
from strategy.config import StrategyConfig, DEFAULT_CONFIG
from strategy.signal_engine import generate_signals
from backtest.regime import (
    extract_enriched_oos_trades,
    analyze_time_distribution,
    analyze_volatility_regimes,
    analyze_market_states,
    analyze_directions,
    analyze_setup_types,
    analyze_concentration,
    compute_block_bootstrap,
    BucketMetrics,
    ConcentrationMetrics,
    BlockBootstrapMetrics,
)


@dataclass
class ValidationComparison:
    val_expectancy_r: float = 0.5253
    val_total_net_r: float = 22.06
    val_profit_factor: float = 4.42
    val_win_rate: float = 0.7857
    val_max_drawdown_r: float = 1.76
    test_expectancy_r: float = 0.0
    test_total_net_r: float = 0.0
    test_profit_factor: float = 0.0
    test_win_rate: float = 0.0
    test_max_drawdown_r: float = 0.0
    expectancy_delta_r: float = 0.0
    pf_delta: float = 0.0
    win_rate_delta: float = 0.0
    max_dd_delta_r: float = 0.0


@dataclass
class FinalHoldoutReport:
    git_commit: str
    baseline_fingerprint: str
    dataset_fingerprint: str
    test_start_index: int
    test_end_index: int
    test_start_date: str
    test_end_date: str
    test_candle_count: int
    data_quality_status: str
    test_metrics: BacktestMetrics = field(default=None)
    validation_comparison: ValidationComparison = field(default=None)
    concentration: ConcentrationMetrics = field(default=None)
    block_bootstrap: BlockBootstrapMetrics = field(default=None)
    time_distribution: list[BucketMetrics] = field(default_factory=list)
    volatility_regimes: list[BucketMetrics] = field(default_factory=list)
    market_states: list[BucketMetrics] = field(default_factory=list)
    directions: list[BucketMetrics] = field(default_factory=list)
    evidence_classification: str = "VALIDATED STRONG"
    evidence_reason: str = ""
    final_test_evaluated: bool = True
    final_test_consumed: bool = True


def classify_holdout_evidence(metrics: BacktestMetrics, val_comp: ValidationComparison) -> tuple[str, str]:
    """Soruşturmasız ve önceden belirlenmiş kurallarla nihai kanıt seviyesini sınıflandırır."""
    if metrics.expectancy_r <= 0 or metrics.total_net_r <= 0:
        return (
            "FAILED TO GENERALIZE",
            "Final holdout net R or expectancy is negative; system failed to generalize to unseen test data.",
        )

    if metrics.expectancy_r >= 0.30 and metrics.profit_factor >= 2.0 and metrics.max_drawdown_r <= 3.0:
        return (
            "VALIDATED STRONG",
            "Final holdout demonstrates strong positive expectancy and robust profit factor consistent with validation baseline.",
        )

    if metrics.expectancy_r > 0:
        return (
            "VALIDATED MODERATE",
            "Final holdout performance remains positive but displays reduced expectancy or higher drawdown compared to validation.",
        )

    return ("INCONCLUSIVE", "Sample size or metrics yield ambiguous evidence.")


def run_final_holdout_evaluation(
    candles: list[dict],
    git_commit: str = "2a2bf12",
    baseline_fingerprint: str = "5a56639725048f3d",
    dataset_fingerprint: str = "gold_m30_2yil_clean",
    config: StrategyConfig = DEFAULT_CONFIG,
) -> FinalHoldoutReport:
    """Nihai saklı test veri seti üzerinde TEK ATIMLIK değerlendirmeyi çalıştırır."""
    split_def, (train_candles, val_candles, test_candles) = split_chronological(candles, 0.60, 0.20, 0.20)

    test_start_idx = split_def.val_end
    test_end_idx = len(candles)
    test_start_date = str(test_candles[0].get("time", ""))
    test_end_date = str(test_candles[-1].get("time", ""))
    test_count = len(test_candles)

    # 1. Veri Kalite Denetimi
    dq_report = audit_dataset(test_candles)
    dq_status = dq_report.status.value

    if dq_status == "FAIL":
        raise RuntimeError("Data quality audit failed on FINAL TEST partition!")

    # 2. Sinyal ve İşlem Simülasyonu
    test_signals = generate_signals(test_candles, config=config)
    test_result = run_backtest(test_candles, test_signals, config=config)

    test_metrics = calculate_metrics(
        test_result.trades,
        total_signals=len(test_signals),
        unfilled_orders=test_result.unfilled_orders,
        skipped_no_tp=test_result.skipped_no_tp,
    )

    # 3. Doğrulama ile Karşılaştırma
    val_comp = ValidationComparison(
        val_expectancy_r=0.5253,
        val_total_net_r=22.06,
        val_profit_factor=4.42,
        val_win_rate=0.7857,
        val_max_drawdown_r=1.76,
        test_expectancy_r=round(test_metrics.expectancy_r, 4),
        test_total_net_r=round(test_metrics.total_net_r, 4),
        test_profit_factor=round(test_metrics.profit_factor, 4),
        test_win_rate=round(test_metrics.win_rate, 4),
        test_max_drawdown_r=round(test_metrics.max_drawdown_r, 4),
        expectancy_delta_r=round(test_metrics.expectancy_r - 0.5253, 4),
        pf_delta=round(test_metrics.profit_factor - 4.42, 4),
        win_rate_delta=round(test_metrics.win_rate - 0.7857, 4),
        max_dd_delta_r=round(test_metrics.max_drawdown_r - 1.76, 4),
    )

    # 4. Zenginleştirilmiş İşlem Analizleri
    # Dummy WalkForwardWindowResult wrapping for regime functions
    from backtest.validation import WalkForwardWindowResult
    dummy_wres = [WalkForwardWindowResult(0, 0, 0, 0, test_count, test_metrics, test_result.trades)]

    enriched = extract_enriched_oos_trades(test_candles, dummy_wres, config=config)

    time_m = analyze_time_distribution(enriched)
    vol_m = analyze_volatility_regimes(enriched)
    state_m = analyze_market_states(enriched)
    dir_m = analyze_directions(enriched)
    conc_m = analyze_concentration(enriched)
    boot_m = compute_block_bootstrap(enriched, seed=42, block_size=3, num_resamples=1000)

    classification, reason = classify_holdout_evidence(test_metrics, val_comp)

    return FinalHoldoutReport(
        git_commit=git_commit,
        baseline_fingerprint=baseline_fingerprint,
        dataset_fingerprint=dataset_fingerprint,
        test_start_index=test_start_idx,
        test_end_index=test_end_idx,
        test_start_date=test_start_date,
        test_end_date=test_end_date,
        test_candle_count=test_count,
        data_quality_status=dq_status,
        test_metrics=test_metrics,
        validation_comparison=val_comp,
        concentration=conc_m,
        block_bootstrap=boot_m,
        time_distribution=time_m,
        volatility_regimes=vol_m,
        market_states=state_m,
        directions=dir_m,
        evidence_classification=classification,
        evidence_reason=reason,
        final_test_evaluated=True,
        final_test_consumed=True,
    )
