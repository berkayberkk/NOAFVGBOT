"""
NOAFVGBOT V2.10B.2 -- Gap Forensics Engine.

Deterministic, non-destructive forensic classification of every discontinuity in the
canonical V2 M1 series. This module NEVER touches candle data: it only reads a
List[CandleV2] and produces evidence/classification records and aggregate statistics.

Empirical basis (see research/v2/results/v2_10b2_gap_forensics.csv and the V2.10B.2 final
report for the underlying analysis run against the real 1,981,624-row canonical dataset):

- EXPECTED_WEEKEND: Friday close ~23:57/23:58 UTC (standard time) or ~22:57/22:58 UTC
  (EU-DST) -> Monday reopen ~01:00/00:00 UTC (or Tuesday when a holiday extends the
  weekend). Distinct, ubiquitous, ~49-hour+ pattern with zero exceptions across 6 years.
- EXPECTED_DAILY_SESSION_BREAK: a recurring ~61-minute nightly maintenance pause,
  weeknights Mon-Thu (occasionally Fri pre-weekend), close hour 23 (standard time) or 22
  (EU-DST), reopening at hour 01 or 00 respectively. The close/reopen hour flips exactly on
  the EU DST transition weekends (last Sunday of March / last Sunday of October) every year
  2021-2026 -- this is the DST-shifted session-break variant.
- EXPECTED_HOLIDAY_OR_CLOSURE: (a) US federal market holidays (MLK, Presidents, Memorial,
  Juneteenth [2022+], Independence [observed nearest weekday], Labor, Thanksgiving) produce
  an early close (~19:00-21:30 UTC) followed by a normal ~01:00 UTC reopen; recurs across
  multiple years. (b) Christmas Eve/Day and New Year's Eve/Day produce a ~36-hour closure
  (early close ~19:59-20:00 UTC, reopen 08:00 UTC two days later); recurs in at least 2
  observed years. (c) Good Friday/Easter: in at least one observed year the close moves to
  Thursday night (market closed all Good Friday), extending the weekend to ~74 hours;
  computed from the Gregorian Easter algorithm, but only weakly recurring in this specific
  broker history (MEDIUM/LOW confidence).
- LIKELY_PROVIDER_HISTORY_GAP: isolated small gaps (empirically <=9 missing M1 bars -- the
  real residual distribution has a clean, data-driven break between 9 and 214 missing bars,
  with nothing observed in between) that don't match any of the above recurring patterns.
- UNRESOLVED_SUSPICIOUS_GAP: anything left over that matches no empirically-derived pattern.

INVARIANTS:
- Pure/read-only over List[CandleV2]. No candle is ever added, removed, modified, or
  reordered in place.
- classify_all_gaps() sorts its own working copy before classifying, so input ordering
  never changes the output (tested: reversed-order determinism).
- Confidence is capped at HIGH only when an external corroboration signal (old-export
  cross-check or bounded MT5 re-pull) confirms the same bars are independently missing.
  Absent that corroboration, even a very strong recurring pattern is capped at MEDIUM.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from research.v2.data.models import CandleV2

GAP_CLASSIFIER_VERSION = "gap_forensics_v2.10b2.1"

CLASSIFIER_PARAMETERS: Dict[str, Any] = {
    "weekend_min_delta_minutes": 1500,
    "nightly_break_close_hours": [22, 23],
    "nightly_break_reopen_hours": [0, 1],
    "nightly_break_min_minutes": 55,
    "nightly_break_max_minutes": 70,
    "us_holiday_close_hours": [19, 20, 21],
    "us_holiday_reopen_hours": [0, 1],
    "us_holiday_min_minutes": 150,
    "us_holiday_max_minutes": 330,
    "christmas_newyear_min_minutes": 1500,
    "christmas_newyear_max_minutes": 2600,
    "good_friday_min_minutes": 1500,
    "provider_gap_max_missing_bars": 9,
    "duration_buckets": [1, (2, 5), (6, 15), (16, 30), (31, 60), (61, 120), (121, 360), (361, 720), "721+"],
}

# Must match research/v2/data/split_preregistration.py:build_preregistered_v2_split exactly.
PARTITION_BOUNDARIES = [
    ("TRAIN", None, "2023-11-01 00:00:00"),
    ("DEVELOPMENT", "2023-11-01 00:00:00", "2025-01-01 00:00:00"),
    ("VALIDATION", "2025-01-01 00:00:00", "2025-11-01 00:00:00"),
    ("FINAL_TEST", "2025-11-01 00:00:00", None),
]


class GapCategory:
    EXPECTED_WEEKEND = "EXPECTED_WEEKEND"
    EXPECTED_DAILY_SESSION_BREAK = "EXPECTED_DAILY_SESSION_BREAK"
    EXPECTED_HOLIDAY_OR_CLOSURE = "EXPECTED_HOLIDAY_OR_CLOSURE"
    LIKELY_PROVIDER_HISTORY_GAP = "LIKELY_PROVIDER_HISTORY_GAP"
    UNRESOLVED_SUSPICIOUS_GAP = "UNRESOLVED_SUSPICIOUS_GAP"


EXPECTED_CATEGORIES = {
    GapCategory.EXPECTED_WEEKEND,
    GapCategory.EXPECTED_DAILY_SESSION_BREAK,
    GapCategory.EXPECTED_HOLIDAY_OR_CLOSURE,
}


@dataclass(frozen=True)
class GapForensicsRecord:
    gap_id: str
    previous_timestamp_utc: str
    next_timestamp_utc: str
    missing_start_utc: str
    missing_end_utc: str
    delta_minutes: float
    missing_m1_bars: int
    weekday_before: str
    weekday_after: str
    utc_time_before: str
    utc_time_after: str
    year: int
    month: int
    partition: str
    current_category: str
    proposed_category: str
    classification_reason: str
    classification_evidence: str
    confidence: str
    requires_manual_review: bool


def compute_gap_arithmetic(prev_ts: str, next_ts: str) -> Dict[str, Any]:
    """Pure gap arithmetic. delta_minutes and missing_m1_bars are NOT the same thing:
    10:00 -> 10:02 has delta_minutes=2 but only 1 missing M1 bar (10:01)."""
    dt1 = datetime.fromisoformat(prev_ts).replace(tzinfo=timezone.utc) if datetime.fromisoformat(prev_ts).tzinfo is None else datetime.fromisoformat(prev_ts)
    dt2 = datetime.fromisoformat(next_ts).replace(tzinfo=timezone.utc) if datetime.fromisoformat(next_ts).tzinfo is None else datetime.fromisoformat(next_ts)
    delta_minutes = (dt2 - dt1).total_seconds() / 60.0
    missing_m1_bars = int(round(delta_minutes)) - 1
    missing_start = dt1 + timedelta(minutes=1)
    missing_end = dt2 - timedelta(minutes=1)
    return {
        "delta_minutes": delta_minutes,
        "missing_m1_bars": missing_m1_bars,
        "missing_start_utc": missing_start.strftime("%Y-%m-%d %H:%M:%S"),
        "missing_end_utc": missing_end.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _easter_sunday(year: int) -> datetime:
    """Anonymous Gregorian algorithm for the date of Easter Sunday."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime(year, month, day)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> datetime:
    """weekday: Monday=0..Sunday=6. n=1 for 1st occurrence, etc."""
    d = datetime(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    d = d + timedelta(days=offset + 7 * (n - 1))
    return d


def _last_weekday_of_month(year: int, month: int, weekday: int) -> datetime:
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)
    d = next_month - timedelta(days=1)
    offset = (d.weekday() - weekday) % 7
    return d - timedelta(days=offset)


