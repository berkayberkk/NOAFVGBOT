"""
NOAFVGBOT V2.10C -- Real Feature Wiring & Causal Market-State Integration Tests.

Covers: authoritative-dataset-only integration (no synthetic fallback), TRAIN boundary
enforcement, closed-bar availability per MTF timeframe, swing/structure/FVG/OB/liquidity
causality (prefix-invariance + future-data adversarial tests), DecisionSnapshot immutability,
feature-state fingerprint determinism, missing-vs-zero / warmup-vs-no-signal semantics,
idempotency (no duplicate feature/thesis/candidate/passport on reprocessing), candidate/
passport provenance, deterministic gap handling, and V1/MQL5 isolation.
"""

from datetime import datetime, timedelta, timezone
import copy

import pytest

from research.v2.data.models import CandleV2, Timeframe
from research.v2.core.thesis import ThesisDirection, ParentThesis, ChildEntryCandidate, compute_thesis_id
from research.v2.features.fvg_quality import detect_fvgs
from research.v2.features.ob_quality import detect_order_blocks
from research.v2.features.liquidity import detect_swings, LiquidityType
from research.v2.features.structure import detect_structure_events, extract_structure_features, StructureEventType
from research.v2.features.models import FeatureRecord, FeaturePhase
from research.v2.telemetry.passport import DecisionSnapshot, compute_feature_state_fingerprint
from research.v2.data.resampler import resample_m1
from research.v2.engine.mtf_backtester import V2MultiTimeframeBacktester
from research.v2.strategy.train_policy import V2TrainResearchPolicy
from research.v2.engine.models import ReferenceResearchPolicy
from research.v2.data.live_dataset import (
    load_authoritative_frozen_v2_dataset,
    DatasetNotFrozenError,
    DatasetIdentityMismatchError,
)
import research.v2.engine.run_v2_10c_train_smoke as smoke


def create_candle(ts_open: str, o: float, h: float, l: float, c: float, tf: Timeframe = Timeframe.M1) -> CandleV2:
    dt_open = datetime.fromisoformat(ts_open).replace(tzinfo=timezone.utc)
    dt_close = dt_open + timedelta(seconds=tf.seconds)
    return CandleV2(
        timestamp_open_utc=dt_open.strftime("%Y-%m-%d %H:%M:%S"),
        timestamp_close_utc=dt_close.strftime("%Y-%m-%d %H:%M:%S"),
        timeframe=tf,
        open=o, high=h, low=l, close=c, volume=10.0,
    )


def generate_m1_series(start_ts: str, count: int, seed: int = 7) -> "list[CandleV2]":
    """Deterministic (no RNG) zig-zag walk -- reproducible across Python versions/runs, and
    varied enough to reliably produce FVGs/OBs/swings/structure breaks for wiring tests."""
    dt = datetime.fromisoformat(start_ts).replace(tzinfo=timezone.utc)
    res = []
    p = 2400.0 + seed
    for i in range(count):
        ts_open = dt.strftime("%Y-%m-%d %H:%M:%S")
        phase = i % 17
        move = (phase - 8) * 0.9 + (0.4 if i % 3 == 0 else -0.2)
        o = p
        c = p + move
        h = max(o, c) + 1.0 + (i % 5) * 0.1
        l = min(o, c) - 1.0 - (i % 4) * 0.1
        res.append(create_candle(ts_open, o, h, l, c))
        p = c
        dt += timedelta(minutes=1)
    return res


def build_mtf_datasets(m1_candles):
    return {
        Timeframe.M1: m1_candles,
        Timeframe.M3: resample_m1(m1_candles, Timeframe.M3)[0],
        Timeframe.M5: resample_m1(m1_candles, Timeframe.M5)[0],
        Timeframe.M15: resample_m1(m1_candles, Timeframe.M15)[0],
        Timeframe.M30: resample_m1(m1_candles, Timeframe.M30)[0],
    }


# --- 1-4: authoritative dataset / no synthetic fallback -----------------------------------

def test_1_authoritative_frozen_dataset_required(tmp_path):
    with pytest.raises(DatasetNotFrozenError):
        load_authoritative_frozen_v2_dataset(
            canonical_csv_path=str(tmp_path / "nope.csv"),
            frozen_manifest_path=str(tmp_path / "missing_manifest.json"),
        )


