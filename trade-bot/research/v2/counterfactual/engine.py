"""
NOAFVGBOT V2.7 — Counterfactual Research Engine.

Provides deterministic evaluation of entry-refinement scenarios (M30 control vs M5/M3 refined entries),
hindsight-safe candidate selection, pairwise delta calculations, and refinement geometry metrics.

INVARIANTS:
- Candidate selection is defined BEFORE outcome path evaluation (never selects candidate by outcome!).
- Zero retroactive entry touches before scenario reference timestamp.
- Same market path observations used for all scenarios of a ParentThesis.
- Zero mutation of ParentThesis or TradePassport domain objects.

V2.10A ADDITION — Incremental scenario tracking:
evaluate_scenario() below is a batch function that rescans a full observation list from
reference_timestamp forward; O(path_length) per call. init_scenario_tracking /
update_scenario_tracking / finalize_scenario_tracking implement the exact same per-bar
outcome/MAE/MFE semantics incrementally (O(1) amortized per new observation), so a caller
holding many concurrently-open scenarios can feed each new M1 close once instead of
rescanning history on every candidate. evaluate_scenario() is kept unchanged for direct
unit testing and as the semantic reference the incremental path is verified against.
"""

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from research.v2.data.models import Timeframe
from research.v2.core.thesis import ThesisDirection, ParentThesis, ChildEntryCandidate
from research.v2.telemetry.excursion import PathObservation, calculate_excursion_as_of
from research.v2.telemetry.passport import OutcomeState
from research.v2.counterfactual.models import (
    ScenarioType,
    SelectionPolicy,
    RefinementGeometry,
    CounterfactualScenario,
    CounterfactualResult,
    CounterfactualPair,
)


def compute_scenario_id(
    thesis_id: str,
    scenario_type: ScenarioType,
    ref_ts: str,
    source_cand_id: Optional[str] = None,
) -> str:
    raw = f"{thesis_id}|{scenario_type.value}|{ref_ts}|{source_cand_id or 'none'}"
    return "scen_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def compute_pair_id(control_scen_id: str, exp_scen_id: str) -> str:
    raw = f"{control_scen_id}|{exp_scen_id}"
    return "pair_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def select_candidate(
    candidates: List[ChildEntryCandidate],
    target_tf: Timeframe,
    policy: SelectionPolicy = SelectionPolicy.FIRST_BY_TIMESTAMP,
) -> Optional[ChildEntryCandidate]:
    """
    Selects a ChildEntryCandidate matching target timeframe deterministically BEFORE outcome evaluation.
    NEVER selects a candidate based on post-event outcome or fill result!
    """
    eligible = [c for c in candidates if c.timeframe == target_tf]
    if not eligible:
        return None

    if policy in (SelectionPolicy.FIRST_BY_TIMESTAMP, SelectionPolicy.FIRST_AVAILABLE):
        # Sort chronologically by created_at then candidate_id
        sorted_cand = sorted(eligible, key=lambda c: (c.created_at, c.candidate_id))
        return sorted_cand[0]

    return eligible[0]