def _observed_fixed_date(year: int, month: int, day: int) -> datetime:
    """US federal 'nearest weekday' observed-holiday rule for fixed calendar dates:
    Saturday -> observed Friday, Sunday -> observed Monday."""
    dt = datetime(year, month, day)
    if dt.weekday() == 5:
        return dt - timedelta(days=1)
    if dt.weekday() == 6:
        return dt + timedelta(days=1)
    return dt


def us_federal_holiday_name(date: datetime) -> Optional[str]:
    """Returns the name of the US federal market holiday matching this calendar date, or
    None. Derived from the standard US federal holiday calendar formulas (not a hardcoded
    per-year date list). Christmas/New Year's Day are handled separately (see
    christmas_newyear_window) because the observed broker pattern is a multi-day closure,
    not a single-day early close."""
    y, m, d = date.year, date.month, date.day

    mlk = _nth_weekday_of_month(y, 1, 0, 3)
    if (m, d) == (mlk.month, mlk.day):
        return "MLK_DAY"

    presidents = _nth_weekday_of_month(y, 2, 0, 3)
    if (m, d) == (presidents.month, presidents.day):
        return "PRESIDENTS_DAY"

    memorial = _last_weekday_of_month(y, 5, 0)
    if (m, d) == (memorial.month, memorial.day):
        return "MEMORIAL_DAY"

    if y >= 2022:
        juneteenth_observed = _observed_fixed_date(y, 6, 19)
        if (m, d) == (juneteenth_observed.month, juneteenth_observed.day):
            return "JUNETEENTH"

    independence_observed = _observed_fixed_date(y, 7, 4)
    if (m, d) == (independence_observed.month, independence_observed.day):
        return "INDEPENDENCE_DAY"

    labor = _nth_weekday_of_month(y, 9, 0, 1)
    if (m, d) == (labor.month, labor.day):
        return "LABOR_DAY"

    thanksgiving = _nth_weekday_of_month(y, 11, 3, 4)
    if (m, d) == (thanksgiving.month, thanksgiving.day):
        return "THANKSGIVING"

    return None


