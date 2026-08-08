"""
NOAFVGBOT V2.DATA.1 — Scientific Data Quality Audit Module.

Provides comprehensive, non-destructive quality auditing for historical XAUUSD M1 data:
OHLC invariant validation, non-finite/non-positive price detection, duplicate classification
(exact vs conflicting), market session / weekend / intraday gap classification, and extreme move diagnostics.

INVARIANTS:
- No silent data repair, interpolation, or synthetic candle insertion.
- Malformed OHLC or conflicting duplicates result in FAIL.
- Weekend/daily session breaks are classified separately from suspicious intraday gaps.
- Extreme moves are diagnostic warnings only and are NEVER deleted.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, List, Optional, Tuple

from research.v2.data.models import CandleV2, Timeframe


class AuditStatus(Enum if 'Enum' in globals() else object):
    pass

from enum import Enum

class DataQualityStatus(Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


class GapCategory(Enum):
    NORMAL_CONTINUOUS = "NORMAL_CONTINUOUS"
    DAILY_SESSION_BREAK = "DAILY_SESSION_BREAK"
    WEEKEND_SESSION_BREAK = "WEEKEND_SESSION_BREAK"
    HOLIDAY_OR_CLOSURE = "HOLIDAY_OR_CLOSURE"
    SUSPICIOUS_INTRASESSION = "SUSPICIOUS_INTRASESSION"
    UNKNOWN_GAP = "UNKNOWN_GAP"


@dataclass(frozen=True)
class GapInfo:
    prev_timestamp: str
    next_timestamp: str
    duration_seconds: float
    estimated_missing_m1_count: int
    category: GapCategory


@dataclass(frozen=True)
class AuditIssue:
    issue_type: str
    severity: str  # "FAIL" or "WARNING"
    description: str
    timestamp_utc: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataAuditReport:
    quality_status: DataQualityStatus
    total_candles: int
    earliest_timestamp: str
    latest_timestamp: str
    raw_row_count: int
    canonical_row_count: int
    exact_duplicates_removed: int
    conflicting_duplicates_count: int
    ohlc_violations_count: int
    non_finite_values_count: int
    non_positive_values_count: int
    weekend_gaps_count: int
    daily_break_gaps_count: int
    suspicious_intraday_gaps_count: int
    extreme_move_warnings_count: int
    issues: Tuple[AuditIssue, ...] = ()
    gaps: Tuple[GapInfo, ...] = ()


def audit_candle_ohlc(c: Any) -> List[AuditIssue]:
    """Audits OHLC invariants for a single candle (CandleV2 or raw dict)."""
    issues: List[AuditIssue] = []

    if isinstance(c, dict):
        ts_open = c.get("timestamp_open_utc", str(c.get("time", "")))
        open_p = float(c.get("open", 0.0))
        high_p = float(c.get("high", 0.0))
        low_p = float(c.get("low", 0.0))
        close_p = float(c.get("close", 0.0))
    else:
        ts_open = c.timestamp_open_utc
        open_p = c.open
        high_p = c.high
        low_p = c.low
        close_p = c.close

    # Non-finite check
    for field_name, val in [("open", open_p), ("high", high_p), ("low", low_p), ("close", close_p)]:
        if not math.isfinite(val):
            issues.append(AuditIssue("NON_FINITE_PRICE", "FAIL", f"{field_name} is non-finite: {val}", ts_open))
        elif val <= 0:
            issues.append(AuditIssue("NON_POSITIVE_PRICE", "FAIL", f"{field_name} is non-positive: {val}", ts_open))

    # OHLC Invariants
    if math.isfinite(open_p) and math.isfinite(high_p) and math.isfinite(low_p) and math.isfinite(close_p):
        max_oc = max(open_p, close_p)
        min_oc = min(open_p, close_p)
        if high_p < max_oc - 1e-9:
            issues.append(AuditIssue("HIGH_LESS_THAN_MAX_OC", "FAIL", f"High ({high_p}) < max(open, close) ({max_oc})", ts_open))
        if low_p > min_oc + 1e-9:
            issues.append(AuditIssue("LOW_GREATER_THAN_MIN_OC", "FAIL", f"Low ({low_p}) > min(open, close) ({min_oc})", ts_open))
        if high_p < low_p - 1e-9:
            issues.append(AuditIssue("HIGH_LESS_THAN_LOW", "FAIL", f"High ({high_p}) < Low ({low_p})", ts_open))

    return issues


def classify_gaps(candles: List[CandleV2]) -> Tuple[List[GapInfo], List[AuditIssue]]:
    """Classifies timestamp gaps into weekend breaks, daily session breaks, and suspicious intraday gaps."""
    gaps: List[GapInfo] = []
    issues: List[AuditIssue] = []

    if len(candles) < 2:
        return gaps, issues

    for i in range(len(candles) - 1):
        c1 = candles[i]
        c2 = candles[i + 1]

        dt1 = datetime.fromisoformat(c1.timestamp_open_utc).replace(tzinfo=timezone.utc)
        dt2 = datetime.fromisoformat(c2.timestamp_open_utc).replace(tzinfo=timezone.utc)

        diff_sec = (dt2 - dt1).total_seconds()
        if diff_sec <= 60:
            continue

        missing_bars = int(diff_sec // 60) - 1

        # Check weekend: dt1 is Friday (4) or dt2 is Sunday (6) / Monday (0)
        is_weekend = (dt1.weekday() == 4 and dt2.weekday() in (6, 0)) or (dt2 - dt1 > timedelta(hours=40))

        # Check daily session break: ~1 hour break between 22:00 UTC and 23:00 UTC
        is_daily_break = (not is_weekend) and (3000 <= diff_sec <= 7200) and (dt1.hour == 21 or dt1.hour == 22)

        if is_weekend:
            cat = GapCategory.WEEKEND_SESSION_BREAK
        elif is_daily_break:
            cat = GapCategory.DAILY_SESSION_BREAK
        else:
            cat = GapCategory.SUSPICIOUS_INTRASESSION
            issues.append(AuditIssue("SUSPICIOUS_INTRADAY_GAP", "WARNING", f"Suspicious gap of {missing_bars} missing M1 bars between {c1.timestamp_open_utc} and {c2.timestamp_open_utc}", c1.timestamp_open_utc))

        gaps.append(GapInfo(c1.timestamp_open_utc, c2.timestamp_open_utc, diff_sec, missing_bars, cat))

    return gaps, issues


def audit_m1_dataset(candles: List[CandleV2], raw_row_count: Optional[int] = None) -> DataAuditReport:
    """Performs full non-destructive quality audit on canonical M1 candle series."""
    if not candles:
        return DataAuditReport(
            quality_status=DataQualityStatus.FAIL,
            total_candles=0,
            earliest_timestamp="",
            latest_timestamp="",
            raw_row_count=raw_row_count or 0,
            canonical_row_count=0,
            exact_duplicates_removed=0,
            conflicting_duplicates_count=0,
            ohlc_violations_count=0,
            non_finite_values_count=0,
            non_positive_values_count=0,
            weekend_gaps_count=0,
            daily_break_gaps_count=0,
            suspicious_intraday_gaps_count=0,
            extreme_move_warnings_count=0,
            issues=(AuditIssue("EMPTY_DATASET", "FAIL", "Candle series is empty"),),
            gaps=(),
        )

    all_issues: List[AuditIssue] = []

    # Sort candles chronologically for audit
    sorted_candles = sorted(candles, key=lambda c: c.timestamp_open_utc)

    # 1. Audit individual candle OHLC
    ohlc_violations = 0
    non_finite_count = 0
    non_positive_count = 0

    for c in sorted_candles:
        c_issues = audit_candle_ohlc(c)
        all_issues.extend(c_issues)
        for iss in c_issues:
            if "NON_FINITE" in iss.issue_type:
                non_finite_count += 1
            elif "NON_POSITIVE" in iss.issue_type:
                non_positive_count += 1
            else:
                ohlc_violations += 1

    # 2. Check duplicates & monotonicity
    seen_ts: Dict[str, CandleV2] = {}
    exact_dups = 0
    conflicting_dups = 0

    for c in candles:
        ts = c.timestamp_open_utc
        if ts in seen_ts:
            prev = seen_ts[ts]
            if (prev.open == c.open and prev.high == c.high and prev.low == c.low and prev.close == c.close):
                exact_dups += 1
            else:
                conflicting_dups += 1
                all_issues.append(AuditIssue("CONFLICTING_DUPLICATE", "FAIL", f"Conflicting OHLC duplicate for timestamp {ts}", ts))
        else:
            seen_ts[ts] = c

    # 3. Classify Gaps
    gaps, gap_issues = classify_gaps(sorted_candles)
    all_issues.extend(gap_issues)

    weekend_gaps = sum(1 for g in gaps if g.category == GapCategory.WEEKEND_SESSION_BREAK)
    daily_gaps = sum(1 for g in gaps if g.category == GapCategory.DAILY_SESSION_BREAK)
    suspicious_gaps = sum(1 for g in gaps if g.category == GapCategory.SUSPICIOUS_INTRASESSION)

    # 4. Diagnostic Extreme Move Detection (Range > 15.0 points on M1)
    extreme_move_count = 0
    for c in sorted_candles:
        rng = c.high - c.low
        if rng > 15.0:
            extreme_move_count += 1
            all_issues.append(AuditIssue("EXTREME_CANDLE_RANGE", "WARNING", f"Extreme M1 range ({rng:.2f} pts) at {c.timestamp_open_utc}", c.timestamp_open_utc))

    # Overall Status Determination
    status = DataQualityStatus.PASS
    has_fail = any(i.severity == "FAIL" for i in all_issues)
    has_warning = any(i.severity == "WARNING" for i in all_issues)

    if has_fail:
        status = DataQualityStatus.FAIL
    elif has_warning:
        status = DataQualityStatus.WARNING

    return DataAuditReport(
        quality_status=status,
        total_candles=len(sorted_candles),
        earliest_timestamp=sorted_candles[0].timestamp_open_utc,
        latest_timestamp=sorted_candles[-1].timestamp_open_utc,
        raw_row_count=raw_row_count or len(candles),
        canonical_row_count=len(sorted_candles),
        exact_duplicates_removed=exact_dups,
        conflicting_duplicates_count=conflicting_dups,
        ohlc_violations_count=ohlc_violations,
        non_finite_values_count=non_finite_count,
        non_positive_values_count=non_positive_count,
        weekend_gaps_count=weekend_gaps,
        daily_break_gaps_count=daily_gaps,
        suspicious_intraday_gaps_count=suspicious_gaps,
        extreme_move_warnings_count=extreme_move_count,
        issues=tuple(all_issues),
        gaps=tuple(gaps),
    )
