"""
NOAFVGBOT V2.7 — Counterfactual Research Domain Models.

Defines immutable scenario, result, pairwise comparison, and refinement geometry domain records
for comparing M30 control vs M5/M3 refined entries without hindsight leakage or thesis mutation.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, Optional, Tuple

from research.v2.data.models import Timeframe
from research.v2.core.thesis import ThesisDirection
from research.v2.telemetry.passport import OutcomeState


class ScenarioType(Enum):
    M30_CONTROL = "M30_CONTROL"
    M5_REFINED = "M5_REFINED"
    M3_REFINED = "M3_REFINED"


class SelectionPolicy(Enum):
    FIRST_BY_TIMESTAMP = "FIRST_BY_TIMESTAMP"
    FIRST_AVAILABLE = "FIRST_AVAILABLE"


@dataclass(frozen=True)
class RefinementGeometry:
    entry_improvement_absolute: float
    entry_improvement_pct_of_m30_risk: float
    risk_distance_change_absolute: float
    risk_distance_change_pct: float
    target_distance_change: float
    entry_delay_minutes: float


@dataclass(frozen=True)
class CounterfactualScenario:
    scenario_id: str
    thesis_id: str
    scenario_type: ScenarioType
    created_at: str
    reference_timestamp: str
    entry_timeframe: Timeframe
    structural_entry: float
    structural_stop: float
    structural_target: Optional[float] = None
    is_available: bool = True
    source_candidate_id: Optional[str] = None
    selection_policy: SelectionPolicy = SelectionPolicy.FIRST_BY_TIMESTAMP
    eligible_candidate_ids: Tuple[str, ...] = ()
    mtf_trace: Dict[str, str] = field(default_factory=dict)
    scenario_version: str = "2.7"

    def __post_init__(self) -> None:
        if self.is_available:
            if self.structural_entry <= 0 or self.structural_stop <= 0:
                raise ValueError("Structural entry and stop prices must be positive")
            if abs(self.structural_entry - self.structural_stop) < 1e-9:
                raise ValueError("Risk distance cannot be zero")


@dataclass(frozen=True)
class CounterfactualResult:
    scenario_id: str
    entry_touched: bool
    entry_touch_timestamp: Optional[str]
    outcome_state: OutcomeState
    gross_structural_r: Optional[float]
    mae_r: float
    mfe_r: float
    mae_absolute: float
    mfe_absolute: float
    bars_to_entry_touch: Optional[int] = None
    is_censored: bool = False
    is_ambiguous: bool = False


@dataclass(frozen=True)
class CounterfactualPair:
    pair_id: str
    thesis_id: str
    control_scenario_id: str
    experimental_scenario_id: str
    pair_state: str  # BOTH_TOUCHED, CONTROL_ONLY_TOUCHED, REFINED_ONLY_TOUCHED, NEITHER_TOUCHED, AMBIGUOUS
    delta_gross_structural_r: Optional[float]
    delta_mae_r: float
    delta_mfe_r: float
    delta_entry_touch: int  # 1 (exp only), -1 (ctrl only), 0 (both/neither)
    delta_risk_distance: float
    delta_time_to_entry_min: Optional[float]
    geometry: Optional[RefinementGeometry] = None