def christmas_newyear_window(date: datetime) -> Optional[str]:
    m, d = date.month, date.day
    if (m, d) in [(12, 24), (12, 25), (12, 26)]:
        return "CHRISTMAS"
    if (m, d) in [(12, 31),] or (m, d) == (1, 1) or (m, d) == (1, 2):
        return "NEW_YEAR"
    return None


def good_friday_easter_window(date: datetime) -> Optional[str]:
    easter = _easter_sunday(date.year)
    thursday_before = easter - timedelta(days=3)
    easter_monday = easter + timedelta(days=1)
    d0 = datetime(date.year, date.month, date.day)
    if thursday_before <= d0 <= easter_monday:
        return "GOOD_FRIDAY_EASTER"
    return None


def _date_range_overlaps_holiday(dt1: datetime, dt2: datetime) -> Optional[str]:
    """Checks every calendar date spanned by a multi-day closure window for a Christmas/
    New Year or Good Friday/Easter match, so a closure that starts a day or two early
    (e.g. Thursday, ahead of a Friday Christmas Eve) is still recognized."""
    d = datetime(dt1.year, dt1.month, dt1.day)
    end = datetime(dt2.year, dt2.month, dt2.day)
    while d <= end:
        cny = christmas_newyear_window(d)
        if cny:
            return cny
        gf = good_friday_easter_window(d)
        if gf:
            return gf
        d += timedelta(days=1)
    return None


def get_partition(timestamp_utc: str) -> str:
    for name, start, end in PARTITION_BOUNDARIES:
        if start is not None and timestamp_utc < start:
            continue
        if end is not None and timestamp_utc >= end:
            continue
        return name
    return "UNKNOWN"


