"""
NOAFVGBOT V2.6 — Research Dataset Builder & Exporter.

Converts V2 TradePassports into scientifically safe research dataset rows (X features vs Y labels),
computes content & schema-sensitive deterministic dataset fingerprints, and exports rows.

INVARIANTS:
- Decision time features (X) use ONLY information known at candidate creation time.
- Missing feature values remain None (never 0 or mean-imputed).
- Outcome labels (Y) are strictly isolated from decision features.
- Full dataset fingerprint changes if ANY content, label, feature, schema, or builder version changes.
"""

import csv
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from research.v2.telemetry.passport import TradePassport, OutcomeState
from research.v2.dataset.schema import (
    ResearchRow,
    ResearchLabels,
    SCHEMA_VERSION,
    BUILDER_VERSION,
    FEATURE_MANIFEST,
    LABEL_MANIFEST,
    validate_no_leakage,
)


@dataclass(frozen=True)
class DatasetSummary:
    total_passports: int
    unique_theses: int
    long_count: int
    short_count: int
    m5_count: int
    m3_count: int
    entry_touched_count: int
    entry_untouched_count: int
    clean_target_count: int
    clean_stop_count: int
    ambiguous_count: int
    censored_count: int
    dataset_fingerprint: str
    builder_version: str = BUILDER_VERSION
    schema_version: str = SCHEMA_VERSION


def build_research_row(passport: TradePassport) -> ResearchRow:
    """Converts a single TradePassport into a validated ResearchRow."""
    snap = passport.decision_snapshot

    # ID fields
    id_fields = {
        "passport_id": passport.passport_id,
        "thesis_id": passport.thesis_id,
        "candidate_id": passport.candidate_id,
        "symbol": passport.symbol,
        "direction": passport.direction.value,
        "candidate_timeframe": passport.candidate_timeframe.name,
        "candidate_created_at": passport.created_at,
    }

    # Decision-Time X Features
    x_features: Dict[str, Any] = {
        "candidate_structural_entry": snap.structural_entry,
        "candidate_structural_stop": snap.structural_stop,
        "candidate_structural_target": snap.structural_target,
        "candidate_risk_distance": abs(snap.structural_entry - snap.structural_stop),
        "candidate_target_distance": abs(snap.structural_target - snap.structural_entry) if snap.structural_target else None,
        "mtf_m15_confirmation_present": "M15" in snap.mtf_trace,
        "mtf_m3_refinement_present": "M3" in snap.mtf_trace,
    }

    feature_known_at: Dict[str, str] = {}
    feature_lineage: Dict[str, Dict[str, Any]] = {}

    # Extract decision features from FeatureRecords
    for rec in snap.feature_records:
        for val_key, val in rec.values.items():
            feat_col_name = f"{rec.feature_type.lower()}.{val_key}"
            x_features[feat_col_name] = val
            feature_known_at[feat_col_name] = rec.known_at_timestamp
            feature_lineage[feat_col_name] = {
                "source_type": rec.feature_type,
                "known_at_timestamp": rec.known_at_timestamp,
                "phase": rec.phase.value,
                "aggregation_rule": "EXACT",
            }

    # Extract liquidity distance features
    nearest_buy: Optional[float] = None
    nearest_sell: Optional[float] = None
    buy_known_at: Optional[str] = None
    sell_known_at: Optional[str] = None

    for lp in snap.liquidity_pools:
        dist = abs(lp.price - snap.structural_entry)
        if lp.side.name == "BUY_SIDE":
            if nearest_buy is None or dist < nearest_buy:
                nearest_buy = dist
                buy_known_at = lp.known_at_timestamp
        elif lp.side.name == "SELL_SIDE":
            if nearest_sell is None or dist < nearest_sell:
                nearest_sell = dist
                sell_known_at = lp.known_at_timestamp

    x_features["liquidity_nearest_buy_distance"] = nearest_buy
    x_features["liquidity_nearest_sell_distance"] = nearest_sell
    if buy_known_at:
        feature_known_at["liquidity_nearest_buy_distance"] = buy_known_at
        feature_lineage["liquidity_nearest_buy_distance"] = {
            "source_type": "LIQUIDITY_POOL",
            "known_at_timestamp": buy_known_at,
            "aggregation_rule": "MIN_DISTANCE",
        }
    if sell_known_at:
        feature_known_at["liquidity_nearest_sell_distance"] = sell_known_at
        feature_lineage["liquidity_nearest_sell_distance"] = {
            "source_type": "LIQUIDITY_POOL",
            "known_at_timestamp": sell_known_at,
            "aggregation_rule": "MIN_DISTANCE",
        }

    # Outcome Y Labels
    ex = passport.get_excursion()
    touched = passport._entry_touched
    state_str = passport.outcome_state.value

    clean_label: Optional[str] = None
    if touched and not passport.is_censored:
        if passport.outcome_state == OutcomeState.TARGET_REACHED:
            clean_label = "TARGET"
        elif passport.outcome_state == OutcomeState.STOP_REACHED:
            clean_label = "STOP"

    y_labels: Dict[str, Any] = {
        "entry_touched": touched,
        "outcome_state": state_str,
        "clean_label": clean_label,
        "mae_r": ex.mae_r,
        "mfe_r": ex.mfe_r,
        "mae_absolute": ex.mae_absolute,
        "mfe_absolute": ex.mfe_absolute,
        "is_ambiguous": passport.outcome_state == OutcomeState.AMBIGUOUS_SAME_BAR,
        "is_censored": passport.is_censored,
        "censor_reason": passport._censor_reason,
    }

    label_known_at: Dict[str, str] = {}
    last_obs_ts = passport.post_entry_path[-1].timestamp_utc if passport.post_entry_path else passport.created_at
    for y_key in y_labels.keys():
        label_known_at[y_key] = last_obs_ts

    meta_fields = {
        "config_fingerprint": passport.config_fingerprint,
        "strategy_version": passport.strategy_version,
        "schema_version": SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "feature_known_at": feature_known_at,
        "label_known_at": label_known_at,
        "feature_lineage": feature_lineage,
    }

    row = ResearchRow(
        id_fields=id_fields,
        x_features=x_features,
        y_labels=y_labels,
        meta_fields=meta_fields,
        schema_version=SCHEMA_VERSION,
    )

    # Validate zero target leakage
    validate_no_leakage(row)
    return row


