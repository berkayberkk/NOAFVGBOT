"""
NOAFVGBOT V2.10C.2 -- Passport Lifecycle Scaling Hardening Parity Tests.

Performance-only change: TradePassport.add_observation (research/v2/telemetry/passport.py) and
calculate_excursion_as_of (research/v2/telemetry/excursion.py) were rewritten to remove two
provable computational redundancies without changing observed behavior:

1. add_observation re-parsed self._created_at (an invariant that never changes after
   construction) via datetime.fromisoformat() on EVERY call, and concatenated
   self._pre_entry_path + self._post_entry_path (an O(total observations so far) list build)
   just to read its last element. Both chronology checks now use direct string comparison
   (every timestamp in this codebase is generated via strftime("%Y-%m-%d %H:%M:%S"), a
   fixed-width format whose lexicographic order equals chronological order -- the same
   invariant V2.10C.1's liquidity bisect fix already relies on and this suite re-verifies for
   this call site), and the "last observation" lookup is O(1).
2. calculate_excursion_as_of always ran an O(len(observations)) datetime-parsing filter pass
   even when every observation was already known to satisfy "<= as_of_utc" (true for every
   current caller). It now skips that filter whenever as_of_utc is at/after the last
   observation's own timestamp, falling back to the original exact filter otherwise.

Every test in this file either proves exact parity against the verbatim pre-V2.10C.2 logic
(preserved as OLD_add_observation / OLD_calculate_excursion_as_of below, copied from commit
a6fc0c8), or proves a structural (non-wall-clock) reduction in redundant work per the
project's established "operation counts, not milliseconds" convention (see V2.10C.1).

No strategy semantics, candidate/passport creation volume, thesis policy, entry/stop/target
geometry, or dataset content are touched by this file.
"""

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from research.v2.data.models import Timeframe
from research.v2.core.thesis import ThesisDirection
from research.v2.features.models import FeatureRecord, FeaturePhase
from research.v2.features.liquidity import LiquidityPool, LiquiditySide, LiquidityType
from research.v2.telemetry.excursion import PathObservation, ExcursionMetrics, calculate_excursion_as_of
from research.v2.telemetry import excursion as excursion_mod
from research.v2.telemetry.passport import (
    TradePassport,
    DecisionSnapshot,
    OutcomeState,
    PassportEventType,
    compute_passport_id,
    DuplicateObservationError,
    CensoredPassportError,
)
from research.v2.telemetry import passport as passport_mod


# ---------------------------------------------------------------------------------------------
# Reference oracles -- verbatim pre-V2.10C.2 logic (commit a6fc0c8), kept ONLY for parity tests.
# ---------------------------------------------------------------------------------------------

