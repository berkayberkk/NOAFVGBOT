"""
NOAFVGBOT — Phase 4E: Regime & Dependence Robustness Module.

Analyzes time distribution, volatility regime, market state, direction, setup type,
concentration, serial dependence, block bootstrap, and leave-one-window-out stability
for out-of-sample (OOS) validation trades.
"""

from dataclasses import dataclass, field, asdict
import math
import random
from typing import Any
import numpy as np

from strategy.config import StrategyConfig, DEFAULT_CONFIG
from strategy.fvg import compute_atr_series
from strategy.trend import detect_trend, TrendDirection
from backtest.validation import calculate_metrics, WalkForwardWindowResult
from backtest.engine import Trade, SignalType


@dataclass
class BucketMetrics:
    bucket_name: str
    filled_trades: int
    total_net_r: float
    expectancy_r: float
    win_rate: float
    profit_factor: float
    max_drawdown_r: float


@dataclass
class ConcentrationMetrics:
    top_1_contribution_r: float
    top_3_contribution_r: float
    top_5_contribution_r: float
    top_10_pct_contribution_pct: float
    after_removing_best_1_r: float
    after_removing_best_1_expectancy: float
    after_removing_best_3_r: float
    after_removing_best_3_expectancy: float
    after_removing_best_5_r: float
    after_removing_best_5_expectancy: float


@dataclass
class SerialDependenceMetrics:
    lag_1_autocorrelation: float
    win_to_win_count: int
    win_to_loss_count: int
    loss_to_win_count: int
    loss_to_loss_count: int
    max_winning_streak: int
    max_losing_streak: int


@dataclass
class BlockBootstrapMetrics:
    seed: int
    block_size: int
    num_resamples: int
    mean_expectancy_r: float
    ci_lower_95: float
    ci_upper_95: float


@dataclass
class LeaveOneWindowOutMetrics:
    excluded_window: str
    filled_trades: int
    total_net_r: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float


@dataclass
class RegimeRobustnessReport:
    baseline_fingerprint: str
    total_oos_trades: int
    time_distribution: list[BucketMetrics] = field(default_factory=list)
    volatility_regimes: list[BucketMetrics] = field(default_factory=list)
    market_states: list[BucketMetrics] = field(default_factory=list)
    directions: list[BucketMetrics] = field(default_factory=list)
    setup_types: list[BucketMetrics] = field(default_factory=list)
    concentration: ConcentrationMetrics = field(default=None)
    serial_dependence: SerialDependenceMetrics = field(default=None)
    block_bootstrap: BlockBootstrapMetrics = field(default=None)
    leave_one_window_out: list[LeaveOneWindowOutMetrics] = field(default_factory=list)
    overall_classification: str = "BROADLY DISTRIBUTED"
    classification_reason: str = ""
    final_test_evaluated: bool = False


def extract_enriched_oos_trades(
    candles: list[dict],
    window_results: list[WalkForwardWindowResult],
    config: StrategyConfig = DEFAULT_CONFIG,
) -> list[dict[str, Any]]:
    """
    Tüm OOS pencere işlemlerini çıkarır ve zaman, ATR, trend durumu bilgileri ile zenginleştirir.
    """
    atr_series = compute_atr_series(candles, config.atr_period)
    trend_states = detect_trend(candles, config=config)

    enriched_trades = []

    for w_res in window_results:
        v_start = w_res.val_start
        for trade in w_res.val_trades:
            abs_signal_idx = v_start + trade.signal.index
            abs_entry_idx = v_start + trade.entry_index
            entry_candle = candles[abs_entry_idx]

            timestamp_str = str(entry_candle.get("time", ""))
            year = timestamp_str[:4] if len(timestamp_str) >= 4 else "UNKNOWN"
            month = timestamp_str[:7] if len(timestamp_str) >= 7 else "UNKNOWN"
            quarter = f"{year}-Q{(int(timestamp_str[5:7])-1)//3 + 1}" if len(timestamp_str) >= 7 else "UNKNOWN"

            atr_val = atr_series[abs_entry_idx] or 0.0
            trend_val = trend_states[abs_signal_idx].direction.value if abs_signal_idx < len(trend_states) else "sideways"

            enriched_trades.append({
                "trade": trade,
                "window_index": w_res.window_index,
                "abs_signal_index": abs_signal_idx,
                "abs_entry_index": abs_entry_idx,
                "timestamp": timestamp_str,
                "year": year,
                "quarter": quarter,
                "month": month,
                "direction": trade.signal.type.value,
                "setup_type": trade.signal.setup_type.value if hasattr(trade.signal.setup_type, "value") else str(trade.signal.setup_type),
                "net_r": trade.net_r_multiple if trade.net_r_multiple is not None else 0.0,
                "won": trade.won,
                "atr": atr_val,
                "trend": trend_val,
            })

    return enriched_trades


