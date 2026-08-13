"""
NOAFVGBOT V2.DATA.2 — Gap Diagnostic Audit Module.

Provides comprehensive, non-destructive diagnostic classification and statistical review
of all intraday/session gaps in the historical XAUUSD M1 dataset.

INVARIANTS:
- Absolutely NO silent data repair, interpolation, or synthetic candle insertion.
- Classifies gaps into EXPECTED_WEEKEND, EXPECTED_DAILY_SESSION_BREAK, EXPECTED_HOLIDAY_OR_MARKET_CLOSURE,
  LIKELY_PROVIDER_HISTORY_GAP, SUSPICIOUS_INTRASESSION_GAP, UNKNOWN.
- Evaluates materiality without modifying market data.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
import json
import math
from typing import Any, Dict, List, Tuple, Optional

from research.v2.data.models import CandleV2, Timeframe


class DetailedGapCategory:
    EXPECTED_WEEKEND = "EXPECTED_WEEKEND"
    EXPECTED_DAILY_SESSION_BREAK = "EXPECTED_DAILY_SESSION_BREAK"
    EXPECTED_HOLIDAY_OR_CLOSURE = "EXPECTED_HOLIDAY_OR_CLOSURE"
    LIKELY_PROVIDER_HISTORY_GAP = "LIKELY_PROVIDER_HISTORY_GAP"
    SUSPICIOUS_INTRASESSION = "SUSPICIOUS_INTRASESSION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class GapDiagnosticRecord:
    gap_id: str
    prev_timestamp_utc: str
    next_timestamp_utc: str
    duration_seconds: float
    estimated_missing_m1_bars: int
    category: str
    weekday_name: str
    utc_hour: int
    prev_close: float
    next_open: float
    price_jump: float


@dataclass(frozen=True)
class GapAuditSummary:
    dataset_fingerprint: str
    total_gaps: int
    category_counts: Dict[str, int]
    missing_m1_by_category: Dict[str, int]
    median_duration_seconds: float
    p90_duration_seconds: float
    max_duration_seconds: float
    yearly_gap_counts: Dict[int, int]
    materiality_conclusion: str
    no_data_repair: bool = True
    unresolved_suspicious_gaps: int = 0


def audit_dataset_gaps(candles: List[CandleV2], dataset_fingerprint: str) -> Tuple[GapAuditSummary, List[GapDiagnosticRecord]]:
    """Performs non-destructive diagnostic analysis of all gaps in canonical M1 series."""
    if len(candles) < 2:
        empty_summary = GapAuditSummary(
            dataset_fingerprint=dataset_fingerprint,
            total_gaps=0,
            category_counts={},
            missing_m1_by_category={},
            median_duration_seconds=0.0,
            p90_duration_seconds=0.0,
            max_duration_seconds=0.0,
            yearly_gap_counts={},
            materiality_conclusion="PASS",
        )
        return empty_summary, []

    sorted_candles = sorted(candles, key=lambda c: c.timestamp_open_utc)
    records: List[GapDiagnosticRecord] = []

    category_counts: Dict[str, int] = {
        DetailedGapCategory.EXPECTED_WEEKEND: 0,
        DetailedGapCategory.EXPECTED_DAILY_SESSION_BREAK: 0,
        DetailedGapCategory.EXPECTED_HOLIDAY_OR_CLOSURE: 0,
        DetailedGapCategory.LIKELY_PROVIDER_HISTORY_GAP: 0,
        DetailedGapCategory.SUSPICIOUS_INTRASESSION: 0,
        DetailedGapCategory.UNKNOWN: 0,
    }

    missing_m1_counts: Dict[str, int] = {k: 0 for k in category_counts}
    yearly_counts: Dict[int, int] = {}
    durations: List[float] = []

    for i in range(len(sorted_candles) - 1):
        c1 = sorted_candles[i]
        c2 = sorted_candles[i + 1]

        dt1 = datetime.fromisoformat(c1.timestamp_open_utc).replace(tzinfo=timezone.utc)
        dt2 = datetime.fromisoformat(c2.timestamp_open_utc).replace(tzinfo=timezone.utc)

        diff_sec = (dt2 - dt1).total_seconds()
        if diff_sec <= 60:
            continue

        missing_bars = int(diff_sec // 60) - 1
        durations.append(diff_sec)

        yr = dt1.year
        yearly_counts[yr] = yearly_counts.get(yr, 0) + 1

        # Gap classification semantics
        # Weekend: Friday -> Sunday/Monday or >40 hrs gap
        is_weekend = (dt1.weekday() == 4 and dt2.weekday() in (6, 0)) or (diff_sec > 140000)

        # Daily session break: 21:00-23:00 UTC break (~1 hr)
        is_daily_break = (not is_weekend) and (3000 <= diff_sec <= 7200) and (dt1.hour in (21, 22))

        # Holiday or market closure: multi-hour break on Christmas/New Year or known holidays
        is_holiday = (not is_weekend) and (diff_sec > 7200) and ((dt1.month == 12 and dt1.day in (24, 25, 31)) or (dt1.month == 1 and dt1.day == 1))

        # Small intraday provider gap: < 15 minutes during trading session
        is_provider_gap = (not is_weekend) and (not is_daily_break) and (not is_holiday) and (diff_sec <= 900)

        if is_weekend:
            cat = DetailedGapCategory.EXPECTED_WEEKEND
        elif is_daily_break:
            cat = DetailedGapCategory.EXPECTED_DAILY_SESSION_BREAK
        elif is_holiday:
            cat = DetailedGapCategory.EXPECTED_HOLIDAY_OR_CLOSURE
        elif is_provider_gap:
            cat = DetailedGapCategory.LIKELY_PROVIDER_HISTORY_GAP
        else:
            cat = DetailedGapCategory.SUSPICIOUS_INTRASESSION

        category_counts[cat] += 1
        missing_m1_counts[cat] += missing_bars

        rec = GapDiagnosticRecord(
            gap_id=f"gap_{i}_{dt1.strftime('%Y%m%d_%H%M')}",
            prev_timestamp_utc=c1.timestamp_open_utc,
            next_timestamp_utc=c2.timestamp_open_utc,
            duration_seconds=diff_sec,
            estimated_missing_m1_bars=missing_bars,
            category=cat,
            weekday_name=dt1.strftime("%A"),
            utc_hour=dt1.hour,
            prev_close=c1.close,
            next_open=c2.open,
            price_jump=abs(c2.open - c1.close),
        )
        records.append(rec)

    durations.sort()
    n = len(durations)
    median_dur = durations[n // 2] if n > 0 else 0.0
    p90_dur = durations[int(n * 0.9)] if n > 0 else 0.0
    max_dur = durations[-1] if n > 0 else 0.0

    suspicious_count = category_counts[DetailedGapCategory.SUSPICIOUS_INTRASESSION]
    unknown_count = category_counts[DetailedGapCategory.UNKNOWN]
    unresolved_count = suspicious_count + unknown_count

    # V2.10B fix: materiality must reflect the actual computed counts, not a constant.
    # Weekend/daily-session/holiday/likely-provider-gap categories are structurally explained
    # (matched by an explicit rule) and are never, by themselves, grounds to withhold
    # ACCEPTABLE_DISCONTINUITIES. SUSPICIOUS_INTRASESSION/UNKNOWN gaps are NOT auto-classified
    # as expected — any unresolved count > 0 forces a review conclusion instead. No repair or
    # reclassification happens here; this only reports what the counts already show.
    if unresolved_count > 0:
        materiality = "UNRESOLVED_GAPS_REQUIRE_REVIEW"
    else:
        materiality = "ACCEPTABLE_DISCONTINUITIES"

    summary = GapAuditSummary(
        dataset_fingerprint=dataset_fingerprint,
        total_gaps=len(records),
        category_counts=category_counts,
        missing_m1_by_category=missing_m1_counts,
        median_duration_seconds=median_dur,
        p90_duration_seconds=p90_dur,
        max_duration_seconds=max_dur,
        yearly_gap_counts=yearly_counts,
        materiality_conclusion=materiality,
        no_data_repair=True,
        unresolved_suspicious_gaps=suspicious_count,
    )

    return summary, records
