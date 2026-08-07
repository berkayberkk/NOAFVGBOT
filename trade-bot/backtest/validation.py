"""
Tarihsel Doğrulama ve Performans Metrikleri Çerçevesi (Historical Validation Framework).

Bu modül kronolojik veri bölme (train/validation/test), yürüyen ileri (walk-forward)
değerlendirme ve sızıntısız (anti-leakage) performans metrikleri sunar.
"""

from dataclasses import dataclass, field
import math
import statistics
from typing import List, Tuple, Dict, Any

from strategy.config import StrategyConfig, DEFAULT_CONFIG
from strategy.signal_engine import generate_signals, Signal
from backtest.engine import run_backtest, BacktestResult, Trade


@dataclass(frozen=True)
class SplitDefinition:
    train_start: int
    train_end: int
    val_start: int
    val_end: int
    test_start: int
    test_end: int
    train_ratio: float = 0.60
    val_ratio: float = 0.20
    test_ratio: float = 0.20


@dataclass
class BacktestMetrics:
    total_signals: int = 0
    filled_trades: int = 0
    unfilled_orders: int = 0
    fill_rate: float = 0.0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_net_r: float = 0.0
    avg_net_r: float = 0.0
    median_net_r: float = 0.0
    expectancy_r: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_r: float = 0.0
    longest_losing_streak: int = 0
    std_dev_net_r: float = 0.0
    downside_dev_net_r: float = 0.0


@dataclass
class WalkForwardWindowResult:
    window_index: int
    train_start: int
    train_end: int
    val_start: int
    val_end: int
    val_metrics: BacktestMetrics = field(default_factory=BacktestMetrics)
    val_trades: List[Trade] = field(default_factory=list)


@dataclass
class ValidationReport:
    total_candles: int = 0
    start_time: str = ""
    end_time: str = ""
    split: SplitDefinition = field(default_factory=lambda: SplitDefinition(0, 0, 0, 0, 0, 0))
    train_metrics: BacktestMetrics = field(default_factory=BacktestMetrics)
    val_metrics: BacktestMetrics = field(default_factory=BacktestMetrics)
    walk_forward_results: List[WalkForwardWindowResult] = field(default_factory=list)
    oos_val_metrics: BacktestMetrics = field(default_factory=BacktestMetrics)
    test_status: str = "NOT EVALUATED (SACRED HOLDOUT)"


