"""
NOAFVGBOT V2.10A — Multi-Timeframe Event-Driven Backtester.

Orchestrates chronological multi-timeframe event streams, ParentThesis lifecycle, liquidity intelligence,
FVG/OB/structure features, child candidate generation, TradePassports, MAE/MFE path telemetry,
counterfactual scenario refinement, execution simulation parity, and leakage-safe dataset building.

INVARIANTS:
- Single canonical event loop (M30 -> M15 -> M5 -> M3 -> M1 same-timestamp ordering).
- Zero peeking into future candles or uncompleted target buckets.
- Strict isolation between structural telemetry (neutral OHLC) and simulated execution (BID/ASK, limit protection, conservative same-bar).
- Zero mutation of frozen V1 files or V1 config modules.
- 100% reconstructible & content-fingerprinted simulation runs.

V2.10A — Bounded lifecycle (engineering fix, not a strategy change):
- ParentThesis now actually reaches a terminal state instead of living forever:
  * INVALIDATED: a new opposite-direction M30 thesis supersedes existing active theses in
    the opposite direction, at the new thesis's own timestamp, before any lower-timeframe
    event at that same timestamp is processed.
  * EXPIRED: a thesis that reaches REFERENCE_ENGINEERING_LIFETIME_M30_BARS completed M30
    bars of age without invalidating or completing is force-expired. This bound exists
    purely to keep engine state finite; it is explicitly NOT a strategy parameter and was
    not chosen by comparing outcomes.
  * COMPLETED is intentionally left unused by the engine in this phase (see class docstring
    below) — invalidation + expiry alone are sufficient to bound state.
- Terminal theses are removed from active_theses immediately, so they can no longer receive
  candidate registrations (a terminal thesis simply isn't looked up any more).
- Counterfactual scenario evaluation is incremental (see counterfactual/engine.py additions):
  each M1 close updates only the currently-open scenarios in O(1) each, instead of rescanning
  the entire historical path on every new candidate.
"""

import bisect
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from research.v2.data.models import CandleV2, Timeframe
from research.v2.data.clock import MultiTimeframeClock, MarketEvent
from research.v2.core.thesis import ParentThesis, ChildEntryCandidate, ThesisDirection, ThesisLifecycleState
from research.v2.features.models import FeatureRecord
from research.v2.features.liquidity import (
    LiquidityPool,
    detect_swings,
    detect_equal_highs_lows,
    analyze_sweeps_and_touches,
    extract_liquidity_event_features,
    LiquidityEventType,
)
from research.v2.features.fvg_quality import detect_fvgs, extract_fvg_features
from research.v2.features.ob_quality import detect_order_blocks, extract_ob_features
from research.v2.features.structure import detect_structure_events, extract_structure_features
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
    ScenarioTrackingState,
    init_scenario_tracking,
    update_scenario_tracking,
    finalize_scenario_tracking,
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


# ENGINEERING_SAFETY_BOUND — exists purely to keep active-thesis state finite and testable.
# NOT a strategy parameter: chosen as a round, structurally meaningful unit (half a trading
# day's worth of M30 bars = 24) and was never compared against outcome/PnL to select this
# value — only against engine state size / runtime, which Section 16 of the V2.10A mission
# does not prohibit (only PnL-based tuning is prohibited). Override via
# V2MultiTimeframeBacktester(thesis_max_active_m30_bars=...) for engineering experiments;
# do not tune this to affect research results.
REFERENCE_ENGINEERING_LIFETIME_M30_BARS = 24

# V2.10C -- MTF timeframes wired for FVG/OB/liquidity/structure feature telemetry, matching
# section 14's explicit MTF list. M1 is intentionally excluded: no feature family in this
# phase's inventory (section 5) was requested at M1 granularity, and running 3/5/15/30-minute
# swing/FVG/OB detection additionally over the full M1 stream would add cost with no requested
# consumer.
MTF_FEATURE_TIMEFRAMES = (Timeframe.M30, Timeframe.M15, Timeframe.M5, Timeframe.M3)

