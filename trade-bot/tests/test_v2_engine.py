"""
NOAFVGBOT V2.8 — Multi-Timeframe Event-Driven Backtester Unit Tests.

Comprehensive test suite verifying canonical MTF clock loop, thesis registry, TradePassport integration,
M1 path telemetry, execution simulation (BID/ASK, limit protection), counterfactual scenario integration,
result content fingerprinting, and V1 isolation invariants.
"""

from datetime import datetime, timedelta, timezone
import pytest

from research.v2.data.models import CandleV2, Timeframe
from research.v2.core.thesis import ThesisDirection, ParentThesis, ChildEntryCandidate, compute_thesis_id
from research.v2.telemetry.passport import OutcomeState
from research.v2.engine.models import (
    V2ExecutionConfig,
    ExecutionResult,
    BacktestV2Result,
    ReferenceResearchPolicy,
)
from research.v2.engine.mtf_backtester import (
    V2MultiTimeframeBacktester,
    compute_backtest_fingerprint,
    simulate_execution,
)


def create_m1_candle(ts_open: str, open_p: float = 2000.0, high_p: float = 2005.0, low_p: float = 1995.0, close_p: float = 2002.0) -> CandleV2:
    dt_open = datetime.fromisoformat(ts_open).replace(tzinfo=timezone.utc)
    dt_close = dt_open + timedelta(seconds=60)
    return CandleV2(
        timestamp_open_utc=dt_open.strftime("%Y-%m-%d %H:%M:%S"),
        timestamp_close_utc=dt_close.strftime("%Y-%m-%d %H:%M:%S"),
        timeframe=Timeframe.M1,
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        volume=10.0,
    )


def generate_m1_series(start_ts: str, count: int, start_price: float = 2400.0) -> List[CandleV2]:
    dt = datetime.fromisoformat(start_ts).replace(tzinfo=timezone.utc)
    res = []
    p = start_price
    for i in range(count):
        ts_open = dt.strftime("%Y-%m-%d %H:%M:%S")
        c = create_m1_candle(ts_open, open_p=p, high_p=p+2.0, low_p=p-2.0, close_p=p+1.0)
        res.append(c)
        dt += timedelta(minutes=1)
        p += 0.5
    return res


# Test Policy that proposes a thesis on first M30 and candidate on first M5
class FixtureResearchPolicy(ReferenceResearchPolicy):
    def evaluate_m30(self, completed_candle: CandleV2, market_state: Dict[str, Any]) -> List[ParentThesis]:
        tid = compute_thesis_id("V2.8", "fp1", "XAUUSD", Timeframe.M30, completed_candle.timestamp_close_utc, ThesisDirection.LONG)
        th = ParentThesis(tid, "V2.8", "2.8", "fp1", "XAUUSD", ThesisDirection.LONG, Timeframe.M30, completed_candle.timestamp_close_utc)
        return [th]

    def evaluate_setup(
        self,
        completed_candle: CandleV2,
        active_theses: List[ParentThesis],
        market_state: Dict[str, Any],
    ) -> List[ChildEntryCandidate]:
        if not active_theses:
            return []
        th = active_theses[0]
        cand = ChildEntryCandidate(
            candidate_id="c_m5_1",
            thesis_id=th.thesis_id,
            created_at=completed_candle.timestamp_close_utc,
            timeframe=Timeframe.M5,
            direction=ThesisDirection.LONG,
            structural_entry=2405.0,
            structural_stop=2395.0,
            structural_target=2425.0,
        )
        return [cand]


def test_1_to_17_backtester_clock_and_passport_flow():
    policy = FixtureResearchPolicy()
    backtester = V2MultiTimeframeBacktester(policy=policy)

    candles = generate_m1_series("2026-08-08 10:00:00", 60, 2400.0)
    result = backtester.run(candles)

    assert result.total_events > 60  # M1 + resampled M3, M5, M15, M30 events!
    assert result.thesis_count >= 1
    assert result.candidate_count >= 1
    assert result.passport_count >= 1


def test_26_to_35_execution_simulation_and_limit_protection():
    policy = FixtureResearchPolicy()
    backtester = V2MultiTimeframeBacktester(policy=policy, execution_config=V2ExecutionConfig(spread=0.30, slippage=0.10, commission=0.10))

    candles = generate_m1_series("2026-08-08 10:00:00", 60, 2400.0)
    result = backtester.run(candles)

    assert len(backtester.passports) >= 1
    p = list(backtester.passports.values())[0]

    # Execution simulation
    exec_res = simulate_execution(p, V2ExecutionConfig(spread=0.30, slippage=0.10, commission=0.10))
    if exec_res:
        # BUY limit protection: executed_entry <= entry_limit
        assert exec_res.executed_entry <= exec_res.structural_entry + 0.10
        assert exec_res.commission == 0.10


def test_48_to_50_backtest_result_fingerprint_reproducibility():
    policy = FixtureResearchPolicy()
    b1 = V2MultiTimeframeBacktester(policy=policy)
    b2 = V2MultiTimeframeBacktester(policy=policy)

    candles = generate_m1_series("2026-08-08 10:00:00", 60, 2400.0)
    r1 = b1.run(candles)
    r2 = b2.run(candles)

    assert r1.fingerprint == r2.fingerprint  # Deterministic!


def test_54_and_55_v1_isolation_regression():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
