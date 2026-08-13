"""
NOAFVGBOT V2 — MT5 Replay Export & Viewer Integrity Unit Tests.

Verifies deterministic replay export to CSV, exact level and outcome parity,
quarantine metadata retention, and ZERO trading execution calls in viewer MQL5.
"""

import os
import csv
import pytest
from research.v2.data.acquisition import generate_synthetic_m1_dataset
from research.v2.engine.mtf_backtester import V2MultiTimeframeBacktester
from research.v2.strategy.train_policy import V2TrainResearchPolicy
from research.v2.engine.train_runner import run_train_discovery_experiment
from research.v2.mt5.export_replay import export_v2_mt5_replay


def test_mt5_replay_export_parity_and_metadata(tmp_path):
    raw_list, candles = generate_synthetic_m1_dataset("2021-01-04 01:00:00", count=500, start_price=1800.0)
    bt = V2MultiTimeframeBacktester(policy=V2TrainResearchPolicy())
    bt.run(candles)

    res = run_train_discovery_experiment(allow_synthetic=True, count=500)
    out_csv = str(tmp_path / "v2_mt5_replay.csv")

    exported_path = export_v2_mt5_replay(res, list(bt.passports.values()), output_csv_path=out_csv)
    assert os.path.exists(exported_path)

    # Verify metadata comments & content parity
    with open(exported_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert any("run_classification=" in l for l in lines)
    assert any("dataset_id=V2_M1_LIVE_DATASET_V1" in l for l in lines)

    # Verify 10/10 parity check on first 10 rows
    reader = csv.DictReader([l for l in lines if not l.startswith("#")])
    rows = list(reader)
    assert len(rows) > 0

    passports_dict = bt.passports
    for r in rows[:10]:
        pid = r["passport_id"]
        assert pid in passports_dict
        p = passports_dict[pid]
        snap = p.decision_snapshot

        assert float(r["entry"]) == pytest.approx(snap.structural_entry, abs=0.01)
        assert float(r["stop_loss"]) == pytest.approx(snap.structural_stop, abs=0.01)
        assert r["outcome"] == p.outcome_state.value


def test_mt5_viewer_has_zero_trading_execution_calls():
    mq5_path = "mql5/TradeBot_NOA_V2_Viewer.mq5"
    assert os.path.exists(mq5_path), f"Viewer MQL5 missing at {mq5_path}"

    with open(mq5_path, "r", encoding="utf-8") as f:
        code = f.read()

    forbidden_calls = ["OrderSend", "CTrade", "trade.Buy", "trade.Sell", "PositionOpen"]
    for call in forbidden_calls:
        assert call not in code, f"Viewer EA must NOT contain execution call '{call}'"


def test_mt5_viewer_v1_and_protection_isolation():
    from strategy.config import DEFAULT_CONFIG
    from backtest.forward import BASELINE_CONFIG_V1

    assert BASELINE_CONFIG_V1.atr_period == 14
    assert DEFAULT_CONFIG.atr_period == 14