# ENGINEERING_SAFETY_BOUND — analogous in kind to REFERENCE_ENGINEERING_LIFETIME_M30_BARS
# above: a per-feature-type rolling-window cap on how much accumulated feature/liquidity
# history a DecisionSnapshot carries. Without a bound, market_state["feature_records"] grows
# for the entire run and every new DecisionSnapshot copies + the dataset builder later
# re-scans the ENTIRE accumulated history-so-far -- profiling a 3,000-M1-row smoke run showed
# this alone accounts for ~77% of runtime and tens of millions of redundant iterations
# (classic O(candidates x accumulated_feature_count) blowup). Dropping OLD, already-causally-
# valid entries from the window is a pure memory/compute bound: it never adds anything, never
# removes a feature/pool that was known at the time it was in the window, and never affects
# WHICH already-released objects are eligible -- only how much past history is still being
# carried forward. Never compared against outcome/PnL/profitability to pick this size, exactly
# like the thesis-lifetime bound above (see also section 18 of the V2.10C mission: "Do not
# duplicate enormous feature payloads unnecessarily").
FEATURE_WINDOW_MAXLEN_PER_TYPE = 20
LIQUIDITY_POOL_WINDOW_MAXLEN = 50


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
    """
    Multi-Timeframe Event-Driven Backtester for NOAFVGBOT V2.

    Completion semantics (V2.10A): ParentThesis.complete() is intentionally never called by
    this engine. The domain model exposes winning_child_id/COMPLETED specifically for "first
    clean child outcome terminates the parent," but that rule requires deciding tie-breaking
    across siblings, whether a STOP counts as clean, and what happens to sibling
    candidates/passports on parent completion — none of which is specified by the existing
    architecture. Inventing that here would be a strategy/domain decision, not an engineering
    bound. Invalidation (opposite-direction supersession) + expiry (bounded M30-bar age) are
    sufficient on their own to guarantee every thesis reaches a terminal state and active_theses
    stays finite, which is this phase's actual goal.
    """

    def __init__(
        self,
        policy: ReferenceResearchPolicy,
        execution_config: Optional[V2ExecutionConfig] = None,
        config_fingerprint: str = "v2_default_fp",
        thesis_max_active_m30_bars: int = REFERENCE_ENGINEERING_LIFETIME_M30_BARS,
    ):
        self.policy = policy
        self.execution_config = execution_config or V2ExecutionConfig()
        self.config_fingerprint = config_fingerprint
        self.thesis_max_active_m30_bars = thesis_max_active_m30_bars

        self.active_theses: Dict[str, ParentThesis] = {}
        self.terminal_theses: Dict[str, ParentThesis] = {}
        self.passports: Dict[str, TradePassport] = {}
        self.active_passports: Dict[str, TradePassport] = {}
        self.seen_candidate_keys: set = set()
        self.scenarios: Dict[str, CounterfactualScenario] = {}
        self.pairs: List[CounterfactualPair] = []
        self.path_observations: List[PathObservation] = []
        self._path_observation_timestamps: List[str] = []  # parallel, sorted; enables bisect catch-up

        self.market_state: Dict[str, Any] = {
            "feature_records": [],
            "liquidity_pools": [],
            "mtf_trace": {},
        }
        self.total_events = 0

        # V2.10C causal feature-release index: known_at_timestamp -> [(kind, obj), ...].
        # Populated once per run() call by _precompute_feature_release_index(); consumed
        # (popped) incrementally in _process_event() as the event stream reaches each
        # timestamp, so market_state never contains a feature/pool before it was knowable.
        self._feature_release_index: Dict[str, List[Tuple[str, Any]]] = {}
        self.feature_release_stats: Dict[str, int] = {"feature_records": 0, "liquidity_pools": 0}

        # Bounded rolling windows backing market_state["feature_records"]/["liquidity_pools"]
        # (see FEATURE_WINDOW_MAXLEN_PER_TYPE docs above). Keyed per feature_type so a
        # high-frequency family (e.g. M3 structure events) cannot starve a low-frequency one
        # (e.g. M30 FVGs) out of the window.
        self._feature_windows: Dict[str, deque] = {}
        self._liquidity_pool_window: deque = deque(maxlen=LIQUIDITY_POOL_WINDOW_MAXLEN)

        # V2.10C coverage telemetry (ENGINEERING_SMOKE_ONLY -- observation counts, never
        # profitability). Keyed by feature_type (for feature_records) / liquidity_type (for
        # liquidity_pools); tracks total-ever-released count, first/last known_at_timestamp,
        # and the set of source timeframes observed -- independent of the bounded windows
        # above, which only retain recent state for DecisionSnapshot construction.
        self.feature_type_telemetry: Dict[str, Dict[str, Any]] = {}

        # V2.10A lifecycle bookkeeping
        self.m30_bar_index = 0
        self.thesis_created_m30_index: Dict[str, int] = {}
        self.created_theses = 0
        self.invalidated_theses = 0
        self.expired_theses = 0
        self.completed_theses = 0
        self.peak_active_theses = 0

        # V2.10A passport bookkeeping
        self.peak_active_passports = 0
        self.path_updates_total = 0

        # V2.10A incremental counterfactual scenario tracking
        self.scenario_states: Dict[str, ScenarioTrackingState] = {}
        self.open_scenario_ids: Set[str] = set()
        self.pending_pairs: List[Tuple[CounterfactualScenario, CounterfactualScenario, ThesisDirection]] = []

    def _precompute_feature_release_index(self, datasets: Dict[Timeframe, List[CandleV2]]) -> Dict[str, List[Tuple[str, Any]]]:
        """
        V2.10C -- Causal feature wiring (FVG / Order Block / liquidity / structure).

        For each MTF timeframe, runs the EXISTING feature engines once over that timeframe's
        full candle list (a precomputation), then indexes every resulting object under the
        exact known_at_timestamp at which it becomes causally knowable -- never under when it
        was computed. Each of these known_at_timestamp values is itself always the
        timestamp_close_utc of some candle in that same timeframe's series (that is how
        detect_fvgs/detect_order_blocks/detect_swings/detect_structure_events define
        known_at), and MultiTimeframeClock guarantees an event fires at that exact timestamp
        before any later event is processed. _process_event() only ever releases an object
        into market_state when the event stream actually reaches its known_at_timestamp, so a
        full-history precomputation cannot leak anything early -- this is option (B) from the
        V2.10C causality requirements: "precomputation whose availability timestamps
        mathematically prevent access before the source bar closes."

        No FVG/OB/liquidity/structure rule is redesigned here -- this only calls the existing
        engines and adapts their outputs into the existing FeatureRecord / LiquidityPool
        contracts already accepted by DecisionSnapshot.
        """
        index: Dict[str, List[Tuple[str, Any]]] = {}

        def release(known_at: str, kind: str, obj: Any) -> None:
            index.setdefault(known_at, []).append((kind, obj))

        for tf in MTF_FEATURE_TIMEFRAMES:
            candles = datasets.get(tf, [])
            if len(candles) < 3:
                continue
            by_close_ts = {c.timestamp_close_utc: c for c in candles}

            # FVG (3-candle pattern; known_at = c3 close)
            for fvg in detect_fvgs(candles):
                c1 = by_close_ts.get(fvg.c1_ts)
                c2 = by_close_ts.get(fvg.c2_ts)
                c3 = by_close_ts.get(fvg.c3_ts)
                if not (c1 and c2 and c3):
                    continue
                rec = extract_fvg_features(fvg, c1, c2, c3, atr=None)
                release(fvg.known_at_timestamp, "feature_record", rec)

            # Order Block (2-candle pattern; known_at = impulse candle close)
            for ob in detect_order_blocks(candles):
                c_src = by_close_ts.get(ob.source_c_ts)
                c_imp = by_close_ts.get(ob.impulse_c_ts)
                if not (c_src and c_imp):
                    continue
                rec = extract_ob_features(ob, c_src, c_imp, atr=None)
                release(ob.known_at_timestamp, "feature_record", rec)

            # Liquidity: swing highs/lows (known_at delayed by right_bars confirmation) +
            # equal-highs/equal-lows clusters derived from them.
            swing_pools = detect_swings(candles)
            for p in swing_pools:
                release(p.known_at_timestamp, "liquidity_pool", p)
            eq_pools = detect_equal_highs_lows(swing_pools)
            for p in eq_pools:
                release(p.known_at_timestamp, "liquidity_pool", p)

            # Liquidity sweep events against swing + equal-high/low pools (known_at = the
            # evaluated candle's own close -- see analyze_sweeps_and_touches).
            all_pools = swing_pools + eq_pools
            pool_by_id = {p.pool_id: p for p in all_pools}
            for ev in analyze_sweeps_and_touches(all_pools, candles):
                if ev.event_type != LiquidityEventType.SWEEP:
                    continue  # scope: SWEEP only (explicit section 12 ask); TOUCH/BREACH skipped
                pool = pool_by_id.get(ev.pool_id)
                if pool is None:
                    continue
                rec = extract_liquidity_event_features(ev, pool)
                release(ev.timestamp_utc, "feature_record", rec)

            # Structure: confirmed swing events + structure breaks (causality-fixed detector).
            for se in detect_structure_events(candles):
                rec = extract_structure_features(se)
                release(se.known_at_timestamp, "feature_record", rec)

        return index

    def _record_feature_telemetry(self, type_key: str, source_timeframe_name: str, known_at_timestamp: str) -> None:
        """ENGINEERING_SMOKE_ONLY coverage bookkeeping -- counts and timestamps only, never
        profitability/outcome. See feature_type_telemetry docs in __init__."""
        t = self.feature_type_telemetry.setdefault(type_key, {
            "count": 0, "timeframes": set(), "first_known_at": known_at_timestamp, "last_known_at": known_at_timestamp,
        })
        t["count"] += 1
        t["timeframes"].add(source_timeframe_name)
        if known_at_timestamp < t["first_known_at"]:
            t["first_known_at"] = known_at_timestamp
        if known_at_timestamp > t["last_known_at"]:
            t["last_known_at"] = known_at_timestamp

    def _terminalize_thesis(self, th: ParentThesis) -> None:
        """Moves a now-terminal thesis out of active_theses so it can no longer receive candidates."""
        self.active_theses.pop(th.thesis_id, None)
        self.terminal_theses[th.thesis_id] = th
        self.thesis_created_m30_index.pop(th.thesis_id, None)

    def _register_scenario(self, scenario: CounterfactualScenario, direction: ThesisDirection) -> None:
        """
        Registers a scenario for incremental tracking. If reference_timestamp lies in the
        past relative to "now" (e.g. M30_CONTROL, whose reference is the thesis's own — possibly
        much earlier — creation time), it is first caught up against the already-observed
        suffix of path_observations located via bisect (O(log n) + O(bars since reference),
        the latter bounded by thesis lifetime, not total dataset size), then registered for
        ordinary forward incremental updates for any observation still to come.
        """
        state = init_scenario_tracking(scenario, direction)
        if not state.resolved:
            start_idx = bisect.bisect_left(self._path_observation_timestamps, scenario.reference_timestamp)
            for obs in self.path_observations[start_idx:]:
                state = update_scenario_tracking(state, obs)
                if state.resolved:
                    break
        self.scenario_states[scenario.scenario_id] = state
        if not state.resolved:
            self.open_scenario_ids.add(scenario.scenario_id)

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

        # 2b. Precompute the causal FVG/OB/liquidity/structure feature-release index (V2.10C).
        self._feature_release_index = self._precompute_feature_release_index(datasets)

        for ev in event_stream:
            self.total_events += 1
            self._process_event(ev)

        # End of dataset: censor open passports
        last_ts = m1_candles[-1].timestamp_close_utc if m1_candles else "2026-08-08 00:00:00"
        for p in self.passports.values():
            if not p.is_censored and p.outcome_state in (OutcomeState.OPEN, OutcomeState.ENTRY_TOUCHED):
                p.censor(last_ts, reason="END_OF_DATA")

        # Finalize counterfactual pairs from accumulated incremental scenario state.
        # Any scenario still unresolved at end-of-data is finalized as-is (mirrors passport
        # end-of-data censoring: no further observations exist to resolve it).
        for scen_ctrl, scen_exp, direction in self.pending_pairs:
            res_ctrl = finalize_scenario_tracking(self.scenario_states[scen_ctrl.scenario_id])
            res_exp = finalize_scenario_tracking(self.scenario_states[scen_exp.scenario_id])
            pair = compare_scenarios(res_ctrl, res_exp, scen_ctrl, scen_exp, direction)
            self.pairs.append(pair)

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

        # 0. Release any FVG/OB/liquidity/structure features that become knowable exactly at
        # this event's timestamp (V2.10C). Popped (not merely read) so each object is
        # released into market_state exactly once, the first time the event stream reaches
        # its known_at_timestamp -- regardless of which timeframe's event triggers that
        # timestamp when multiple timeframes close simultaneously.
        released = self._feature_release_index.pop(ev.timestamp_utc, None)
        if released:
            for kind, obj in released:
                if kind == "feature_record":
                    self._feature_windows.setdefault(obj.feature_type, deque(maxlen=FEATURE_WINDOW_MAXLEN_PER_TYPE)).append(obj)
                    self.feature_release_stats["feature_records"] += 1
                    self._record_feature_telemetry(obj.feature_type, obj.source_timeframe.name, obj.known_at_timestamp)
                elif kind == "liquidity_pool":
                    self._liquidity_pool_window.append(obj)
                    self.feature_release_stats["liquidity_pools"] += 1
                    self._record_feature_telemetry(obj.liquidity_type.value, obj.source_timeframe.name, obj.known_at_timestamp)
            # Rebuild the flat, policy/snapshot-visible views only when something actually
            # changed (not on every event) -- cheap because each is bounded, never O(total
            # history): at most len(feature_types) * FEATURE_WINDOW_MAXLEN_PER_TYPE and
            # LIQUIDITY_POOL_WINDOW_MAXLEN respectively.
            self.market_state["feature_records"] = [f for w in self._feature_windows.values() for f in w]
            self.market_state["liquidity_pools"] = list(self._liquidity_pool_window)

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
            self._path_observation_timestamps.append(obs.timestamp_utc)

            # Update active passports only
            to_remove = []
            for pid, p in self.active_passports.items():
                if not p.is_censored and p.outcome_state in (OutcomeState.OPEN, OutcomeState.ENTRY_TOUCHED):
                    try:
                        p.add_observation(obs)
                        self.path_updates_total += 1
                        if p.outcome_state not in (OutcomeState.OPEN, OutcomeState.ENTRY_TOUCHED) or p.is_censored:
                            to_remove.append(pid)
                    except Exception:
                        to_remove.append(pid)
                else:
                    to_remove.append(pid)

            for pid in to_remove:
                self.active_passports.pop(pid, None)

            # Feed the same observation to currently-open counterfactual scenarios, O(1) each,
            # instead of rescanning all historical path_observations per candidate (V2.10A).
            resolved_scenario_ids = []
            for sid in self.open_scenario_ids:
                new_state = update_scenario_tracking(self.scenario_states[sid], obs)
                self.scenario_states[sid] = new_state
                if new_state.resolved:
                    resolved_scenario_ids.append(sid)
            for sid in resolved_scenario_ids:
                self.open_scenario_ids.discard(sid)

        # 2. Update MTF trace
        self.market_state["mtf_trace"][tf.name] = c.timestamp_close_utc

        # 3. Process M30 event -> lifecycle bounding, then MacroThesisPolicy
        if tf == Timeframe.M30:
            self.m30_bar_index += 1

            # 3a. Age-based expiry, evaluated BEFORE lower-timeframe events at this timestamp
            # (an already-expired thesis must not be able to emit a same-timestamp candidate).
            for th_id in list(self.active_theses.keys()):
                th = self.active_theses[th_id]
                created_idx = self.thesis_created_m30_index.get(th_id, self.m30_bar_index)
                age = self.m30_bar_index - created_idx
                if age >= self.thesis_max_active_m30_bars and not th.is_terminal():
                    th.expire(c.timestamp_close_utc, reason="ENGINEERING_LIFETIME_EXPIRED")
                    self.expired_theses += 1
                    self._terminalize_thesis(th)

            # 3b. New thesis proposals: invalidate opposite-direction incumbents BEFORE
            # registering the new thesis, then register it (same-timestamp candidate
            # eligibility for a brand-new thesis is preserved — see class docs / V2.10A tests).
            new_theses = self.policy.evaluate_m30(c, self.market_state)
            for th in new_theses:
                if th.thesis_id in self.active_theses or th.thesis_id in self.terminal_theses:
                    continue

                opposite_dir = ThesisDirection.SHORT if th.direction == ThesisDirection.LONG else ThesisDirection.LONG
                for other_id in list(self.active_theses.keys()):
                    other = self.active_theses[other_id]
                    if other.direction == opposite_dir and not other.is_terminal():
                        other.invalidate(c.timestamp_close_utc, reason="OPPOSITE_DIRECTION_M30_THESIS")
                        self.invalidated_theses += 1
                        self._terminalize_thesis(other)

                th.activate(c.timestamp_close_utc, reason="M30_THESIS_ACTIVATED")
                self.active_theses[th.thesis_id] = th
                self.thesis_created_m30_index[th.thesis_id] = self.m30_bar_index
                self.created_theses += 1
                self.peak_active_theses = max(self.peak_active_theses, len(self.active_theses))

        # 4. Process M15 event -> M15 Confirmation Evidence
        elif tf == Timeframe.M15:
            for th in self.active_theses.values():
                evidence_ids = [e.evidence_id for e in th.evidence]
                if "M15" not in evidence_ids:
                    # Record observational confirmation trace
                    pass

        # 5. Process M5/M3 events -> EntryCandidatePolicy (Scoped strictly to matching timeframe event)
        elif tf in (Timeframe.M5, Timeframe.M3):
            candidates = self.policy.evaluate_setup(c, list(self.active_theses.values()), self.market_state)
            for cand in candidates:
                if cand.timeframe == tf:
                    self._on_candidate_generated(cand)

    def _on_candidate_generated(self, cand: ChildEntryCandidate) -> None:
        th = self.active_theses.get(cand.thesis_id)
        if not th:
            return

        # Candidate Deduplication by Semantic Key
        cand_key = (
            cand.thesis_id,
            cand.timeframe.name,
            cand.created_at,
            cand.direction.name,
            cand.structural_entry,
            cand.structural_stop,
            cand.structural_target,
        )
        if cand_key in self.seen_candidate_keys:
            return
        self.seen_candidate_keys.add(cand_key)

        pid = compute_passport_id(th.thesis_id, cand.candidate_id, self.config_fingerprint, cand.created_at)
        if pid in self.passports:
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
        self.active_passports[pid] = passport
        self.peak_active_passports = max(self.peak_active_passports, len(self.active_passports))

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

        # Register both scenarios for incremental tracking; the resulting CounterfactualPair
        # is finalized once at end-of-run() from accumulated state (see run()), not rescanned
        # from scratch here. This also means M5/M3_REFINED scenarios now correctly see their
        # own forward path as it happens, instead of the pre-V2.10A behavior of being evaluated
        # against an empty observation window (path_observations never yet contained any bar
        # at or after cand.created_at at the moment this function ran) — see V2.10A report.
        self._register_scenario(scen_ctrl, th.direction)
        self._register_scenario(scen_exp, th.direction)
        self.pending_pairs.append((scen_ctrl, scen_exp, th.direction))