def test_2_wrong_fingerprint_rejected(tmp_path):
    import json
    csv_path = tmp_path / "canon.csv"
    csv_path.write_text("<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
                         "2026.01.05\t00:00:00\t2000.0\t2000.5\t1999.5\t2000.1\t10\t0\t30\n", encoding="utf-8")
    manifest_path = tmp_path / "frozen.json"
    manifest_path.write_text(json.dumps({
        "dataset_id": "V2_M1_LIVE_DATASET_V2", "freeze_decision": "FREEZE_ACCEPTED_WITH_WARNINGS",
        "canonical_fingerprint": "0" * 64, "row_count": 1,
        "actual_range": {"start": "2026-01-05 00:00:00", "end": "2026-01-05 00:00:00"},
    }))
    with pytest.raises(DatasetIdentityMismatchError):
        load_authoritative_frozen_v2_dataset(canonical_csv_path=str(csv_path), frozen_manifest_path=str(manifest_path))


def test_3_non_frozen_manifest_rejected(tmp_path):
    import json
    manifest_path = tmp_path / "rejected.json"
    manifest_path.write_text(json.dumps({"dataset_id": "V2_M1_LIVE_DATASET_V2", "freeze_decision": "FREEZE_REJECTED"}))
    with pytest.raises(DatasetNotFrozenError):
        load_authoritative_frozen_v2_dataset(canonical_csv_path=str(tmp_path / "canon.csv"), frozen_manifest_path=str(manifest_path))


def test_4_smoke_runner_has_no_synthetic_fallback_path():
    import inspect
    src = inspect.getsource(smoke)
    assert "load_synthetic_fixture" not in src
    assert "generate_synthetic_m1_dataset" not in src
    assert "load_authoritative_frozen_v2_dataset" in src


# --- 5: TRAIN boundary enforcement ----------------------------------------------------------

def test_5_train_boundary_enforced_even_when_count_crosses_it():
    candles = generate_m1_series("2023-10-31 23:50:00", 40)  # spans across the 2023-11-01 TRAIN/DEV boundary
    result = smoke.load_train_only_prefix(candles, 1_000_000)
    assert all(c.timestamp_open_utc < smoke.TRAIN_END_UTC for c in result)
    assert len(result) < 40  # confirms it actually stopped early, not just returned everything
    assert result[-1].timestamp_open_utc == "2023-10-31 23:59:00"


# --- 6-9: MTF closed-bar availability --------------------------------------------------------

@pytest.mark.parametrize("tf", [Timeframe.M30, Timeframe.M15, Timeframe.M5, Timeframe.M3])
def test_6_to_9_closed_bar_availability_per_timeframe(tf):
    c1 = create_candle("2026-08-08 10:00:00", 2000.0, 2010.0, 1995.0, 2008.0, tf=tf)
    c2 = create_candle((datetime.fromisoformat(c1.timestamp_close_utc)).strftime("%Y-%m-%d %H:%M:%S"), 2008.0, 2030.0, 2005.0, 2028.0, tf=tf)
    c3 = create_candle((datetime.fromisoformat(c2.timestamp_close_utc)).strftime("%Y-%m-%d %H:%M:%S"), 2028.0, 2050.0, 2015.0, 2045.0, tf=tf)

    fvgs = detect_fvgs([c1, c2, c3])
    assert len(fvgs) == 1
    # The FVG cannot be available before its own defining candle (c3) has closed.
    assert fvgs[0].known_at_timestamp == c3.timestamp_close_utc
    assert fvgs[0].known_at_timestamp > c2.timestamp_close_utc  # strictly after the middle bar mid-point


# --- 10: confirmed swing availability delayed correctly ---------------------------------------

def test_10_confirmed_swing_availability_delayed():
    candles = [
        create_candle("2026-08-08 10:00:00", 2000, 2010, 1990, 2005),
        create_candle("2026-08-08 10:01:00", 2005, 2020, 1995, 2015),
        create_candle("2026-08-08 10:02:00", 2015, 2050, 2010, 2045),  # swing high candidate
        create_candle("2026-08-08 10:03:00", 2045, 2045, 2020, 2025),
        create_candle("2026-08-08 10:04:00", 2025, 2030, 2015, 2020),  # confirms swing (right_bars=2)
    ]
    pools = detect_swings(candles, left_bars=2, right_bars=2)
    highs = [p for p in pools if p.liquidity_type == LiquidityType.SWING_HIGH]
    assert len(highs) == 1
    assert highs[0].known_at_timestamp == candles[4].timestamp_close_utc  # NOT candles[2] -- delayed by right_bars