def evaluate_scenario(
    scenario: CounterfactualScenario,
    observations: List[PathObservation],
    direction: ThesisDirection,
) -> CounterfactualResult:
    """Evaluates a counterfactual scenario against market path observations strictly >= reference_timestamp."""
    if not scenario.is_available:
        return CounterfactualResult(
            scenario_id=scenario.scenario_id,
            entry_touched=False,
            entry_touch_timestamp=None,
            outcome_state=OutcomeState.ENTRY_NOT_TOUCHED,
            gross_structural_r=None,
            mae_r=0.0,
            mfe_r=0.0,
            mae_absolute=0.0,
            mfe_absolute=0.0,
            is_censored=False,
            is_ambiguous=False,
        )

    t_ref = datetime.fromisoformat(scenario.reference_timestamp).replace(tzinfo=timezone.utc)

    # Filter observations >= reference_timestamp (No retroactive fills!)
    valid_obs = [
        o for o in observations
        if datetime.fromisoformat(o.timestamp_utc).replace(tzinfo=timezone.utc) >= t_ref
    ]

    entry = scenario.structural_entry
    stop = scenario.structural_stop
    target = scenario.structural_target
    risk_dist = abs(entry - stop)

    pre_entry_obs: List[PathObservation] = []
    post_entry_obs: List[PathObservation] = []
    entry_touched = False
    entry_touch_ts: Optional[str] = None
    outcome = OutcomeState.OPEN

    for obs in valid_obs:
        if not entry_touched:
            touched = (obs.low <= entry <= obs.high)
            if touched:
                entry_touched = True
                entry_touch_ts = obs.timestamp_utc
                outcome = OutcomeState.ENTRY_TOUCHED
                post_entry_obs.append(obs)

                # Check same-bar stop & target collision
                stop_hit = (obs.low <= stop) if direction == ThesisDirection.LONG else (obs.high >= stop)
                target_hit = (target is not None) and ((obs.high >= target) if direction == ThesisDirection.LONG else (obs.low <= target))

                if stop_hit and target_hit:
                    outcome = OutcomeState.AMBIGUOUS_SAME_BAR
                elif stop_hit:
                    outcome = OutcomeState.STOP_REACHED
                elif target_hit:
                    outcome = OutcomeState.TARGET_REACHED
            else:
                pre_entry_obs.append(obs)
        else:
            post_entry_obs.append(obs)
            if outcome in (OutcomeState.ENTRY_TOUCHED, OutcomeState.OPEN):
                stop_hit = (obs.low <= stop) if direction == ThesisDirection.LONG else (obs.high >= stop)
                target_hit = (target is not None) and ((obs.high >= target) if direction == ThesisDirection.LONG else (obs.low <= target))

                if stop_hit and target_hit:
                    outcome = OutcomeState.AMBIGUOUS_SAME_BAR
                elif stop_hit:
                    outcome = OutcomeState.STOP_REACHED
                elif target_hit:
                    outcome = OutcomeState.TARGET_REACHED

    # Calculate Gross Structural R
    gross_r: Optional[float] = None
    if entry_touched:
        if outcome == OutcomeState.TARGET_REACHED and target is not None:
            target_dist = abs(target - entry)
            gross_r = target_dist / risk_dist if risk_dist > 0 else None
        elif outcome == OutcomeState.STOP_REACHED:
            gross_r = -1.0
        elif outcome == OutcomeState.AMBIGUOUS_SAME_BAR:
            gross_r = None  # Never force an R value on ambiguous outcomes!

    # Calculate MAE & MFE on post-entry path
    ex = calculate_excursion_as_of(
        reference_price=entry,
        direction=direction,
        risk_distance=risk_dist,
        observations=post_entry_obs,
        as_of_utc=valid_obs[-1].timestamp_utc if valid_obs else scenario.reference_timestamp,
    )

    bars_to_touch = len(pre_entry_obs) if entry_touched else None

    return CounterfactualResult(
        scenario_id=scenario.scenario_id,
        entry_touched=entry_touched,
        entry_touch_timestamp=entry_touch_ts,
        outcome_state=outcome,
        gross_structural_r=gross_r,
        mae_r=ex.mae_r,
        mfe_r=ex.mfe_r,
        mae_absolute=ex.mae_absolute,
        mfe_absolute=ex.mfe_absolute,
        bars_to_entry_touch=bars_to_touch,
        is_censored=False,
        is_ambiguous=(outcome == OutcomeState.AMBIGUOUS_SAME_BAR),
    )


