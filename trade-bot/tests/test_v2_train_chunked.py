"""
Chunked TRAIN coverage merge-logic testleri.
run_chunk/run() gercek datasetle calisiyor (yavas) -- burada sadece deterministik,
veri bagimsiz merge_chunk_reports() mantigini test ediyoruz.
"""

from research.v2.engine.run_v2_train_chunked import merge_chunk_reports


def make_report(first_ts, last_ts, events, theses, passports, feature_type="FVG",
                 obs=10, tfs=("M30",)):
    return {
        "size_actual": 1000,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "runtime_seconds": 1.0,
        "total_events": events,
        "peak_active_theses": theses,
        "peak_active_passports": passports,
        "created_theses": theses,
        "invalidated_theses": 0,
        "expired_theses": 0,
        "passport_count": passports,
        "feature_release_stats": {},
        "feature_coverage": {
            feature_type: {
                "observations": obs,
                "timeframes_represented": list(tfs),
                "first_availability_timestamp": first_ts,
                "last_availability_timestamp": last_ts,
            }
        },
        "backtest_fingerprint": "fp",
    }


def test_merge_sums_counts_across_chunks():
    reports = [
        make_report("2021-01-01 00:00:00", "2021-01-02 00:00:00", events=100, theses=5, passports=3),
        make_report("2021-01-02 00:00:00", "2021-01-03 00:00:00", events=200, theses=7, passports=4),
    ]
    merged = merge_chunk_reports(reports)
    assert merged["chunk_count"] == 2
    assert merged["total_events"] == 300
    assert merged["created_theses_total"] == 12
    assert merged["passport_count_total"] == 7


def test_merge_takes_max_of_peaks_not_sum():
    reports = [
        make_report("t0", "t1", events=1, theses=5, passports=3),
        make_report("t1", "t2", events=1, theses=9, passports=2),
    ]
    merged = merge_chunk_reports(reports)
    assert merged["peak_active_theses_max_across_chunks"] == 9
    assert merged["peak_active_passports_max_across_chunks"] == 3


def test_merge_unions_timeframes_and_sums_observations_per_feature_type():
    reports = [
        make_report("2021-01-01 00:00:00", "2021-01-02 00:00:00", 1, 1, 1, "FVG", obs=10, tfs=("M30",)),
        make_report("2021-01-02 00:00:00", "2021-01-03 00:00:00", 1, 1, 1, "FVG", obs=15, tfs=("M15", "M5")),
    ]
    merged = merge_chunk_reports(reports)
    fvg = merged["feature_coverage_merged"]["FVG"]
    assert fvg["observations"] == 25
    assert fvg["timeframes_represented"] == ["M15", "M30", "M5"]
    assert fvg["first_availability_timestamp"] == "2021-01-01 00:00:00"
    assert fvg["last_availability_timestamp"] == "2021-01-03 00:00:00"


def test_merge_empty_list_does_not_crash():
    merged = merge_chunk_reports([])
    assert merged["chunk_count"] == 0
    assert merged["total_events"] == 0
    assert merged["peak_active_theses_max_across_chunks"] == 0