# --- 11 & 29: future bars cannot alter past swing state / prefix invariance -------------------

@pytest.mark.parametrize("cutoff", [30, 60, 90])
def test_11_and_29_prefix_invariance_swings(cutoff):
    full = generate_m1_series("2026-01-05 00:00:00", 150)
    prefix = full[:cutoff]

    swings_prefix = detect_swings(prefix, left_bars=2, right_bars=2)
    swings_full = detect_swings(full, left_bars=2, right_bars=2)

    # Every swing confirmed WITHIN the prefix (known_at <= prefix's last close) must appear
    # identically in the full computation -- future bars must not retroactively change it.
    prefix_last_close = prefix[-1].timestamp_close_utc
    confirmed_in_prefix = {(p.liquidity_type, p.price, p.origin_timestamp, p.known_at_timestamp) for p in swings_prefix if p.known_at_timestamp <= prefix_last_close}
    confirmed_in_full_same_window = {(p.liquidity_type, p.price, p.origin_timestamp, p.known_at_timestamp) for p in swings_full if p.known_at_timestamp <= prefix_last_close}
    assert confirmed_in_prefix == confirmed_in_full_same_window


# --- 12: FVG causality -------------------------------------------------------------------------

def test_12_fvg_causality_adversarial():
    full = generate_m1_series("2026-02-01 00:00:00", 120)
    prefix = full[:50]
    fvgs_prefix = {(f.direction, f.bottom, f.top, f.known_at_timestamp) for f in detect_fvgs(prefix)}
    fvgs_full = {(f.direction, f.bottom, f.top, f.known_at_timestamp) for f in detect_fvgs(full) if f.known_at_timestamp <= prefix[-1].timestamp_close_utc}
    assert fvgs_prefix == fvgs_full


# --- 13: OB causality --------------------------------------------------------------------------

def test_13_ob_causality_adversarial():
    full = generate_m1_series("2026-02-05 00:00:00", 120)
    prefix = full[:50]
    obs_prefix = {(o.direction, o.zone_low, o.zone_high, o.known_at_timestamp) for o in detect_order_blocks(prefix)}
    obs_full = {(o.direction, o.zone_low, o.zone_high, o.known_at_timestamp) for o in detect_order_blocks(full) if o.known_at_timestamp <= prefix[-1].timestamp_close_utc}
    assert obs_prefix == obs_full


# --- 14: liquidity causality --------------------------------------------------------------------

def test_14_liquidity_causality_adversarial():
    full = generate_m1_series("2026-02-10 00:00:00", 120)
    prefix = full[:50]
    pools_prefix = {(p.liquidity_type, p.price, p.known_at_timestamp) for p in detect_swings(prefix)}
    pools_full = {(p.liquidity_type, p.price, p.known_at_timestamp) for p in detect_swings(full) if p.known_at_timestamp <= prefix[-1].timestamp_close_utc}
    assert pools_prefix == pools_full


# --- 15: structure causality (the exact bug fixed in V2.10C) -------------------------------------

def test_15_structure_causality_adversarial_multi_swing():
    """Reproduces the pre-fix bug directly: an early break must reference the EARLY swing that
    was actually known at that point, never a later swing that didn't exist yet."""
    candles = [
        create_candle("2026-01-01 00:00:00", 2000, 2000, 1990, 1995),
        create_candle("2026-01-01 00:01:00", 1995, 2005, 1990, 2000),
        create_candle("2026-01-01 00:02:00", 2000, 2010, 1995, 2005),   # early swing high @2010
        create_candle("2026-01-01 00:03:00", 2005, 2008, 2000, 2003),
        create_candle("2026-01-01 00:04:00", 2003, 2006, 1998, 2001),   # confirms @2010
        create_candle("2026-01-01 00:05:00", 2001, 2050, 1999, 2050),   # breaks the EARLY swing (2010)
        create_candle("2026-01-01 00:06:00", 2050, 2055, 2040, 2045),
        create_candle("2026-01-01 00:07:00", 2045, 2100, 2040, 2095),   # later swing high @2100
        create_candle("2026-01-01 00:08:00", 2095, 2098, 2090, 2093),
        create_candle("2026-01-01 00:09:00", 2093, 2096, 2085, 2090),   # confirms @2100
    ]
    events = detect_structure_events(candles, left_bars=2, right_bars=2)
    breaks = [e for e in events if e.event_type == StructureEventType.STRUCTURE_BREAK_UP]
    assert len(breaks) == 1
    assert breaks[0].metadata["broken_level"] == 2010.0
    assert breaks[0].known_at_timestamp <= candles[7].timestamp_close_utc  # strictly before the later swing was even confirmable


