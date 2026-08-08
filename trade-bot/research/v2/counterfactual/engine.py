"""
NOAFVGBOT V2.7 — Counterfactual Research Engine.

Provides deterministic evaluation of entry-refinement scenarios (M30 control vs M5/M3 refined entries),
hindsight-safe candidate selection, pairwise delta calculations, and refinement geometry metrics.

INVARIANTS:
- Candidate selection is defined BEFORE outcome path evaluation (never selects candidate by outcome!).
- Zero retroactive entry touches before scenario reference timestamp.
- Same market path observations used for all scenarios of a ParentThesis.
- Zero mutation of ParentThesis or TradePassport domain objects.
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