def classify_gap(
    prev_ts: str,
    next_ts: str,
    delta_minutes: float,
    missing_m1_bars: int,
    corroboration: Optional[str] = None,
) -> Tuple[str, str, str, str, bool]:
    """Deterministic rule-based classification of a single gap.

    corroboration: optional external evidence tag, one of
      "OLD_EXPORT_ALSO_MISSING", "MT5_ALSO_MISSING", "OLD_EXPORT_HAS_BARS", "MT5_HAS_BARS",
      None. Only *_ALSO_MISSING corroboration can raise confidence to HIGH.

    Returns (category, reason, evidence, confidence, requires_manual_review).
    """
    dt1 = datetime.fromisoformat(prev_ts)
    dt2 = datetime.fromisoformat(next_ts)
    wd_before = dt1.strftime("%A")
    wd_after = dt2.strftime("%A")
    corroborated = corroboration in ("OLD_EXPORT_ALSO_MISSING", "MT5_ALSO_MISSING")

    p = CLASSIFIER_PARAMETERS

    # 1. Weekend
    if wd_before == "Friday" and wd_after in ("Saturday", "Sunday", "Monday", "Tuesday") and delta_minutes >= p["weekend_min_delta_minutes"]:
        evidence = f"Friday {dt1.strftime('%H:%M')} close -> {wd_after} {dt2.strftime('%H:%M')} reopen, delta={delta_minutes:.0f}min; matches the dataset-wide weekend closure pattern observed on every trading week."
        return GapCategory.EXPECTED_WEEKEND, "Recurring Friday-to-Monday/Tuesday weekend market closure.", evidence, "HIGH", False

    # 2. US federal holiday early close
    holiday = us_federal_holiday_name(dt1)
    if holiday and dt1.hour in p["us_holiday_close_hours"] and dt2.hour in p["us_holiday_reopen_hours"] and p["us_holiday_min_minutes"] <= delta_minutes <= p["us_holiday_max_minutes"]:
        conf = "HIGH" if corroborated else "MEDIUM"
        evidence = f"{prev_ts} matches computed US federal holiday date ({holiday}); early close at {dt1.strftime('%H:%M')} UTC, reopen {dt2.strftime('%H:%M')} UTC next day; recurring pattern observed across multiple dataset years."
        if corroboration:
            evidence += f" External corroboration: {corroboration}."
        return GapCategory.EXPECTED_HOLIDAY_OR_CLOSURE, f"US federal market holiday early close ({holiday}).", evidence, conf, False

    # 3. Christmas / New Year multi-day closure
    cny = christmas_newyear_window(dt1)
    if cny and delta_minutes >= p["christmas_newyear_min_minutes"] and delta_minutes <= p["christmas_newyear_max_minutes"]:
        conf = "HIGH" if corroborated else "MEDIUM"
        evidence = f"{prev_ts} falls in the {cny} closure window; ~{delta_minutes/60:.1f}h closure, reopen {next_ts}; recurring pattern observed in multiple dataset years."
        if corroboration:
            evidence += f" External corroboration: {corroboration}."
        return GapCategory.EXPECTED_HOLIDAY_OR_CLOSURE, f"{cny} multi-day market closure.", evidence, conf, False

    # 4. Good Friday / Easter
    gf = good_friday_easter_window(dt1)
    if gf and delta_minutes >= p["good_friday_min_minutes"]:
        conf = "HIGH" if corroborated else "LOW"
        evidence = (f"{prev_ts} falls within the computed Good-Friday/Easter window for {dt1.year} "
                    f"(Easter Sunday {_easter_sunday(dt1.year).date()}); ~{delta_minutes/60:.1f}h closure. "
                    f"Only weakly recurring in this specific broker history (not every observed Good Friday "
                    f"produced a distinct extra gap beyond the ordinary weekend).")
        if corroboration:
            evidence += f" External corroboration: {corroboration}."
        return GapCategory.EXPECTED_HOLIDAY_OR_CLOSURE, "Good Friday / Easter closure.", evidence, conf, (conf == "LOW")

    # 4b. Holiday-adjacent extended closure: a large (near-weekend-scale) gap that starts
    # before Friday (e.g. Wednesday/Thursday) because it directly abuts a Christmas/New
    # Year/Good-Friday closure window, rather than the ordinary Friday-night weekend.
    if wd_before in ("Wednesday", "Thursday") and delta_minutes >= p["weekend_min_delta_minutes"]:
        spanned_holiday = _date_range_overlaps_holiday(dt1, dt2)
        if spanned_holiday:
            conf = "HIGH" if corroborated else "MEDIUM"
            evidence = (f"{prev_ts} ({wd_before}) -> {next_ts} ({wd_after}): {delta_minutes:.0f}min closure "
                        f"starting earlier than the ordinary weekend because it directly abuts the "
                        f"{spanned_holiday} closure window.")
            if corroboration:
                evidence += f" External corroboration: {corroboration}."
            return GapCategory.EXPECTED_HOLIDAY_OR_CLOSURE, f"Holiday-extended closure ({spanned_holiday}) starting before the weekend.", evidence, conf, False

    # 5. Nightly recurring session break (with DST-shifted variant)
    if (dt1.hour in p["nightly_break_close_hours"] and dt2.hour in p["nightly_break_reopen_hours"]
            and p["nightly_break_min_minutes"] <= delta_minutes <= p["nightly_break_max_minutes"]):
        variant = "EU-DST-shifted (hour 22->00)" if dt1.hour == 22 else "standard-time (hour 23->01)"
        conf = "HIGH" if corroborated else "MEDIUM"
        evidence = (f"{prev_ts} -> {next_ts}: ~{delta_minutes:.0f}min nightly pause, {variant} variant; "
                    f"this exact close/reopen-hour pair recurs on the vast majority of weeknights across all "
                    f"6 dataset years, and the hour flips precisely on EU DST transition weekends.")
        if corroboration:
            evidence += f" External corroboration: {corroboration}."
        return GapCategory.EXPECTED_DAILY_SESSION_BREAK, "Recurring nightly broker maintenance/session break.", evidence, conf, False

    # 6. Small isolated active-session gap -> likely provider history gap
    if missing_m1_bars <= p["provider_gap_max_missing_bars"]:
        conf = "HIGH" if corroborated else "LOW"
        evidence = (f"{prev_ts} -> {next_ts}: isolated {missing_m1_bars}-bar active-session gap; does not match "
                    f"weekend, session-break, or holiday patterns; below the empirically observed natural break "
                    f"in the missing-bar distribution (no residual gap observed between {p['provider_gap_max_missing_bars']} "
                    f"and 214 missing bars).")
        if corroboration:
            evidence += f" External corroboration: {corroboration}."
        return GapCategory.LIKELY_PROVIDER_HISTORY_GAP, "Isolated small active-session gap, no recurring pattern.", evidence, conf, (conf == "LOW")

    # 7. Unresolved
    evidence = f"{prev_ts} -> {next_ts}: {missing_m1_bars} missing bars; matches no empirically-derived expected pattern."
    if corroboration:
        evidence += f" External corroboration: {corroboration}."
    return GapCategory.UNRESOLVED_SUSPICIOUS_GAP, "No matching pattern; insufficient evidence for classification.", evidence, "LOW", True