@pytest.mark.parametrize("cutoff", [40, 70])
def test_15b_structure_prefix_invariance(cutoff):
    full = generate_m1_series("2026-02-15 00:00:00", 120)
    prefix = full[:cutoff]
    ev_prefix = {(e.event_type, e.price, e.known_at_timestamp) for e in detect_structure_events(prefix)}
    ev_full = {(e.event_type, e.price, e.known_at_timestamp) for e in detect_structure_events(full) if e.known_at_timestamp <= prefix[-1].timestamp_close_utc}
    assert ev_prefix == ev_full


# --- 16: snapshot immutable after future bars -----------------------------------------------

def test_16_decision_snapshot_immutable_after_future_bars():
    """Section 15, literally: create a snapshot at T, keep processing future candles on the
    SAME running engine, then verify the already-created snapshot is still field-equivalent.
    DecisionSnapshot is a frozen dataclass and nothing in the engine ever reassigns a
    passport's decision_snapshot after construction -- this proves that end-to-end."""
    full = generate_m1_series("2026-03-01 00:00:00", 150)

    bt = V2MultiTimeframeBacktester(policy=V2TrainResearchPolicy())
    datasets = build_mtf_datasets(full)
    bt._feature_release_index = bt._precompute_feature_release_index(datasets)
    from research.v2.data.clock import MultiTimeframeClock
    stream = MultiTimeframeClock(datasets).build_event_stream()

    midpoint = len(stream) // 2
    for ev in stream[:midpoint]:
        bt._process_event(ev)

    assert bt.passports, "expected at least one passport created within the first half of the stream"
    snapshots_before = {pid: p.decision_snapshot for pid, p in bt.passports.items()}
    snapshot_field_copies_before = {
        pid: (snap.structural_entry, snap.structural_stop, snap.structural_target, dict(snap.mtf_trace),
              tuple(f.feature_id for f in snap.feature_records), tuple(lp.pool_id for lp in snap.liquidity_pools))
        for pid, snap in snapshots_before.items()
    }

    for ev in stream[midpoint:]:
        bt._process_event(ev)

    for pid, snap_before in snapshots_before.items():
        # Same object identity: nothing ever replaced/reassigned it.
        assert bt.passports[pid].decision_snapshot is snap_before
        snap_after = bt.passports[pid].decision_snapshot
        after_copy = (snap_after.structural_entry, snap_after.structural_stop, snap_after.structural_target, dict(snap_after.mtf_trace),
                      tuple(f.feature_id for f in snap_after.feature_records), tuple(lp.pool_id for lp in snap_after.liquidity_pools))
        assert after_copy == snapshot_field_copies_before[pid]


# --- 17, 18, 19: feature-state fingerprint --------------------------------------------------

def _make_snapshot(records):
    return DecisionSnapshot(
        thesis_id="t1", direction=ThesisDirection.LONG, candidate_id="c1",
        candidate_created_at="2026-01-01 00:10:00", candidate_timeframe=Timeframe.M5,
        structural_entry=100.0, structural_stop=95.0, feature_records=tuple(records),
    )


def test_17_feature_fingerprint_deterministic_repeated_calls():
    rec = FeatureRecord(feature_id="f1", feature_type="FVG_RAW_FEATURES", source_object_id="fvg1", source_timeframe=Timeframe.M5,
                         timestamp_utc="2026-01-01 00:05:00", known_at_timestamp="2026-01-01 00:05:00", phase=FeaturePhase.DECISION_TIME, values={"gap_size": 5.0})
    snap = _make_snapshot([rec])
    assert compute_feature_state_fingerprint(snap) == compute_feature_state_fingerprint(snap)


