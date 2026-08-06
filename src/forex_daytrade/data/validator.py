"""Structured data-quality validation for normalized bar datasets.

`ERROR`-severity issues indicate corruption that should not occur in
legitimate MT5 data (duplicates, non-positive prices, inconsistent OHLC,
future timestamps). `WARNING`-severity issues (weekend bars, missing-bar
gaps, spread anomalies) are flagged for review but do not, by themselves,
indicate a broken dataset, since legitimate holiday gaps and wide spreads
do occur.

`IngestionValidationReport`/`IngestionValidationIssue` are the ingestion
pipeline's own report shape (per-dataset symbol/timeframe/total_rows,
per-issue count/sample_timestamps) — intentionally distinct from
`forex_daytrade.domain.validation.ValidationReport`/`ValidationIssue`,
which is the generic, dataset-identity-free contract other domain models
attach as their `validation_report` field. `Severity` itself has no
ingestion-specific meaning, so it is imported directly from the domain
layer rather than redeclared here.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from forex_daytrade.data.types import IngestionTimeframe
from forex_daytrade.domain.validation import Severity

logger = logging.getLogger(__name__)

_MAX_SAMPLE = 5


@dataclass(frozen=True)
class IngestionValidationIssue:
    check: str
    severity: Severity
    message: str
    count: int
    sample_timestamps: tuple[str, ...] = ()


@dataclass(frozen=True)
class IngestionValidationReport:
    symbol: str
    timeframe: str
    total_rows: int
    issues: tuple[IngestionValidationIssue, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity is Severity.ERROR for issue in self.issues)

    @property
    def errors(self) -> tuple[IngestionValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[IngestionValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.WARNING)


def _sample_timestamps(timestamps: pd.Series[Any], limit: int = _MAX_SAMPLE) -> tuple[str, ...]:
    return tuple(str(ts) for ts in timestamps.head(limit))


def check_empty(df: pd.DataFrame) -> IngestionValidationIssue | None:
    if len(df) == 0:
        return IngestionValidationIssue(
            check="empty_dataset",
            severity=Severity.ERROR,
            message="Dataset has zero rows.",
            count=0,
        )
    return None


def check_duplicate_timestamps(
    df: pd.DataFrame, timestamp_column: str = "timestamp_utc"
) -> IngestionValidationIssue | None:
    duplicated = df[timestamp_column].duplicated(keep=False)
    count = int(duplicated.sum())
    if count == 0:
        return None
    return IngestionValidationIssue(
        check="duplicate_timestamps",
        severity=Severity.ERROR,
        message=f"Found {count} rows with duplicate {timestamp_column} values.",
        count=count,
        sample_timestamps=_sample_timestamps(df.loc[duplicated, timestamp_column]),
    )


def check_negative_prices(df: pd.DataFrame) -> IngestionValidationIssue | None:
    price_columns = ["open", "high", "low", "close"]
    invalid = (df[price_columns] <= 0).any(axis=1)
    count = int(invalid.sum())
    if count == 0:
        return None
    return IngestionValidationIssue(
        check="negative_or_zero_prices",
        severity=Severity.ERROR,
        message=f"Found {count} rows with non-positive OHLC prices.",
        count=count,
        sample_timestamps=_sample_timestamps(df.loc[invalid, "timestamp_utc"]),
    )


def check_ohlc_consistency(df: pd.DataFrame) -> IngestionValidationIssue | None:
    high_ok = df["high"] >= df[["open", "close", "low"]].max(axis=1)
    low_ok = df["low"] <= df[["open", "close", "high"]].min(axis=1)
    invalid = ~(high_ok & low_ok)
    count = int(invalid.sum())
    if count == 0:
        return None
    return IngestionValidationIssue(
        check="ohlc_consistency",
        severity=Severity.ERROR,
        message=f"Found {count} rows where high/low do not bound open/close.",
        count=count,
        sample_timestamps=_sample_timestamps(df.loc[invalid, "timestamp_utc"]),
    )


def check_spread_anomalies(
    df: pd.DataFrame, max_spread_points: int = 200
) -> IngestionValidationIssue | None:
    if "spread" not in df.columns:
        return None
    invalid = (df["spread"] < 0) | (df["spread"] > max_spread_points)
    count = int(invalid.sum())
    if count == 0:
        return None
    return IngestionValidationIssue(
        check="spread_anomalies",
        severity=Severity.WARNING,
        message=f"Found {count} rows with spread outside [0, {max_spread_points}] points.",
        count=count,
        sample_timestamps=_sample_timestamps(df.loc[invalid, "timestamp_utc"]),
    )


def check_weekend_bars(
    df: pd.DataFrame, timestamp_column: str = "timestamp_utc"
) -> IngestionValidationIssue | None:
    weekday = df[timestamp_column].dt.weekday
    invalid = weekday.isin([5, 6])
    count = int(invalid.sum())
    if count == 0:
        return None
    return IngestionValidationIssue(
        check="weekend_bars",
        severity=Severity.WARNING,
        message=f"Found {count} bars timestamped on a Saturday or Sunday (UTC).",
        count=count,
        sample_timestamps=_sample_timestamps(df.loc[invalid, timestamp_column]),
    )


def check_future_timestamps(
    df: pd.DataFrame,
    timestamp_column: str = "timestamp_utc",
    now: datetime | None = None,
) -> IngestionValidationIssue | None:
    reference = now if now is not None else datetime.now(UTC)
    invalid = df[timestamp_column] > pd.Timestamp(reference)
    count = int(invalid.sum())
    if count == 0:
        return None
    return IngestionValidationIssue(
        check="future_timestamps",
        severity=Severity.ERROR,
        message=f"Found {count} bars timestamped after {reference.isoformat()}.",
        count=count,
        sample_timestamps=_sample_timestamps(df.loc[invalid, timestamp_column]),
    )


def check_missing_bars(
    df: pd.DataFrame, timeframe: IngestionTimeframe, timestamp_column: str = "timestamp_utc"
) -> IngestionValidationIssue | None:
    if len(df) < 2:
        return None
    ordered = df.sort_values(timestamp_column)
    gaps = ordered[timestamp_column].diff().dropna()
    expected = timeframe.timedelta

    weekday = ordered[timestamp_column].dt.weekday
    prev_weekday = weekday.shift(1)
    is_weekend_crossing = (prev_weekday == 4) & weekday.isin([0, 6])

    oversized = gaps > expected
    unexplained = oversized & ~is_weekend_crossing.loc[gaps.index]
    unexplained_gaps = gaps[unexplained]
    count = len(unexplained_gaps)
    if count == 0:
        return None
    return IngestionValidationIssue(
        check="missing_bars",
        severity=Severity.WARNING,
        message=f"Found {count} gaps larger than the expected {expected} bar interval.",
        count=count,
        sample_timestamps=_sample_timestamps(
            ordered.loc[unexplained_gaps.index, timestamp_column]
        ),
    )


def validate_dataset(
    df: pd.DataFrame,
    symbol: str,
    timeframe: IngestionTimeframe,
    *,
    now: datetime | None = None,
    max_spread_points: int = 200,
) -> IngestionValidationReport:
    """Run the full suite of data-quality checks over a normalized dataset."""
    checks: list[IngestionValidationIssue | None] = [check_empty(df)]
    if len(df) > 0:
        checks.extend(
            [
                check_duplicate_timestamps(df),
                check_negative_prices(df),
                check_ohlc_consistency(df),
                check_spread_anomalies(df, max_spread_points=max_spread_points),
                check_weekend_bars(df),
                check_future_timestamps(df, now=now),
                check_missing_bars(df, timeframe),
            ]
        )
    issues = tuple(issue for issue in checks if issue is not None)
    return IngestionValidationReport(
        symbol=symbol, timeframe=timeframe.value, total_rows=len(df), issues=issues
    )


def report_path(base_dir: Path, symbol: str, timeframe: str) -> Path:
    return base_dir / f"{symbol}_{timeframe}_validation.json"


def save_validation_report(report: IngestionValidationReport, base_dir: Path) -> Path:
    """Persist a validation report as JSON under `base_dir`, returning the path."""
    base_dir.mkdir(parents=True, exist_ok=True)
    path = report_path(base_dir, report.symbol, report.timeframe)
    payload: dict[str, Any] = {
        "symbol": report.symbol,
        "timeframe": report.timeframe,
        "total_rows": report.total_rows,
        "is_valid": report.is_valid,
        "issues": [
            {
                "check": issue.check,
                "severity": issue.severity.value,
                "message": issue.message,
                "count": issue.count,
                "sample_timestamps": list(issue.sample_timestamps),
            }
            for issue in report.issues
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Saved validation report", extra={"path": str(path), "is_valid": report.is_valid})
    return path
