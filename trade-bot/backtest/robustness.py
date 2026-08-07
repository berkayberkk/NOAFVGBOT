"""
Yerel Parametre Hassasiyeti ve Dayanıklılık Modülü (Parameter Sensitivity & Robustness).

Bu modül BASELINE_CONFIG_V1 etrafında tek bir parametreyi değiştirerek (±%5, ±%10)
duyarlılık ve plato analizleri gerçekleştirir. Test veri kümesi KESİNLİKLE KULLANILMAZ.
"""

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import List, Dict, Any, Tuple

from backtest.validation import run_walk_forward, BacktestMetrics, split_chronological
from strategy.config import StrategyConfig, DEFAULT_CONFIG


@dataclass
class VariantResult:
    parameter_name: str
    variant_value: Any
    baseline_value: Any
    percentage_change: float
    total_signals: int
    filled_trades: int
    win_rate: float
    total_net_r: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    profitable_windows: int
    losing_windows: int
    expectancy_degradation_pct: float
    net_r_degradation_pct: float
    max_dd_increase_pct: float


@dataclass
class ParameterRobustnessReport:
    parameter_name: str
    baseline_value: Any
    variants: List[VariantResult] = field(default_factory=list)
    classification: str = "ROBUST"  # ROBUST, SENSITIVE, FRAGILE
    plateau: str = "MODERATE PLATEAU"  # BROAD PLATEAU, MODERATE PLATEAU, NARROW SPIKE
    worst_expectancy_r: float = 0.0
    worst_total_net_r: float = 0.0
    worst_max_drawdown_r: float = 0.0


@dataclass
class GlobalRobustnessSummary:
    baseline_hash: str
    dataset_hash: str
    total_variants_tested: int
    positive_expectancy_variants: int
    positive_expectancy_pct: float
    positive_total_net_r_variants: int
    positive_total_net_r_pct: float
    high_win_window_variants: int
    high_win_window_pct: float
    worst_case_variant: str
    worst_case_expectancy_r: float
    worst_case_total_net_r: float
    worst_case_max_drawdown_r: float
    median_expectancy_r: float
    median_total_net_r: float
    min_trade_count: int
    median_trade_count: int
    max_trade_count: int
    overall_classification: str
    final_test_evaluated: bool = False


def generate_parameter_perturbations(param_name: str, baseline_val: Any) -> List[Tuple[Any, float]]:
    """
    Parametre için ±%5 ve ±%10 sapma değerleri üretir.
    Tam sayılar için benzersiz tamsayı değerler üretilir.
    """
    results: List[Tuple[Any, float]] = []

    if isinstance(baseline_val, bool):
        return results

    if isinstance(baseline_val, int):
        mults = [-0.10, -0.05, 0.05, 0.10]
        seen_vals = {baseline_val}
        for m in mults:
            cand = int(round(baseline_val * (1.0 + m)))
            if cand == baseline_val:
                cand = baseline_val + (1 if m > 0 else -1)
            if cand > 0 and cand not in seen_vals:
                seen_vals.add(cand)
                pct = ((cand - baseline_val) / baseline_val) * 100.0
                results.append((cand, round(pct, 2)))
    elif isinstance(baseline_val, float):
        for m in [-0.10, -0.05, 0.05, 0.10]:
            cand = round(baseline_val * (1.0 + m), 4)
            pct = round(m * 100.0, 2)
            results.append((cand, pct))

    return results


def classify_parameter(
    baseline_exp: float, baseline_net_r: float, baseline_dd: float, variants: List[VariantResult]
) -> Tuple[str, str]:
    """
    Önceden tanımlı kurallara göre parametreyi ROBUST, SENSITIVE veya FRAGILE olarak sınıflandırır.
    """
    if not variants:
        return "ROBUST", "BROAD PLATEAU"

    all_positive_exp = all(v.expectancy_r > 0 for v in variants)
    any_negative_exp = any(v.expectancy_r <= 0 for v in variants)

    worst_exp = min(v.expectancy_r for v in variants)
    exp_degradations = [v.expectancy_degradation_pct for v in variants]
    max_degradation = max(exp_degradations) if exp_degradations else 0.0

    worst_window_wins = min(v.profitable_windows for v in variants)

    # 1. Sınıflandırma
    if any_negative_exp or max_degradation > 70.0 or worst_window_wins < 2:
        classification = "FRAGILE"
    elif max_degradation > 40.0:
        classification = "SENSITIVE"
    else:
        classification = "ROBUST"

    # 2. Plato Tespiti
    exp_spread = max(v.expectancy_r for v in variants) - worst_exp
    if exp_spread < 0.10 * baseline_exp:
        plateau = "BROAD PLATEAU"
    elif exp_spread < 0.40 * baseline_exp:
        plateau = "MODERATE PLATEAU"
    else:
        plateau = "NARROW SPIKE"

    return classification, plateau


