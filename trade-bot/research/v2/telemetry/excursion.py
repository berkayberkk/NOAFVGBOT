"""
NOAFVGBOT V2.5 — Path Observation & Excursion (MAE/MFE) Telemetry.

Provides deterministic calculation of Maximum Adverse Excursion (MAE) and Maximum
Favorable Excursion (MFE) as-of any requested observation timestamp.

INVARIANTS:
- Reference price is structural_entry (no broker fill simulation in V2.5).
- MAE >= 0 and MFE >= 0 clamped.
- R-normalization uses structural risk distance abs(entry - stop).
- As-of queries exclude future observations strictly.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import List, Optional

from research.v2.data.models import Timeframe
from research.v2.core.thesis import ThesisDirection


@dataclass(frozen=True)
class PathObservation:
    observation_id: str
    passport_id: str
    timestamp_utc: str
    timeframe: Timeframe
    open: float
    high: float
    low: float
    close: float
    source_candle_id: str

    def __post_init__(self) -> None:
        for field_name, val in [("open", self.open), ("high", self.high), ("low", self.low), ("close", self.close)]:
            if not math.isfinite(val) or val <= 0:
                raise ValueError(f"PathObservation {field_name} must be positive, got: {val}")

        max_oc = max(self.open, self.close)
        min_oc = min(self.open, self.close)
        if self.high < max_oc - 1e-9:
            raise ValueError(f"PathObservation high ({self.high}) cannot be < max(open, close) ({max_oc})")
        if self.low > min_oc + 1e-9:
            raise ValueError(f"PathObservation low ({self.low}) cannot be > min(open, close) ({min_oc})")


@dataclass(frozen=True)
class ExcursionMetrics:
    mae_absolute: float
    mae_r: float
    mae_timestamp: Optional[str]
    mfe_absolute: float
    mfe_r: float
    mfe_timestamp: Optional[str]
    initial_risk_distance: float
    reference_price: float
    reference_type: str = "STRUCTURAL_ENTRY"


def calculate_excursion_as_of(
    reference_price: float,
    direction: ThesisDirection,
    risk_distance: float,
    observations: List[PathObservation],
    as_of_utc: str,
) -> ExcursionMetrics:
    """Calculates MAE and MFE deterministically as-of as_of_utc."""
    if reference_price <= 0:
        raise ValueError(f"Reference price must be positive, got: {reference_price}")
    if risk_distance < 0:
        raise ValueError(f"Risk distance cannot be negative, got: {risk_distance}")

    # V2.10C.2 -- fast path, performance only. `observations` is always chronologically
    # non-decreasing (both current callers -- TradePassport.get_excursion()'s post_entry_path,
    # and evaluate_scenario()'s post_entry_obs -- build it that way), so whenever as_of_utc is
    # at/after the last observation's own timestamp, EVERY observation already satisfies
    # "<= as_of_utc" and the filter is a guaranteed no-op. Both current callers hit this path
    # every time (get_excursion()'s default as_of IS the last post-entry observation;
    # evaluate_scenario() passes exactly valid_obs[-1]). Falls back to the original exact
    # per-observation datetime filter, unchanged, whenever as_of_utc is strictly earlier.
    if not observations:
        valid_obs = observations
    elif as_of_utc >= observations[-1].timestamp_utc:
        valid_obs = observations
    else:
        t_as_of = datetime.fromisoformat(as_of_utc).replace(tzinfo=timezone.utc)
        valid_obs = [
            o for o in observations
            if datetime.fromisoformat(o.timestamp_utc).replace(tzinfo=timezone.utc) <= t_as_of
        ]

    if not valid_obs:
        return ExcursionMetrics(
            mae_absolute=0.0,
            mae_r=0.0,
            mae_timestamp=None,
            mfe_absolute=0.0,
            mfe_r=0.0,
            mfe_timestamp=None,
            initial_risk_distance=risk_distance,
            reference_price=reference_price,
        )

    mae_abs = 0.0
    mae_ts: Optional[str] = None
    mfe_abs = 0.0
    mfe_ts: Optional[str] = None

    for obs in valid_obs:
        if direction == ThesisDirection.LONG:
            # Adverse = price below reference
            adverse = max(0.0, reference_price - obs.low)
            if adverse > mae_abs:
                mae_abs = adverse
                mae_ts = obs.timestamp_utc

            # Favorable = price above reference
            favorable = max(0.0, obs.high - reference_price)
            if favorable > mfe_abs:
                mfe_abs = favorable
                mfe_ts = obs.timestamp_utc

        else:  # SHORT
            # Adverse = price above reference
            adverse = max(0.0, obs.high - reference_price)
            if adverse > mae_abs:
                mae_abs = adverse
                mae_ts = obs.timestamp_utc

            # Favorable = price below reference
            favorable = max(0.0, reference_price - obs.low)
            if favorable > mfe_abs:
                mfe_abs = favorable
                mfe_ts = obs.timestamp_utc

    mae_r = (mae_abs / risk_distance) if risk_distance > 0 else 0.0
    mfe_r = (mfe_abs / risk_distance) if risk_distance > 0 else 0.0

    return ExcursionMetrics(
        mae_absolute=mae_abs,
        mae_r=mae_r,
        mae_timestamp=mae_ts,
        mfe_absolute=mfe_abs,
        mfe_r=mfe_r,
        mfe_timestamp=mfe_ts,
        initial_risk_distance=risk_distance,
        reference_price=reference_price,
    )
