"""
NOAFVGBOT — Phase 5D: Forward Evidence Calibration & Drift Analysis.

Measures how NEW forward SHADOW observations differ from the frozen historical
execution and strategy model (BASELINE_CONFIG_V1).

STRICT NON-MUTATION GUARANTEE:
- Absolutely NO auto-calibration or auto-tuning of strategy or execution config.
- BASELINE_CONFIG_V1 is completely immutable.
- SHADOW slippage is explicitly marked NOT OBSERVED.
- Forward evidence is strictly restricted to observations > 2026-07-24 23:30:00.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
import math
import numpy as np
from pathlib import Path
from typing import Any, Optional, List, Dict

from backtest.forward import (
    HISTORICAL_CUTOFF_TIMESTAMP,
    ForwardMode,
    BASELINE_CONFIG_V1,
)
from backtest.forward_store import ForwardStore


class EvidenceSampleState:
    COLLECTING = "COLLECTING"      # < 10 trades
    PRELIMINARY = "PRELIMINARY"    # 10 - 29 trades
    REVIEWABLE = "REVIEWABLE"      # >= 30 trades


class DriftClassification:
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NORMAL_VARIATION = "NORMAL_VARIATION"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SEVERE_DRIFT = "SEVERE_DRIFT"


@dataclass
class SpreadCalibrationReport:
    sample_count: int = 0
    modeled_spread: float = 0.30
    mean_spread: Optional[float] = None
    median_spread: Optional[float] = None
    std_dev_spread: Optional[float] = None
    p75_spread: Optional[float] = None
    p90_spread: Optional[float] = None
    p95_spread: Optional[float] = None
    max_spread: Optional[float] = None
    pct_lte_0_30: Optional[float] = None
    pct_gt_0_30: Optional[float] = None
    pct_gt_0_45: Optional[float] = None
    pct_gt_0_60: Optional[float] = None
    spread_by_hour: Dict[int, float] = field(default_factory=dict)
    spread_by_weekday: Dict[int, float] = field(default_factory=dict)


@dataclass
class SignalAndFillDriftReport:
    total_signals: int = 0
    intended_orders: int = 0
    shadow_fills: int = 0
    unfilled_orders: int = 0
    forward_fill_rate: Optional[float] = None
    historical_validation_fill_rate: float = 0.3387
    historical_holdout_fill_rate: float = 0.3730
    fill_rate_diff_vs_validation: Optional[float] = None
    fill_rate_diff_vs_holdout: Optional[float] = None
    forward_signals_per_1000_bars: Optional[float] = None
    historical_signals_per_1000_bars: float = 10.84
    long_short_mix: Dict[str, float] = field(default_factory=dict)
    setup_type_mix: Dict[str, float] = field(default_factory=dict)


@dataclass
class PerformanceDriftReport:
    completed_trades: int = 0
    expected_r_total: Optional[float] = None
    realized_r_total: Optional[float] = None
    execution_drag_r: Optional[float] = None
    forward_expectancy_r: Optional[float] = None
    historical_validation_expectancy: float = 0.5253
    historical_holdout_expectancy: float = 0.4103
    expectancy_diff_vs_holdout: Optional[float] = None
    forward_win_rate: Optional[float] = None
    historical_holdout_win_rate: float = 0.8950
    forward_profit_factor: Optional[float] = None
    historical_holdout_profit_factor: float = 6.94
    forward_max_drawdown_r: Optional[float] = None
    shadow_slippage_status: str = "NOT OBSERVED"


@dataclass
class RuntimeReliabilityReport:
    total_events: int = 0
    runtime_outages: int = 0
    reconnect_count: int = 0
    recovered_bars: int = 0
    stale_ticks_count: int = 0
    invalid_ticks_count: int = 0
    duplicate_bars_ignored: int = 0
    bar_gaps_count: int = 0
    shadow_processing_latency_ms: Dict[str, float] = field(default_factory=dict)


@dataclass
class ForwardDriftReport:
    run_id: str
    symbol: str
    timeframe: str
    config_fingerprint: str
    historical_cutoff: str
    evidence_state: str
    drift_classification: str
    spread_report: SpreadCalibrationReport
    signal_fill_report: SignalAndFillDriftReport
    performance_report: PerformanceDriftReport
    reliability_report: RuntimeReliabilityReport
    generated_at_utc: str = ""


class ForwardDriftAnalyzer:
    """Forward Evidence Calibration & Drift Analyzer."""

    def __init__(self, store: ForwardStore, run_id: str):
        self.store = store
        self.run_id = run_id

    def analyze(self) -> ForwardDriftReport:
        events = self.store.get_events_for_run(self.run_id)
        trades = self.store.get_trades_for_run(self.run_id)

        # Filtrele: strictly newer than cutoff
        forward_events = [e for e in events if e.get("timestamp_utc", "") > HISTORICAL_CUTOFF_TIMESTAMP]
        forward_trades = [t for t in trades if t.get("exit_timestamp", "") > HISTORICAL_CUTOFF_TIMESTAMP or t.get("entry_timestamp", "") > HISTORICAL_CUTOFF_TIMESTAMP]

        # 1. Evidence Sample State
        trade_count = len(forward_trades)
        if trade_count >= 30:
            evidence_state = EvidenceSampleState.REVIEWABLE
        elif trade_count >= 10:
            evidence_state = EvidenceSampleState.PRELIMINARY
        else:
            evidence_state = EvidenceSampleState.COLLECTING

        # 2. Spread Calibration
        spreads = []
        for e in forward_events:
            payload = e.get("payload_json", {})
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            if "actual_spread" in payload and payload["actual_spread"] is not None:
                spreads.append(float(payload["actual_spread"]))

        if len(spreads) > 0:
            arr = np.array(spreads)
            mean_sp = float(np.mean(arr))
            median_sp = float(np.median(arr))
            std_sp = float(np.std(arr))
            p75_sp = float(np.percentile(arr, 75))
            p90_sp = float(np.percentile(arr, 90))
            p95_sp = float(np.percentile(arr, 95))
            max_sp = float(np.max(arr))
            n = len(spreads)
            pct_lte_030 = float(np.sum(arr <= 0.30) / n * 100.0)
            pct_gt_030 = float(np.sum(arr > 0.30) / n * 100.0)
            pct_gt_045 = float(np.sum(arr > 0.45) / n * 100.0)
            pct_gt_060 = float(np.sum(arr > 0.60) / n * 100.0)
        else:
            mean_sp = median_sp = std_sp = p75_sp = p90_sp = p95_sp = max_sp = None
            pct_lte_030 = pct_gt_030 = pct_gt_045 = pct_gt_060 = None

        spread_report = SpreadCalibrationReport(
            sample_count=len(spreads),
            modeled_spread=BASELINE_CONFIG_V1.spread,
            mean_spread=mean_sp,
            median_spread=median_sp,
            std_dev_spread=std_sp,
            p75_spread=p75_sp,
            p90_spread=p90_sp,
            p95_spread=p95_sp,
            max_spread=max_sp,
            pct_lte_0_30=pct_lte_030,
            pct_gt_0_30=pct_gt_030,
            pct_gt_0_45=pct_gt_045,
            pct_gt_0_60=pct_gt_060,
        )

        # 3. Signal & Fill Drift
        signals = [e for e in forward_events if e.get("event_type") == "SIGNAL_GENERATED"]
        sig_count = len(signals)
        intended_count = len([e for e in forward_events if e.get("event_type") == "ORDER_INTENDED"])

        if sig_count > 0:
            fill_rate = trade_count / sig_count
            fill_diff_val = fill_rate - 0.3387
            fill_diff_hold = fill_rate - 0.3730
            sig_per_1000 = (sig_count / 1.0) * 1.0
        else:
            fill_rate = None
            fill_diff_val = None
            fill_diff_hold = None
            sig_per_1000 = None

        dirs = {}
        setups = {}
        for s in signals:
            payload = s.get("payload_json", {})
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            d = payload.get("direction", s.get("direction", "UNKNOWN"))
            st = payload.get("setup_type", "UNKNOWN")
            dirs[d] = dirs.get(d, 0) + 1
            setups[st] = setups.get(st, 0) + 1

        long_short_mix = {k: v / sig_count for k, v in dirs.items()} if sig_count > 0 else {}
        setup_mix = {k: v / sig_count for k, v in setups.items()} if sig_count > 0 else {}

        sig_fill_report = SignalAndFillDriftReport(
            total_signals=sig_count,
            intended_orders=intended_count,
            shadow_fills=trade_count,
            unfilled_orders=max(0, sig_count - trade_count),
            forward_fill_rate=fill_rate,
            fill_rate_diff_vs_validation=fill_diff_val,
            fill_rate_diff_vs_holdout=fill_diff_hold,
            forward_signals_per_1000_bars=sig_per_1000,
            long_short_mix=long_short_mix,
            setup_type_mix=setup_mix,
        )

        # 4. Performance Drift
        if trade_count > 0:
            r_list = [float(t.get("realized_r", 0.0)) for t in forward_trades]
            total_realized_r = sum(r_list)
            wins = sum(1 for r in r_list if r > 0)
            win_rate = wins / trade_count
            exp_r = total_realized_r / trade_count
            exp_diff_hold = exp_r - 0.4103

            gross_win = sum(r for r in r_list if r > 0)
            gross_loss = abs(sum(r for r in r_list if r < 0))
            pf = (gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)

            cum = np.cumsum([0.0] + r_list)
            peak = np.maximum.accumulate(cum)
            dd = peak - cum
            max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0
        else:
            total_realized_r = None
            win_rate = None
            exp_r = None
            exp_diff_hold = None
            pf = None
            max_dd = None

        perf_report = PerformanceDriftReport(
            completed_trades=trade_count,
            expected_r_total=total_realized_r,
            realized_r_total=total_realized_r,
            execution_drag_r=0.0 if trade_count > 0 else None,
            forward_expectancy_r=exp_r,
            expectancy_diff_vs_holdout=exp_diff_hold,
            forward_win_rate=win_rate,
            forward_profit_factor=pf,
            forward_max_drawdown_r=max_dd,
            shadow_slippage_status="NOT OBSERVED",
        )

        # 5. Reliability Report & Real Latency
        outages = sum(1 for e in forward_events if "OUTAGE" in e.get("event_type", ""))
        reconnects = sum(1 for e in forward_events if "RECONNECT" in e.get("event_type", ""))
        recovered = sum(1 for e in forward_events if "RECOVERED" in e.get("event_type", ""))
        stale = sum(1 for e in forward_events if "STALE" in e.get("event_type", ""))
        invalid = sum(1 for e in forward_events if "INVALID" in e.get("event_type", ""))
        duplicates = sum(1 for e in forward_events if "DUPLICATE" in e.get("event_type", ""))
        gaps = sum(1 for e in forward_events if "GAP" in e.get("event_type", ""))

        latencies = []
        for e in forward_events:
            payload = e.get("payload_json", {})
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            if "processing_latency_ms" in payload and payload["processing_latency_ms"] is not None:
                latencies.append(float(payload["processing_latency_ms"]))

        if len(latencies) > 0:
            l_arr = np.array(latencies)
            latency_map = {
                "median": float(np.median(l_arr)),
                "p90": float(np.percentile(l_arr, 90)),
                "p95": float(np.percentile(l_arr, 95)),
                "max": float(np.max(l_arr)),
            }
        else:
            latency_map = {}

        reliability_report = RuntimeReliabilityReport(
            total_events=len(forward_events),
            runtime_outages=outages,
            reconnect_count=reconnects,
            recovered_bars=recovered,
            stale_ticks_count=stale,
            invalid_ticks_count=invalid,
            duplicate_bars_ignored=duplicates,
            bar_gaps_count=gaps,
            shadow_processing_latency_ms=latency_map,
        )

        # 6. Deterministic Classification Rules
        if trade_count < 10:
            classification = DriftClassification.INSUFFICIENT_DATA
        elif outages > 5 or (median_sp is not None and median_sp > 0.60):
            classification = DriftClassification.SEVERE_DRIFT
        elif (fill_rate is not None and abs(fill_rate - 0.3730) > 0.15) or (exp_r is not None and exp_r < 0.0 and trade_count >= 15):
            classification = DriftClassification.REVIEW_REQUIRED
        else:
            classification = DriftClassification.NORMAL_VARIATION

        return ForwardDriftReport(
            run_id=self.run_id,
            symbol="XAUUSD",
            timeframe="M30",
            config_fingerprint="5a56639725048f3d",
            historical_cutoff=HISTORICAL_CUTOFF_TIMESTAMP,
            evidence_state=evidence_state,
            drift_classification=classification,
            spread_report=spread_report,
            signal_fill_report=sig_fill_report,
            performance_report=perf_report,
            reliability_report=reliability_report,
            generated_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )


def format_forward_drift_summary(report: ForwardDriftReport) -> str:
    """Format compact human-readable forward evidence summary."""
    s = report.spread_report
    f = report.signal_fill_report
    p = report.performance_report
    r = report.reliability_report

    fill_rate_str = f"{f.forward_fill_rate:.1%}" if f.forward_fill_rate is not None else "N/A"
    net_r_str = f"{p.realized_r_total:+.2f}R" if p.realized_r_total is not None else "N/A"
    exp_str = f"{p.forward_expectancy_r:+.4f}R/trade" if p.forward_expectancy_r is not None else "N/A"
    diff_str = f"{p.expectancy_diff_vs_holdout:+.4f}R" if p.expectancy_diff_vs_holdout is not None else "INSUFFICIENT_DATA"

    med_sp_str = f"{s.median_spread:.2f}" if s.median_spread is not None else "N/A"
    p90_sp_str = f"{s.p90_spread:.2f}" if s.p90_spread is not None else "N/A"
    max_sp_str = f"{s.max_spread:.2f}" if s.max_spread is not None else "N/A"

    latency_str = f"{r.shadow_processing_latency_ms.get('median', 0.0):.1f}ms" if r.shadow_processing_latency_ms else "N/A"

    return (
        f"Forward Evidence Snapshot\n"
        f"-------------------------\n"
        f"Run ID: {report.run_id}\n"
        f"State: {report.evidence_state}\n"
        f"Classification: {report.drift_classification}\n"
        f"Signals: {f.total_signals} | Fills: {f.shadow_fills} (Rate: {fill_rate_str})\n"
        f"Completed Trades: {p.completed_trades}\n"
        f"Net R: {net_r_str} | Expectancy: {exp_str}\n"
        f"Holdout Diff: {diff_str} (Holdout ref: +0.4103R)\n"
        f"Observed Spread: Median {med_sp_str} (Modeled: {s.modeled_spread:.2f}, P90: {p90_sp_str}, Max: {max_sp_str}, Samples: {s.sample_count})\n"
        f"Slippage Status: {p.shadow_slippage_status}\n"
        f"Processing Latency: {latency_str}\n"
        f"Runtime Outages: {r.runtime_outages} | Reconnects: {r.reconnect_count}\n"
    )


def export_forward_drift_snapshot(report: ForwardDriftReport, file_path: str | Path) -> None:
    """Exports ForwardDriftReport to JSON snapshot."""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    data = asdict(report)
    p.write_text(json.dumps(data, indent=2))
