"""Generic validation-report contract for the domain layer.

Distinct from `forex_daytrade.data.validator.IngestionValidationReport`,
which is the data layer's pandas-based, dataset-quality-check-specific
report (symbol/timeframe/total_rows, per-issue count/sample_timestamps).
This is the pandas-free, general-purpose contract other domain models
attach as their `validation_report` field (see `market_data.py`).
`Severity` itself, unlike the report shape, is fully shared — the data
layer imports it from here directly rather than redeclaring it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class Severity(StrEnum):
    """Severity of a single validation issue."""

    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A single validation finding."""

    check: str
    severity: Severity
    message: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Aggregate validation result: issues plus arbitrary summary statistics."""

    issues: tuple[ValidationIssue, ...] = ()
    statistics: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        """Issues at `Severity.ERROR`."""
        return tuple(issue for issue in self.issues if issue.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        """Issues at `Severity.WARNING`."""
        return tuple(issue for issue in self.issues if issue.severity is Severity.WARNING)

    @property
    def is_valid(self) -> bool:
        """Whether the report contains no `Severity.ERROR` issues."""
        return len(self.errors) == 0