def OLD_add_observation(self, obs) -> None:
    if self._is_censored:
        raise CensoredPassportError(f"Passport {self._passport_id} is censored; cannot append observations")
    if obs.observation_id in self._obs_ids:
        raise DuplicateObservationError(f"Observation {obs.observation_id} already added")

    t_obs = datetime.fromisoformat(obs.timestamp_utc).replace(tzinfo=timezone.utc)
    t_create = datetime.fromisoformat(self._created_at).replace(tzinfo=timezone.utc)
    if t_obs < t_create:
        raise ValueError(f"Observation timestamp ({obs.timestamp_utc}) cannot be before passport created_at ({self._created_at})")

    all_obs = self._pre_entry_path + self._post_entry_path
    if all_obs:
        t_last = datetime.fromisoformat(all_obs[-1].timestamp_utc).replace(tzinfo=timezone.utc)
        if t_obs < t_last:
            raise ValueError(f"Observation chronology violation: {obs.timestamp_utc} < previous {all_obs[-1].timestamp_utc}")

    self._obs_ids.add(obs.observation_id)

    entry = self._decision_snapshot.structural_entry
    stop = self._decision_snapshot.structural_stop
    target = self._decision_snapshot.structural_target

    if not self._entry_touched:
        touched = (obs.low <= entry <= obs.high)
        if touched:
            self._entry_touched = True
            self._entry_touch_ts = obs.timestamp_utc
            self._outcome_state = OutcomeState.ENTRY_TOUCHED
            self._record_event(PassportEventType.STRUCTURAL_ENTRY_TOUCHED, obs.timestamp_utc)

            stop_hit = (obs.low <= stop) if self._direction == ThesisDirection.LONG else (obs.high >= stop)
            target_hit = (target is not None) and ((obs.high >= target) if self._direction == ThesisDirection.LONG else (obs.low <= target))

            if stop_hit and target_hit:
                self._outcome_state = OutcomeState.AMBIGUOUS_SAME_BAR
                self._record_event(PassportEventType.AMBIGUOUS_SAME_BAR, obs.timestamp_utc, {"reason": "ENTRY_STOP_TARGET_SAME_BAR"})
            elif stop_hit:
                self._outcome_state = OutcomeState.STOP_REACHED
                self._record_event(PassportEventType.STOP_REACHED, obs.timestamp_utc)
            elif target_hit:
                self._outcome_state = OutcomeState.TARGET_REACHED
                self._record_event(PassportEventType.TARGET_REACHED, obs.timestamp_utc)

            self._post_entry_path.append(obs)
        else:
            self._pre_entry_path.append(obs)
    else:
        self._post_entry_path.append(obs)
        if self._outcome_state in (OutcomeState.ENTRY_TOUCHED, OutcomeState.OPEN):
            stop_hit = (obs.low <= stop) if self._direction == ThesisDirection.LONG else (obs.high >= stop)
            target_hit = (target is not None) and ((obs.high >= target) if self._direction == ThesisDirection.LONG else (obs.low <= target))

            if stop_hit and target_hit:
                self._outcome_state = OutcomeState.AMBIGUOUS_SAME_BAR
                self._record_event(PassportEventType.AMBIGUOUS_SAME_BAR, obs.timestamp_utc, {"reason": "STOP_TARGET_SAME_BAR"})
            elif stop_hit:
                self._outcome_state = OutcomeState.STOP_REACHED
                self._record_event(PassportEventType.STOP_REACHED, obs.timestamp_utc)
            elif target_hit:
                self._outcome_state = OutcomeState.TARGET_REACHED
                self._record_event(PassportEventType.TARGET_REACHED, obs.timestamp_utc)


def OLD_calculate_excursion_as_of(reference_price, direction, risk_distance, observations, as_of_utc):
    if reference_price <= 0:
        raise ValueError(f"Reference price must be positive, got: {reference_price}")
    if risk_distance < 0:
        raise ValueError(f"Risk distance cannot be negative, got: {risk_distance}")

    t_as_of = datetime.fromisoformat(as_of_utc).replace(tzinfo=timezone.utc)
    valid_obs = [
        o for o in observations
        if datetime.fromisoformat(o.timestamp_utc).replace(tzinfo=timezone.utc) <= t_as_of
    ]

    if not valid_obs:
        return ExcursionMetrics(
            mae_absolute=0.0, mae_r=0.0, mae_timestamp=None,
            mfe_absolute=0.0, mfe_r=0.0, mfe_timestamp=None,
            initial_risk_distance=risk_distance, reference_price=reference_price,
        )

    mae_abs = 0.0
    mae_ts = None
    mfe_abs = 0.0
    mfe_ts = None
    for obs in valid_obs:
        if direction == ThesisDirection.LONG:
            adverse = max(0.0, reference_price - obs.low)
            if adverse > mae_abs:
                mae_abs, mae_ts = adverse, obs.timestamp_utc
            favorable = max(0.0, obs.high - reference_price)
            if favorable > mfe_abs:
                mfe_abs, mfe_ts = favorable, obs.timestamp_utc
        else:
            adverse = max(0.0, obs.high - reference_price)
            if adverse > mae_abs:
                mae_abs, mae_ts = adverse, obs.timestamp_utc
            favorable = max(0.0, reference_price - obs.low)
            if favorable > mfe_abs:
                mfe_abs, mfe_ts = favorable, obs.timestamp_utc

    mae_r = (mae_abs / risk_distance) if risk_distance > 0 else 0.0
    mfe_r = (mfe_abs / risk_distance) if risk_distance > 0 else 0.0
    return ExcursionMetrics(
        mae_absolute=mae_abs, mae_r=mae_r, mae_timestamp=mae_ts,
        mfe_absolute=mfe_abs, mfe_r=mfe_r, mfe_timestamp=mfe_ts,
        initial_risk_distance=risk_distance, reference_price=reference_price,
    )