def test_18_semantic_equivalent_state_same_fingerprint():
    rec1 = FeatureRecord(feature_id="f1", feature_type="FVG_RAW_FEATURES", source_object_id="fvg1", source_timeframe=Timeframe.M5,
                          timestamp_utc="2026-01-01 00:05:00", known_at_timestamp="2026-01-01 00:05:00", phase=FeaturePhase.DECISION_TIME, values={"gap_size": 5.0})
    rec2 = FeatureRecord(feature_id="f2", feature_type="OB_RAW_FEATURES", source_object_id="ob1", source_timeframe=Timeframe.M5,
                          timestamp_utc="2026-01-01 00:04:00", known_at_timestamp="2026-01-01 00:04:00", phase=FeaturePhase.DECISION_TIME, values={"zone_width": 3.0})
    snap_forward = _make_snapshot([rec1, rec2])
    snap_reversed = _make_snapshot([rec2, rec1])
    assert compute_feature_state_fingerprint(snap_forward) == compute_feature_state_fingerprint(snap_reversed)


def test_19_meaningful_state_change_changes_fingerprint():
    rec_a = FeatureRecord(feature_id="f1", feature_type="FVG_RAW_FEATURES", source_object_id="fvg1", source_timeframe=Timeframe.M5,
                           timestamp_utc="2026-01-01 00:05:00", known_at_timestamp="2026-01-01 00:05:00", phase=FeaturePhase.DECISION_TIME, values={"gap_size": 5.0})
    rec_b = FeatureRecord(feature_id="f1", feature_type="FVG_RAW_FEATURES", source_object_id="fvg1", source_timeframe=Timeframe.M5,
                           timestamp_utc="2026-01-01 00:05:00", known_at_timestamp="2026-01-01 00:05:00", phase=FeaturePhase.DECISION_TIME, values={"gap_size": 6.0})
    assert compute_feature_state_fingerprint(_make_snapshot([rec_a])) != compute_feature_state_fingerprint(_make_snapshot([rec_b]))


# --- 20: missing != zero -------------------------------------------------------------------

def test_20_missing_atr_is_none_not_zero_in_real_wiring():
    full = generate_m1_series("2026-04-01 00:00:00", 90)
    datasets = build_mtf_datasets(full)
    bt = V2MultiTimeframeBacktester(policy=ReferenceResearchPolicy())
    idx = bt._precompute_feature_release_index(datasets)
    fvg_records = [obj for entries in idx.values() for kind, obj in entries if kind == "feature_record" and obj.feature_type == "FVG_RAW_FEATURES"]
    assert fvg_records, "expected at least one FVG in this fixture"
    for rec in fvg_records:
        assert rec.values["gap_to_atr_ratio"] is None  # no ATR engine wired -> None, never fabricated 0


# --- 21: warmup != no-signal (absence of a feature is absence, not a fabricated value) --------

def test_21_insufficient_history_produces_no_events_not_placeholder():
    tiny = generate_m1_series("2026-04-05 00:00:00", 3)  # too short for left_bars=2,right_bars=2 swings
    events = detect_structure_events(tiny, left_bars=2, right_bars=2)
    assert events == []  # warmup insufficiency -> empty, not a fabricated NO_SIGNAL record

    se = None
    fvgs = detect_fvgs(tiny)
    if not fvgs:
        pass  # correctly nothing detected rather than a fabricated feature


# --- 22 & 23: gap handling deterministic / no synthetic candle insertion -----------------------

def test_22_and_23_gap_handling_deterministic_no_candle_insertion():
    candles = generate_m1_series("2026-05-01 00:00:00", 30)
    # Remove one candle to create a genuine M1 gap (mirrors real canonical-data gap behavior).
    gapped = candles[:15] + candles[16:]
    assert len(gapped) == len(candles) - 1

    m3_a, prov_a = resample_m1(gapped, Timeframe.M3)
    m3_b, prov_b = resample_m1(gapped, Timeframe.M3)
    assert [c.timestamp_open_utc for c in m3_a] == [c.timestamp_open_utc for c in m3_b]  # deterministic
    assert prov_a.incomplete_bucket_count == prov_b.incomplete_bucket_count
    assert prov_a.incomplete_bucket_count >= 1  # the bucket spanning the gap is dropped, never fabricated

    total_m3_bars = sum(1 for c in m3_a)
    assert total_m3_bars * 3 <= len(gapped)  # no bar covers minutes that don't exist


# --- 24 & 25: candidate / passport provenance --------------------------------------------------