def run_robustness_analysis(
    candles: List[Dict[str, Any]],
    baseline_config: StrategyConfig = DEFAULT_CONFIG,
    num_wf_windows: int = 4,
    dataset_hash: str = "",
) -> Tuple[List[ParameterRobustnessReport], GlobalRobustnessSummary]:
    """
    BASELINE_CONFIG_V1 etrafında tüm strateji parametrelerini teker teker test eder.
    TEST veri kümesi KESİNLİKLE DIŞARIDA TUTULUR.
    """
    split_def, (train_candles, val_candles, test_candles) = split_chronological(candles, 0.60, 0.20, 0.20)
    test_holdout_size = len(test_candles)

    # 1. Baseline Değerlendirmesi
    _, baseline_oos = run_walk_forward(
        candles,
        num_windows=num_wf_windows,
        mode="expanding",
        config=baseline_config,
        min_train_size=len(train_candles) // 2,
        val_size=len(val_candles) // 2,
        test_holdout_size=test_holdout_size,
    )

    baseline_exp = baseline_oos.expectancy_r
    baseline_net_r = baseline_oos.total_net_r
    baseline_dd = baseline_oos.max_drawdown_r

    config_dict = {
        "atr_period": baseline_config.atr_period,
        "min_gap_to_atr_ratio": baseline_config.min_gap_to_atr_ratio,
        "max_gap_to_atr_ratio": baseline_config.max_gap_to_atr_ratio,
        "max_middle_candle_ratio": baseline_config.max_middle_candle_ratio,
        "avg_range_period": baseline_config.avg_range_period,
        "strong_move_ratio": baseline_config.strong_move_ratio,
        "swing_lookback": baseline_config.swing_lookback,
        "tolerance_atr_ratio": baseline_config.tolerance_atr_ratio,
        "min_level_touch_count": baseline_config.min_level_touch_count,
        "ema_period": baseline_config.ema_period,
    }

    baseline_hash = hashlib.sha256(str(baseline_config).encode("utf-8")).hexdigest()[:16]

    param_reports: List[ParameterRobustnessReport] = []
    all_variant_results: List[VariantResult] = []

    for param_name, base_val in config_dict.items():
        perturbations = generate_parameter_perturbations(param_name, base_val)
        var_results: List[VariantResult] = []

        for cand_val, pct_change in perturbations:
            # Varyasyon yapılandırması oluştur
            kw = dict(config_dict)
            kw[param_name] = cand_val
            # Maliyetler baseline ile 100% aynı tutulur
            kw["spread"] = baseline_config.spread
            kw["slippage"] = baseline_config.slippage
            kw["commission"] = baseline_config.commission

            var_cfg = StrategyConfig(**kw)

            wf_res, var_oos = run_walk_forward(
                candles,
                num_windows=num_wf_windows,
                mode="expanding",
                config=var_cfg,
                min_train_size=len(train_candles) // 2,
                val_size=len(val_candles) // 2,
                test_holdout_size=test_holdout_size,
            )

            prof_wins = sum(1 for w in wf_res if w.val_metrics.total_net_r > 0)
            lose_wins = len(wf_res) - prof_wins

            exp_deg = ((baseline_exp - var_oos.expectancy_r) / baseline_exp) * 100.0 if baseline_exp > 0 else 0.0
            r_deg = ((baseline_net_r - var_oos.total_net_r) / baseline_net_r) * 100.0 if baseline_net_r > 0 else 0.0
            dd_inc = ((var_oos.max_drawdown_r - baseline_dd) / baseline_dd) * 100.0 if baseline_dd > 0 else 0.0

            vr = VariantResult(
                parameter_name=param_name,
                variant_value=cand_val,
                baseline_value=base_val,
                percentage_change=pct_change,
                total_signals=var_oos.total_signals,
                filled_trades=var_oos.filled_trades,
                win_rate=round(var_oos.win_rate, 4),
                total_net_r=round(var_oos.total_net_r, 2),
                expectancy_r=round(var_oos.expectancy_r, 4),
                profit_factor=round(var_oos.profit_factor, 2),
                max_drawdown_r=round(var_oos.max_drawdown_r, 2),
                profitable_windows=prof_wins,
                losing_windows=lose_wins,
                expectancy_degradation_pct=round(exp_deg, 2),
                net_r_degradation_pct=round(r_deg, 2),
                max_dd_increase_pct=round(dd_inc, 2),
            )
            var_results.append(vr)
            all_variant_results.append(vr)

        classification, plateau = classify_parameter(baseline_exp, baseline_net_r, baseline_dd, var_results)

        w_exp = min((v.expectancy_r for v in var_results), default=baseline_exp)
        w_r = min((v.total_net_r for v in var_results), default=baseline_net_r)
        w_dd = max((v.max_drawdown_r for v in var_results), default=baseline_dd)

        p_report = ParameterRobustnessReport(
            parameter_name=param_name,
            baseline_value=base_val,
            variants=var_results,
            classification=classification,
            plateau=plateau,
            worst_expectancy_r=w_exp,
            worst_total_net_r=w_r,
            worst_max_drawdown_r=w_dd,
        )
        param_reports.append(p_report)

    # Global Özet
    n_total = len(all_variant_results)
    pos_exp = sum(1 for v in all_variant_results if v.expectancy_r > 0)
    pos_r = sum(1 for v in all_variant_results if v.total_net_r > 0)
    high_win = sum(1 for v in all_variant_results if v.profitable_windows >= 3)

    worst_variant = min(all_variant_results, key=lambda v: v.expectancy_r)

    exp_list = sorted([v.expectancy_r for v in all_variant_results])
    r_list = sorted([v.total_net_r for v in all_variant_results])
    trades_list = sorted([v.filled_trades for v in all_variant_results])

    med_exp = exp_list[len(exp_list) // 2] if exp_list else 0.0
    med_r = r_list[len(r_list) // 2] if r_list else 0.0

    any_fragile = any(pr.classification == "FRAGILE" for pr in param_reports)
    any_sensitive = any(pr.classification == "SENSITIVE" for pr in param_reports)

    if any_fragile:
        overall_class = "FRAGILE"
    elif any_sensitive:
        overall_class = "SENSITIVE"
    else:
        overall_class = "ROBUST"

    global_summary = GlobalRobustnessSummary(
        baseline_hash=baseline_hash,
        dataset_hash=dataset_hash,
        total_variants_tested=n_total,
        positive_expectancy_variants=pos_exp,
        positive_expectancy_pct=round((pos_exp / n_total) * 100.0, 2) if n_total > 0 else 0.0,
        positive_total_net_r_variants=pos_r,
        positive_total_net_r_pct=round((pos_r / n_total) * 100.0, 2) if n_total > 0 else 0.0,
        high_win_window_variants=high_win,
        high_win_window_pct=round((high_win / n_total) * 100.0, 2) if n_total > 0 else 0.0,
        worst_case_variant=f"{worst_variant.parameter_name}={worst_variant.variant_value}",
        worst_case_expectancy_r=worst_variant.expectancy_r,
        worst_case_total_net_r=worst_variant.total_net_r,
        worst_case_max_drawdown_r=worst_variant.max_drawdown_r,
        median_expectancy_r=med_exp,
        median_total_net_r=med_r,
        min_trade_count=trades_list[0] if trades_list else 0,
        median_trade_count=trades_list[len(trades_list) // 2] if trades_list else 0,
        max_trade_count=trades_list[-1] if trades_list else 0,
        overall_classification=overall_class,
        final_test_evaluated=False,
    )

    return param_reports, global_summary
