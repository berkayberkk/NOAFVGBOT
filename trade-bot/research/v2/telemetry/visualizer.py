"""
NOAFVGBOT V2 — Trade Visualization Window Module.

Computes exact candle chart window bounds for TradePassport visualization, ensuring
complete coverage from pre-entry context (20 bars) through entry, full post-entry path,
and outcome timestamp (TP / SL / Ambiguous / Censored) plus post-outcome context (10 bars).

INVARIANTS:
- Does NOT alter strategy logic, TP/SL rules, or backtest outcome values.
- Guarantees 100% visibility of TP and SL exit candles on rendered chart windows.
- Consumes authoritative engine truth from TradePassport.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from research.v2.telemetry.passport import TradePassport, OutcomeState, PathObservation, ThesisDirection


@dataclass(frozen=True)
class RenderedChartWindow:
    passport_id: str
    direction: str
    candidate_timeframe: str
    created_at: str
    entry_touch_ts: Optional[str]
    outcome_ts: Optional[str]
    outcome_state: str
    structural_entry: float
    structural_stop: float
    structural_target: Optional[float]
    mae_r: float
    mfe_r: float
    candles: Tuple[PathObservation, ...]
    pre_entry_context_bars: int
    post_outcome_context_bars: int
    entry_candle_index: int
    outcome_candle_index: int
    tp_candle_visible: bool
    sl_candle_visible: bool

    def to_dict(self) -> Dict[str, Any]:
        """Serializes chart window metadata for chart rendering UI."""
        return {
            "passport_id": self.passport_id,
            "direction": self.direction,
            "candidate_timeframe": self.candidate_timeframe,
            "created_at": self.created_at,
            "entry_touch_ts": self.entry_touch_ts,
            "outcome_ts": self.outcome_ts,
            "outcome_state": self.outcome_state,
            "structural_entry": self.structural_entry,
            "structural_stop": self.structural_stop,
            "structural_target": self.structural_target,
            "mae_r": self.mae_r,
            "mfe_r": self.mfe_r,
            "candle_count": len(self.candles),
            "pre_entry_context_bars": self.pre_entry_context_bars,
            "post_outcome_context_bars": self.post_outcome_context_bars,
            "entry_candle_index": self.entry_candle_index,
            "outcome_candle_index": self.outcome_candle_index,
            "tp_candle_visible": self.tp_candle_visible,
            "sl_candle_visible": self.sl_candle_visible,
        }


def render_trade_chart_window(
    passport: TradePassport,
    full_market_path: List[PathObservation],
    pre_context: int = 20,
    post_context: int = 10,
) -> RenderedChartWindow:
    """Calculates exact chart window bounds ensuring complete trade lifecycle visibility."""
    all_obs = passport.pre_entry_path + passport.post_entry_path
    path_to_use = full_market_path if full_market_path else list(all_obs)

    if not path_to_use:
        raise ValueError(f"No market observations available for passport {passport.passport_id}")

    # Determine key timestamps from passport events
    entry_touch_ts = passport.entry_touch_ts
    outcome_ts: Optional[str] = None
    outcome_state_name = passport.outcome_state.value

    for ev in passport.events:
        if ev.event_type.value in ("TARGET_REACHED", "STOP_REACHED", "AMBIGUOUS_SAME_BAR", "CENSORED"):
            outcome_ts = ev.timestamp_utc
            break

    if not outcome_ts and passport.post_entry_path:
        outcome_ts = passport.post_entry_path[-1].timestamp_utc

    # Find candle indices in market path
    entry_idx = 0
    outcome_idx = len(path_to_use) - 1

    for i, obs in enumerate(path_to_use):
        if entry_touch_ts and obs.timestamp_utc == entry_touch_ts:
            entry_idx = i
        if outcome_ts and obs.timestamp_utc == outcome_ts:
            outcome_idx = i

    start_idx = max(0, entry_idx - pre_context)
    end_idx = min(len(path_to_use), outcome_idx + post_context + 1)

    window_candles = tuple(path_to_use[start_idx:end_idx])

    # Calculate index relative to window
    rel_entry_idx = entry_idx - start_idx
    rel_outcome_idx = outcome_idx - start_idx

    # Check TP / SL visibility on outcome candle
    snap = passport.decision_snapshot
    tp_visible = False
    sl_visible = False

    if 0 <= rel_outcome_idx < len(window_candles):
        out_obs = window_candles[rel_outcome_idx]
        if snap.structural_target is not None:
            if passport.direction == ThesisDirection.LONG:
                tp_visible = out_obs.high >= snap.structural_target
            else:
                tp_visible = out_obs.low <= snap.structural_target

        if passport.direction == ThesisDirection.LONG:
            sl_visible = out_obs.low <= snap.structural_stop
        else:
            sl_visible = out_obs.high >= snap.structural_stop

    # Calculate excursion metrics
    excursion = passport.get_excursion()

    return RenderedChartWindow(
        passport_id=passport.passport_id,
        direction=passport.direction.value,
        candidate_timeframe=passport.candidate_timeframe.name,
        created_at=passport.created_at,
        entry_touch_ts=entry_touch_ts,
        outcome_ts=outcome_ts,
        outcome_state=outcome_state_name,
        structural_entry=snap.structural_entry,
        structural_stop=snap.structural_stop,
        structural_target=snap.structural_target,
        mae_r=excursion.mae_r,
        mfe_r=excursion.mfe_r,
        candles=window_candles,
        pre_entry_context_bars=pre_context,
        post_outcome_context_bars=post_context,
        entry_candle_index=rel_entry_idx,
        outcome_candle_index=rel_outcome_idx,
        tp_candle_visible=tp_visible if passport.outcome_state == OutcomeState.TARGET_REACHED else False,
        sl_candle_visible=sl_visible if passport.outcome_state == OutcomeState.STOP_REACHED else False,
    )