def compare_scenarios(
    ctrl_res: CounterfactualResult,
    exp_res: CounterfactualResult,
    ctrl_scen: CounterfactualScenario,
    exp_scen: CounterfactualScenario,
    direction: ThesisDirection,
) -> CounterfactualPair:
    """Pairs control and experimental scenarios and calculates pairwise deltas and geometry metrics."""
    pid = compute_pair_id(ctrl_scen.scenario_id, exp_scen.scenario_id)

    # Determine Pair State
    if ctrl_res.is_ambiguous or exp_res.is_ambiguous:
        pair_state = "AMBIGUOUS"
    elif ctrl_res.entry_touched and exp_res.entry_touched:
        pair_state = "BOTH_TOUCHED"
    elif ctrl_res.entry_touched and not exp_res.entry_touched:
        pair_state = "CONTROL_ONLY_TOUCHED"
    elif not ctrl_res.entry_touched and exp_res.entry_touched:
        pair_state = "REFINED_ONLY_TOUCHED"
    else:
        pair_state = "NEITHER_TOUCHED"

    # Delta Gross R
    delta_r: Optional[float] = None
    if ctrl_res.gross_structural_r is not None and exp_res.gross_structural_r is not None:
        delta_r = exp_res.gross_structural_r - ctrl_res.gross_structural_r

    delta_mae = exp_res.mae_r - ctrl_res.mae_r
    delta_mfe = exp_res.mfe_r - ctrl_res.mfe_r

    delta_touch = (1 if exp_res.entry_touched else 0) - (1 if ctrl_res.entry_touched else 0)

    ctrl_risk = abs(ctrl_scen.structural_entry - ctrl_scen.structural_stop)
    exp_risk = abs(exp_scen.structural_entry - exp_scen.structural_stop)
    delta_risk = exp_risk - ctrl_risk

    # Entry delay calculation
    t_ctrl = datetime.fromisoformat(ctrl_scen.reference_timestamp).replace(tzinfo=timezone.utc)
    t_exp = datetime.fromisoformat(exp_scen.reference_timestamp).replace(tzinfo=timezone.utc)
    delay_min = max(0.0, (t_exp - t_ctrl).total_seconds() / 60.0)

    # Geometry Metrics
    geometry: Optional[RefinementGeometry] = None
    if ctrl_scen.is_available and exp_scen.is_available:
        if direction == ThesisDirection.LONG:
            # Entry improvement = control entry - experimental entry (positive means lower/better entry for long!)
            improvement_abs = ctrl_scen.structural_entry - exp_scen.structural_entry
        else:
            # For short, entry improvement = experimental entry - control entry (higher entry is better for short!)
            improvement_abs = exp_scen.structural_entry - ctrl_scen.structural_entry

        improvement_pct_risk = (improvement_abs / ctrl_risk) if ctrl_risk > 0 else 0.0
        risk_change_pct = (delta_risk / ctrl_risk) if ctrl_risk > 0 else 0.0

        ctrl_target_dist = abs(ctrl_scen.structural_target - ctrl_scen.structural_entry) if ctrl_scen.structural_target else 0.0
        exp_target_dist = abs(exp_scen.structural_target - exp_scen.structural_entry) if exp_scen.structural_target else 0.0

        geometry = RefinementGeometry(
            entry_improvement_absolute=improvement_abs,
            entry_improvement_pct_of_m30_risk=improvement_pct_risk,
            risk_distance_change_absolute=delta_risk,
            risk_distance_change_pct=risk_change_pct,
            target_distance_change=exp_target_dist - ctrl_target_dist,
            entry_delay_minutes=delay_min,
        )

    return CounterfactualPair(
        pair_id=pid,
        thesis_id=ctrl_scen.thesis_id,
        control_scenario_id=ctrl_scen.scenario_id,
        experimental_scenario_id=exp_scen.scenario_id,
        pair_state=pair_state,
        delta_gross_structural_r=delta_r,
        delta_mae_r=delta_mae,
        delta_mfe_r=delta_mfe,
        delta_entry_touch=delta_touch,
        delta_risk_distance=delta_risk,
        delta_time_to_entry_min=delay_min,
        geometry=geometry,
    )


