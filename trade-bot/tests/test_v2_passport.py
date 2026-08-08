"""
NOAFVGBOT V2.5 — Trade Passport & MAE/MFE Telemetry Unit Tests.

Comprehensive test suite verifying TradePassport identity, decision snapshot safety,
pre/post-entry path separation, MAE/MFE calculation, same-bar ambiguity, censoring,
full replay reconstructibility, decision_view isolation, and V1 isolation.
"""

from datetime import datetime, timedelta, timezone
import pytest

from research.v2.data.models import Timeframe
from research.v2.core.thesis import ThesisDirection
from research.v2.features.models import FeatureRecord, FeaturePhase
from research.v2.features.liquidity import LiquidityPool, LiquiditySide, LiquidityType
from research.v2.telemetry.excursion import PathObservation, ExcursionMetrics, calculate_excursion_as_of
from research.v2.telemetry.passport import (
    TradePassport,
    DecisionSnapshot,
    OutcomeState,
    PassportEvent,
    PassportEventType,
    compute_passport_id,
    DuplicateObservationError,
    CensoredPassportError,
    rebuild_passport_from_events,
)


def create_snapshot(cand_created_at: str = "2026-08-08 11:30:00") -> DecisionSnapshot:
    rec = FeatureRecord(
        feature_id="f1",
        feature_type="FVG",
        source_object_id="fvg1",
        source_timeframe=Timeframe.M5,
        timestamp_utc="2026-08-08 11:00:00",
        known_at_timestamp="2026-08-08 11:30:00",
        phase=FeaturePhase.DECISION_TIME,
        values={"gap_size": 5.0},
    )
    lp = LiquidityPool("lp1", LiquidityType.SWING_HIGH, LiquiditySide.BUY_SIDE, 2050.0, Timeframe.M30, "2026-08-08 10:30:00", "2026-08-08 11:30:00")

    return DecisionSnapshot(
        thesis_id="th_123",
        direction=ThesisDirection.LONG,
        candidate_id="cand_1",
        candidate_created_at=cand_created_at,
        candidate_timeframe=Timeframe.M5,
        structural_entry=2400.0,
        structural_stop=2390.0,
        structural_target=2420.0,
        feature_records=(rec,),
        liquidity_pools=(lp,),
        mtf_trace={"M30": "parent", "M5": "candidate"},
    )


def create_sample_passport(cand_created_at: str = "2026-08-08 11:30:00") -> TradePassport:
    snap = create_snapshot(cand_created_at)
    pid = compute_passport_id("th_123", "cand_1", "fp123", cand_created_at)
    return TradePassport(
        passport_id=pid,
        strategy_version="V2.5",
        schema_version="2.5",
        config_fingerprint="fp123",
        thesis_id="th_123",
        candidate_id="cand_1",
        symbol="XAUUSD",
        direction=ThesisDirection.LONG,
        candidate_timeframe=Timeframe.M5,
        created_at=cand_created_at,
        decision_snapshot=snap,
    )


def test_1_to_3_passport_identity_and_serialization():
    pid1 = compute_passport_id("th_123", "cand_1", "fp123", "2026-08-08 11:30:00")
    pid2 = compute_passport_id("th_123", "cand_1", "fp123", "2026-08-08 11:30:00")
    assert pid1 == pid2

    # Different candidate produces different ID
    pid3 = compute_passport_id("th_123", "cand_2", "fp123", "2026-08-08 11:30:00")
    assert pid1 != pid3

    p = create_sample_passport()
    data = p.to_dict()
    deserialized = TradePassport.from_dict(data)
    assert deserialized.passport_id == p.passport_id
    assert deserialized.decision_snapshot.structural_entry == 2400.0


def test_4_to_10_decision_safety_and_view_isolation():
    # 5. POST_EVENT feature rejected in DecisionSnapshot
    bad_rec = FeatureRecord(
        feature_id="f_bad",
        feature_type="FVG",
        source_object_id="fvg1",
        source_timeframe=Timeframe.M5,
        timestamp_utc="2026-08-08 11:00:00",
        known_at_timestamp="2026-08-08 11:30:00",
        phase=FeaturePhase.POST_EVENT,
        values={"mitigated": True},
    )
    with pytest.raises(ValueError, match="rejects POST_EVENT feature"):
        DecisionSnapshot("th_1", ThesisDirection.LONG, "c1", "2026-08-08 11:30:00", Timeframe.M5, 2400.0, 2390.0, feature_records=(bad_rec,))

    # 6. Future-known feature rejected
    future_rec = FeatureRecord(
        feature_id="f_fut",
        feature_type="FVG",
        source_object_id="fvg1",
        source_timeframe=Timeframe.M5,
        timestamp_utc="2026-08-08 11:00:00",
        known_at_timestamp="2026-08-08 12:00:00",  # known AFTER candidate 11:30:00
        phase=FeaturePhase.DECISION_TIME,
        values={"gap_size": 5.0},
    )
    with pytest.raises(ValueError, match="rejects future feature"):
        DecisionSnapshot("th_1", ThesisDirection.LONG, "c1", "2026-08-08 11:30:00", Timeframe.M5, 2400.0, 2390.0, feature_records=(future_rec,))

    # 10. decision_view isolation
    p = create_sample_passport()
    dv1 = p.decision_view()
    assert "outcome_state" not in dv1
    assert "mae" not in dv1