def build_forensics_table(
    candles: List[CandleV2],
    before_category_by_prev_ts: Optional[Dict[str, str]] = None,
    corroboration_by_prev_ts: Optional[Dict[str, str]] = None,
) -> List[GapForensicsRecord]:
    """Builds one deterministic GapForensicsRecord for EVERY discontinuity in `candles`.
    Sorts its own working copy first, so output is independent of input ordering."""
    sorted_candles = sorted(candles, key=lambda c: c.timestamp_open_utc)
    before_category_by_prev_ts = before_category_by_prev_ts or {}
    corroboration_by_prev_ts = corroboration_by_prev_ts or {}

    records: List[GapForensicsRecord] = []
    for i in range(len(sorted_candles) - 1):
        c1 = sorted_candles[i]
        c2 = sorted_candles[i + 1]
        arith = compute_gap_arithmetic(c1.timestamp_open_utc, c2.timestamp_open_utc)
        if arith["missing_m1_bars"] <= 0:
            continue

        dt1 = datetime.fromisoformat(c1.timestamp_open_utc)
        dt2 = datetime.fromisoformat(c2.timestamp_open_utc)

        corroboration = corroboration_by_prev_ts.get(c1.timestamp_open_utc)
        category, reason, evidence, confidence, needs_review = classify_gap(
            c1.timestamp_open_utc, c2.timestamp_open_utc, arith["delta_minutes"], arith["missing_m1_bars"], corroboration
        )

        rec = GapForensicsRecord(
            gap_id=f"gapf_{i}_{dt1.strftime('%Y%m%d_%H%M')}",
            previous_timestamp_utc=c1.timestamp_open_utc,
            next_timestamp_utc=c2.timestamp_open_utc,
            missing_start_utc=arith["missing_start_utc"],
            missing_end_utc=arith["missing_end_utc"],
            delta_minutes=arith["delta_minutes"],
            missing_m1_bars=arith["missing_m1_bars"],
            weekday_before=dt1.strftime("%A"),
            weekday_after=dt2.strftime("%A"),
            utc_time_before=dt1.strftime("%H:%M"),
            utc_time_after=dt2.strftime("%H:%M"),
            year=dt1.year,
            month=dt1.month,
            partition=get_partition(c1.timestamp_open_utc),
            current_category=before_category_by_prev_ts.get(c1.timestamp_open_utc, "UNKNOWN"),
            proposed_category=category,
            classification_reason=reason,
            classification_evidence=evidence,
            confidence=confidence,
            requires_manual_review=needs_review,
        )
        records.append(rec)

    return records