class ScenarioTrackingState:
    """
    Mutable incremental tracking state for one CounterfactualScenario.

    Carries exactly the running state evaluate_scenario() would otherwise recompute from
    scratch on every call: whether/when entry was touched, current outcome, running MAE/MFE,
    and whether the scenario has reached a terminal state (resolved=True) and no longer
    needs further observations.

    Deliberately a plain mutated-in-place class (not a frozen dataclass): with many thousands
    of concurrently open scenarios each receiving one update per M1 close, dataclasses.replace()
    dominated runtime (~3.6M calls, ~70% of wall time in early profiling) purely from its
    reflection/reconstruction overhead. In-place attribute mutation removes that entirely
    without changing any outcome semantics — update_scenario_tracking()'s return value is
    still the authoritative state to store, exactly as when it returned a new instance.
    """
    __slots__ = (
        "scenario_id", "reference_timestamp", "structural_entry", "structural_stop",
        "structural_target", "direction", "risk_distance", "entry_touched",
        "entry_touch_timestamp", "outcome_state", "mae_absolute", "mae_timestamp",
        "mfe_absolute", "mfe_timestamp", "bars_before_touch", "resolved",
    )

    def __init__(
        self,
        scenario_id: str,
        reference_timestamp: str,
        structural_entry: float,
        structural_stop: float,
        structural_target: Optional[float],
        direction: ThesisDirection,
        risk_distance: float,
        entry_touched: bool = False,
        entry_touch_timestamp: Optional[str] = None,
        outcome_state: OutcomeState = OutcomeState.OPEN,
        mae_absolute: float = 0.0,
        mae_timestamp: Optional[str] = None,
        mfe_absolute: float = 0.0,
        mfe_timestamp: Optional[str] = None,
        bars_before_touch: int = 0,
        resolved: bool = False,
    ):
        self.scenario_id = scenario_id
        self.reference_timestamp = reference_timestamp
        self.structural_entry = structural_entry
        self.structural_stop = structural_stop
        self.structural_target = structural_target
        self.direction = direction
        self.risk_distance = risk_distance
        self.entry_touched = entry_touched
        self.entry_touch_timestamp = entry_touch_timestamp
        self.outcome_state = outcome_state
        self.mae_absolute = mae_absolute
        self.mae_timestamp = mae_timestamp
        self.mfe_absolute = mfe_absolute
        self.mfe_timestamp = mfe_timestamp
        self.bars_before_touch = bars_before_touch
        self.resolved = resolved


_TERMINAL_OUTCOME_STATES = (
    OutcomeState.STOP_REACHED,
    OutcomeState.TARGET_REACHED,
    OutcomeState.AMBIGUOUS_SAME_BAR,
)


def init_scenario_tracking(scenario: CounterfactualScenario, direction: ThesisDirection) -> ScenarioTrackingState:
    """Initializes incremental tracking state for a scenario. Mirrors evaluate_scenario()'s setup."""
    if not scenario.is_available:
        return ScenarioTrackingState(
            scenario_id=scenario.scenario_id,
            reference_timestamp=scenario.reference_timestamp,
            structural_entry=scenario.structural_entry,
            structural_stop=scenario.structural_stop,
            structural_target=scenario.structural_target,
            direction=direction,
            risk_distance=0.0,
            outcome_state=OutcomeState.ENTRY_NOT_TOUCHED,
            resolved=True,
        )

    risk_dist = abs(scenario.structural_entry - scenario.structural_stop)
    return ScenarioTrackingState(
        scenario_id=scenario.scenario_id,
        reference_timestamp=scenario.reference_timestamp,
        structural_entry=scenario.structural_entry,
        structural_stop=scenario.structural_stop,
        structural_target=scenario.structural_target,
        direction=direction,
        risk_distance=risk_dist,
    )


def _apply_excursion_step(state: ScenarioTrackingState, obs: PathObservation) -> None:
    """Single-observation MAE/MFE running-max update, mutating state in place. Mirrors calculate_excursion_as_of()'s per-bar body."""
    entry = state.structural_entry
    if state.direction == ThesisDirection.LONG:
        adverse = obs.low
        adverse = entry - adverse if adverse < entry else 0.0
        favorable = obs.high
        favorable = favorable - entry if favorable > entry else 0.0
    else:
        adverse = obs.high
        adverse = adverse - entry if adverse > entry else 0.0
        favorable = obs.low
        favorable = entry - favorable if favorable < entry else 0.0

    if adverse > state.mae_absolute:
        state.mae_absolute = adverse
        state.mae_timestamp = obs.timestamp_utc

    if favorable > state.mfe_absolute:
        state.mfe_absolute = favorable
        state.mfe_timestamp = obs.timestamp_utc


def _outcome_step(state: ScenarioTrackingState, obs: PathObservation) -> OutcomeState:
    """Single-observation stop/target/ambiguous check. Mirrors evaluate_scenario()'s per-bar body."""
    stop = state.structural_stop
    target = state.structural_target
    direction = state.direction

    stop_hit = (obs.low <= stop) if direction == ThesisDirection.LONG else (obs.high >= stop)
    target_hit = (target is not None) and (
        (obs.high >= target) if direction == ThesisDirection.LONG else (obs.low <= target)
    )

    if stop_hit and target_hit:
        return OutcomeState.AMBIGUOUS_SAME_BAR
    elif stop_hit:
        return OutcomeState.STOP_REACHED
    elif target_hit:
        return OutcomeState.TARGET_REACHED
    return state.outcome_state


