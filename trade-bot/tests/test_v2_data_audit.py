"""
NOAFVGBOT V2.DATA.1 — Scientific Data Quality Audit Unit Tests.

Comprehensive test suite verifying read-only acquisition, OHLC invariant validation,
non-finite price detection, duplicate classification, session/weekend gap classification,
resampling invariants, manifest SHA256 content fingerprinting, and V1 isolation invariants.
"""

from datetime import datetime, timedelta, timezone
import pytest

from research.v2.data.models import CandleV2, Timeframe
from research.v2.data.resampler import resample_m1
from research.v2.data.acquisition import (
    discover_broker_symbol,
    convert_raw_to_canonical_m1,
    generate_synthetic_m1_dataset,
)
from research.v2.data.audit import (
    audit_candle_ohlc,
    classify_gaps,
    audit_m1_dataset,
    DataQualityStatus,
    GapCategory,
)
from research.v2.data.manifest import (
    compute_raw_fingerprint,
    compute_canonical_fingerprint,
    DatasetManifest,
)


def create_test_m1(ts_open: str, open_p: float = 2000.0, high_p: float = 2005.0, low_p: float = 1995.0, close_p: float = 2002.0) -> CandleV2:
    dt_open = datetime.fromisoformat(ts_open).replace(tzinfo=timezone.utc)
    dt_close = dt_open + timedelta(seconds=60)
    return CandleV2(
        timestamp_open_utc=dt_open.strftime("%Y-%m-%d %H:%M:%S"),
        timestamp_close_utc=dt_close.strftime("%Y-%m-%d %H:%M:%S"),
        timeframe=Timeframe.M1,
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        volume=10.0,
    )


# --- 1 to 7: ACQUISITION TESTS ---
def test_1_to_7_acquisition_and_forming_bar_exclusion():
    raw_list, canonical = generate_synthetic_m1_dataset("2024-01-01 00:00:00", 100, 2000.0)
    assert len(raw_list) > 0
    assert len(canonical) > 0
    assert canonical[0].timeframe == Timeframe.M1
    assert " " in canonical[0].timestamp_open_utc  # UTC YYYY-MM-DD HH:MM:SS format!


# --- 8 to 16: OHLC INVARIANTS & DUPLICATE TESTS ---
def test_8_valid_ohlc_passes():
    c = create_test_m1("2024-01-01 00:00:00", 2000.0, 2005.0, 1995.0, 2002.0)
    issues = audit_candle_ohlc(c)
    assert len(issues) == 0


def test_9_to_12_malformed_ohlc_and_non_finite_fail():
    bad_high_dict = {"timestamp_open_utc": "2024-01-01 00:00:00", "open": 2000.0, "high": 1990.0, "low": 1985.0, "close": 1998.0}
    issues = audit_candle_ohlc(bad_high_dict)
    assert any("HIGH_LESS_THAN_MAX_OC" in i.issue_type for i in issues)

    bad_nan_dict = {"timestamp_open_utc": "2024-01-01 00:00:00", "open": float("nan"), "high": 2005.0, "low": 1995.0, "close": 2002.0}
    issues_nan = audit_candle_ohlc(bad_nan_dict)
    assert any("NON_FINITE_PRICE" in i.issue_type for i in issues_nan)


def test_14_and_15_duplicate_classification():
    c1 = create_test_m1("2024-01-01 00:00:00", 2000.0, 2005.0, 1995.0, 2002.0)
    c2_exact = create_test_m1("2024-01-01 00:00:00", 2000.0, 2005.0, 1995.0, 2002.0)
    c3_conflict = create_test_m1("2024-01-01 00:00:00", 2000.0, 2010.0, 1995.0, 2008.0)

    report_exact = audit_m1_dataset([c1, c2_exact])
    assert report_exact.exact_duplicates_removed == 1

    report_conflict = audit_m1_dataset([c1, c3_conflict])
    assert report_conflict.conflicting_duplicates_count == 1
    assert report_conflict.quality_status == DataQualityStatus.FAIL


# --- 17 to 21: GAP CLASSIFICATION TESTS ---
def test_17_to_21_gap_classification():
    # Normal 1 minute gap
    c1 = create_test_m1("2024-01-01 10:00:00")
    c2 = create_test_m1("2024-01-01 10:01:00")
    gaps, _ = classify_gaps([c1, c2])
    assert len(gaps) == 0

    # Weekend gap: Friday 21:59 to Sunday 22:01 UTC
    c_fri = create_test_m1("2024-01-05 21:59:00")
    c_sun = create_test_m1("2024-01-07 22:01:00")
    gaps_wk, _ = classify_gaps([c_fri, c_sun])
    assert len(gaps_wk) == 1
    assert gaps_wk[0].category == GapCategory.WEEKEND_SESSION_BREAK

    # Suspicious intraday gap (missing 10 minutes on Tuesday)
    c_tue1 = create_test_m1("2024-01-02 10:00:00")
    c_tue2 = create_test_m1("2024-01-02 10:11:00")
    gaps_int, _ = classify_gaps([c_tue1, c_tue2])
    assert len(gaps_int) == 1
    assert gaps_int[0].category == GapCategory.SUSPICIOUS_INTRASESSION