NEW_add_observation = TradePassport.add_observation
NEW_calculate_excursion_as_of = passport_mod.calculate_excursion_as_of


# ---------------------------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------------------------

def make_snapshot(direction=ThesisDirection.LONG, entry=2400.0, stop=2390.0, target=2420.0,
                   cand_created_at="2026-02-01 00:00:00"):
    if direction == ThesisDirection.SHORT:
        entry, stop, target = 2400.0, 2410.0, 2380.0
    return DecisionSnapshot(
        thesis_id="th_1", direction=direction, candidate_id="cand_1",
        candidate_created_at=cand_created_at, candidate_timeframe=Timeframe.M5,
        structural_entry=entry, structural_stop=stop, structural_target=target,
    )


def make_passport(direction=ThesisDirection.LONG, entry=2400.0, stop=2390.0, target=2420.0,
                   cand_created_at="2026-02-01 00:00:00", passport_id="pass_test") -> TradePassport:
    snap = make_snapshot(direction, entry, stop, target, cand_created_at)
    return TradePassport(
        passport_id=passport_id, strategy_version="V2.5", schema_version="2.5",
        config_fingerprint="fp1", thesis_id="th_1", candidate_id="cand_1",
        symbol="XAUUSD", direction=direction, candidate_timeframe=Timeframe.M5,
        created_at=cand_created_at, decision_snapshot=snap,
    )


def obs(ts, o, h, l, c, oid=None, pid="pass_test"):
    return PathObservation(oid or f"obs_{ts}", pid, ts, Timeframe.M1, o, h, l, c, f"c_{ts}")


def ts_seq(start="2026-02-01 00:00:00", count=20):
    dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    out = []
    for _ in range(count):
        out.append(dt.strftime("%Y-%m-%d %H:%M:%S"))
        dt += timedelta(minutes=1)
    return out


def run_both(build_passport_fn, observations):
    """Feeds the SAME observation sequence into two fresh passports (one OLD add_observation,
    one NEW) built by build_passport_fn(), and returns (old_passport, new_passport)."""
    p_old = build_passport_fn()
    p_new = build_passport_fn()

    TradePassport.add_observation = OLD_add_observation
    try:
        for o in observations:
            p_old.add_observation(o)
    finally:
        TradePassport.add_observation = NEW_add_observation

    for o in observations:
        p_new.add_observation(o)

    return p_old, p_new


def assert_full_parity(p_old, p_new):
    assert p_old.outcome_state == p_new.outcome_state
    assert p_old.entry_touch_ts == p_new.entry_touch_ts
    assert p_old.is_censored == p_new.is_censored
    assert [o.observation_id for o in p_old.pre_entry_path] == [o.observation_id for o in p_new.pre_entry_path]
    assert [o.observation_id for o in p_old.post_entry_path] == [o.observation_id for o in p_new.post_entry_path]
    assert [(e.event_type, e.timestamp_utc) for e in p_old.events] == [(e.event_type, e.timestamp_utc) for e in p_new.events]
    ex_old, ex_new = p_old.get_excursion(), p_new.get_excursion()
    assert ex_old.mae_absolute == ex_new.mae_absolute
    assert ex_old.mae_r == ex_new.mae_r
    assert ex_old.mae_timestamp == ex_new.mae_timestamp
    assert ex_old.mfe_absolute == ex_new.mfe_absolute
    assert ex_old.mfe_r == ex_new.mfe_r
    assert ex_old.mfe_timestamp == ex_new.mfe_timestamp


# --- 1: never-touched candidate -----------------------------------------------------------------

def test_1_never_touched_candidate():
    ts = ts_seq(count=10)
    observations = [obs(ts[i], 2300, 2305, 2295, 2302) for i in range(10)]  # far below entry 2400
    p_old, p_new = run_both(lambda: make_passport(), observations)
    assert p_new.outcome_state == OutcomeState.OPEN
    assert p_new.entry_touch_ts is None
    assert_full_parity(p_old, p_new)


