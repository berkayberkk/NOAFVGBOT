"""
NOAFVGBOT V2 — MT5 Replay Exporter.

Exports V2 TradePassport decisions and telemetry into a deterministic CSV file
formatted for MetaTrader 5 (MT5) Visual Tester / Viewer EA rendering.

INVARIANTS:
- Preserves exact engine truth and decision parameters from TradePassport.
- Includes run classification and quarantine metadata in file header.
- Does NOT alter strategy logic, TP/SL rules, or backtest outcome values.
"""

import os
import csv
import sys
import shutil
import glob
from typing import List, Dict, Any, Optional

from research.v2.telemetry.passport import TradePassport, OutcomeState
from research.v2.data.acquisition import generate_synthetic_m1_dataset
from research.v2.engine.mtf_backtester import V2MultiTimeframeBacktester
from research.v2.strategy.train_policy import V2TrainResearchPolicy
from research.v2.engine.train_runner import run_train_discovery_experiment


def export_v2_mt5_replay(
    result_data: Dict[str, Any],
    passports: List[TradePassport],
    output_csv_path: str = "research/v2/results/v2_mt5_replay.csv",
) -> str:
    """Exports V2 trade telemetry to MT5-compatible replay CSV format."""
    os.makedirs(os.path.dirname(output_csv_path), exist_ok=True)

    exp = result_data.get("experiment", {})
    status = result_data.get("status", "UNKNOWN")
    run_scope = exp.get("run_scope", "PARTIAL_SMOKE")
    dataset_id = exp.get("dataset_id", "V2_M1_LIVE_DATASET_V1")
    ds_fp = exp.get("dataset_fingerprint", "N/A")
    exp_fp = exp.get("experiment_fingerprint", "N/A")

    fieldnames = [
        "timestamp_utc",
        "thesis_id",
        "candidate_id",
        "passport_id",
        "direction",
        "parent_timeframe",
        "candidate_timeframe",
        "entry",
        "stop_loss",
        "take_profit",
        "state",
        "entry_touch_timestamp",
        "outcome_timestamp",
        "outcome",
        "mae_r",
        "mfe_r",
    ]

    with open(output_csv_path, "w", newline="", encoding="utf-8") as f:
        # Write metadata comments
        f.write(f"# run_classification={status}|{run_scope}\n")
        f.write(f"# dataset_id={dataset_id}\n")
        f.write(f"# dataset_fingerprint={ds_fp}\n")
        f.write(f"# experiment_fingerprint={exp_fp}\n")

        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for p in passports:
            snap = p.decision_snapshot
            ex = p.get_excursion()

            outcome_ts = None
            for ev in p.events:
                if ev.event_type.value in ("TARGET_REACHED", "STOP_REACHED", "AMBIGUOUS_SAME_BAR", "CENSORED"):
                    outcome_ts = ev.timestamp_utc
                    break

            writer.writerow({
                "timestamp_utc": p.created_at,
                "thesis_id": p.thesis_id,
                "candidate_id": p.candidate_id,
                "passport_id": p.passport_id,
                "direction": p.direction.value,
                "parent_timeframe": "M30",
                "candidate_timeframe": p.candidate_timeframe.name,
                "entry": f"{snap.structural_entry:.2f}",
                "stop_loss": f"{snap.structural_stop:.2f}",
                "take_profit": f"{snap.structural_target:.2f}" if snap.structural_target is not None else "",
                "state": p.outcome_state.value,
                "entry_touch_timestamp": p.entry_touch_ts or "",
                "outcome_timestamp": outcome_ts or "",
                "outcome": p.outcome_state.value,
                "mae_r": f"{ex.mae_r:.2f}",
                "mfe_r": f"{ex.mfe_r:.2f}",
            })

    return output_csv_path


def copy_replay_to_mt5_files(csv_path: str) -> Optional[str]:
    """Copies exported replay CSV file to MetaTrader 5 MQL5/Files and Common/Files directories."""
    terminal_base = os.path.expanduser(r"~\AppData\Roaming\MetaQuotes\Terminal")
    if not os.path.exists(terminal_base):
        return None

    copied_paths = []
    
    # 1. Common Files directory (Accessible by Strategy Tester)
    common_dir = os.path.join(terminal_base, "Common", "Files")
    os.makedirs(common_dir, exist_ok=True)
    common_dest = os.path.join(common_dir, os.path.basename(csv_path))
    shutil.copy(csv_path, common_dest)
    copied_paths.append(common_dest)

    # 2. Terminal MQL5/Files directory
    files_dirs = glob.glob(os.path.join(terminal_base, "*", "MQL5", "Files"))
    for fd in files_dirs:
        dest_file = os.path.join(fd, os.path.basename(csv_path))
        shutil.copy(csv_path, dest_file)
        copied_paths.append(dest_file)

    return copied_paths[0] if copied_paths else None


if __name__ == "__main__":
    raw_list, candles = generate_synthetic_m1_dataset("2021-01-04 01:00:00", count=500, start_price=1800.0)
    bt = V2MultiTimeframeBacktester(policy=V2TrainResearchPolicy())
    bt.run(candles)

    res = run_train_discovery_experiment(allow_synthetic=True, count=500)
    out_csv = export_v2_mt5_replay(res, list(bt.passports.values()))
    print("V2 Replay CSV generated successfully at:", out_csv)

    if "--copy-to-mt5" in sys.argv:
        mt5_dest = copy_replay_to_mt5_files(out_csv)
        if mt5_dest:
            print("Copied replay CSV to MT5 Files directory:", mt5_dest)
        else:
            print("MT5 MQL5/Files directory not found on system.")
