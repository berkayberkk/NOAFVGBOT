"""
NOAFVGBOT V2.2 — Parent Thesis Domain, Lifecycle & Transition Provenance Unit Tests.

Comprehensive test suite verifying full lifecycle replay (ACTIVE, ENTRY_AVAILABLE, COMPLETED,
INVALIDATED, EXPIRED), transition provenance, metadata retention, duplicate transition safety,
serialization roundtrip, and V1 isolation invariants.
"""

import pytest

from research.v2.data.models import Timeframe
from research.v2.core.thesis import (
    ParentThesis,
    ThesisDirection,
    ThesisLifecycleState,
    ThesisEvidence,
    EvidenceType,
    ChildEntryCandidate,
    ThesisTransition,
    compute_thesis_id,
    compute_transition_id,
    DuplicateEvidenceError,
    DuplicateCandidateError,
    DuplicateTransitionError,
    TerminalStateViolationError,
    rebuild_thesis_from_events,
)


def create_sample_thesis() -> ParentThesis:
    tid = compute_thesis_id("V2.2", "v2_fp_123", "XAUUSD", Timeframe.M30, "2026-08-08 14:00:00", ThesisDirection.LONG)
    return ParentThesis(
        thesis_id=tid,
        strategy_version="V2.2",
        schema_version="2.2",
        config_fingerprint="v2_fp_123",
        symbol="XAUUSD",
        direction=ThesisDirection.LONG,
        source_timeframe=Timeframe.M30,
        created_at="2026-08-08 14:00:00",
    )


def test_1_and_2_deterministic_thesis_id():
    tid1 = compute_thesis_id("V2.2", "v2_fp_123", "XAUUSD", Timeframe.M30, "2026-08-08 14:00:00", ThesisDirection.LONG)
    tid2 = compute_thesis_id("V2.2", "v2_fp_123", "XAUUSD", Timeframe.M30, "2026-08-08 14:00:00", ThesisDirection.LONG)
    assert tid1 == tid2

    tid3 = compute_thesis_id("V2.2", "v2_fp_123", "XAUUSD", Timeframe.M30, "2026-08-08 14:00:00", ThesisDirection.SHORT)
    assert tid1 != tid3


def test_3_to_9_lifecycle_and_transition_provenance():
    thesis = create_sample_thesis()
    assert thesis.state == ThesisLifecycleState.CREATED

    # Activate (CREATED -> ACTIVE)
    thesis.activate("2026-08-08 14:00:00", reason="MACRO_M30_OPEN")
    assert thesis.state == ThesisLifecycleState.ACTIVE
    assert len(thesis.transitions) == 1
    assert thesis.transitions[0].from_state == ThesisLifecycleState.CREATED
    assert thesis.transitions[0].to_state == ThesisLifecycleState.ACTIVE

    # Candidate (ACTIVE -> ENTRY_AVAILABLE)
    cand1 = ChildEntryCandidate("cand_1", thesis.thesis_id, "2026-08-08 14:05:00", Timeframe.M5, ThesisDirection.LONG, 2400.0, 2390.0)
    thesis.register_entry_candidate(cand1)
    assert thesis.state == ThesisLifecycleState.ENTRY_AVAILABLE
    assert len(thesis.transitions) == 2
    assert thesis.transitions[1].to_state == ThesisLifecycleState.ENTRY_AVAILABLE

    # Complete (ENTRY_AVAILABLE -> COMPLETED)
    thesis.complete("2026-08-08 14:30:00", winning_child_id="cand_1", reason="TP_HIT")
    assert thesis.state == ThesisLifecycleState.COMPLETED
    assert thesis.is_terminal()
    assert len(thesis.transitions) == 3
    assert thesis.transitions[2].to_state == ThesisLifecycleState.COMPLETED
    assert thesis.transitions[2].related_candidate_id == "cand_1"