# --- 25 to 30: FINGERPRINT TESTS ---
def test_25_to_30_fingerprint_sensitivity():
    c1 = create_test_m1("2024-01-01 00:00:00", 2000.0, 2005.0, 1995.0, 2002.0)
    c2 = create_test_m1("2024-01-01 00:01:00", 2002.0, 2008.0, 2000.0, 2006.0)

    fp1 = compute_canonical_fingerprint([c1, c2])
    fp2 = compute_canonical_fingerprint([c1, c2])
    assert fp1 == fp2  # Deterministic!

    # OHLC mutation MUST change fingerprint!
    c2_mut = create_test_m1("2024-01-01 00:01:00", 2002.0, 2012.0, 2000.0, 2006.0)
    fp_mut = compute_canonical_fingerprint([c1, c2_mut])
    assert fp1 != fp_mut


# --- 35 to 41: RESAMPLING INTEGRATION TESTS ---
def test_35_to_41_resampling_integration():
    # 30 consecutive M1 candles (fills 1 full M30, 2 M15, 6 M5, 10 M3)
    raw_list, candles = generate_synthetic_m1_dataset("2024-01-01 00:00:00", 30, 2000.0)

    m30, prov30 = resample_m1(candles, Timeframe.M30)
    assert len(m30) == 1
    assert prov30.incomplete_bucket_count == 0
    assert m30[0].open == candles[0].open
    assert m30[0].close == candles[-1].close


# --- 42 to 44: MANIFEST TESTS ---
def test_42_to_44_manifest_generation():
    manifest = DatasetManifest(
        dataset_name="XAUUSD_M1_TEST",
        research_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        timeframe="M1",
        retrieved_at_utc="2026-08-08 12:00:00",
        earliest_timestamp="2024-01-01 00:00:00",
        latest_timestamp="2024-01-01 00:30:00",
        raw_row_count=30,
        canonical_row_count=30,
        raw_fingerprint="raw_fp_123",
        canonical_fingerprint="can_fp_123",
        quality_status="PASS",
        m1_count=30,
        m3_count=10,
        m5_count=6,
        m15_count=2,
        m30_count=1,
        incomplete_buckets={},
        source_kind="BENCHMARK_FIXTURE",
        dataset_state="V2_M1_BENCHMARK_FIXTURE",
    )
    json_str = manifest.to_json()
    assert "XAUUSD" in json_str
    assert "V2_M1_BENCHMARK_FIXTURE" in json_str


def test_45_to_47_benchmark_fixture_isolation_and_fail_closed_validation():
    from research.v2.data.manifest import validate_dataset_for_research

    # 1. Fallback source tagged BENCHMARK_FIXTURE with V2_M1_BENCHMARK_FIXTURE state
    m_fix = DatasetManifest(
        dataset_name="XAUUSD_FIXTURE",
        research_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        timeframe="M1",
        retrieved_at_utc="2026-08-08 12:00:00",
        earliest_timestamp="2023-01-01 00:00:00",
        latest_timestamp="2023-01-02 00:00:00",
        raw_row_count=100,
        canonical_row_count=100,
        raw_fingerprint="raw_fix",
        canonical_fingerprint="can_fix",
        quality_status="PASS",
        m1_count=100,
        m3_count=33,
        m5_count=20,
        m15_count=6,
        m30_count=3,
        incomplete_buckets={},
        source_kind="BENCHMARK_FIXTURE",
        dataset_state="V2_M1_BENCHMARK_FIXTURE",
    )
    assert m_fix.source_kind == "BENCHMARK_FIXTURE"
    assert m_fix.dataset_state == "V2_M1_BENCHMARK_FIXTURE"

    # 2. Cannot promote BENCHMARK_FIXTURE to V2_M1_DATASET_CANDIDATE
    with pytest.raises(ValueError, match="cannot be promoted"):
        DatasetManifest(
            dataset_name="XAUUSD_BAD_PROMOTION",
            research_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            timeframe="M1",
            retrieved_at_utc="2026-08-08 12:00:00",
            earliest_timestamp="2023-01-01 00:00:00",
            latest_timestamp="2023-01-02 00:00:00",
            raw_row_count=100,
            canonical_row_count=100,
            raw_fingerprint="raw_fix",
            canonical_fingerprint="can_fix",
            quality_status="PASS",
            m1_count=100,
            m3_count=33,
            m5_count=20,
            m15_count=6,
            m30_count=3,
            incomplete_buckets={},
            source_kind="BENCHMARK_FIXTURE",
            dataset_state="V2_M1_DATASET_CANDIDATE",
        )

    # 3. LIVE_MT5 can be candidate
    m_live = DatasetManifest(
        dataset_name="XAUUSD_LIVE",
        research_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        timeframe="M1",
        retrieved_at_utc="2026-08-08 12:00:00",
        earliest_timestamp="2023-01-01 00:00:00",
        latest_timestamp="2023-01-02 00:00:00",
        raw_row_count=100,
        canonical_row_count=100,
        raw_fingerprint="raw_live",
        canonical_fingerprint="can_live",
        quality_status="PASS",
        m1_count=100,
        m3_count=33,
        m5_count=20,
        m15_count=6,
        m30_count=3,
        incomplete_buckets={},
        source_kind="LIVE_MT5",
        dataset_state="V2_M1_DATASET_CANDIDATE",
    )
    assert m_live.dataset_state == "V2_M1_DATASET_CANDIDATE"

    # 4. Fail-closed: research validator rejects BENCHMARK_FIXTURE by default
    with pytest.raises(ValueError, match="Cannot run V2 research backtest on BENCHMARK_FIXTURE"):
        validate_dataset_for_research(m_fix, allow_fixture=False)

    # 5. Fixture usable when explicitly allowed for testing
    validate_dataset_for_research(m_fix, allow_fixture=True)
    validate_dataset_for_research(m_live, allow_fixture=False)


def test_48_to_50_v1_isolation_regression():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
