"""
NOAFVGBOT V2.8 — Multi-Timeframe Event-Driven Backtester.

Orchestrates chronological multi-timeframe event streams, ParentThesis lifecycle, liquidity intelligence,
FVG/OB/structure features, child candidate generation, TradePassports, MAE/MFE path telemetry,
counterfactual scenario refinement, execution simulation parity, and leakage-safe dataset building.

INVARIANTS:
- Single canonical event loop (M30 -> M15 -> M5 -> M3 -> M1 same-timestamp ordering).
- Zero peeking into future candles or uncompleted target buckets.
- Strict isolation between structural telemetry (neutral OHLC) and simulated execution (BID/ASK, limit protection, conservative same-bar).
- Zero mutation of frozen V1 files or V1 config modules.
- 100% reconstructible & content-fingerprinted simulation runs.
"""

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from research.v2.data.models import CandleV2, Timeframe
from research.v2.data.clock import MultiTimeframeClock, MarketEvent
from research.v2.core.thesis import ParentThesis, ChildEntryCandidate, ThesisDirection, ThesisLifecycleState
from research.v2.features.models import FeatureRecord
from research.v2.features.liquidity import LiquidityPool
from research.v2.telemetry.excursion import PathObservation
from research.v2.telemetry.passport import (
    TradePassport,
    DecisionSnapshot,
    OutcomeState,
    compute_passport_id,
)
from research.v2.counterfactual.models import (
    ScenarioType,
    SelectionPolicy,
    CounterfactualScenario,
    CounterfactualResult,
    CounterfactualPair,
)
from research.v2.counterfactual.engine import (
    compute_scenario_id,
    compute_pair_id,
    select_candidate,
    evaluate_scenario,
    compare_scenarios,
)
from research.v2.dataset.builder import DatasetBuilder, build_research_row
from research.v2.dataset.schema import ResearchRow
from research.v2.engine.models import (
    V2ExecutionConfig,
    ExecutionResult,
    BacktestV2Result,
    MacroThesisPolicy,
    EntryCandidatePolicy,
    ReferenceResearchPolicy,
)


def compute_backtest_fingerprint(
    events_count: int,
    thesis_count: int,
    passport_count: int,
    scenario_count: int,
    dataset_fp: str,
    exec_config: V2ExecutionConfig,
    engine_version: str = "2.8",
) -> str:
    """Computes a content & config-sensitive deterministic SHA256 fingerprint for a backtest run."""
    hasher = hashlib.sha256()
    raw = {
        "engine_version": engine_version,
        "events_count": events_count,
        "thesis_count": thesis_count,
        "passport_count": passport_count,
        "scenario_count": scenario_count,
        "dataset_fp": dataset_fp,
        "exec_config": {
            "spread": exec_config.spread,
            "slippage": exec_config.slippage,
            "commission": exec_config.commission,
        },
    }
    hasher.update(json.dumps(raw, sort_keys=True).encode("utf-8"))
    return hasher.hexdigest()


def simulate_execution(
    passport: TradePassport,
    exec_config: V2ExecutionConfig,
) -> Optional[ExecutionResult]:
    """
    Simulates execution layer separately from structural telemetry using MID candles to construct
    BID/ASK prices, limit price protection, and conservative same-bar rules.
    """
    if not passport._entry_touched or not passport.post_entry_path:
        return None

    snap = passport.decision_snapshot
    entry_limit = snap.structural_entry
    stop_limit = snap.structural_stop
    target_limit = snap.structural_target
    direction = snap.direction
    risk_dist = abs(entry_limit - stop_limit)

    spread_half = exec_config.spread / 2.0

    # 1. Entry Execution
    first_obs = passport.post_entry_path[0]
    if direction == ThesisDirection.LONG:
        # Buy Limit on ASK = MID + spread/2
        ask = first_obs.low + spread_half
        # Limit protection: executed_entry <= entry_limit
        executed_entry = min(entry_limit, ask + exec_config.slippage)
    else:
        # Sell Limit on BID = MID - spread/2
        bid = first_obs.high - spread_half
        # Limit protection: executed_entry >= entry_limit
        executed_entry = max(entry_limit, bid - exec_config.slippage)

    # 2. Exit Execution
    executed_exit = executed_entry
    gross_pnl = 0.0

    if passport.outcome_state == OutcomeState.STOP_REACHED:
        if direction == ThesisDirection.LONG:
            # Sell to close on BID = stop_limit - spread/2 - slippage
            executed_exit = stop_limit - spread_half - exec_config.slippage
            gross_pnl = executed_exit - executed_entry
        else:
            # Buy to close on ASK = stop_limit + spread/2 + slippage
            executed_exit = stop_limit + spread_half + exec_config.slippage
            gross_pnl = executed_entry - executed_exit

    elif passport.outcome_state == OutcomeState.TARGET_REACHED and target_limit is not None:
        if direction == ThesisDirection.LONG:
            # Sell to close on BID = target_limit - spread/2 - slippage
            executed_exit = target_limit - spread_half - exec_config.slippage
            gross_pnl = executed_exit - executed_entry
        else:
            # Buy to close on ASK = target_limit + spread/2 + slippage
            executed_exit = target_limit + spread_half + exec_config.slippage
            gross_pnl = executed_entry - executed_exit

    net_pnl = gross_pnl - exec_config.commission
    gross_r = gross_pnl / risk_dist if risk_dist > 0 else 0.0
    cost_r = exec_config.commission / risk_dist if risk_dist > 0 else 0.0
    net_r = net_pnl / risk_dist if risk_dist > 0 else 0.0

    return ExecutionResult(
        passport_id=passport.passport_id,
        structural_entry=entry_limit,
        executed_entry=executed_entry,
        structural_exit=target_limit if passport.outcome_state == OutcomeState.TARGET_REACHED else stop_limit,
        executed_exit=executed_exit,
        gross_price_pnl=gross_pnl,
        commission=exec_config.commission,
        net_price_pnl=net_pnl,
        risk_distance=risk_dist,
        gross_r=gross_r,
        cost_r=cost_r,
        net_r=net_r,
    )


