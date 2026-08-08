"""
NOAFVGBOT V2.5 — Trade Passport & Research Telemetry Module.

Provides an immutable, replayable Trade Passport recording decision-time snapshot,
hindsight-free feature availability, pre/post-entry path telemetry, excursion (MAE/MFE)
metrics, and research outcome states.

INVARIANTS:
- DecisionSnapshot accepts ONLY DECISION_TIME features with known_at_timestamp <= candidate_created_at.
- Zero future outcome or post-event telemetry in decision_view().
- Pre-entry path is separated from post-entry path (trade MAE/MFE begins at structural entry touch).
- Same-bar entry/stop/target collisions are labeled AMBIGUOUS_SAME_BAR.
- Censored passports accept no further path observations.
- 100% reconstructible from seed + snapshot + observations + events.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from research.v2.data.models import Timeframe
from research.v2.core.thesis import ThesisDirection
from research.v2.features.models import FeatureRecord, FeaturePhase
from research.v2.features.liquidity import LiquidityPool
from research.v2.telemetry.excursion import PathObservation, ExcursionMetrics, calculate_excursion_as_of


class OutcomeState(Enum):
    OPEN = "OPEN"
    ENTRY_NOT_TOUCHED = "ENTRY_NOT_TOUCHED"
    ENTRY_TOUCHED = "ENTRY_TOUCHED"
    STOP_REACHED = "STOP_REACHED"
    TARGET_REACHED = "TARGET_REACHED"
    AMBIGUOUS_SAME_BAR = "AMBIGUOUS_SAME_BAR"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PassportEventType(Enum):
    PASSPORT_CREATED = "PASSPORT_CREATED"
    STRUCTURAL_ENTRY_TOUCHED = "STRUCTURAL_ENTRY_TOUCHED"
    STOP_REACHED = "STOP_REACHED"
    TARGET_REACHED = "TARGET_REACHED"
    AMBIGUOUS_SAME_BAR = "AMBIGUOUS_SAME_BAR"
    CENSORED = "CENSORED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class DuplicateObservationError(Exception):
    """Raised when an observation with an existing ID is re-added."""
    pass


class CensoredPassportError(Exception):
    """Raised when attempting to add observations to a censored passport."""
    pass


@dataclass(frozen=True)
class PassportEvent:
    event_id: str
    passport_id: str
    event_type: PassportEventType
    timestamp_utc: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            json.dumps(self.metadata)
        except Exception as e:
            raise ValueError(f"PassportEvent metadata must be JSON-serializable: {e}")


@dataclass(frozen=True)
class DecisionSnapshot:
    thesis_id: str
    direction: ThesisDirection
    candidate_id: str
    candidate_created_at: str
    candidate_timeframe: Timeframe
    structural_entry: float
    structural_stop: float
    structural_target: Optional[float] = None
    feature_records: Tuple[FeatureRecord, ...] = ()
    liquidity_pools: Tuple[LiquidityPool, ...] = ()
    mtf_trace: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        t_cand = datetime.fromisoformat(self.candidate_created_at).replace(tzinfo=timezone.utc)

        # Reject POST_EVENT features or future features
        for f in self.feature_records:
            if f.phase != FeaturePhase.DECISION_TIME:
                raise ValueError(f"DecisionSnapshot rejects POST_EVENT feature: {f.feature_id}")
            t_f = datetime.fromisoformat(f.known_at_timestamp).replace(tzinfo=timezone.utc)
            if t_f > t_cand:
                raise ValueError(f"DecisionSnapshot rejects future feature {f.feature_id} (known_at {f.known_at_timestamp} > candidate {self.candidate_created_at})")

        # Reject future liquidity
        for lp in self.liquidity_pools:
            t_lp = datetime.fromisoformat(lp.known_at_timestamp).replace(tzinfo=timezone.utc)
            if t_lp > t_cand:
                raise ValueError(f"DecisionSnapshot rejects future liquidity pool {lp.pool_id} (known_at {lp.known_at_timestamp} > candidate {self.candidate_created_at})")

        # Geometry validation
        if self.structural_entry <= 0 or self.structural_stop <= 0:
            raise ValueError("Entry and stop prices must be positive numbers")
        if self.direction == ThesisDirection.LONG and self.structural_stop >= self.structural_entry:
            raise ValueError("LONG candidate stop_loss must be < entry price")
        if self.direction == ThesisDirection.SHORT and self.structural_stop <= self.structural_entry:
            raise ValueError("SHORT candidate stop_loss must be > entry price")


def compute_passport_id(
    thesis_id: str,
    candidate_id: str,
    config_fingerprint: str,
    created_at: str,
) -> str:
    raw = f"{thesis_id}|{candidate_id}|{config_fingerprint}|{created_at}"
    return "pass_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class TradePassport:
    """Domain model representing an immutable research Trade Passport."""

    def __init__(
        self,
        passport_id: str,
        strategy_version: str,
        schema_version: str,
        config_fingerprint: str,
        thesis_id: str,
        candidate_id: str,
        symbol: str,
        direction: ThesisDirection,
        candidate_timeframe: Timeframe,
        created_at: str,
        decision_snapshot: DecisionSnapshot,
    ):
        self._passport_id = passport_id
        self._strategy_version = strategy_version
        self._schema_version = schema_version
        self._config_fingerprint = config_fingerprint
        self._thesis_id = thesis_id
        self._candidate_id = candidate_id
        self._symbol = symbol
        self._direction = direction
        self._candidate_timeframe = candidate_timeframe
        self._created_at = created_at
        self._decision_snapshot = decision_snapshot

        self._pre_entry_path: List[PathObservation] = []
        self._post_entry_path: List[PathObservation] = []
        self._events: List[PassportEvent] = []
        self._obs_ids: set = set()
        self._event_ids: set = set()

        self._entry_touched: bool = False
        self._entry_touch_ts: Optional[str] = None
        self._outcome_state: OutcomeState = OutcomeState.OPEN
        self._is_censored: bool = False
        self._censor_ts: Optional[str] = None
        self._censor_reason: str = ""

        # Initial risk distance
        self._initial_risk_distance = abs(decision_snapshot.structural_entry - decision_snapshot.structural_stop)

        # Record initial event
        self._record_event(PassportEventType.PASSPORT_CREATED, created_at)

    # Immutable Attribute Properties
    @property
    def passport_id(self) -> str: return self._passport_id
    @property
    def strategy_version(self) -> str: return self._strategy_version
    @property
    def schema_version(self) -> str: return self._schema_version
    @property
    def config_fingerprint(self) -> str: return self._config_fingerprint
    @property
    def thesis_id(self) -> str: return self._thesis_id
    @property
    def candidate_id(self) -> str: return self._candidate_id
    @property
    def symbol(self) -> str: return self._symbol
    @property
    def direction(self) -> ThesisDirection: return self._direction
    @property
    def candidate_timeframe(self) -> Timeframe: return self._candidate_timeframe
    @property
    def created_at(self) -> str: return self._created_at
    @property
    def decision_snapshot(self) -> DecisionSnapshot: return self._decision_snapshot
    @property
    def entry_touch_ts(self) -> Optional[str]: return self._entry_touch_ts
    @property
    def outcome_state(self) -> OutcomeState: return self._outcome_state
    @property
    def is_censored(self) -> bool: return self._is_censored
    @property
    def pre_entry_path(self) -> Tuple[PathObservation, ...]: return tuple(self._pre_entry_path)
    @property
    def post_entry_path(self) -> Tuple[PathObservation, ...]: return tuple(self._post_entry_path)
    @property
    def events(self) -> Tuple[PassportEvent, ...]: return tuple(self._events)

    def _record_event(self, event_type: PassportEventType, timestamp_utc: str, metadata: Optional[Dict[str, Any]] = None) -> PassportEvent:
        raw_id = f"{self._passport_id}|{event_type.value}|{timestamp_utc}"
        eid = "pe_" + hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]

        if eid in self._event_ids:
            # Idempotent ignore
            return [e for e in self._events if e.event_id == eid][0]

        event = PassportEvent(
            event_id=eid,
            passport_id=self._passport_id,
            event_type=event_type,
            timestamp_utc=timestamp_utc,
            metadata=metadata or {},
        )
        self._events.append(event)
        self._event_ids.add(eid)
        return event

    def add_observation(self, obs: PathObservation) -> None:
        """Appends path observation chronologically and updates path telemetry."""
        if self._is_censored:
            raise CensoredPassportError(f"Passport {self._passport_id} is censored; cannot append observations")

        if obs.observation_id in self._obs_ids:
            raise DuplicateObservationError(f"Observation {obs.observation_id} already added")

        t_obs = datetime.fromisoformat(obs.timestamp_utc).replace(tzinfo=timezone.utc)
        t_create = datetime.fromisoformat(self._created_at).replace(tzinfo=timezone.utc)

        if t_obs < t_create:
            raise ValueError(f"Observation timestamp ({obs.timestamp_utc}) cannot be before passport created_at ({self._created_at})")

        all_obs = self._pre_entry_path + self._post_entry_path
        if all_obs:
            t_last = datetime.fromisoformat(all_obs[-1].timestamp_utc).replace(tzinfo=timezone.utc)
            if t_obs < t_last:
                raise ValueError(f"Observation chronology violation: {obs.timestamp_utc} < previous {all_obs[-1].timestamp_utc}")

        self._obs_ids.add(obs.observation_id)

        entry = self._decision_snapshot.structural_entry
        stop = self._decision_snapshot.structural_stop
        target = self._decision_snapshot.structural_target

        # Check Entry Touch if not yet touched
        if not self._entry_touched:
            touched = (obs.low <= entry <= obs.high)
            if touched:
                self._entry_touched = True
                self._entry_touch_ts = obs.timestamp_utc
                self._outcome_state = OutcomeState.ENTRY_TOUCHED
                self._record_event(PassportEventType.STRUCTURAL_ENTRY_TOUCHED, obs.timestamp_utc)

                # Check same-bar collision (entry, stop, target hit in exact same candle!)
                stop_hit = (obs.low <= stop) if self._direction == ThesisDirection.LONG else (obs.high >= stop)
                target_hit = (target is not None) and ((obs.high >= target) if self._direction == ThesisDirection.LONG else (obs.low <= target))

                if stop_hit and target_hit:
                    self._outcome_state = OutcomeState.AMBIGUOUS_SAME_BAR
                    self._record_event(PassportEventType.AMBIGUOUS_SAME_BAR, obs.timestamp_utc, {"reason": "ENTRY_STOP_TARGET_SAME_BAR"})
                elif stop_hit:
                    self._outcome_state = OutcomeState.STOP_REACHED
                    self._record_event(PassportEventType.STOP_REACHED, obs.timestamp_utc)
                elif target_hit:
                    self._outcome_state = OutcomeState.TARGET_REACHED
                    self._record_event(PassportEventType.TARGET_REACHED, obs.timestamp_utc)

                self._post_entry_path.append(obs)
            else:
                self._pre_entry_path.append(obs)
        else:
            # Already touched -> append to post-entry path and check outcome
            self._post_entry_path.append(obs)

            if self._outcome_state in (OutcomeState.ENTRY_TOUCHED, OutcomeState.OPEN):
                stop_hit = (obs.low <= stop) if self._direction == ThesisDirection.LONG else (obs.high >= stop)
                target_hit = (target is not None) and ((obs.high >= target) if self._direction == ThesisDirection.LONG else (obs.low <= target))

                if stop_hit and target_hit:
                    self._outcome_state = OutcomeState.AMBIGUOUS_SAME_BAR
                    self._record_event(PassportEventType.AMBIGUOUS_SAME_BAR, obs.timestamp_utc, {"reason": "STOP_TARGET_SAME_BAR"})
                elif stop_hit:
                    self._outcome_state = OutcomeState.STOP_REACHED
                    self._record_event(PassportEventType.STOP_REACHED, obs.timestamp_utc)
                elif target_hit:
                    self._outcome_state = OutcomeState.TARGET_REACHED
                    self._record_event(PassportEventType.TARGET_REACHED, obs.timestamp_utc)

    def censor(self, timestamp_utc: str, reason: str = "") -> None:
        """Censors the passport research history."""
        self._is_censored = True
        self._censor_ts = timestamp_utc
        self._censor_reason = reason
        self._record_event(PassportEventType.CENSORED, timestamp_utc, {"reason": reason})

    def get_excursion(self, as_of_utc: Optional[str] = None) -> ExcursionMetrics:
        """Calculates trade MAE/MFE metrics on post-entry path as-of timestamp."""
        as_of = as_of_utc or (self._post_entry_path[-1].timestamp_utc if self._post_entry_path else self._created_at)
        return calculate_excursion_as_of(
            reference_price=self._decision_snapshot.structural_entry,
            direction=self._direction,
            risk_distance=self._initial_risk_distance,
            observations=self._post_entry_path,
            as_of_utc=as_of,
        )

    def decision_view(self) -> Dict[str, Any]:
        """Returns decision-time view containing ZERO post-event outcome or path telemetry."""
        return {
            "passport_id": self._passport_id,
            "strategy_version": self._strategy_version,
            "schema_version": self._schema_version,
            "config_fingerprint": self._config_fingerprint,
            "thesis_id": self._thesis_id,
            "candidate_id": self._candidate_id,
            "symbol": self._symbol,
            "direction": self._direction.value,
            "candidate_timeframe": self._candidate_timeframe.name,
            "created_at": self._created_at,
            "decision_snapshot": {
                "structural_entry": self._decision_snapshot.structural_entry,
                "structural_stop": self._decision_snapshot.structural_stop,
                "structural_target": self._decision_snapshot.structural_target,
                "feature_count": len(self._decision_snapshot.feature_records),
                "liquidity_pool_count": len(self._decision_snapshot.liquidity_pools),
                "mtf_trace": self._decision_snapshot.mtf_trace,
            },
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serializes TradePassport state to JSON-compatible dictionary."""
        return {
            "passport_id": self._passport_id,
            "strategy_version": self._strategy_version,
            "schema_version": self._schema_version,
            "config_fingerprint": self._config_fingerprint,
            "thesis_id": self._thesis_id,
            "candidate_id": self._candidate_id,
            "symbol": self._symbol,
            "direction": self._direction.value,
            "candidate_timeframe": self._candidate_timeframe.name,
            "created_at": self._created_at,
            "outcome_state": self._outcome_state.value,
            "entry_touched": self._entry_touched,
            "entry_touch_ts": self._entry_touch_ts,
            "is_censored": self._is_censored,
            "censor_ts": self._censor_ts,
            "censor_reason": self._censor_reason,
            "decision_snapshot": {
                "thesis_id": self._decision_snapshot.thesis_id,
                "direction": self._decision_snapshot.direction.value,
                "candidate_id": self._decision_snapshot.candidate_id,
                "candidate_created_at": self._decision_snapshot.candidate_created_at,
                "candidate_timeframe": self._decision_snapshot.candidate_timeframe.name,
                "structural_entry": self._decision_snapshot.structural_entry,
                "structural_stop": self._decision_snapshot.structural_stop,
                "structural_target": self._decision_snapshot.structural_target,
                "mtf_trace": self._decision_snapshot.mtf_trace,
            },
            "pre_entry_path": [
                {
                    "observation_id": o.observation_id,
                    "passport_id": o.passport_id,
                    "timestamp_utc": o.timestamp_utc,
                    "timeframe": o.timeframe.name,
                    "open": o.open,
                    "high": o.high,
                    "low": o.low,
                    "close": o.close,
                    "source_candle_id": o.source_candle_id,
                }
                for o in self._pre_entry_path
            ],
            "post_entry_path": [
                {
                    "observation_id": o.observation_id,
                    "passport_id": o.passport_id,
                    "timestamp_utc": o.timestamp_utc,
                    "timeframe": o.timeframe.name,
                    "open": o.open,
                    "high": o.high,
                    "low": o.low,
                    "close": o.close,
                    "source_candle_id": o.source_candle_id,
                }
                for o in self._post_entry_path
            ],
            "events": [
                {
                    "event_id": e.event_id,
                    "passport_id": e.passport_id,
                    "event_type": e.event_type.value,
                    "timestamp_utc": e.timestamp_utc,
                    "metadata": e.metadata,
                }
                for e in self._events
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradePassport":
        """Reconstructs TradePassport from serialized dictionary."""
        snap_d = data["decision_snapshot"]
        snap = DecisionSnapshot(
            thesis_id=snap_d["thesis_id"],
            direction=ThesisDirection[snap_d["direction"]],
            candidate_id=snap_d["candidate_id"],
            candidate_created_at=snap_d["candidate_created_at"],
            candidate_timeframe=Timeframe[snap_d["candidate_timeframe"]],
            structural_entry=snap_d["structural_entry"],
            structural_stop=snap_d["structural_stop"],
            structural_target=snap_d.get("structural_target"),
            mtf_trace=snap_d.get("mtf_trace", {}),
        )

        passport = cls(
            passport_id=data["passport_id"],
            strategy_version=data["strategy_version"],
            schema_version=data["schema_version"],
            config_fingerprint=data["config_fingerprint"],
            thesis_id=data["thesis_id"],
            candidate_id=data["candidate_id"],
            symbol=data["symbol"],
            direction=ThesisDirection[data["direction"]],
            candidate_timeframe=Timeframe[data["candidate_timeframe"]],
            created_at=data["created_at"],
            decision_snapshot=snap,
        )

        passport._outcome_state = OutcomeState[data["outcome_state"]]
        passport._entry_touched = data.get("entry_touched", False)
        passport._entry_touch_ts = data.get("entry_touch_ts")
        passport._is_censored = data.get("is_censored", False)
        passport._censor_ts = data.get("censor_ts")
        passport._censor_reason = data.get("censor_reason", "")

        for po_data in data.get("pre_entry_path", []):
            po = PathObservation(
                observation_id=po_data["observation_id"],
                passport_id=po_data["passport_id"],
                timestamp_utc=po_data["timestamp_utc"],
                timeframe=Timeframe[po_data["timeframe"]],
                open=po_data["open"],
                high=po_data["high"],
                low=po_data["low"],
                close=po_data["close"],
                source_candle_id=po_data["source_candle_id"],
            )
            passport._pre_entry_path.append(po)
            passport._obs_ids.add(po.observation_id)

        for po_data in data.get("post_entry_path", []):
            po = PathObservation(
                observation_id=po_data["observation_id"],
                passport_id=po_data["passport_id"],
                timestamp_utc=po_data["timestamp_utc"],
                timeframe=Timeframe[po_data["timeframe"]],
                open=po_data["open"],
                high=po_data["high"],
                low=po_data["low"],
                close=po_data["close"],
                source_candle_id=po_data["source_candle_id"],
            )
            passport._post_entry_path.append(po)
            passport._obs_ids.add(po.observation_id)

        for ev_data in data.get("events", []):
            ev = PassportEvent(
                event_id=ev_data["event_id"],
                passport_id=ev_data["passport_id"],
                event_type=PassportEventType[ev_data["event_type"]],
                timestamp_utc=ev_data["timestamp_utc"],
                metadata=ev_data.get("metadata", {}),
            )
            if ev.event_id not in passport._event_ids:
                passport._events.append(ev)
                passport._event_ids.add(ev.event_id)

        return passport


def rebuild_passport_from_events(
    seed_data: Dict[str, Any],
    decision_snapshot: DecisionSnapshot,
    observations: List[PathObservation],
    events: List[PassportEvent],
) -> TradePassport:
    """Reconstructs TradePassport state machine deterministically from seed + snapshot + observations + events."""
    passport = TradePassport(
        passport_id=seed_data["passport_id"],
        strategy_version=seed_data.get("strategy_version", "V2.5"),
        schema_version=seed_data.get("schema_version", "2.5"),
        config_fingerprint=seed_data.get("config_fingerprint", "fp123"),
        thesis_id=seed_data["thesis_id"],
        candidate_id=seed_data["candidate_id"],
        symbol=seed_data.get("symbol", "XAUUSD"),
        direction=ThesisDirection[seed_data["direction"]],
        candidate_timeframe=Timeframe[seed_data.get("candidate_timeframe", "M5")],
        created_at=seed_data["created_at"],
        decision_snapshot=decision_snapshot,
    )

    # Replay observations chronologically
    sorted_obs = sorted(observations, key=lambda o: (o.timestamp_utc, o.observation_id))
    for obs in sorted_obs:
        passport.add_observation(obs)

    # Replay censor if present
    for ev in events:
        if ev.event_type == PassportEventType.CENSORED and not passport.is_censored:
            passport.censor(ev.timestamp_utc, ev.metadata.get("reason", ""))

    return passport