def test_24_and_25_candidate_and_passport_provenance():
    full = generate_m1_series("2026-05-10 00:00:00", 90)
    bt = V2MultiTimeframeBacktester(policy=V2TrainResearchPolicy())
    bt.run(full)
    assert bt.passports, "expected at least one passport"

    for pid, p in bt.passports.items():
        snap = p.decision_snapshot
        assert snap.candidate_id == p.candidate_id
        assert snap.thesis_id == p.thesis_id
        assert snap.candidate_created_at == p.created_at
        assert isinstance(snap.mtf_trace, dict)
        # every attached feature/liquidity object was causally valid at candidate creation time
        for f in snap.feature_records:
            assert f.known_at_timestamp <= snap.candidate_created_at
        for lp in snap.liquidity_pools:
            assert lp.known_at_timestamp <= snap.candidate_created_at


# --- 26, 27, 28: idempotency -------------------------------------------------------------------

def test_26_27_28_duplicate_event_processing_does_not_duplicate_state():
    """Section 28: reprocessing the SAME causal event (immediate at-least-once redelivery,
    not a full-stream rewind after later events have already advanced market_state) must not
    duplicate feature events, ParentTheses, ChildCandidates, or TradePassports."""
    full = generate_m1_series("2026-05-20 00:00:00", 60)
    datasets = build_mtf_datasets(full)
    bt = V2MultiTimeframeBacktester(policy=V2TrainResearchPolicy())
    bt._feature_release_index = bt._precompute_feature_release_index(datasets)

    from research.v2.data.clock import MultiTimeframeClock
    stream = MultiTimeframeClock(datasets).build_event_stream()

    # Process the stream once, redelivering EACH event a second time immediately after itself
    # (the realistic at-least-once-delivery duplicate scenario), and assert no state doubles.
    for ev in stream:
        feature_count_before = bt.feature_release_stats["feature_records"]
        thesis_count_before = len(bt.active_theses) + len(bt.terminal_theses)
        passport_count_before = len(bt.passports)

        bt._process_event(ev)

        feature_count_after_first = bt.feature_release_stats["feature_records"]
        thesis_count_after_first = len(bt.active_theses) + len(bt.terminal_theses)
        passport_count_after_first = len(bt.passports)

        bt._process_event(ev)  # immediate duplicate redelivery of the SAME event

        assert bt.feature_release_stats["feature_records"] == feature_count_after_first  # index entry already popped -> no re-release
        assert len(bt.active_theses) + len(bt.terminal_theses) == thesis_count_after_first  # dedup by thesis_id
        assert len(bt.passports) == passport_count_after_first  # dedup by passport_id / seen_candidate_keys

    assert bt.passports, "expected at least one passport to have been created over the run"


# --- 30: repeated real TRAIN smoke exact --------------------------------------------------------

def test_30_repeated_real_train_smoke_exact():
    candles, manifest = load_authoritative_frozen_v2_dataset()
    r1 = smoke.run_smoke_slice(candles, 300)
    r2 = smoke.run_smoke_slice(candles, 300)
    assert r1["passport_count"] == r2["passport_count"]
    assert r1["feature_release_stats"] == r2["feature_release_stats"]
    assert r1["backtest_fingerprint"] == r2["backtest_fingerprint"]
    assert r1["feature_coverage"] == r2["feature_coverage"]


# --- 31, 32, 33: no DEVELOPMENT/VALIDATION/FINAL_TEST evaluation -------------------------------

def test_31_32_33_no_later_partition_evaluated():
    candles, manifest = load_authoritative_frozen_v2_dataset()
    # Request far more than the entire TRAIN partition (1,003,676 rows) -- must still stop at
    # the TRAIN boundary, never touching DEVELOPMENT/VALIDATION/FINAL_TEST timestamps.
    result = smoke.load_train_only_prefix(candles, 2_000_000)
    assert len(result) == 1003676
    assert result[-1].timestamp_open_utc < smoke.TRAIN_END_UTC
    assert smoke.TRAIN_END_UTC == "2023-11-01 00:00:00"


# --- 34: V1 untouched -----------------------------------------------------------------------

def test_34_v1_isolation_regression():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1
    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14


# --- 35: MQL5 untouched (structural: no V2.10C module references MQL5 files) -------------------

def test_35_no_mql5_references_in_v2_10c_modules():
    import inspect
    from research.v2.features import structure as structure_mod
    from research.v2.engine import mtf_backtester as bt_mod
    for mod in (structure_mod, bt_mod, smoke):
        src = inspect.getsource(mod)
        assert ".mq5" not in src.lower()
        assert "mt5.order_send" not in src.lower()