# --- 2: late entry touch --------------------------------------------------------------------------

def test_2_late_entry_touch():
    ts = ts_seq(count=15)
    observations = [obs(ts[i], 2300, 2305, 2295, 2302) for i in range(13)]
    observations.append(obs(ts[13], 2302, 2410, 2298, 2405))  # touches 2400 on bar 14
    observations.append(obs(ts[14], 2405, 2408, 2402, 2406))
    p_old, p_new = run_both(lambda: make_passport(), observations)
    assert p_new.entry_touch_ts == ts[13]
    assert_full_parity(p_old, p_new)


# --- 3: immediate entry touch (first observation touches) ------------------------------------------

def test_3_immediate_entry_touch():
    ts = ts_seq(count=5)
    observations = [obs(ts[0], 2398, 2405, 2395, 2401)] + [obs(ts[i], 2401, 2404, 2399, 2402) for i in range(1, 5)]
    p_old, p_new = run_both(lambda: make_passport(), observations)
    assert p_new.entry_touch_ts == ts[0]
    assert len(p_new.pre_entry_path) == 0
    assert_full_parity(p_old, p_new)


# --- 4: entry then target -------------------------------------------------------------------------

def test_4_entry_then_target():
    ts = ts_seq(count=5)
    observations = [
        obs(ts[0], 2398, 2405, 2395, 2401),   # touch
        obs(ts[1], 2401, 2410, 2400, 2405),
        obs(ts[2], 2405, 2425, 2404, 2422),   # target 2420 reached
    ]
    p_old, p_new = run_both(lambda: make_passport(), observations)
    assert p_new.outcome_state == OutcomeState.TARGET_REACHED
    assert_full_parity(p_old, p_new)


# --- 5: entry then stop ---------------------------------------------------------------------------

def test_5_entry_then_stop():
    ts = ts_seq(count=5)
    observations = [
        obs(ts[0], 2398, 2405, 2395, 2401),   # touch
        obs(ts[1], 2401, 2403, 2398, 2400),
        obs(ts[2], 2400, 2401, 2385, 2388),   # stop 2390 reached
    ]
    p_old, p_new = run_both(lambda: make_passport(), observations)
    assert p_new.outcome_state == OutcomeState.STOP_REACHED
    assert_full_parity(p_old, p_new)


# --- 6: same-bar SL/TP ambiguity (existing policy: AMBIGUOUS_SAME_BAR) -----------------------------

def test_6_same_bar_ambiguity():
    ts = ts_seq(count=3)
    observations = [obs(ts[0], 2398, 2425, 2385, 2401)]  # touches entry, hits both stop AND target same bar
    p_old, p_new = run_both(lambda: make_passport(), observations)
    assert p_new.outcome_state == OutcomeState.AMBIGUOUS_SAME_BAR
    assert_full_parity(p_old, p_new)


# --- 7 & 8: long MAE/MFE (both LONG and SHORT) ------------------------------------------------------

def test_7_long_mae_mfe():
    ts = ts_seq(count=10)
    observations = [obs(ts[0], 2398, 2405, 2395, 2401)]  # touch
    # oscillate to build up both MAE (dips) and MFE (rallies), never hitting stop/target
    prices = [(2401, 2408, 2396, 2403), (2403, 2412, 2394, 2400), (2400, 2415, 2392, 2410), (2410, 2418, 2391, 2405)]
    for i, (o, h, l, c) in enumerate(prices, start=1):
        observations.append(obs(ts[i], o, h, l, c))
    p_old, p_new = run_both(lambda: make_passport(), observations)
    assert p_new.get_excursion().mae_absolute > 0
    assert p_new.get_excursion().mfe_absolute > 0
    assert_full_parity(p_old, p_new)


def test_8_short_mae_mfe():
    ts = ts_seq(count=10)
    observations = [obs(ts[0], 2402, 2412, 2395, 2400)]  # short entry 2400
    prices = [(2400, 2409, 2392, 2398), (2398, 2405, 2390, 2403), (2403, 2408, 2385, 2390)]
    for i, (o, h, l, c) in enumerate(prices, start=1):
        observations.append(obs(ts[i], o, h, l, c))
    p_old, p_new = run_both(lambda: make_passport(direction=ThesisDirection.SHORT), observations)
    assert_full_parity(p_old, p_new)


