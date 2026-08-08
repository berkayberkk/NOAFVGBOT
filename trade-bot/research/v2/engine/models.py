"""
NOAFVGBOT V2.8 — Engine Execution Config, Result, and Policy Interface Models.

Defines V2ExecutionConfig, ExecutionResult, BacktestV2Result, and policy interfaces
(MacroThesisPolicy, EntryCandidatePolicy, ReferenceResearchPolicy) for isolated historical simulation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple

from research.v2.data.models import CandleV2, Timeframe
from research.v2.core.thesis import ParentThesis, ChildEntryCandidate, ThesisDirection
from research.v2.counterfactual.models import CounterfactualPair
from research.v2.dataset.schema import ResearchRow


@dataclass(frozen=True)
class V2ExecutionConfig:
    spread: float = 0.30
    slippage: float = 0.10
    commission: float = 0.10


@dataclass(frozen=True)
class ExecutionResult:
    passport_id: str
    structural_entry: float
    executed_entry: float
    structural_exit: float
    executed_exit: float
    gross_price_pnl: float
    commission: float
    net_price_pnl: float
    risk_distance: float
    gross_r: float
    cost_r: float
    net_r: float


@dataclass(frozen=True)
class BacktestV2Result:
    fingerprint: str
    execution_config: V2ExecutionConfig
    total_events: int
    thesis_count: int
    candidate_count: int
    passport_count: int
    scenario_count: int
    structural_outcomes: Dict[str, int]
    execution_outcomes: Dict[str, int]
    counterfactual_pairs: List[CounterfactualPair]
    research_rows: List[ResearchRow]
    censored_count: int
    ambiguous_count: int
    engine_version: str = "2.8"
    policy_version: str = "2.8"


class MacroThesisPolicy(ABC):
    """Interface for proposing M30 ParentThesis seeds."""

    @abstractmethod
    def evaluate_m30(self, completed_candle: CandleV2, market_state: Dict[str, Any]) -> List[ParentThesis]:
        pass


class EntryCandidatePolicy(ABC):
    """Interface for creating ChildEntryCandidate setups on M5/M3 events."""

    @abstractmethod
    def evaluate_setup(
        self,
        completed_candle: CandleV2,
        active_theses: List[ParentThesis],
        market_state: Dict[str, Any],
    ) -> List[ChildEntryCandidate]:
        pass


class ReferenceResearchPolicy(MacroThesisPolicy, EntryCandidatePolicy):
    """Simple deterministic reference policy used for integration testing and engine verification."""

    def __init__(self, trigger_bar_count: int = 1):
        self.trigger_bar_count = trigger_bar_count

    def evaluate_m30(self, completed_candle: CandleV2, market_state: Dict[str, Any]) -> List[ParentThesis]:
        # Return empty list unless explicitly driven by test fixture
        return market_state.get("proposed_theses", [])

    def evaluate_setup(
        self,
        completed_candle: CandleV2,
        active_theses: List[ParentThesis],
        market_state: Dict[str, Any],
    ) -> List[ChildEntryCandidate]:
        # Return empty list unless explicitly driven by test fixture
        return market_state.get("proposed_candidates", [])