def test_14_to_17_entry_touch_and_path_separation():
    p = create_sample_passport("2026-08-08 11:30:00")  # entry 2400, stop 2390, target 2420

    # Observation 1: Price above entry (2410-2415) -> Pre-entry path!
    obs1 = PathObservation("obs1", p.passport_id, "2026-08-08 11:35:00", Timeframe.M5, 2410.0, 2415.0, 2408.0, 2412.0, "c1")
    p.add_observation(obs1)
    assert p.outcome_state == OutcomeState.OPEN
    assert len(p.pre_entry_path) == 1
    assert len(p.post_entry_path) == 0

    # Observation 2: Price reaches entry (2398-2405, covers 2400) -> Entry Touched!
    obs2 = PathObservation("obs2", p.passport_id, "2026-08-08 11:40:00", Timeframe.M5, 2412.0, 2415.0, 2398.0, 2402.0, "c2")
    p.add_observation(obs2)
    assert p.outcome_state == OutcomeState.ENTRY_TOUCHED
    assert len(p.pre_entry_path) == 1
    assert len(p.post_entry_path) == 1


def test_18_to_27_mae_mfe_and_r_normalization():
    # Long entry 2400, stop 2390 (risk 10)
    p = create_sample_passport("2026-08-08 11:30:00")
    obs_touch = PathObservation("obs1", p.passport_id, "2026-08-08 11:35:00", Timeframe.M5, 2402.0, 2410.0, 2395.0, 2408.0, "c1")
    p.add_observation(obs_touch)  # Touch at 2400! Low was 2395 (adverse 5), High was 2410 (favorable 10)

    ex = p.get_excursion()
    assert ex.mae_absolute == 5.0
    assert ex.mae_r == 0.5  # 5 / 10
    assert ex.mfe_absolute == 10.0
    assert ex.mfe_r == 1.0  # 10 / 10


def test_28_to_33_outcomes_and_same_bar_ambiguity():
    # Stop reached test
    p_stop = create_sample_passport("2026-08-08 11:30:00")
    obs_touch = PathObservation("obs1", p_stop.passport_id, "2026-08-08 11:35:00", Timeframe.M5, 2402.0, 2405.0, 2398.0, 2401.0, "c1")
    obs_stop = PathObservation("obs2", p_stop.passport_id, "2026-08-08 11:40:00", Timeframe.M5, 2401.0, 2402.0, 2388.0, 2389.0, "c2")  # Low 2388 <= stop 2390
    p_stop.add_observation(obs_touch)
    p_stop.add_observation(obs_stop)
    assert p_stop.outcome_state == OutcomeState.STOP_REACHED

    # Ambiguous same-bar test (entry 2400, stop 2390, target 2420 hit in single candle 2385 to 2425)
    p_amb = create_sample_passport("2026-08-08 11:30:00")
    obs_wild = PathObservation("obs_wild", p_amb.passport_id, "2026-08-08 11:35:00", Timeframe.M5, 2400.0, 2425.0, 2385.0, 2410.0, "c1")
    p_amb.add_observation(obs_wild)
    assert p_amb.outcome_state == OutcomeState.AMBIGUOUS_SAME_BAR


def test_38_to_40_censoring():
    p = create_sample_passport("2026-08-08 11:30:00")
    p.censor("2026-08-08 12:00:00", reason="DATASET_END")
    assert p.is_censored is True

    # Appending observation after censor fails
    obs = PathObservation("obs_late", p.passport_id, "2026-08-08 12:05:00", Timeframe.M5, 2400.0, 2405.0, 2395.0, 2401.0, "c1")
    with pytest.raises(CensoredPassportError):
        p.add_observation(obs)


def test_41_to_48_replay_reconstructibility():
    p = create_sample_passport("2026-08-08 11:30:00")
    obs1 = PathObservation("obs1", p.passport_id, "2026-08-08 11:35:00", Timeframe.M5, 2402.0, 2410.0, 2395.0, 2408.0, "c1")
    p.add_observation(obs1)

    all_obs = list(p.pre_entry_path) + list(p.post_entry_path)
    rebuilt = rebuild_passport_from_events(p.to_dict(), p.decision_snapshot, all_obs, list(p.events))

    assert rebuilt.passport_id == p.passport_id
    assert rebuilt.outcome_state == p.outcome_state
    assert rebuilt.get_excursion().mae_absolute == p.get_excursion().mae_absolute


def test_54_and_55_v1_isolation_regression():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