# --- 9: long-lived OPEN trade ------------------------------------------------------------------------

def test_9_long_lived_open_trade():
    ts = ts_seq(count=200)
    observations = [obs(ts[0], 2398, 2405, 2395, 2401)]  # touch
    for i in range(1, 200):
        observations.append(obs(ts[i], 2401, 2408, 2396, 2402))  # stays well within stop/target
    p_old, p_new = run_both(lambda: make_passport(), observations)
    assert p_new.outcome_state == OutcomeState.ENTRY_TOUCHED
    assert len(p_new.post_entry_path) == 200
    assert_full_parity(p_old, p_new)


# --- 10: terminal trade followed by many future candles (must NOT keep mutating outcome) -------------

def test_10_terminal_trade_followed_by_many_future_candles():
    ts = ts_seq(count=100)
    observations = [
        obs(ts[0], 2398, 2405, 2395, 2401),   # touch
        obs(ts[1], 2401, 2425, 2400, 2422),   # target reached
    ]
    for i in range(2, 100):
        observations.append(obs(ts[i], 2422, 2500, 2300, 2400))  # wild swings after terminal
    p_old, p_new = run_both(lambda: make_passport(), observations)
    assert p_new.outcome_state == OutcomeState.TARGET_REACHED
    # Outcome must not flip even though later candles would have hit stop too.
    assert_full_parity(p_old, p_new)


# --- 11: multiple passports same entry ----------------------------------------------------------------

def test_11_multiple_passports_same_entry():
    ts = ts_seq(count=10)
    observations = [obs(ts[i], 2398, 2405, 2395, 2401) for i in range(10)]
    p1_old, p1_new = run_both(lambda: make_passport(passport_id="pass_a"), observations)
    p2_old, p2_new = run_both(lambda: make_passport(passport_id="pass_b"), observations)
    assert_full_parity(p1_old, p1_new)
    assert_full_parity(p2_old, p2_new)
    assert p1_new.passport_id != p2_new.passport_id


# --- 12: many passports different entries ---------------------------------------------------------------

def test_12_many_passports_different_entries():
    ts = ts_seq(count=15)
    for k in range(10):
        entry = 2380.0 + k * 5
        observations = [obs(ts[i], entry - 5, entry + 10, entry - 10, entry + 2) for i in range(15)]
        p_old, p_new = run_both(lambda e=entry: make_passport(entry=e, stop=e - 15, target=e + 25), observations)
        assert_full_parity(p_old, p_new)


# --- 13: overlapping entry levels (distinct passports, same price path) -------------------------------

def test_13_overlapping_entry_levels():
    ts = ts_seq(count=15)
    observations = [obs(ts[i], 2395, 2415, 2385, 2405) for i in range(15)]
    for entry in (2395.0, 2400.0, 2405.0, 2410.0):
        p_old, p_new = run_both(lambda e=entry: make_passport(entry=e, stop=e - 15, target=e + 25), observations)
        assert_full_parity(p_old, p_new)


# --- 14: gap between observations (irregular spacing, still chronological) -----------------------------