def update_scenario_tracking(state: ScenarioTrackingState, obs: PathObservation) -> ScenarioTrackingState:
    """
    Applies one new PathObservation to scenario tracking state in O(1), mutating and
    returning the same state object (the caller re-stores the return value regardless,
    so this is transparent to callers).

    Semantic parity with evaluate_scenario(): observations strictly before reference_timestamp
    are ignored (no retroactive fills); once resolved, no further updates are applied (mirrors
    evaluate_scenario() never un-terminalizing an outcome).
    """
    if state.resolved:
        return state

    if obs.timestamp_utc < state.reference_timestamp:
        return state

    if not state.entry_touched:
        touched = (obs.low <= state.structural_entry <= obs.high)
        if not touched:
            state.bars_before_touch += 1
            return state

        state.entry_touched = True
        state.entry_touch_timestamp = obs.timestamp_utc
        state.outcome_state = OutcomeState.ENTRY_TOUCHED
        state.outcome_state = _outcome_step(state, obs)
        _apply_excursion_step(state, obs)
        state.resolved = state.outcome_state in _TERMINAL_OUTCOME_STATES
        return state

    # Already touched: keep updating post-entry excursion + outcome while still open.
    _apply_excursion_step(state, obs)
    if state.outcome_state in (OutcomeState.ENTRY_TOUCHED, OutcomeState.OPEN):
        state.outcome_state = _outcome_step(state, obs)

    state.resolved = state.outcome_state in _TERMINAL_OUTCOME_STATES
    return state


def finalize_scenario_tracking(state: ScenarioTrackingState) -> CounterfactualResult:
    """Converts accumulated incremental tracking state into the standard CounterfactualResult shape."""
    gross_r: Optional[float] = None
    if state.entry_touched:
        if state.outcome_state == OutcomeState.TARGET_REACHED and state.structural_target is not None:
            target_dist = abs(state.structural_target - state.structural_entry)
            gross_r = target_dist / state.risk_distance if state.risk_distance > 0 else None
        elif state.outcome_state == OutcomeState.STOP_REACHED:
            gross_r = -1.0
        elif state.outcome_state == OutcomeState.AMBIGUOUS_SAME_BAR:
            gross_r = None

    mae_r = (state.mae_absolute / state.risk_distance) if state.risk_distance > 0 else 0.0
    mfe_r = (state.mfe_absolute / state.risk_distance) if state.risk_distance > 0 else 0.0

    return CounterfactualResult(
        scenario_id=state.scenario_id,
        entry_touched=state.entry_touched,
        entry_touch_timestamp=state.entry_touch_timestamp,
        outcome_state=state.outcome_state,
        gross_structural_r=gross_r,
        mae_r=mae_r,
        mfe_r=mfe_r,
        mae_absolute=state.mae_absolute,
        mfe_absolute=state.mfe_absolute,
        bars_to_entry_touch=(state.bars_before_touch if state.entry_touched else None),
        is_censored=False,
        is_ambiguous=(state.outcome_state == OutcomeState.AMBIGUOUS_SAME_BAR),
    )


def compute_counterfactual_fingerprint(pairs: List[CounterfactualPair], version: str = "2.7") -> str:
    """Computes a deterministic content & schema-sensitive SHA256 fingerprint for counterfactual pair results."""
    hasher = hashlib.sha256()
    hasher.update(version.encode("utf-8"))

    sorted_pairs = sorted(pairs, key=lambda p: (p.thesis_id, p.pair_id))
    for p in sorted_pairs:
        raw_dict = {
            "pair_id": p.pair_id,
            "thesis_id": p.thesis_id,
            "control_id": p.control_scenario_id,
            "exp_id": p.experimental_scenario_id,
            "pair_state": p.pair_state,
            "delta_gross_r": p.delta_gross_structural_r,
            "delta_mae": p.delta_mae_r,
            "delta_mfe": p.delta_mfe_r,
        }
        hasher.update(json.dumps(raw_dict, sort_keys=True).encode("utf-8"))

    return hasher.hexdigest()
