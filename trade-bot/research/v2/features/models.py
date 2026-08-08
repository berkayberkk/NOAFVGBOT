"""
NOAFVGBOT V2.4 — Feature Intelligence Base Models.

Defines the common FeatureRecord schema, decision-time vs post-event classification,
as-of availability validation, and ThesisEvidence conversion adapter.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, Optional

from research.v2.data.models import Timeframe
from research.v2.core.thesis import ThesisEvidence, EvidenceType


class FeaturePhase(Enum):
    DECISION_TIME = "DECISION_TIME"
    POST_EVENT = "POST_EVENT"


@dataclass(frozen=True)
class FeatureRecord:
    feature_id: str
    feature_type: str
    source_object_id: str
    source_timeframe: Timeframe
    timestamp_utc: str
    known_at_timestamp: str
    phase: FeaturePhase
    values: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    feature_version: str = "2.4"

    def __post_init__(self) -> None:
        # Validate JSON payload compatibility
        try:
            json.dumps(self.values)
            json.dumps(self.provenance)
        except Exception as e:
            raise ValueError(f"FeatureRecord values and provenance must be JSON-serializable: {e}")

        t_orig = datetime.fromisoformat(self.timestamp_utc).replace(tzinfo=timezone.utc)
        t_known = datetime.fromisoformat(self.known_at_timestamp).replace(tzinfo=timezone.utc)

        if t_known < t_orig:
            raise ValueError(f"known_at_timestamp ({self.known_at_timestamp}) cannot be < timestamp_utc ({self.timestamp_utc})")

    def to_thesis_evidence(self, thesis_id: str) -> ThesisEvidence:
        """Converts FeatureRecord into immutable ThesisEvidence record."""
        return ThesisEvidence(
            evidence_id=f"ev_feat_{self.feature_id}",
            thesis_id=thesis_id,
            timestamp_utc=self.known_at_timestamp,
            timeframe=self.source_timeframe,
            evidence_type=EvidenceType.M1_OBSERVATION,
            payload={
                "feature_id": self.feature_id,
                "feature_type": self.feature_type,
                "source_object_id": self.source_object_id,
                "phase": self.phase.value,
                "values": self.values,
                "provenance": self.provenance,
            },
            source_candle_close_timestamp=self.known_at_timestamp,
        )


def compute_feature_id(
    feature_type: str,
    source_object_id: str,
    source_timeframe: Timeframe,
    timestamp_utc: str,
) -> str:
    """Computes deterministic SHA256 feature ID."""
    raw = f"{feature_type}|{source_object_id}|{source_timeframe.name}|{timestamp_utc}"
    return "feat_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def validate_feature_availability(record: FeatureRecord, as_of_utc: str) -> bool:
    """Validates that record is observable as of as_of_utc (known_at_timestamp <= as_of_utc)."""
    t_known = datetime.fromisoformat(record.known_at_timestamp).replace(tzinfo=timezone.utc)
    t_as_of = datetime.fromisoformat(as_of_utc).replace(tzinfo=timezone.utc)
    return t_known <= t_as_of