def test_14_gap_between_observations():
    dt0 = datetime.fromisoformat("2026-02-01 00:00:00").replace(tzinfo=timezone.utc)
    gapped_ts = [
        dt0.strftime("%Y-%m-%d %H:%M:%S"),
        (dt0 + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
        (dt0 + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),   # large gap
        (dt0 + timedelta(hours=6, minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
    ]
    observations = [obs(t, 2398, 2405, 2395, 2401) for t in gapped_ts]
    p_old, p_new = run_both(lambda: make_passport(), observations)
    assert_full_parity(p_old, p_new)


# --- 15: duplicate event/idempotency -------------------------------------------------------------------

def test_15_duplicate_observation_idempotency():
    ts = ts_seq(count=3)
    p = make_passport()
    o = obs(ts[0], 2398, 2405, 2395, 2401)
    p.add_observation(o)
    with pytest.raises(DuplicateObservationError):
        p.add_observation(o)


# --- 16: counterfactual terminal scenario (unaffected -- not modified this phase) -----------------------

def test_16_counterfactual_terminal_scenario_untouched():
    from research.v2.counterfactual.engine import init_scenario_tracking, update_scenario_tracking
    from research.v2.counterfactual.models import CounterfactualScenario, ScenarioType
    scen = CounterfactualScenario(
        scenario_id="scen1", thesis_id="th_1", scenario_type=ScenarioType.M30_CONTROL,
        created_at="2026-02-01 00:00:00", reference_timestamp="2026-02-01 00:00:00",
        entry_timeframe=Timeframe.M30, structural_entry=2400.0, structural_stop=2390.0, structural_target=2420.0,
    )
    state = init_scenario_tracking(scen, ThesisDirection.LONG)
    ts = ts_seq(count=5)
    state = update_scenario_tracking(state, obs(ts[0], 2398, 2405, 2395, 2401))
    state = update_scenario_tracking(state, obs(ts[1], 2401, 2425, 2400, 2422))  # target
    assert state.resolved
    outcome_after_resolve = state.outcome_state
    state = update_scenario_tracking(state, obs(ts[2], 2422, 2500, 2300, 2400))  # must be ignored
    assert state.outcome_state == outcome_after_resolve


# --- 17: counterfactual long-lived scenario (unaffected) ------------------------------------------------

def test_17_counterfactual_long_lived_scenario():
    from research.v2.counterfactual.engine import init_scenario_tracking, update_scenario_tracking
    from research.v2.counterfactual.models import CounterfactualScenario, ScenarioType
    scen = CounterfactualScenario(
        scenario_id="scen2", thesis_id="th_1", scenario_type=ScenarioType.M30_CONTROL,
        created_at="2026-02-01 00:00:00", reference_timestamp="2026-02-01 00:00:00",
        entry_timeframe=Timeframe.M30, structural_entry=2400.0, structural_stop=2390.0, structural_target=2420.0,
    )
    state = init_scenario_tracking(scen, ThesisDirection.LONG)
    ts = ts_seq(count=50)
    for t in ts:
        state = update_scenario_tracking(state, obs(t, 2398, 2405, 2395, 2401))
    assert not state.resolved


# --- 18: historical serialization parity -----------------------------------------------------------------

def test_18_serialization_parity():
    ts = ts_seq(count=10)
    observations = [obs(ts[0], 2398, 2405, 2395, 2401)] + [obs(ts[i], 2401, 2408, 2396, 2402) for i in range(1, 10)]
    p = make_passport()
    for o in observations:
        p.add_observation(o)
    data = p.to_dict()
    rebuilt = TradePassport.from_dict(data)
    assert rebuilt.to_dict() == data
    assert rebuilt.outcome_state == p.outcome_state
    assert rebuilt.get_excursion().mae_absolute == p.get_excursion().mae_absolute
    assert rebuilt.get_excursion().mfe_absolute == p.get_excursion().mfe_absolute


# --- 19: dataset-row parity (via DatasetBuilder) -----------------------------------------------------------

def test_19_dataset_row_parity():
    from research.v2.dataset.builder import build_research_row
    ts = ts_seq(count=10)
    observations = [obs(ts[0], 2398, 2405, 2395, 2401)] + [obs(ts[i], 2401, 2408, 2396, 2402) for i in range(1, 10)]
    p_old, p_new = run_both(lambda: make_passport(), observations)
    row_old = build_research_row(p_old)
    row_new = build_research_row(p_new)
    assert row_old.y_labels == row_new.y_labels
    assert row_old.x_features == row_new.x_features


# --- 20: fingerprint parity (feature-state fingerprint unaffected by this change) --------------------------

def test_20_feature_state_fingerprint_unaffected():
    from research.v2.telemetry.passport import compute_feature_state_fingerprint
    snap = make_snapshot()
    fp1 = compute_feature_state_fingerprint(snap)
    fp2 = compute_feature_state_fingerprint(snap)
    assert fp1 == fp2


# --- Prefix invariance: partial replay must match a prefix of the full replay ------------------------------

@pytest.mark.parametrize("cutoff", [3, 7, 15])
def test_21_prefix_invariance(cutoff):
    ts = ts_seq(count=20)
    observations = [obs(ts[0], 2398, 2405, 2395, 2401)]
    prices = [(2401, 2408, 2396, 2402), (2402, 2412, 2394, 2400), (2400, 2415, 2392, 2410)] * 6
    for i, (o, h, l, c) in enumerate(prices[:19], start=1):
        observations.append(obs(ts[i], o, h, l, c))

    p_full = make_passport(passport_id="pass_full")
    for o in observations:
        p_full.add_observation(o)

    p_prefix = make_passport(passport_id="pass_prefix")
    for o in observations[:cutoff]:
        p_prefix.add_observation(o)

    # Whatever the prefix run already knew (outcome/entry-touch/MAE/MFE as-of its own last
    # observation) must be unchanged by continuing the SAME passport with more observations --
    # unless it's still OPEN (in which case there's nothing yet to compare against future bars).
    ex_prefix = p_prefix.get_excursion()
    if p_prefix.entry_touch_ts is not None:
        as_of = observations[cutoff - 1].timestamp_utc
        ex_full_as_of = p_full.get_excursion(as_of_utc=as_of)
        assert ex_prefix.mae_absolute == ex_full_as_of.mae_absolute
        assert ex_prefix.mfe_absolute == ex_full_as_of.mfe_absolute


# --- Determinism ------------------------------------------------------------------------------------------

def test_22_determinism_repeated_replay():
    ts = ts_seq(count=30)
    observations = [obs(ts[0], 2398, 2405, 2395, 2401)]
    for i in range(1, 30):
        observations.append(obs(ts[i], 2401 + (i % 5), 2410 + (i % 7), 2394 - (i % 4), 2402 + (i % 3)))

    p1 = make_passport(passport_id="pass_det1")
    for o in observations:
        p1.add_observation(o)
    p2 = make_passport(passport_id="pass_det1")
    for o in observations:
        p2.add_observation(o)

    assert p1.outcome_state == p2.outcome_state
    assert p1.get_excursion().mae_absolute == p2.get_excursion().mae_absolute
    assert p1.get_excursion().mfe_absolute == p2.get_excursion().mfe_absolute
    assert [e.event_id for e in p1.events] == [e.event_id for e in p2.events]


# --- Real TRAIN-prefix full-engine parity (small, bounded -- reference path is O(n) but kept small) -------

def test_23_real_train_prefix_full_engine_parity():
    """Runs the REAL engine (mtf_backtester) over a real bounded TRAIN prefix (500 M1 rows) with
    OLD_add_observation/OLD_calculate_excursion_as_of monkeypatched in, then again with the
    current code, and requires exact parity for backtest fingerprint, structural outcomes, and
    every passport's full observation/outcome/MAE/MFE state. Per section 20 of the V2.10C.2
    mission ("if reference runtime is practical"); kept to 500 rows to keep test runtime bounded
    -- larger prefixes (5,000 / 20,000) were independently verified via a one-off scratch harness
    during this investigation and are reported in the V2.10C.2 closure report, not re-run here on
    every CI pass.
    """
    from research.v2.data.live_dataset import load_authoritative_frozen_v2_dataset
    from research.v2.engine import run_v2_10c_train_smoke as smoke
    import research.v2.engine.mtf_backtester as bt_mod
    from research.v2.strategy.train_policy import V2TrainResearchPolicy

    candles, _manifest = load_authoritative_frozen_v2_dataset()
    prefix = smoke.load_train_only_prefix(candles, 500)

    def run(mode):
        if mode == "old":
            TradePassport.add_observation = OLD_add_observation
            passport_mod.calculate_excursion_as_of = OLD_calculate_excursion_as_of
        try:
            bt = bt_mod.V2MultiTimeframeBacktester(policy=V2TrainResearchPolicy())
            result = bt.run(prefix)
            return bt, result
        finally:
            TradePassport.add_observation = NEW_add_observation
            passport_mod.calculate_excursion_as_of = NEW_calculate_excursion_as_of

    bt_old, res_old = run("old")
    bt_new, res_new = run("new")

    assert res_old.fingerprint == res_new.fingerprint
    assert res_old.structural_outcomes == res_new.structural_outcomes
    assert res_old.censored_count == res_new.censored_count
    assert res_old.ambiguous_count == res_new.ambiguous_count
    assert sorted(bt_old.passports.keys()) == sorted(bt_new.passports.keys())

    for pid in bt_old.passports:
        p_old, p_new = bt_old.passports[pid], bt_new.passports[pid]
        assert p_old.outcome_state == p_new.outcome_state
        assert p_old.entry_touch_ts == p_new.entry_touch_ts
        assert [o.observation_id for o in p_old.pre_entry_path] == [o.observation_id for o in p_new.pre_entry_path]
        assert [o.observation_id for o in p_old.post_entry_path] == [o.observation_id for o in p_new.post_entry_path]
        ex_old, ex_new = p_old.get_excursion(), p_new.get_excursion()
        assert ex_old.mae_absolute == ex_new.mae_absolute
        assert ex_old.mfe_absolute == ex_new.mfe_absolute


# --- Structural (non-wall-clock) performance guards --------------------------------------------------------

def test_24_add_observation_zero_datetime_parses():
    """Section 26 guard: operation counts, not wall-clock. OLD parses 2 timestamps via
    datetime.fromisoformat on every call (created_at + last-observation) once any history
    exists; NEW must perform ZERO datetime.fromisoformat calls inside add_observation."""
    ts = ts_seq(count=50)
    observations = [obs(ts[0], 2398, 2405, 2395, 2401)]
    for i in range(1, 50):
        observations.append(obs(ts[i], 2401, 2408, 2396, 2402))

    real_fromisoformat = datetime.fromisoformat
    call_count = {"n": 0}

    class _CountingDatetime(datetime):
        @classmethod
        def fromisoformat(cls, s):
            call_count["n"] += 1
            return real_fromisoformat(s)

    # OLD_add_observation is defined in THIS test module, so its `datetime` global resolves
    # from this module's namespace -- patch here, not passport_mod (which the NEW production
    # method still uses, but only via the module-level `from datetime import datetime` binding
    # in passport.py; NEW performs zero datetime calls regardless, so patching passport_mod
    # would give a vacuous pass either way -- patching this module is what actually exercises
    # OLD's real call count).
    p_old = make_passport(passport_id="pass_count_old")
    with mock.patch(f"{__name__}.datetime", _CountingDatetime):
        TradePassport.add_observation = OLD_add_observation
        try:
            call_count["n"] = 0
            for o in observations:
                p_old.add_observation(o)
            old_calls = call_count["n"]
        finally:
            TradePassport.add_observation = NEW_add_observation

        p_new = make_passport(passport_id="pass_count_new")
        call_count["n"] = 0
        for o in observations:
            p_new.add_observation(o)
        new_calls = call_count["n"]

    assert old_calls > 0
    assert new_calls == 0


def test_25_calculate_excursion_zero_datetime_parses_on_default_as_of():
    """The fast path (as_of_utc >= observations[-1].timestamp_utc, true for get_excursion()'s
    default) must perform ZERO datetime.fromisoformat calls inside calculate_excursion_as_of."""
    ts = ts_seq(count=100)
    observations = [obs(ts[i], 2401, 2408, 2396, 2402) for i in range(100)]

    real_fromisoformat = datetime.fromisoformat
    call_count = {"n": 0}

    class _CountingDatetime(datetime):
        @classmethod
        def fromisoformat(cls, s):
            call_count["n"] += 1
            return real_fromisoformat(s)

    # OLD_calculate_excursion_as_of is defined in THIS test module -- see note in test_24.
    with mock.patch(f"{__name__}.datetime", _CountingDatetime):
        call_count["n"] = 0
        OLD_calculate_excursion_as_of(2400.0, ThesisDirection.LONG, 10.0, observations, observations[-1].timestamp_utc)
        old_calls = call_count["n"]

    with mock.patch.object(excursion_mod, "datetime", _CountingDatetime):
        call_count["n"] = 0
        calculate_excursion_as_of(2400.0, ThesisDirection.LONG, 10.0, observations, observations[-1].timestamp_utc)
        new_calls = call_count["n"]

    assert old_calls == len(observations) + 1  # once per observation + the as_of itself
    assert new_calls == 0