def calculate_bucket_metrics(bucket_name: str, trades: list[dict[str, Any]]) -> BucketMetrics:
    """Verilen işlem kümesi için temel istatistikleri hesaplar."""
    if not trades:
        return BucketMetrics(bucket_name, 0, 0.0, 0.0, 0.0, 0.0, 0.0)

    trade_objs = [t["trade"] for t in trades if t.get("trade") is not None]
    if len(trade_objs) == len(trades):
        m = calculate_metrics(trade_objs, len(trades), 0, 0)
        return BucketMetrics(
            bucket_name=bucket_name,
            filled_trades=len(trades),
            total_net_r=round(m.total_net_r, 4),
            expectancy_r=round(m.expectancy_r, 4),
            win_rate=round(m.win_rate, 4),
            profit_factor=round(m.profit_factor, 4),
            max_drawdown_r=round(m.max_drawdown_r, 4),
        )

    r_vals = [t["net_r"] for t in trades]
    wins = [r for r in r_vals if r > 0]
    losses = [abs(r) for r in r_vals if r < 0]
    total_r = sum(r_vals)
    exp = total_r / len(r_vals)
    win_rate = len(wins) / len(r_vals)
    pf = sum(wins) / sum(losses) if sum(losses) > 0 else (999.0 if sum(wins) > 0 else 0.0)

    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in r_vals:
        cum += r
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    return BucketMetrics(
        bucket_name=bucket_name,
        filled_trades=len(trades),
        total_net_r=round(total_r, 4),
        expectancy_r=round(exp, 4),
        win_rate=round(win_rate, 4),
        profit_factor=round(pf, 4),
        max_drawdown_r=round(max_dd, 4),
    )


def analyze_time_distribution(enriched_trades: list[dict[str, Any]]) -> list[BucketMetrics]:
    """Zaman bazlı (Yıl ve Çeyrek) kırılımları hesaplar."""
    by_year: dict[str, list] = {}
    by_quarter: dict[str, list] = {}

    for t in enriched_trades:
        by_year.setdefault(t["year"], []).append(t)
        by_quarter.setdefault(t["quarter"], []).append(t)

    metrics = []
    for yr in sorted(by_year.keys()):
        metrics.append(calculate_bucket_metrics(f"Year {yr}", by_year[yr]))
    for qtr in sorted(by_quarter.keys()):
        metrics.append(calculate_bucket_metrics(f"Quarter {qtr}", by_quarter[qtr]))

    return metrics