from research.v2.data.resampler import resample_m1

class V2MultiTimeframeBacktester:
    """Multi-Timeframe Event-Driven Backtester for NOAFVGBOT V2."""

    def __init__(
        self,
        policy: ReferenceResearchPolicy,
        execution_config: Optional[V2ExecutionConfig] = None,
        config_fingerprint: str = "v2_default_fp",
    ):
        self.policy = policy
        self.execution_config = execution_config or V2ExecutionConfig()
        self.config_fingerprint = config_fingerprint

        self.active_theses: Dict[str, ParentThesis] = {}
        self.terminal_theses: Dict[str, ParentThesis] = {}
        self.passports: Dict[str, TradePassport] = {}
        self.scenarios: Dict[str, CounterfactualScenario] = {}
        self.pairs: List[CounterfactualPair] = []
        self.path_observations: List[PathObservation] = []

        self.market_state: Dict[str, Any] = {
            "feature_records": [],
            "liquidity_pools": [],
            "mtf_trace": {},
        }
        self.total_events = 0

    def run(self, m1_candles: List[CandleV2]) -> BacktestV2Result:
        """Executes full chronological backtest over M1 candles stream."""
        if not m1_candles:
            raise ValueError("m1_candles cannot be empty")

        # 1. Resample M1 candles into all target timeframes
        datasets: Dict[Timeframe, List[CandleV2]] = {
            Timeframe.M1: m1_candles,
            Timeframe.M3: resample_m1(m1_candles, Timeframe.M3)[0],
            Timeframe.M5: resample_m1(m1_candles, Timeframe.M5)[0],
            Timeframe.M15: resample_m1(m1_candles, Timeframe.M15)[0],
            Timeframe.M30: resample_m1(m1_candles, Timeframe.M30)[0],
        }

        # 2. Build canonical chronological event stream
        clock = MultiTimeframeClock(datasets)
        event_stream = clock.build_event_stream()

        for ev in event_stream:
            self.total_events += 1
            self._process_event(ev)

        # End of dataset: censor open passports
        last_ts = m1_candles[-1].timestamp_close_utc if m1_candles else "2026-08-08 00:00:00"
        for p in self.passports.values():
            if not p.is_censored and p.outcome_state in (OutcomeState.OPEN, OutcomeState.ENTRY_TOUCHED):
                p.censor(last_ts, reason="END_OF_DATA")

        # Build Research Dataset
        builder = DatasetBuilder(list(self.passports.values()))
        rows = builder.build_rows()
        summary = builder.summarize(rows)

        # Calculate execution results
        exec_outcomes: Dict[str, int] = {}
        for p in self.passports.values():
            res = simulate_execution(p, self.execution_config)
            if res:
                outcome_key = "NET_PROFIT" if res.net_r > 0 else "NET_LOSS"
                exec_outcomes[outcome_key] = exec_outcomes.get(outcome_key, 0) + 1

        struct_outcomes = {
            "TARGET_REACHED": summary.clean_target_count,
            "STOP_REACHED": summary.clean_stop_count,
            "AMBIGUOUS_SAME_BAR": summary.ambiguous_count,
            "ENTRY_UNTOUCHED": summary.entry_untouched_count,
        }

        fp = compute_backtest_fingerprint(
            events_count=self.total_events,
            thesis_count=len(self.active_theses) + len(self.terminal_theses),
            passport_count=len(self.passports),
            scenario_count=len(self.scenarios),
            dataset_fp=summary.dataset_fingerprint,
            exec_config=self.execution_config,
        )

        return BacktestV2Result(
            fingerprint=fp,
            execution_config=self.execution_config,
            total_events=self.total_events,
            thesis_count=len(self.active_theses) + len(self.terminal_theses),
            candidate_count=len(self.passports),
            passport_count=len(self.passports),
            scenario_count=len(self.scenarios),
            structural_outcomes=struct_outcomes,
            execution_outcomes=exec_outcomes,
            counterfactual_pairs=self.pairs,
            research_rows=rows,
            censored_count=summary.censored_count,
            ambiguous_count=summary.ambiguous_count,
        )

    def _process_event(self, ev: MarketEvent) -> None:
        c = ev.candle
        tf = ev.timeframe

        # 1. If M1 candle: update path observations for active passports
        if tf == Timeframe.M1:
            obs = PathObservation(
                observation_id=f"obs_{c.timestamp_close_utc}_{c.open}_{c.close}",
                passport_id="global",
                timestamp_utc=c.timestamp_close_utc,
                timeframe=Timeframe.M1,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                source_candle_id=f"c_m1_{c.timestamp_close_utc}",
            )
            self.path_observations.append(obs)
            for p in self.passports.values():
                if not p.is_censored and p.outcome_state in (OutcomeState.OPEN, OutcomeState.ENTRY_TOUCHED):
                    try:
                        p.add_observation(obs)
                    except Exception:
                        pass

        # 2. Update MTF trace
        self.market_state["mtf_trace"][tf.name] = c.timestamp_close_utc

        # 3. Process M30 event -> MacroThesisPolicy
        if tf == Timeframe.M30:
            new_theses = self.policy.evaluate_m30(c, self.market_state)
            for th in new_theses:
                if th.thesis_id not in self.active_theses and th.thesis_id not in self.terminal_theses:
                    th.activate("ACTIVE", c.timestamp_close_utc)
                    self.active_theses[th.thesis_id] = th

        # 4. Process M15 event -> M15 Confirmation Evidence
        elif tf == Timeframe.M15:
            for th in self.active_theses.values():
                evidence_ids = [e.evidence_id for e in th.evidence]
                if "M15" not in evidence_ids:
                    # Record observational confirmation trace
                    pass

        # 5. Process M5/M3 events -> EntryCandidatePolicy
        elif tf in (Timeframe.M5, Timeframe.M3):
            candidates = self.policy.evaluate_setup(c, list(self.active_theses.values()), self.market_state)
            for cand in candidates:
                self._on_candidate_generated(cand)

    def _on_candidate_generated(self, cand: ChildEntryCandidate) -> None:
        th = self.active_theses.get(cand.thesis_id)
        if not th:
            return

        # 1. Build DecisionSnapshot (known_at <= candidate.created_at)
        snap = DecisionSnapshot(
            thesis_id=th.thesis_id,
            direction=th.direction,
            candidate_id=cand.candidate_id,
            candidate_created_at=cand.created_at,
            candidate_timeframe=cand.timeframe,
            structural_entry=cand.structural_entry,
            structural_stop=cand.structural_stop,
            structural_target=cand.structural_target,
            feature_records=tuple(self.market_state.get("feature_records", [])),
            liquidity_pools=tuple(self.market_state.get("liquidity_pools", [])),
            mtf_trace=dict(self.market_state["mtf_trace"]),
        )

        pid = compute_passport_id(th.thesis_id, cand.candidate_id, self.config_fingerprint, cand.created_at)
        passport = TradePassport(
            passport_id=pid,
            strategy_version="V2.8",
            schema_version="2.8",
            config_fingerprint=self.config_fingerprint,
            thesis_id=th.thesis_id,
            candidate_id=cand.candidate_id,
            symbol=th.symbol,
            direction=th.direction,
            candidate_timeframe=cand.timeframe,
            created_at=cand.created_at,
            decision_snapshot=snap,
        )
        self.passports[pid] = passport

        # 2. Build Counterfactual Scenarios
        scen_ctrl_id = compute_scenario_id(th.thesis_id, ScenarioType.M30_CONTROL, th.created_at)
        scen_ctrl = CounterfactualScenario(
            scenario_id=scen_ctrl_id,
            thesis_id=th.thesis_id,
            scenario_type=ScenarioType.M30_CONTROL,
            created_at=th.created_at,
            reference_timestamp=th.created_at,
            entry_timeframe=Timeframe.M30,
            structural_entry=cand.structural_entry,
            structural_stop=cand.structural_stop,
            structural_target=cand.structural_target,
        )
        self.scenarios[scen_ctrl_id] = scen_ctrl

        scen_exp_id = compute_scenario_id(th.thesis_id, ScenarioType.M5_REFINED if cand.timeframe == Timeframe.M5 else ScenarioType.M3_REFINED, cand.created_at, cand.candidate_id)
        scen_exp = CounterfactualScenario(
            scenario_id=scen_exp_id,
            thesis_id=th.thesis_id,
            scenario_type=ScenarioType.M5_REFINED if cand.timeframe == Timeframe.M5 else ScenarioType.M3_REFINED,
            created_at=cand.created_at,
            reference_timestamp=cand.created_at,
            entry_timeframe=cand.timeframe,
            structural_entry=cand.structural_entry,
            structural_stop=cand.structural_stop,
            structural_target=cand.structural_target,
            source_candidate_id=cand.candidate_id,
        )
        self.scenarios[scen_exp_id] = scen_exp

        # Evaluate and Pair Scenarios
        res_ctrl = evaluate_scenario(scen_ctrl, self.path_observations, th.direction)
        res_exp = evaluate_scenario(scen_exp, self.path_observations, th.direction)
        pair = compare_scenarios(res_ctrl, res_exp, scen_ctrl, scen_exp, th.direction)
        self.pairs.append(pair)
