"""
NOAFVGBOT V2.9 — TRAIN Research Policy Module.

Provides explicit, deterministic V2 TRAIN discovery research policy for evaluating
M30 macro theses, M15 confirmation context, and M5/M3 entry candidate refinements.

INVARIANTS:
- Uses pre-existing frozen V1 constants as REFERENCE_HYPOTHESIS_V1_DERIVED.
- NO arbitrary post-hoc parameter mining or hyperparameter search.
- Preserves 100% V1 strategy isolation (V1 files remain untouched).
"""

from typing import Any, Dict, List, Optional
from research.v2.data.models import CandleV2, Timeframe
from research.v2.core.thesis import (
    ParentThesis,
    ChildEntryCandidate,
    ThesisDirection,
    compute_thesis_id,
)
from research.v2.engine.models import ReferenceResearchPolicy


REFERENCE_HYPOTHESIS_V1_DERIVED = {
    "atr_period": 14,
    "fvg_min_points": 0.50,
    "ob_impulse_ratio": 1.5,
    "risk_reward_ratio": 2.0,
    "default_stop_points": 10.0,
}


class V2TrainResearchPolicy(ReferenceResearchPolicy):
    """Deterministic V2 TRAIN Discovery Policy for M30/M15/M5/M3 ablation research."""

    def __init__(self, config_fingerprint: str = "v1_derived_train_fp"):
        self.config_fingerprint = config_fingerprint

    def evaluate_m30(self, completed_candle: CandleV2, market_state: Dict[str, Any]) -> List[ParentThesis]:
        """Evaluates completed M30 candle for macro parent thesis creation."""
        theses: List[ParentThesis] = []

        # Bullish M30 condition: Close > Open by >= 1.0 point
        if completed_candle.close >= completed_candle.open + 1.0:
            tid = compute_thesis_id(
                "2.9",
                self.config_fingerprint,
                "XAUUSD",
                Timeframe.M30,
                completed_candle.timestamp_close_utc,
                ThesisDirection.LONG,
            )
            th = ParentThesis(
                thesis_id=tid,
                strategy_version="V2.9",
                schema_version="2.9",
                config_fingerprint=self.config_fingerprint,
                symbol="XAUUSD",
                direction=ThesisDirection.LONG,
                source_timeframe=Timeframe.M30,
                created_at=completed_candle.timestamp_close_utc,
            )
            theses.append(th)

        # Bearish M30 condition: Open > Close by >= 1.0 point
        elif completed_candle.open >= completed_candle.close + 1.0:
            tid = compute_thesis_id(
                "2.9",
                self.config_fingerprint,
                "XAUUSD",
                Timeframe.M30,
                completed_candle.timestamp_close_utc,
                ThesisDirection.SHORT,
            )
            th = ParentThesis(
                thesis_id=tid,
                strategy_version="V2.9",
                schema_version="2.9",
                config_fingerprint=self.config_fingerprint,
                symbol="XAUUSD",
                direction=ThesisDirection.SHORT,
                source_timeframe=Timeframe.M30,
                created_at=completed_candle.timestamp_close_utc,
            )
            theses.append(th)

        return theses

    def evaluate_setup(
        self,
        completed_candle: CandleV2,
        active_theses: List[ParentThesis],
        market_state: Dict[str, Any],
    ) -> List[ChildEntryCandidate]:
        """Evaluates lower timeframe (M5/M3) setup for entry candidate refinement."""
        candidates: List[ChildEntryCandidate] = []
        if not active_theses:
            return candidates

        for th in active_theses:
            cand_id = f"cand_{completed_candle.timeframe.name}_{th.thesis_id}_{completed_candle.timestamp_close_utc}"

            if th.direction == ThesisDirection.LONG:
                entry_p = completed_candle.close - 1.0
                stop_p = entry_p - 10.0
                target_p = entry_p + 20.0
            else:
                entry_p = completed_candle.close + 1.0
                stop_p = entry_p + 10.0
                target_p = entry_p - 20.0

            cand = ChildEntryCandidate(
                candidate_id=cand_id,
                thesis_id=th.thesis_id,
                created_at=completed_candle.timestamp_close_utc,
                timeframe=completed_candle.timeframe,
                direction=th.direction,
                structural_entry=entry_p,
                structural_stop=stop_p,
                structural_target=target_p,
            )
            candidates.append(cand)

        return candidates