def analyze_volatility_regimes(enriched_trades: list[dict[str, Any]]) -> list[BucketMetrics]:
    """
    İşlem anındaki ATR değerlerine göre LOW, MEDIUM, HIGH volatilite rejimlerini hesaplar.
    Ayrışma: OOS kümesi içindeki 33. ve 66. yüzdelikler (tertiles) baz alınır.
    """
    if not enriched_trades:
        return []

    atrs = [t["atr"] for t in enriched_trades]
    q33, q66 = np.percentile(atrs, [33.33, 66.67])

    low_t, med_t, high_t = [], [], []
    for t in enriched_trades:
        if t["atr"] <= q33:
            low_t.append(t)
        elif t["atr"] <= q66:
            med_t.append(t)
        else:
            high_t.append(t)

    return [
        calculate_bucket_metrics(f"LOW Volatility (ATR <= {q33:.2f})", low_t),
        calculate_bucket_metrics(f"MEDIUM Volatility ({q33:.2f} < ATR <= {q66:.2f})", med_t),
        calculate_bucket_metrics(f"HIGH Volatility (ATR > {q66:.2f})", high_t),
    ]


def analyze_market_states(enriched_trades: list[dict[str, Any]]) -> list[BucketMetrics]:
    """Trend yönüne (UP, DOWN, SIDEWAYS) göre kırılım."""
    by_trend: dict[str, list] = {}
    for t in enriched_trades:
        by_trend.setdefault(t["trend"].upper(), []).append(t)

    return [calculate_bucket_metrics(f"Trend {tr}", by_trend[tr]) for tr in sorted(by_trend.keys())]


def analyze_directions(enriched_trades: list[dict[str, Any]]) -> list[BucketMetrics]:
    """Yön (BUY vs SELL) bazlı kırılım."""
    buys = [t for t in enriched_trades if t["direction"] == "buy"]
    sells = [t for t in enriched_trades if t["direction"] == "sell"]
    return [
        calculate_bucket_metrics("LONG (BUY)", buys),
        calculate_bucket_metrics("SHORT (SELL)", sells),
    ]


def analyze_setup_types(enriched_trades: list[dict[str, Any]]) -> list[BucketMetrics]:
    """Sinyal türüne (A+, FVG, OB, vb.) göre kırılım."""
    by_setup: dict[str, list] = {}
    for t in enriched_trades:
        by_setup.setdefault(t["setup_type"], []).append(t)

    return [calculate_bucket_metrics(f"Setup {st}", by_setup[st]) for st in sorted(by_setup.keys())]


def analyze_concentration(enriched_trades: list[dict[str, Any]]) -> ConcentrationMetrics:
    """En iyi kazanan işlemlerin toplam PnL üzerindeki etkisini ölçer."""
    r_values = sorted([t["net_r"] for t in enriched_trades], reverse=True)
    total_r = sum(r_values)
    n = len(r_values)

    if n == 0 or total_r == 0:
        return ConcentrationMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    top_1 = r_values[0] if n >= 1 else 0.0
    top_3 = sum(r_values[:3]) if n >= 3 else total_r
    top_5 = sum(r_values[:5]) if n >= 5 else total_r

    top_10_pct_count = max(1, int(math.ceil(n * 0.10)))
    top_10_pct_sum = sum(r_values[:top_10_pct_count])
    top_10_pct_contrib = (top_10_pct_sum / total_r) * 100.0 if total_r != 0 else 0.0

    r_no_1 = r_values[1:] if n > 1 else []
    r_no_3 = r_values[3:] if n > 3 else []
    r_no_5 = r_values[5:] if n > 5 else []

    return ConcentrationMetrics(
        top_1_contribution_r=round(top_1, 4),
        top_3_contribution_r=round(top_3, 4),
        top_5_contribution_r=round(top_5, 4),
        top_10_pct_contribution_pct=round(top_10_pct_contrib, 2),
        after_removing_best_1_r=round(sum(r_no_1), 4),
        after_removing_best_1_expectancy=round(sum(r_no_1) / len(r_no_1), 4) if r_no_1 else 0.0,
        after_removing_best_3_r=round(sum(r_no_3), 4),
        after_removing_best_3_expectancy=round(sum(r_no_3) / len(r_no_3), 4) if r_no_3 else 0.0,
        after_removing_best_5_r=round(sum(r_no_5), 4),
        after_removing_best_5_expectancy=round(sum(r_no_5) / len(r_no_5), 4) if r_no_5 else 0.0,
    )


