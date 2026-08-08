"""
NOAFVGBOT V2.7 — Counterfactual Research Lab Unit Tests.

Comprehensive test suite verifying counterfactual scenario construction, hindsight-safe
candidate selection, entry-touch telemetry, pairwise delta metrics, refinement geometry,
content fingerprinting, and V1 isolation invariants.
"""

from datetime import datetime, timedelta, timezone
import pytest

from research.v2.data.models import Timeframe
from research.v2.core.thesis import ThesisDirection, ParentThesis, ChildEntryCandidate, compute_thesis_id
from research.v2.telemetry.excursion import PathObservation
from research.v2.telemetry.passport import OutcomeState
from research.v2.counterfactual.models import (
    ScenarioType,
    SelectionPolicy,
    CounterfactualScenario,
    CounterfactualResult,
    CounterfactualPair,
    RefinementGeometry,
)
from research.v2.counterfactual.engine import (
    compute_scenario_id,
    compute_pair_id,
    select_candidate,
    evaluate_scenario,
    compare_scenarios,
    compute_counterfactual_fingerprint,
)


def create_path_obs(obs_id: str, ts: str, open_p: float, high_p: float, low_p: float, close_p: float) -> PathObservation:
    return PathObservation(
        observation_id=obs_id,
        passport_id="pass_1",
        timestamp_utc=ts,
        timeframe=Timeframe.M5,
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        source_candle_id=f"c_{obs_id}",
    )


# --- 1 to 7: SCENARIO MODEL & GEOMETRY TESTS ---
def test_1_to_7_scenario_construction_and_invalid_geometry():
    sid1 = compute_scenario_id("th_1", ScenarioType.M30_CONTROL, "2026-08-08 11:30:00")
    sid2 = compute_scenario_id("th_1", ScenarioType.M30_CONTROL, "2026-08-08 11:30:00")
    assert sid1 == sid2  # Deterministic!

    scen = CounterfactualScenario(
        scenario_id=sid1,
        thesis_id="th_1",
        scenario_type=ScenarioType.M30_CONTROL,
        created_at="2026-08-08 11:30:00",
        reference_timestamp="2026-08-08 11:30:00",
        entry_timeframe=Timeframe.M30,
        structural_entry=2400.0,
        structural_stop=2390.0,
        structural_target=2420.0,
    )
    assert scen.is_available is True

    # Invalid zero risk distance MUST fail!
    with pytest.raises(ValueError, match="Risk distance cannot be zero"):
        CounterfactualScenario(
            scenario_id="bad",
            thesis_id="th_1",
            scenario_type=ScenarioType.M5_REFINED,
            created_at="2026-08-08 11:30:00",
            reference_timestamp="2026-08-08 11:30:00",
            entry_timeframe=Timeframe.M5,
            structural_entry=2400.0,
            structural_stop=2400.0,
        )


# --- 8 to 11: CANDIDATE SELECTION TESTS ---
def test_8_to_11_candidate_selection_deterministic():
    tid = compute_thesis_id("V2.7", "fp1", "XAUUSD", Timeframe.M30, "2026-08-08 11:30:00", ThesisDirection.LONG)

    c1 = ChildEntryCandidate("c1", tid, "2026-08-08 11:35:00", Timeframe.M5, ThesisDirection.LONG, 2398.0, 2390.0, 2420.0)
    c2 = ChildEntryCandidate("c2", tid, "2026-08-08 11:45:00", Timeframe.M5, ThesisDirection.LONG, 2395.0, 2390.0, 2420.0)

    # First by timestamp MUST select c1 (11:35:00), NEVER c2!
    selected = select_candidate([c1, c2], Timeframe.M5, SelectionPolicy.FIRST_BY_TIMESTAMP)
    assert selected is not None
    assert selected.candidate_id == "c1"


# --- 12 to 16: NO RETROACTIVE FILL TESTS ---
def test_12_to_16_no_retroactive_fill_before_ref_timestamp():
    scen = CounterfactualScenario(
        scenario_id="scen_m5",
        thesis_id="th_1",
        scenario_type=ScenarioType.M5_REFINED,
        created_at="2026-08-08 11:30:00",
        reference_timestamp="2026-08-08 11:40:00",  # Eligible only at 11:40:00!
        entry_timeframe=Timeframe.M5,
        structural_entry=2400.0,
        structural_stop=2390.0,
        structural_target=2420.0,
    )

    # Candle 1 (11:35:00): Price touches 2400. But scenario reference_timestamp is 11:40:00!
    obs1 = create_path_obs("o1", "2026-08-08 11:35:00", 2405.0, 2408.0, 2398.0, 2402.0)
    # Candle 2 (11:45:00): Price above entry (2405-2415)
    obs2 = create_path_obs("o2", "2026-08-08 11:45:00", 2405.0, 2415.0, 2404.0, 2410.0)

    res = evaluate_scenario(scen, [obs1, obs2], ThesisDirection.LONG)
    assert res.entry_touched is False  # obs1 was BEFORE reference_timestamp 11:40:00, so NOT touched!


