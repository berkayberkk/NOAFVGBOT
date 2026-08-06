"""Canonical trading-session label enum for the domain layer.

`TradingSession` is the single source of truth for session labels: the
data layer's `forex_daytrade.data.sessions.classify_sessions` imports and
returns these values directly rather than maintaining its own copy — see
ARCHITECTURE.md's Domain Layer section. This module contains no
session-detection logic, only the label contract itself.
"""

from __future__ import annotations

from enum import StrEnum


class TradingSession(StrEnum):
    """Trading session classification for a point in time."""

    ASIAN = "asian"
    LONDON = "london"
    NEW_YORK = "new_york"
    LONDON_NEW_YORK_OVERLAP = "london_newyork_overlap"
    ROLLOVER = "rollover"
    OFF_SESSION = "off_session"