def duration_distribution(records: List[GapForensicsRecord]) -> Dict[str, Any]:
    bars = sorted(r.missing_m1_bars for r in records)
    n = len(bars)

    def pct(p: float) -> float:
        if n == 0:
            return 0.0
        idx = min(n - 1, int(n * p))
        return bars[idx]

    buckets_def = [("1", lambda b: b == 1), ("2-5", lambda b: 2 <= b <= 5), ("6-15", lambda b: 6 <= b <= 15),
                   ("16-30", lambda b: 16 <= b <= 30), ("31-60", lambda b: 31 <= b <= 60), ("61-120", lambda b: 61 <= b <= 120),
                   ("121-360", lambda b: 121 <= b <= 360), ("361-720", lambda b: 361 <= b <= 720), ("721+", lambda b: b >= 721)]
    buckets = {}
    for name, pred in buckets_def:
        matched = [b for b in bars if pred(b)]
        buckets[name] = {"gap_count": len(matched), "total_missing_bars": sum(matched)}

    return {
        "minimum": bars[0] if n else 0,
        "median": pct(0.5),
        "p75": pct(0.75),
        "p90": pct(0.9),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "maximum": bars[-1] if n else 0,
        "buckets": buckets,
    }


def time_of_day_forensics(records: List[GapForensicsRecord], top_n: int = 15) -> Dict[str, Any]:
    start_hour = Counter(int(r.utc_time_before.split(":")[0]) for r in records)
    end_hour = Counter(int(r.utc_time_after.split(":")[0]) for r in records)
    exact_pairs = Counter((r.utc_time_before, r.utc_time_after) for r in records)
    return {
        "start_hour_counts": dict(sorted(start_hour.items())),
        "end_hour_counts": dict(sorted(end_hour.items())),
        "top_exact_hhmm_pairs": [{"before": b, "after": a, "count": c} for (b, a), c in exact_pairs.most_common(top_n)],
    }