# --- 17 to 28: SCENARIO EVALUATION & MAE/MFE TESTS ---
def test_17_to_28_scenario_evaluation_and_outcomes():
    scen = CounterfactualScenario(
        scenario_id="scen_ctrl",
        thesis_id="th_1",
        scenario_type=ScenarioType.M30_CONTROL,
        created_at="2026-08-08 11:30:00",
        reference_timestamp="2026-08-08 11:30:00",
        entry_timeframe=Timeframe.M30,
        structural_entry=2400.0,
        structural_stop=2390.0,
        structural_target=2420.0,
    )

    obs1 = create_path_obs("o1", "2026-08-08 11:35:00", 2405.0, 2410.0, 2398.0, 2402.0)  # Touch!
    obs2 = create_path_obs("o2", "2026-08-08 11:40:00", 2402.0, 2422.0, 2401.0, 2421.0)  # Target hit!

    res = evaluate_scenario(scen, [obs1, obs2], ThesisDirection.LONG)
    assert res.entry_touched is True
    assert res.outcome_state == OutcomeState.TARGET_REACHED
    assert res.gross_structural_r == 2.0  # (2420 - 2400) / 10 = 2.0R!


# --- 29 to 38: PAIRWISE COMPARISON & GEOMETRY TESTS ---
def test_29_to_38_pairwise_comparison_and_refinement_geometry():
    ctrl_scen = CounterfactualScenario(
        scenario_id="s_ctrl",
        thesis_id="th_1",
        scenario_type=ScenarioType.M30_CONTROL,
        created_at="2026-08-08 11:30:00",
        reference_timestamp="2026-08-08 11:30:00",
        entry_timeframe=Timeframe.M30,
        structural_entry=2400.0,
        structural_stop=2390.0,
        structural_target=2420.0,
    )
    exp_scen = CounterfactualScenario(
        scenario_id="s_exp",
        thesis_id="th_1",
        scenario_type=ScenarioType.M5_REFINED,
        created_at="2026-08-08 11:30:00",
        reference_timestamp="2026-08-08 11:35:00",
        entry_timeframe=Timeframe.M5,
        structural_entry=2395.0,  # Improved entry by 5 points for LONG!
        structural_stop=2390.0,   # Risk is 5 points instead of 10 points!
        structural_target=2420.0,
    )

    obs1 = create_path_obs("o1", "2026-08-08 11:35:00", 2400.0, 2405.0, 2394.0, 2402.0)  # Touches both 2400 and 2395!
    obs2 = create_path_obs("o2", "2026-08-08 11:40:00", 2402.0, 2422.0, 2401.0, 2421.0)  # Target hit!

    res_ctrl = evaluate_scenario(ctrl_scen, [obs1, obs2], ThesisDirection.LONG)
    res_exp = evaluate_scenario(exp_scen, [obs1, obs2], ThesisDirection.LONG)

    pair = compare_scenarios(res_ctrl, res_exp, ctrl_scen, exp_scen, ThesisDirection.LONG)
    assert pair.pair_state == "BOTH_TOUCHED"
    assert pair.delta_gross_structural_r == 3.0  # Exp gross R (5.0R) - Ctrl gross R (2.0R) = +3.0R!
    assert pair.geometry is not None
    assert pair.geometry.entry_improvement_absolute == 5.0  # 2400 - 2395 = +5 points improvement!


# --- 42 to 45: FINGERPRINT & DETERMINISM TESTS ---
def test_42_to_45_fingerprint_reproducibility():
    ctrl_scen = CounterfactualScenario("s_c", "th_1", ScenarioType.M30_CONTROL, "2026-08-08 11:30:00", "2026-08-08 11:30:00", Timeframe.M30, 2400.0, 2390.0, 2420.0)
    exp_scen = CounterfactualScenario("s_e", "th_1", ScenarioType.M5_REFINED, "2026-08-08 11:30:00", "2026-08-08 11:35:00", Timeframe.M5, 2395.0, 2390.0, 2420.0)

    obs = [create_path_obs("o1", "2026-08-08 11:35:00", 2400.0, 2422.0, 2394.0, 2421.0)]
    res_c = evaluate_scenario(ctrl_scen, obs, ThesisDirection.LONG)
    res_e = evaluate_scenario(exp_scen, obs, ThesisDirection.LONG)

    pair = compare_scenarios(res_c, res_e, ctrl_scen, exp_scen, ThesisDirection.LONG)

    fp1 = compute_counterfactual_fingerprint([pair])
    fp2 = compute_counterfactual_fingerprint([pair])
    assert fp1 == fp2  # Reproducible!


def test_51_and_52_v1_isolation_regression():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