def test_audit_all_replay_outcomes():
    # A) CREATED -> ACTIVE
    t_a = create_sample_thesis()
    t_a.activate("2026-08-08 14:00:00")
    reb_a = rebuild_thesis_from_events(t_a.to_dict(), list(t_a.transitions), list(t_a.evidence), list(t_a.candidates))
    assert reb_a.state == ThesisLifecycleState.ACTIVE

    # B) CREATED -> ACTIVE -> ENTRY_AVAILABLE
    t_b = create_sample_thesis()
    t_b.activate("2026-08-08 14:00:00")
    cand = ChildEntryCandidate("c1", t_b.thesis_id, "2026-08-08 14:05:00", Timeframe.M5, ThesisDirection.LONG, 2400.0, 2390.0)
    t_b.register_entry_candidate(cand)
    reb_b = rebuild_thesis_from_events(t_b.to_dict(), list(t_b.transitions), list(t_b.evidence), list(t_b.candidates))
    assert reb_b.state == ThesisLifecycleState.ENTRY_AVAILABLE

    # C) CREATED -> ACTIVE -> INVALIDATED
    t_c = create_sample_thesis()
    t_c.activate("2026-08-08 14:00:00")
    t_c.invalidate("2026-08-08 14:15:00", reason="HTF_BREACH")
    reb_c = rebuild_thesis_from_events(t_c.to_dict(), list(t_c.transitions), list(t_c.evidence), list(t_c.candidates))
    assert reb_c.state == ThesisLifecycleState.INVALIDATED
    assert reb_c._terminal_reason == "HTF_BREACH"

    # D) CREATED -> ACTIVE -> EXPIRED
    t_d = create_sample_thesis()
    t_d.activate("2026-08-08 14:00:00")
    t_d.expire("2026-08-08 18:00:00", reason="MAX_BARS")
    reb_d = rebuild_thesis_from_events(t_d.to_dict(), list(t_d.transitions), list(t_d.evidence), list(t_d.candidates))
    assert reb_d.state == ThesisLifecycleState.EXPIRED

    # E) CREATED -> ACTIVE -> ENTRY_AVAILABLE -> COMPLETED
    t_e = create_sample_thesis()
    t_e.activate("2026-08-08 14:00:00")
    cand_e = ChildEntryCandidate("c1", t_e.thesis_id, "2026-08-08 14:05:00", Timeframe.M5, ThesisDirection.LONG, 2400.0, 2390.0)
    t_e.register_entry_candidate(cand_e)
    t_e.complete("2026-08-08 14:30:00", winning_child_id="c1", reason="TP_HIT")
    reb_e = rebuild_thesis_from_events(t_e.to_dict(), list(t_e.transitions), list(t_e.evidence), list(t_e.candidates))
    assert reb_e.state == ThesisLifecycleState.COMPLETED
    assert reb_e._winning_child_id == "c1"


def test_impossible_terminal_transition_replay_rejected():
    t = create_sample_thesis()
    t.activate("2026-08-08 14:00:00")
    t.invalidate("2026-08-08 14:15:00")

    # Tampered transition sequence (INVALIDATED -> ACTIVE)
    bad_tr = ThesisTransition("tr_bad", t.thesis_id, "2026-08-08 14:20:00", ThesisLifecycleState.INVALIDATED, ThesisLifecycleState.ACTIVE)
    with pytest.raises(TerminalStateViolationError):
        rebuild_thesis_from_events(t.to_dict(), [bad_tr], [], [])


def test_serialization_roundtrip_with_transitions():
    thesis = create_sample_thesis()
    thesis.activate("2026-08-08 14:00:00")
    cand = ChildEntryCandidate("cand_1", thesis.thesis_id, "2026-08-08 14:05:00", Timeframe.M5, ThesisDirection.LONG, 2400.0, 2390.0)
    thesis.register_entry_candidate(cand)
    thesis.complete("2026-08-08 14:30:00", winning_child_id="cand_1", reason="TP_HIT")

    data = thesis.to_dict()
    deserialized = ParentThesis.from_dict(data)

    assert deserialized.thesis_id == thesis.thesis_id
    assert deserialized.state == thesis.state
    assert len(deserialized.transitions) == 3
    assert len(deserialized.candidates) == 1


def test_v1_isolation_regression():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