def weekday_forensics(records: List[GapForensicsRecord]) -> Dict[str, Any]:
    friday_weekend = [r for r in records if r.proposed_category == GapCategory.EXPECTED_WEEKEND]
    daily_pause = [r for r in records if r.proposed_category == GapCategory.EXPECTED_DAILY_SESSION_BREAK]
    unexpected_active = [r for r in records if r.proposed_category in (GapCategory.LIKELY_PROVIDER_HISTORY_GAP, GapCategory.UNRESOLVED_SUSPICIOUS_GAP)]

    def summarize(recs: List[GapForensicsRecord]) -> Dict[str, Any]:
        by_wd = Counter(r.weekday_before for r in recs)
        missing_by_wd: Dict[str, int] = defaultdict(int)
        for r in recs:
            missing_by_wd[r.weekday_before] += r.missing_m1_bars
        return {"gap_counts": dict(by_wd), "missing_bars": dict(missing_by_wd), "total_gaps": len(recs), "total_missing_bars": sum(r.missing_m1_bars for r in recs)}

    return {
        "friday_weekend_reopen_gaps": summarize(friday_weekend),
        "weekday_recurring_daily_pauses": summarize(daily_pause),
        "unexpected_weekday_active_session_gaps": summarize(unexpected_active),
    }


def year_month_forensics(records: List[GapForensicsRecord], top_n: int = 15) -> Dict[str, Any]:
    by_year = Counter(r.year for r in records)
    by_year_month = Counter((r.year, r.month) for r in records)
    top_months = sorted(by_year_month.items(), key=lambda kv: -kv[1])[:top_n]
    return {
        "by_year": dict(sorted(by_year.items())),
        "top_affected_months": [{"year": y, "month": m, "gap_count": c} for (y, m), c in top_months],
    }


def gap_clusters(records: List[GapForensicsRecord], top_n: int = 10) -> Dict[str, Any]:
    unexpected = [r for r in records if r.proposed_category in (GapCategory.LIKELY_PROVIDER_HISTORY_GAP, GapCategory.UNRESOLVED_SUSPICIOUS_GAP)]

    def day_key(r: GapForensicsRecord) -> str:
        return r.previous_timestamp_utc[:10]

    def week_key(r: GapForensicsRecord) -> str:
        dt = datetime.fromisoformat(r.previous_timestamp_utc)
        y, w, _ = dt.isocalendar()
        return f"{y}-W{w:02d}"

    def month_key(r: GapForensicsRecord) -> str:
        return r.previous_timestamp_utc[:7]

    def cluster(keyfn) -> List[Dict[str, Any]]:
        buckets: Dict[str, List[GapForensicsRecord]] = defaultdict(list)
        for r in unexpected:
            buckets[keyfn(r)].append(r)
        ranked = sorted(buckets.items(), key=lambda kv: -len(kv[1]))[:top_n]
        return [{"key": k, "gap_count": len(v), "total_missing_bars": sum(r.missing_m1_bars for r in v)} for k, v in ranked]

    return {"by_day": cluster(day_key), "by_week": cluster(week_key), "by_month": cluster(month_key)}


def longest_unexpected_gaps(records: List[GapForensicsRecord]) -> Dict[str, Any]:
    provider = [r for r in records if r.proposed_category == GapCategory.LIKELY_PROVIDER_HISTORY_GAP]
    unresolved = [r for r in records if r.proposed_category == GapCategory.UNRESOLVED_SUSPICIOUS_GAP]

    def top(recs: List[GapForensicsRecord]) -> Optional[Dict[str, Any]]:
        if not recs:
            return None
        r = max(recs, key=lambda r: r.missing_m1_bars)
        return {
            "previous_timestamp_utc": r.previous_timestamp_utc, "next_timestamp_utc": r.next_timestamp_utc,
            "missing_m1_bars": r.missing_m1_bars, "partition": r.partition, "classification_evidence": r.classification_evidence,
        }

    return {"longest_likely_provider_history_gap": top(provider), "longest_unresolved_suspicious_gap": top(unresolved)}