def analyze_serial_dependence(enriched_trades: list[dict[str, Any]]) -> SerialDependenceMetrics:
    """Serisel bağımlılık, otokorelasyon ve ardışık seri analizleri."""
    r_series = [t["net_r"] for t in enriched_trades]
    n = len(r_series)

    if n < 2:
        return SerialDependenceMetrics(0.0, 0, 0, 0, 0, 0, 0)

    # Lag-1 Autocorrelation
    arr = np.array(r_series)
    mean_val = np.mean(arr)
    var_val = np.var(arr)
    if var_val == 0:
        autocorr = 0.0
    else:
        autocorr = float(np.mean((arr[:-1] - mean_val) * (arr[1:] - mean_val)) / var_val)

    # Win/Loss Transitions
    w_w, w_l, l_w, l_l = 0, 0, 0, 0
    max_w_streak, max_l_streak = 0, 0
    cur_w_streak, cur_l_streak = 0, 0

    for i, t in enumerate(enriched_trades):
        won = t["won"]
        if won:
            cur_w_streak += 1
            cur_l_streak = 0
            max_w_streak = max(max_w_streak, cur_w_streak)
        else:
            cur_l_streak += 1
            cur_w_streak = 0
            max_l_streak = max(max_l_streak, cur_l_streak)

        if i > 0:
            prev_won = enriched_trades[i - 1]["won"]
            if prev_won and won:
                w_w += 1
            elif prev_won and not won:
                w_l += 1
            elif not prev_won and won:
                l_w += 1
            else:
                l_l += 1

    return SerialDependenceMetrics(
        lag_1_autocorrelation=round(autocorr, 4),
        win_to_win_count=w_w,
        win_to_loss_count=w_l,
        loss_to_win_count=l_w,
        loss_to_loss_count=l_l,
        max_winning_streak=max_w_streak,
        max_losing_streak=max_l_streak,
    )


def compute_block_bootstrap(
    enriched_trades: list[dict[str, Any]],
    seed: int = 42,
    block_size: int = 3,
    num_resamples: int = 1000,
) -> BlockBootstrapMetrics:
    """Sabit blok boyutuyla Blok Bootstrap %95 Güven Aralığı hesabı."""
    r_series = [t["net_r"] for t in enriched_trades]
    n = len(r_series)
    if n == 0:
        return BlockBootstrapMetrics(seed, block_size, num_resamples, 0.0, 0.0, 0.0)

    rng = random.Random(seed)
    num_blocks_needed = int(math.ceil(n / block_size))
    max_start_idx = max(0, n - block_size)

    boot_means = []
    for _ in range(num_resamples):
        sample = []
        for _ in range(num_blocks_needed):
            idx = rng.randint(0, max_start_idx) if max_start_idx > 0 else 0
            sample.extend(r_series[idx : idx + block_size])
        sample = sample[:n]
        boot_means.append(sum(sample) / n)

    boot_means.sort()
    ci_lower = boot_means[int(num_resamples * 0.025)]
    ci_upper = boot_means[int(num_resamples * 0.975)]
    mean_exp = sum(boot_means) / num_resamples

    return BlockBootstrapMetrics(
        seed=seed,
        block_size=block_size,
        num_resamples=num_resamples,
        mean_expectancy_r=round(mean_exp, 4),
        ci_lower_95=round(ci_lower, 4),
        ci_upper_95=round(ci_upper, 4),
    )