def split_chronological(
    candles: List[Dict[str, Any]],
    train_ratio: float = 0.60,
    val_ratio: float = 0.20,
    test_ratio: float = 0.20,
    min_candles: int = 50,
) -> Tuple[SplitDefinition, Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """
    Verisetini kronolojik sıraya sadık kalarak rastgele karıştırma ve örtüşme olmadan böler.
    """
    total = len(candles)
    if total < min_candles:
        raise ValueError(f"Yetersiz veriseti: {total} mum (minimum {min_candles} olmalı)")

    ratio_sum = train_ratio + val_ratio + test_ratio
    if abs(ratio_sum - 1.0) > 1e-5:
        raise ValueError(f"Bölme oranları toplamı 1.0 olmalıdır (mevcut: {ratio_sum})")

    if train_ratio <= 0 or val_ratio <= 0 or test_ratio <= 0:
        raise ValueError("Tüm bölme oranları pozitif olmalıdır")

    n_train = int(total * train_ratio)
    n_val = int(total * val_ratio)
    n_test = total - n_train - n_val

    if n_train < 10 or n_val < 5 or n_test < 5:
        raise ValueError("Mum sayısı küme başına çok düşük")

    train_start, train_end = 0, n_train
    val_start, val_end = n_train, n_train + n_val
    test_start, test_end = n_train + n_val, total

    split_def = SplitDefinition(
        train_start=train_start,
        train_end=train_end,
        val_start=val_start,
        val_end=val_end,
        test_start=test_start,
        test_end=test_end,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        test_ratio=test_ratio,
    )

    train_candles = candles[train_start:train_end]
    val_candles = candles[val_start:val_end]
    test_candles = candles[test_start:test_end]

    return split_def, (train_candles, val_candles, test_candles)


def calculate_metrics(trades: List[Trade], total_signals: int = 0, unfilled_orders: int = 0, skipped_no_tp: int = 0) -> BacktestMetrics:
    """
    İşlem listesinden tüm performans metriklerini güvenli ve sıfıra bölme hatasız hesaplar.
    """
    metrics = BacktestMetrics()
    metrics.total_signals = total_signals
    metrics.filled_trades = len(trades)
    metrics.unfilled_orders = unfilled_orders

    if total_signals > 0:
        metrics.fill_rate = len(trades) / total_signals
    else:
        metrics.fill_rate = 0.0

    if not trades:
        return metrics

    r_values = [t.net_r_multiple if t.net_r_multiple is not None else 0.0 for t in trades]
    wins = [t for t in trades if t.won]
    losses = [t for t in trades if not t.won]

    metrics.wins = len(wins)
    metrics.losses = len(losses)
    metrics.win_rate = len(wins) / len(trades)
    metrics.total_net_r = sum(r_values)
    metrics.avg_net_r = metrics.total_net_r / len(trades)
    metrics.median_net_r = statistics.median(r_values) if r_values else 0.0

    avg_win = (sum(t.net_r_multiple for t in wins) / len(wins)) if wins else 0.0
    avg_loss = (abs(sum(t.net_r_multiple for t in losses)) / len(losses)) if losses else 0.0

    # Beklenen Değer (Expectancy in R)
    metrics.expectancy_r = (metrics.win_rate * avg_win) - ((1.0 - metrics.win_rate) * avg_loss)

    # Kar Faktörü (Profit Factor)
    gross_profits = sum(t.net_r_multiple for t in wins if t.net_r_multiple > 0)
    gross_losses = abs(sum(t.net_r_multiple for t in losses if t.net_r_multiple < 0))

    if gross_losses > 0:
        metrics.profit_factor = gross_profits / gross_losses
    elif gross_profits > 0:
        metrics.profit_factor = float('inf')
    else:
        metrics.profit_factor = 0.0

    # Maksimum Drawdown (Kumülatif R cinsinden)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in r_values:
        equity += r
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    metrics.max_drawdown_r = max_dd

    # En Uzun Kayıp Serisi (Longest Losing Streak)
    curr_streak = 0
    max_streak = 0
    for t in trades:
        if not t.won:
            curr_streak += 1
            if curr_streak > max_streak:
                max_streak = curr_streak
        else:
            curr_streak = 0
    metrics.longest_losing_streak = max_streak

    # Standart Sapma ve Downside Sapma
    if len(r_values) > 1:
        metrics.std_dev_net_r = statistics.stdev(r_values)
        negative_r = [r for r in r_values if r < 0]
        if negative_r:
            metrics.downside_dev_net_r = math.sqrt(sum(r**2 for r in negative_r) / len(negative_r))
        else:
            metrics.downside_dev_net_r = 0.0
    else:
        metrics.std_dev_net_r = 0.0
        metrics.downside_dev_net_r = 0.0

    return metrics


def run_walk_forward(
    candles: List[Dict[str, Any]],
    num_windows: int = 4,
    mode: str = "expanding",
    config: StrategyConfig = DEFAULT_CONFIG,
    min_train_size: int = 100,
    val_size: int = 50,
    test_holdout_size: int = 0,
) -> Tuple[List[WalkForwardWindowResult], BacktestMetrics]:
    """
    Kronolojik yürüyen ileri (Walk-Forward) değerlendirmesi çalıştırır.
    Test veri kümesi tamamen saklı tutulur (holdout).
    """
    total_available = len(candles) - test_holdout_size
    if total_available < min_train_size + val_size:
        raise ValueError("Walk-forward çalıştırmak için yetersiz mum sayısı")

    eval_candles = candles[:total_available]

    window_results: List[WalkForwardWindowResult] = []
    all_oos_trades: List[Trade] = []
    total_oos_signals = 0
    total_oos_unfilled = 0

    step_size = max(1, (total_available - min_train_size - val_size) // max(1, num_windows - 1)) if num_windows > 1 else 0

    for w in range(num_windows):
        if mode == "expanding":
            tr_start = 0
            tr_end = min_train_size + w * step_size
        elif mode == "rolling":
            tr_start = w * step_size
            tr_end = tr_start + min_train_size
        else:
            raise ValueError(f"Bilinmeyen walk-forward modu: {mode}")

        v_start = tr_end
        v_end = min(v_start + val_size, total_available)

        if v_start >= v_end:
            break

        # Sadece doğrulama penceresi verileri üzerinde sinyal üretimi ve backtest
        val_window_candles = eval_candles[v_start:v_end]
        val_signals = generate_signals(val_window_candles, config=config)
        val_result = run_backtest(val_window_candles, val_signals, config=config)

        val_metrics = calculate_metrics(
            val_result.trades,
            total_signals=len(val_signals),
            unfilled_orders=val_result.unfilled_orders,
            skipped_no_tp=val_result.skipped_no_tp,
        )

        w_result = WalkForwardWindowResult(
            window_index=w,
            train_start=tr_start,
            train_end=tr_end,
            val_start=v_start,
            val_end=v_end,
            val_metrics=val_metrics,
            val_trades=val_result.trades,
        )

        window_results.append(w_result)
        all_oos_trades.extend(val_result.trades)
        total_oos_signals += len(val_signals)
        total_oos_unfilled += val_result.unfilled_orders

    aggregate_oos_metrics = calculate_metrics(
        all_oos_trades,
        total_signals=total_oos_signals,
        unfilled_orders=total_oos_unfilled,
    )

    return window_results, aggregate_oos_metrics


def build_validation_report(
    candles: List[Dict[str, Any]],
    config: StrategyConfig = DEFAULT_CONFIG,
    train_ratio: float = 0.60,
    val_ratio: float = 0.20,
    test_ratio: float = 0.20,
    num_wf_windows: int = 4,
) -> ValidationReport:
    """
    Eksiksiz kronolojik doğrulama raporu oluşturur. Test kümesi kesinlikle değerlendirilmez (Holdout).
    """
    report = ValidationReport()
    report.total_candles = len(candles)
    if candles:
        report.start_time = str(candles[0].get("time", ""))
        report.end_time = str(candles[-1].get("time", ""))

    split_def, (train_candles, val_candles, test_candles) = split_chronological(
        candles, train_ratio=train_ratio, val_ratio=val_ratio, test_ratio=test_ratio
    )
    report.split = split_def

    # Train evaluation
    tr_signals = generate_signals(train_candles, config=config)
    tr_result = run_backtest(train_candles, tr_signals, config=config)
    report.train_metrics = calculate_metrics(
        tr_result.trades, len(tr_signals), tr_result.unfilled_orders, tr_result.skipped_no_tp
    )

    # Validation evaluation
    val_signals = generate_signals(val_candles, config=config)
    val_result = run_backtest(val_candles, val_signals, config=config)
    report.val_metrics = calculate_metrics(
        val_result.trades, len(val_signals), val_result.unfilled_orders, val_result.skipped_no_tp
    )

    # Walk-forward on non-test data
    wf_results, oos_metrics = run_walk_forward(
        candles,
        num_windows=num_wf_windows,
        mode="expanding",
        config=config,
        min_train_size=len(train_candles) // 2 if len(train_candles) > 100 else len(train_candles),
        val_size=len(val_candles) // 2 if len(val_candles) > 50 else len(val_candles),
        test_holdout_size=len(test_candles),
    )

    report.walk_forward_results = wf_results
    report.oos_val_metrics = oos_metrics
    report.test_status = "NOT EVALUATED (SACRED HOLDOUT)"

    return report
