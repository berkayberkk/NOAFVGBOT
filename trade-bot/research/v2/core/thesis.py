"""
NOAFVGBOT V2.2 — Parent Thesis Domain, Lifecycle & Transition Provenance Module.

Defines ParentThesis, ThesisLifecycleState, ThesisEvidence, ChildEntryCandidate,
and immutable ThesisTransition records for full lifecycle replay and provenance auditing.

INVARIANTS:
- Frozen V1 files remain untouched.
- ParentThesis state is 100% reconstructible from seed + transitions + evidence + candidates.
- Terminal states (COMPLETED, INVALIDATED, EXPIRED) cannot be reactivated.
- Candidate entry timeframes are strictly M5 or M3.
- All domain events use content-based deterministic IDs and canonical ordering.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from research.v2.data.models import Timeframe


class ThesisDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class ThesisLifecycleState(Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    ENTRY_AVAILABLE = "ENTRY_AVAILABLE"
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


TERMINAL_STATES = {
    ThesisLifecycleState.COMPLETED,
    ThesisLifecycleState.INVALIDATED,
    ThesisLifecycleState.EXPIRED,
}


class EvidenceType(Enum):
    M30_MACRO = "M30_MACRO"
    M15_CONFIRMATION = "M15_CONFIRMATION"
    M5_SETUP = "M5_SETUP"
    M3_REFINEMENT = "M3_REFINEMENT"
    M1_OBSERVATION = "M1_OBSERVATION"
    INVALIDATION = "INVALIDATION"
    EXPIRY = "EXPIRY"
    ENTRY_CANDIDATE = "ENTRY_CANDIDATE"
    COMPLETION = "COMPLETION"


class DuplicateEvidenceError(Exception):
    """Raised when evidence with an existing ID is re-added."""
    pass


class DuplicateCandidateError(Exception):
    """Raised when a candidate with an existing ID is registered."""
    pass


class DuplicateTransitionError(Exception):
    """Raised when a transition with an existing ID is recorded."""
    pass


class TerminalStateViolationError(Exception):
    """Raised when an operation violates terminal state immutability."""
    pass


@dataclass(frozen=True)
class ThesisTransition:
    transition_id: str
    thesis_id: str
    timestamp_utc: str
    from_state: ThesisLifecycleState
    to_state: ThesisLifecycleState
    reason: str = ""
    related_candidate_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "2.2"

    def __post_init__(self) -> None:
        try:
            json.dumps(self.metadata)
        except Exception as e:
            raise ValueError(f"Transition metadata must be JSON-serializable: {e}")


@dataclass(frozen=True)
class ThesisEvidence:
    evidence_id: str
    thesis_id: str
    timestamp_utc: str
    timeframe: Timeframe
    evidence_type: EvidenceType
    payload: Dict[str, Any] = field(default_factory=dict)
    source_candle_close_timestamp: str = ""

    def __post_init__(self) -> None:
        try:
            json.dumps(self.payload)
        except Exception as e:
            raise ValueError(f"Evidence payload must be JSON-serializable: {e}")

        if not self.source_candle_close_timestamp:
            object.__setattr__(self, "source_candle_close_timestamp", self.timestamp_utc)

        t_ev = datetime.fromisoformat(self.timestamp_utc).replace(tzinfo=timezone.utc)
        t_src = datetime.fromisoformat(self.source_candle_close_timestamp).replace(tzinfo=timezone.utc)

        if t_src > t_ev:
            raise ValueError(f"source_candle_close_timestamp ({self.source_candle_close_timestamp}) cannot be > evidence timestamp_utc ({self.timestamp_utc})")


@dataclass(frozen=True)
class ChildEntryCandidate:
    candidate_id: str
    thesis_id: str
    created_at: str
    timeframe: Timeframe
    direction: ThesisDirection
    structural_entry: float
    structural_stop: float
    structural_target: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timeframe not in (Timeframe.M5, Timeframe.M3):
            raise ValueError(f"ChildEntryCandidate timeframe must be M5 or M3, got: {self.timeframe}")

        if self.structural_entry <= 0 or self.structural_stop <= 0:
            raise ValueError("Entry and stop prices must be positive numbers")

        if self.direction == ThesisDirection.LONG and self.structural_stop >= self.structural_entry:
            raise ValueError("LONG candidate stop_loss must be < entry price")
        if self.direction == ThesisDirection.SHORT and self.structural_stop <= self.structural_entry:
            raise ValueError("SHORT candidate stop_loss must be > entry price")


def compute_thesis_id(
    strategy_version: str,
    config_fingerprint: str,
    symbol: str,
    source_timeframe: Timeframe,
    source_candle_close_timestamp: str,
    direction: ThesisDirection,
    structural_fingerprint: str = "",
) -> str:
    raw = f"{strategy_version}|{config_fingerprint}|{symbol}|{source_timeframe.name}|{source_candle_close_timestamp}|{direction.name}|{structural_fingerprint}"
    return "th_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def compute_transition_id(
    thesis_id: str,
    timestamp_utc: str,
    from_state: ThesisLifecycleState,
    to_state: ThesisLifecycleState,
    reason: str = "",
    related_candidate_id: Optional[str] = None,
) -> str:
    raw = f"{thesis_id}|{timestamp_utc}|{from_state.value}|{to_state.value}|{reason}|{related_candidate_id or ''}"
    return "tr_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class ParentThesis:
    """Domain model representing a Higher-Timeframe Market Thesis."""

    def __init__(
        self,
        thesis_id: str,
        strategy_version: str,
        schema_version: str,
        config_fingerprint: str,
        symbol: str,
        direction: ThesisDirection,
        source_timeframe: Timeframe,
        created_at: str,
        initial_state: ThesisLifecycleState = ThesisLifecycleState.CREATED,
    ):
        self._thesis_id = thesis_id
        self._strategy_version = strategy_version
        self._schema_version = schema_version
        self._config_fingerprint = config_fingerprint
        self._symbol = symbol
        self._direction = direction
        self._source_timeframe = source_timeframe
        self._created_at = created_at

        self._state = initial_state
        self._evidence: List[ThesisEvidence] = []
        self._candidates: List[ChildEntryCandidate] = []
        self._transitions: List[ThesisTransition] = []
        
        self._evidence_ids: set = set()
        self._candidate_ids: set = set()
        self._transition_ids: set = set()

        self._activated_at: Optional[str] = None
        self._completed_at: Optional[str] = None
        self._invalidated_at: Optional[str] = None
        self._expired_at: Optional[str] = None
        self._terminal_reason: str = ""
        self._winning_child_id: Optional[str] = None

    @property
    def thesis_id(self) -> str: return self._thesis_id
    @property
    def strategy_version(self) -> str: return self._strategy_version
    @property
    def schema_version(self) -> str: return self._schema_version
    @property
    def config_fingerprint(self) -> str: return self._config_fingerprint
    @property
    def symbol(self) -> str: return self._symbol
    @property
    def direction(self) -> ThesisDirection: return self._direction
    @property
    def source_timeframe(self) -> Timeframe: return self._source_timeframe
    @property
    def created_at(self) -> str: return self._created_at
    @property
    def state(self) -> ThesisLifecycleState: return self._state
    @property
    def evidence(self) -> Tuple[ThesisEvidence, ...]: return tuple(self._evidence)
    @property
    def candidates(self) -> Tuple[ChildEntryCandidate, ...]: return tuple(self._candidates)
    @property
    def transitions(self) -> Tuple[ThesisTransition, ...]: return tuple(self._transitions)

    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    def _record_transition(
        self,
        timestamp_utc: str,
        from_state: ThesisLifecycleState,
        to_state: ThesisLifecycleState,
        reason: str = "",
        related_candidate_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ThesisTransition:
        tr_id = compute_transition_id(self._thesis_id, timestamp_utc, from_state, to_state, reason, related_candidate_id)
        if tr_id in self._transition_ids:
            raise DuplicateTransitionError(f"Transition {tr_id} already recorded")

        transition = ThesisTransition(
            transition_id=tr_id,
            thesis_id=self._thesis_id,
            timestamp_utc=timestamp_utc,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            related_candidate_id=related_candidate_id,
            metadata=metadata or {},
            schema_version=self._schema_version,
        )
        self._transitions.append(transition)
        self._transition_ids.add(tr_id)
        return transition

    def activate(self, timestamp_utc: str, reason: str = "") -> None:
        """Transitions CREATED -> ACTIVE."""
        if self.is_terminal():
            raise TerminalStateViolationError(f"Cannot activate thesis in terminal state {self._state}")
        if self._state != ThesisLifecycleState.CREATED:
            raise ValueError(f"Can only activate from CREATED state, current state: {self._state}")

        old_state = self._state
        self._state = ThesisLifecycleState.ACTIVE
        self._activated_at = timestamp_utc
        self._record_transition(timestamp_utc, old_state, self._state, reason=reason)

    def register_entry_candidate(self, candidate: ChildEntryCandidate) -> None:
        """Registers lower-timeframe child entry candidate."""
        if self.is_terminal():
            raise TerminalStateViolationError(f"Cannot register entry candidate on terminal thesis {self._state}")
        if candidate.thesis_id != self._thesis_id:
            raise ValueError(f"Candidate thesis_id ({candidate.thesis_id}) mismatch with thesis ({self._thesis_id})")
        if candidate.direction != self._direction:
            raise ValueError(f"Candidate direction ({candidate.direction}) mismatch with thesis ({self._direction})")

        if candidate.candidate_id in self._candidate_ids:
            raise DuplicateCandidateError(f"Candidate {candidate.candidate_id} already registered")

        self._candidates.append(candidate)
        self._candidate_ids.add(candidate.candidate_id)

        if self._state == ThesisLifecycleState.ACTIVE:
            old_state = self._state
            self._state = ThesisLifecycleState.ENTRY_AVAILABLE
            self._record_transition(candidate.created_at, old_state, self._state, reason="ENTRY_CANDIDATE_REGISTERED", related_candidate_id=candidate.candidate_id)

    def add_evidence(self, evidence: ThesisEvidence) -> None:
        """Appends evidence in strict non-decreasing chronological order."""
        if evidence.thesis_id != self._thesis_id:
            raise ValueError(f"Evidence thesis_id mismatch: {evidence.thesis_id} != {self._thesis_id}")

        if evidence.evidence_id in self._evidence_ids:
            raise DuplicateEvidenceError(f"Evidence {evidence.evidence_id} already added")

        t_ev = datetime.fromisoformat(evidence.timestamp_utc).replace(tzinfo=timezone.utc)
        t_create = datetime.fromisoformat(self._created_at).replace(tzinfo=timezone.utc)

        if t_ev < t_create:
            raise ValueError(f"Evidence timestamp ({evidence.timestamp_utc}) cannot be before thesis created_at ({self._created_at})")

        if self._evidence:
            last_ev_dt = datetime.fromisoformat(self._evidence[-1].timestamp_utc).replace(tzinfo=timezone.utc)
            if t_ev < last_ev_dt:
                raise ValueError(f"Evidence chronology violation: {evidence.timestamp_utc} < previous {self._evidence[-1].timestamp_utc}")

        self._evidence.append(evidence)
        self._evidence_ids.add(evidence.evidence_id)

    def invalidate(self, timestamp_utc: str, reason: str = "") -> None:
        """Transitions ACTIVE | ENTRY_AVAILABLE | CREATED -> INVALIDATED."""
        if self.is_terminal():
            raise TerminalStateViolationError(f"Thesis already in terminal state {self._state}")

        old_state = self._state
        self._state = ThesisLifecycleState.INVALIDATED
        self._invalidated_at = timestamp_utc
        self._terminal_reason = reason
        self._record_transition(timestamp_utc, old_state, self._state, reason=reason)

    def expire(self, timestamp_utc: str, reason: str = "") -> None:
        """Transitions ACTIVE | ENTRY_AVAILABLE | CREATED -> EXPIRED."""
        if self.is_terminal():
            raise TerminalStateViolationError(f"Thesis already in terminal state {self._state}")

        old_state = self._state
        self._state = ThesisLifecycleState.EXPIRED
        self._expired_at = timestamp_utc
        self._terminal_reason = reason
        self._record_transition(timestamp_utc, old_state, self._state, reason=reason)

    def complete(self, timestamp_utc: str, winning_child_id: Optional[str] = None, reason: str = "") -> None:
        """Transitions ENTRY_AVAILABLE -> COMPLETED."""
        if self.is_terminal():
            raise TerminalStateViolationError(f"Thesis already in terminal state {self._state}")
        if self._state != ThesisLifecycleState.ENTRY_AVAILABLE:
            raise ValueError(f"Can only complete from ENTRY_AVAILABLE state, current state: {self._state}")

        old_state = self._state
        self._state = ThesisLifecycleState.COMPLETED
        self._completed_at = timestamp_utc
        self._winning_child_id = winning_child_id
        self._terminal_reason = reason
        self._record_transition(timestamp_utc, old_state, self._state, reason=reason, related_candidate_id=winning_child_id)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes ParentThesis state to JSON-compatible dictionary."""
        return {
            "thesis_id": self._thesis_id,
            "strategy_version": self._strategy_version,
            "schema_version": self._schema_version,
            "config_fingerprint": self._config_fingerprint,
            "symbol": self._symbol,
            "direction": self._direction.value,
            "source_timeframe": self._source_timeframe.name,
            "created_at": self._created_at,
            "state": self._state.value,
            "activated_at": self._activated_at,
            "completed_at": self._completed_at,
            "invalidated_at": self._invalidated_at,
            "expired_at": self._expired_at,
            "terminal_reason": self._terminal_reason,
            "winning_child_id": self._winning_child_id,
            "transitions": [
                {
                    "transition_id": tr.transition_id,
                    "thesis_id": tr.thesis_id,
                    "timestamp_utc": tr.timestamp_utc,
                    "from_state": tr.from_state.value,
                    "to_state": tr.to_state.value,
                    "reason": tr.reason,
                    "related_candidate_id": tr.related_candidate_id,
                    "metadata": tr.metadata,
                    "schema_version": tr.schema_version,
                }
                for tr in self._transitions
            ],
            "evidence": [
                {
                    "evidence_id": e.evidence_id,
                    "thesis_id": e.thesis_id,
                    "timestamp_utc": e.timestamp_utc,
                    "timeframe": e.timeframe.name,
                    "evidence_type": e.evidence_type.value,
                    "payload": e.payload,
                    "source_candle_close_timestamp": e.source_candle_close_timestamp,
                }
                for e in self._evidence
            ],
            "candidates": [
                {
                    "candidate_id": c.candidate_id,
                    "thesis_id": c.thesis_id,
                    "created_at": c.created_at,
                    "timeframe": c.timeframe.name,
                    "direction": c.direction.value,
                    "structural_entry": c.structural_entry,
                    "structural_stop": c.structural_stop,
                    "structural_target": c.structural_target,
                    "metadata": c.metadata,
                }
                for c in self._candidates
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParentThesis":
        """Reconstructs ParentThesis from serialized dictionary."""
        thesis = cls(
            thesis_id=data["thesis_id"],
            strategy_version=data["strategy_version"],
            schema_version=data["schema_version"],
            config_fingerprint=data["config_fingerprint"],
            symbol=data["symbol"],
            direction=ThesisDirection[data["direction"]],
            source_timeframe=Timeframe[data["source_timeframe"]],
            created_at=data["created_at"],
            initial_state=ThesisLifecycleState[data["state"]],
        )
        thesis._activated_at = data.get("activated_at")
        thesis._completed_at = data.get("completed_at")
        thesis._invalidated_at = data.get("invalidated_at")
        thesis._expired_at = data.get("expired_at")
        thesis._terminal_reason = data.get("terminal_reason", "")
        thesis._winning_child_id = data.get("winning_child_id")

        for tr_data in data.get("transitions", []):
            tr = ThesisTransition(
                transition_id=tr_data["transition_id"],
                thesis_id=tr_data["thesis_id"],
                timestamp_utc=tr_data["timestamp_utc"],
                from_state=ThesisLifecycleState[tr_data["from_state"]],
                to_state=ThesisLifecycleState[tr_data["to_state"]],
                reason=tr_data.get("reason", ""),
                related_candidate_id=tr_data.get("related_candidate_id"),
                metadata=tr_data.get("metadata", {}),
                schema_version=tr_data.get("schema_version", "2.2"),
            )
            thesis._transitions.append(tr)
            thesis._transition_ids.add(tr.transition_id)

        for e_data in data.get("evidence", []):
            ev = ThesisEvidence(
                evidence_id=e_data["evidence_id"],
                thesis_id=e_data["thesis_id"],
                timestamp_utc=e_data["timestamp_utc"],
                timeframe=Timeframe[e_data["timeframe"]],
                evidence_type=EvidenceType[e_data["evidence_type"]],
                payload=e_data.get("payload", {}),
                source_candle_close_timestamp=e_data.get("source_candle_close_timestamp", ""),
            )
            thesis._evidence.append(ev)
            thesis._evidence_ids.add(ev.evidence_id)

        for c_data in data.get("candidates", []):
            cand = ChildEntryCandidate(
                candidate_id=c_data["candidate_id"],
                thesis_id=c_data["thesis_id"],
                created_at=c_data["created_at"],
                timeframe=Timeframe[c_data["timeframe"]],
                direction=ThesisDirection[c_data["direction"]],
                structural_entry=c_data["structural_entry"],
                structural_stop=c_data["structural_stop"],
                structural_target=c_data.get("structural_target"),
                metadata=c_data.get("metadata", {}),
            )
            thesis._candidates.append(cand)
            thesis._candidate_ids.add(cand.candidate_id)

        return thesis


def rebuild_thesis_from_events(
    seed_data: Dict[str, Any],
    transitions: List[ThesisTransition],
    evidence_events: List[ThesisEvidence],
    candidate_events: List[ChildEntryCandidate],
) -> ParentThesis:
    """
    Reconstructs ParentThesis state machine deterministically from seed + transitions + evidence + candidates.
    Chronological canonical sorting guarantees deterministic execution order.
    """
    thesis = ParentThesis(
        thesis_id=seed_data["thesis_id"],
        strategy_version=seed_data.get("strategy_version", "NOAFVGBOT_V2_RESEARCH"),
        schema_version=seed_data.get("schema_version", "2.2"),
        config_fingerprint=seed_data.get("config_fingerprint", "v2_config_hash"),
        symbol=seed_data.get("symbol", "XAUUSD"),
        direction=ThesisDirection[seed_data["direction"]] if isinstance(seed_data["direction"], str) else seed_data["direction"],
        source_timeframe=Timeframe[seed_data["source_timeframe"]] if isinstance(seed_data["source_timeframe"], str) else seed_data["source_timeframe"],
        created_at=seed_data["created_at"],
        initial_state=ThesisLifecycleState.CREATED,
    )

    # Sort transitions chronologically
    sorted_transitions = sorted(transitions, key=lambda tr: (tr.timestamp_utc, tr.transition_id))

    for tr in sorted_transitions:
        if tr.from_state != thesis.state:
            raise TerminalStateViolationError(f"Replay transition error: expected from_state {thesis.state}, got {tr.from_state}")

        if tr.to_state == ThesisLifecycleState.ACTIVE:
            thesis.activate(tr.timestamp_utc, reason=tr.reason)
        elif tr.to_state == ThesisLifecycleState.ENTRY_AVAILABLE:
            cand_match = next((c for c in candidate_events if c.candidate_id == tr.related_candidate_id), None)
            if cand_match and cand_match.candidate_id not in thesis._candidate_ids:
                thesis.register_entry_candidate(cand_match)
            else:
                old_st = thesis._state
                thesis._state = ThesisLifecycleState.ENTRY_AVAILABLE
                if tr.transition_id not in thesis._transition_ids:
                    thesis._record_transition(tr.timestamp_utc, old_st, thesis._state, reason=tr.reason, related_candidate_id=tr.related_candidate_id)
        elif tr.to_state == ThesisLifecycleState.INVALIDATED:
            thesis.invalidate(tr.timestamp_utc, reason=tr.reason)
        elif tr.to_state == ThesisLifecycleState.EXPIRED:
            thesis.expire(tr.timestamp_utc, reason=tr.reason)
        elif tr.to_state == ThesisLifecycleState.COMPLETED:
            thesis.complete(tr.timestamp_utc, winning_child_id=tr.related_candidate_id, reason=tr.reason)

    # Add candidates
    sorted_candidates = sorted(candidate_events, key=lambda c: (c.created_at, c.candidate_id))
    for cand in sorted_candidates:
        if cand.candidate_id not in thesis._candidate_ids:
            # If state wasn't transitioned via transition replay, register directly
            if thesis.state == ThesisLifecycleState.ACTIVE:
                thesis.register_entry_candidate(cand)
            else:
                thesis._candidates.append(cand)
                thesis._candidate_ids.add(cand.candidate_id)

    # Add evidence
    sorted_evidence = sorted(evidence_events, key=lambda e: (e.timestamp_utc, e.evidence_id))
    for ev in sorted_evidence:
        if ev.evidence_id not in thesis._evidence_ids:
            thesis.add_evidence(ev)

    return thesis