def compute_leave_one_window_out(
    window_results: list[WalkForwardWindowResult],
) -> list[LeaveOneWindowOutMetrics]:
    """4 OOS penceresinin her birini sırayla hariç tutarak birleşik metrikleri yeniden hesaplar."""
    metrics_list = []
    n_windows = len(window_results)

    for i in range(n_windows):
        included = [w for idx, w in enumerate(window_results) if idx != i]
        comb_trades = []
        for w in included:
            comb_trades.extend(w.val_trades)

        if not comb_trades:
            continue

        m = calculate_metrics(comb_trades, len(comb_trades), 0, 0)
        metrics_list.append(LeaveOneWindowOutMetrics(
            excluded_window=f"Exclude W{i}",
            filled_trades=len(comb_trades),
            total_net_r=round(m.total_net_r, 4),
            expectancy_r=round(m.expectancy_r, 4),
            profit_factor=round(m.profit_factor, 4),
            max_drawdown_r=round(m.max_drawdown_r, 4),
        ))

    return metrics_list


def classify_regime_robustness(
    time_metrics: list[BucketMetrics],
    vol_metrics: list[BucketMetrics],
    concentration: ConcentrationMetrics,
    low_metrics: list[LeaveOneWindowOutMetrics],
) -> tuple[str, str]:
    """
    OOS Edge dayanıklılığını kural bazlı sınıflandırır.
    Sınıflar: BROADLY DISTRIBUTED, PARTIALLY CONCENTRATED, HIGHLY CONCENTRATED
    """
    # Her pencere çıkarıldığında expectancy pozitif mi?
    all_low_positive = all(m.expectancy_r > 0 for m in low_metrics)
    # En iyi 3 işlem çıkarıldığında net R pozitif mi?
    positive_after_top3 = concentration.after_removing_best_3_r > 0

    if not all_low_positive or not positive_after_top3:
        return (
            "HIGHLY CONCENTRATED",
            "Aggregate OOS edge disappears or flips negative when key windows or top trades are removed.",
        )

    # Volatilite ve Zaman rejimlerinde ciddi bozulma var mı?
    non_empty_time = [m for m in time_metrics if m.filled_trades >= 3]
    negative_time_count = sum(1 for m in non_empty_time if m.expectancy_r < 0)

    if negative_time_count > 1 or concentration.top_5_contribution_r > concentration.after_removing_best_5_r * 2:
        return (
            "PARTIALLY CONCENTRATED",
            "Performance is positive overall but relies partially on high-volatility windows or specific clusters.",
        )

    return (
        "BROADLY DISTRIBUTED",
        "Edge is positive across all OOS windows, time periods, volatility regimes, and directions even after removing top winning trades.",
    )


def run_regime_robustness_analysis(
    candles: list[dict],
    window_results: list[WalkForwardWindowResult],
    baseline_fingerprint: str = "5a56639725048f3d",
    config: StrategyConfig = DEFAULT_CONFIG,
) -> RegimeRobustnessReport:
    """Tüm Phase 4E rejim ve bağımlılık analizlerini yürütür ve rapor döner."""
    enriched = extract_enriched_oos_trades(candles, window_results, config=config)

    time_m = analyze_time_distribution(enriched)
    vol_m = analyze_volatility_regimes(enriched)
    state_m = analyze_market_states(enriched)
    dir_m = analyze_directions(enriched)
    setup_m = analyze_setup_types(enriched)
    conc_m = analyze_concentration(enriched)
    ser_m = analyze_serial_dependence(enriched)
    boot_m = compute_block_bootstrap(enriched, seed=42, block_size=3, num_resamples=1000)
    low_m = compute_leave_one_window_out(window_results)

    classification, reason = classify_regime_robustness(time_m, vol_m, conc_m, low_m)

    return RegimeRobustnessReport(
        baseline_fingerprint=baseline_fingerprint,
        total_oos_trades=len(enriched),
        time_distribution=time_m,
        volatility_regimes=vol_m,
        market_states=state_m,
        directions=dir_m,
        setup_types=setup_m,
        concentration=conc_m,
        serial_dependence=ser_m,
        block_bootstrap=boot_m,
        leave_one_window_out=low_m,
        overall_classification=classification,
        classification_reason=reason,
        final_test_evaluated=False,
    )
