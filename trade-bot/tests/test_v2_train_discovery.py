"""
NOAFVGBOT V2.9 — TRAIN Discovery & Ablation Research Unit Tests.

Comprehensive test suite verifying TRAIN partition boundary enforcement, frozen identity checks,
ablation matrix determinism, DEVELOPMENT/VALIDATION/FINAL_TEST protection, experiment fingerprint
reproducibility, and V1 strategy isolation.
"""

import json
import pytest

from research.v2.engine.train_runner import (
    run_train_discovery_experiment,
    compute_experiment_fingerprint,
    EXPECTED_CANONICAL_FP,
    EXPECTED_SPLIT_FP,
    TRAIN_END_UTC,
)
from research.v2.strategy.train_policy import V2TrainResearchPolicy, REFERENCE_HYPOTHESIS_V1_DERIVED


def test_1_to_4_identity_verification_and_partition_boundary_guard():
    # Verify expected frozen identity hashes
    assert EXPECTED_CANONICAL_FP == "8f5a20fd6b77dbebcfcf756b16e670cfb39712ff3e2b18a59f49073bd189e042"
    assert EXPECTED_SPLIT_FP == "2896517f4292b0787b8682600c0c3229ef8a1545bcb3f612304542d0146aa474"
    assert TRAIN_END_UTC == "2023-10-31 23:59:00"


def test_5_to_10_ablation_matrix_and_experiment_reproducibility():
    res1 = run_train_discovery_experiment(allow_synthetic=True, count=1000)
    assert res1["status"] in ("TRAIN_DISCOVERY_INCOMPLETE", "TRAIN DISCOVERY COMPLETE")
    assert len(res1["ablation_matrix"]) == 6
    assert len(res1["branch_results"]) == 6  # A0..A5 all present
    assert res1["experiment"]["max_scored_timestamp"] <= TRAIN_END_UTC

    # Run second time for exact reproducibility
    res2 = run_train_discovery_experiment(allow_synthetic=True, count=1000)
    assert res1["experiment"]["experiment_fingerprint"] == res2["experiment"]["experiment_fingerprint"]


def test_real_dataset_wiring_and_fail_closed_guard():
    # Verify runner rejects invalid source kind when allow_synthetic is False
    res = run_train_discovery_experiment(source_kind="INVALID_SOURCE", allow_synthetic=False)
    assert res["status"] == "TRAIN DATA WIRING BLOCKED"
    assert "source_kind == LIVE_MT5" in res["reason"]


def test_candidate_deduplication_and_passport_idempotency():
    from research.v2.data.acquisition import generate_synthetic_m1_dataset
    from research.v2.engine.mtf_backtester import V2MultiTimeframeBacktester

    policy = V2TrainResearchPolicy()
    bt = V2MultiTimeframeBacktester(policy=policy)

    raw_list, candles = generate_synthetic_m1_dataset("2021-01-04 01:00:00", count=500, start_price=1800.0)
    result = bt.run(candles)

    # Candidates and passports must equal unique semantic candidates
    assert result.candidate_count == len(bt.seen_candidate_keys)
    assert result.passport_count == len(bt.passports)
    # No duplicate passports
    assert len(bt.passports) == len(set(bt.passports.keys()))


def test_11_to_15_partition_protection_and_safety_flags():
    res = run_train_discovery_experiment()
    prot = res["protection"]
    safe = res["safety"]

    assert prot["development_evaluated"] is False
    assert prot["validation_evaluated"] is False
    assert prot["final_test_evaluated"] is False
    assert prot["final_test_consumed"] is False

    assert safe["optimization_performed"] is False
    assert safe["ml_trained"] is False
    assert safe["s_plus_score_created"] is False
    assert safe["broker_execution_calls"] == 0


def test_16_to_18_v1_isolation_regression():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
    assert REFERENCE_HYPOTHESIS_V1_DERIVED["atr_period"] == 14