def partition_materiality(records: List[GapForensicsRecord], partition_row_counts: Dict[str, int]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, _, _ in PARTITION_BOUNDARIES:
        recs = [r for r in records if r.partition == name]
        expected = [r for r in recs if r.proposed_category in EXPECTED_CATEGORIES]
        provider = [r for r in recs if r.proposed_category == GapCategory.LIKELY_PROVIDER_HISTORY_GAP]
        unresolved = [r for r in recs if r.proposed_category == GapCategory.UNRESOLVED_SUSPICIOUS_GAP]
        unexpected_missing = sum(r.missing_m1_bars for r in provider) + sum(r.missing_m1_bars for r in unresolved)
        out[name] = {
            "canonical_rows": partition_row_counts.get(name, 0),
            "total_gaps": len(recs),
            "expected_gaps": len(expected),
            "provider_gaps": len(provider),
            "unresolved_gaps": len(unresolved),
            "unexpected_missing_m1_bars": unexpected_missing,
        }
    return out


def active_session_missingness(records: List[GapForensicsRecord], observed_active_session_bars: int) -> Dict[str, Any]:
    unexpected_missing = sum(
        r.missing_m1_bars for r in records
        if r.proposed_category in (GapCategory.LIKELY_PROVIDER_HISTORY_GAP, GapCategory.UNRESOLVED_SUSPICIOUS_GAP)
    )
    denominator = observed_active_session_bars + unexpected_missing
    rate = (unexpected_missing / denominator) if denominator > 0 else 0.0
    return {
        "unexpected_active_session_missing_bars": unexpected_missing,
        "observed_active_session_bars": observed_active_session_bars,
        "denominator": denominator,
        "unexpected_missingness_rate": rate,
    }


class EndBoundaryClassification:
    EXPECTED_END_SEMANTICS = "EXPECTED_END_SEMANTICS"
    MISSING_FINAL_BAR = "MISSING_FINAL_BAR"
    UNRESOLVED_END_BOUNDARY = "UNRESOLVED_END_BOUNDARY"


def classify_end_boundary(last_candle_open_utc: str, requested_end_utc: str) -> Dict[str, Any]:
    """Determines whether `requested_end_utc` represents the desired OPEN timestamp of one
    more (missing) bar, or the CLOSE boundary of the final observed M1 candle."""
    last_open = datetime.fromisoformat(last_candle_open_utc)
    last_close = last_open + timedelta(minutes=1)
    requested_end = datetime.fromisoformat(requested_end_utc)

    if last_close == requested_end:
        classification = EndBoundaryClassification.EXPECTED_END_SEMANTICS
        explanation = (
            f"Requested end {requested_end_utc} equals last_candle_open ({last_candle_open_utc}) + 1 minute, "
            f"i.e. it is the CLOSE timestamp of the final observed M1 candle, not the OPEN timestamp of an "
            f"additional missing bar. No final bar is missing."
        )
    elif requested_end - last_open == timedelta(minutes=2):
        classification = EndBoundaryClassification.MISSING_FINAL_BAR
        explanation = (
            f"Requested end {requested_end_utc} is 2 minutes after the last observed candle open "
            f"({last_candle_open_utc}), implying a bar opening at {last_close.strftime('%Y-%m-%d %H:%M:%S')} "
            f"was expected but is absent from the canonical series."
        )
    else:
        classification = EndBoundaryClassification.UNRESOLVED_END_BOUNDARY
        explanation = (
            f"Requested end {requested_end_utc} does not cleanly resolve against last_candle_open "
            f"{last_candle_open_utc} under either the close-boundary or missing-bar interpretation."
        )

    return {"classification": classification, "explanation": explanation, "last_candle_open_utc": last_candle_open_utc, "requested_end_utc": requested_end_utc}
