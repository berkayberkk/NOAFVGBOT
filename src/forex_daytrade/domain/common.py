"""Shared validation helpers used across domain models.

Kept separate from `forex_daytrade.domain.validation` (which defines the
`ValidationReport` contract for dataset-level checks); this module holds
small per-field invariant checks reused by individual model constructors
(e.g. `Candle`, `Tick`).
"""

from __future__ import annotations

from datetime import datetime


def require_timezone_aware(value: datetime, error_type: type[Exception], field_name: str) -> None:
    """Raise `error_type` if `value` is a naive (timezone-unaware) datetime."""
    if value.tzinfo is None:
        raise error_type(f"{field_name} must be timezone-aware, got a naive datetime.")
