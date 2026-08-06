"""Unit tests for forex_daytrade.domain.common."""

from datetime import UTC, datetime

import pytest

from forex_daytrade.domain.common import require_timezone_aware


def test_aware_datetime_passes() -> None:
    require_timezone_aware(datetime(2026, 1, 5, tzinfo=UTC), ValueError, "field")


def test_naive_datetime_raises_given_error_type() -> None:
    with pytest.raises(ValueError, match="field must be timezone-aware"):
        require_timezone_aware(datetime(2026, 1, 5), ValueError, "field")


def test_uses_provided_error_type() -> None:
    class CustomError(Exception):
        pass

    with pytest.raises(CustomError):
        require_timezone_aware(datetime(2026, 1, 5), CustomError, "field")