def compute_dataset_fingerprint(
    rows: List[ResearchRow],
    config_fp: str = "default_fp",
    builder_version: str = BUILDER_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    """
    Computes a content & schema-sensitive deterministic SHA256 fingerprint for a list of research rows.
    Changes whenever any x value, y value, id value, null status, manifest, or schema version changes.
    """
    hasher = hashlib.sha256()

    # Header section
    header = {
        "builder_version": builder_version,
        "schema_version": schema_version,
        "config_fingerprint": config_fp,
        "feature_manifest_keys": sorted(list(FEATURE_MANIFEST.keys())),
        "label_manifest_keys": sorted(list(LABEL_MANIFEST.keys())),
    }
    hasher.update(json.dumps(header, sort_keys=True).encode("utf-8"))

    # Canonical sorting by (candidate_created_at, passport_id)
    sorted_rows = sorted(
        rows,
        key=lambda r: (r.id_fields["candidate_created_at"], r.id_fields["passport_id"])
    )

    for r in sorted_rows:
        row_dict = r.to_flat_dict()
        row_str = json.dumps(row_dict, sort_keys=True, default=str)
        hasher.update(row_str.encode("utf-8"))

    return hasher.hexdigest()


class DatasetBuilder:
    """Builds and validates a research dataset from TradePassports."""

    def __init__(self, passports: List[TradePassport]):
        self.passports = passports

    def build_rows(self) -> List[ResearchRow]:
        """Converts passports into validated ResearchRows."""
        rows: List[ResearchRow] = []
        seen_passports = set()

        for p in self.passports:
            if p.passport_id in seen_passports:
                raise ValueError(f"Duplicate passport_id detected: {p.passport_id}")
            seen_passports.add(p.passport_id)

            row = build_research_row(p)
            rows.append(row)

        return rows

    def summarize(self, rows: List[ResearchRow]) -> DatasetSummary:
        """Generates compact statistical summary of the research dataset."""
        theses = set()
        longs = 0
        shorts = 0
        m5s = 0
        m3s = 0
        touched = 0
        untouched = 0
        targets = 0
        stops = 0
        ambiguous = 0
        censored = 0

        for r in rows:
            theses.add(r.id_fields["thesis_id"])
            if r.id_fields["direction"] == "LONG":
                longs += 1
            else:
                shorts += 1

            if r.id_fields["candidate_timeframe"] == "M5":
                m5s += 1
            else:
                m3s += 1

            if r.y_labels["entry_touched"]:
                touched += 1
            else:
                untouched += 1

            if r.y_labels["clean_label"] == "TARGET":
                targets += 1
            elif r.y_labels["clean_label"] == "STOP":
                stops += 1

            if r.y_labels["is_ambiguous"]:
                ambiguous += 1
            if r.y_labels["is_censored"]:
                censored += 1

        fp = compute_dataset_fingerprint(rows)

        return DatasetSummary(
            total_passports=len(rows),
            unique_theses=len(theses),
            long_count=longs,
            short_count=shorts,
            m5_count=m5s,
            m3_count=m3s,
            entry_touched_count=touched,
            entry_untouched_count=untouched,
            clean_target_count=targets,
            clean_stop_count=stops,
            ambiguous_count=ambiguous,
            censored_count=censored,
            dataset_fingerprint=fp,
        )


def export_jsonl(rows: List[ResearchRow], filepath: str) -> None:
    """Exports research rows deterministically to JSONL format."""
    sorted_rows = sorted(rows, key=lambda r: (r.id_fields["candidate_created_at"], r.id_fields["passport_id"]))
    with open(filepath, "w", encoding="utf-8") as f:
        for r in sorted_rows:
            f.write(json.dumps(r.to_flat_dict(), sort_keys=True) + "\n")


def export_csv(rows: List[ResearchRow], filepath: str) -> None:
    """Exports research rows deterministically to CSV format."""
    sorted_rows = sorted(rows, key=lambda r: (r.id_fields["candidate_created_at"], r.id_fields["passport_id"]))
    if not sorted_rows:
        return

    flat_rows = [r.to_flat_dict() for r in sorted_rows]
    fieldnames = sorted(flat_rows[0].keys())

    with open(filepath, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for fr in flat_rows:
            writer.writerow(fr)


def import_jsonl(filepath: str) -> List[ResearchRow]:
    """Imports research rows from JSONL format and validates structure."""
    rows: List[ResearchRow] = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            flat_dict = json.loads(line)

            id_fields = {}
            x_features = {}
            y_labels = {}
            meta_fields = {}

            for k, v in flat_dict.items():
                if k.startswith("id."):
                    id_fields[k[3:]] = v
                elif k.startswith("x."):
                    x_features[k[2:]] = v
                elif k.startswith("y."):
                    y_labels[k[2:]] = v
                elif k.startswith("meta."):
                    meta_fields[k[5:]] = v

            row = ResearchRow(
                id_fields=id_fields,
                x_features=x_features,
                y_labels=y_labels,
                meta_fields=meta_fields,
            )
            rows.append(row)
    return rows
