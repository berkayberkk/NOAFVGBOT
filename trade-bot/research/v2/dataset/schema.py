"""
NOAFVGBOT V2.6 — Leakage-Safe Research Dataset Schema & Validation.

Defines the ResearchRow, ResearchLabels, FeatureManifest, LabelManifest,
and manifest/provenance leakage validation rules for scientifically safe research datasets.

INVARIANTS:
- Strict namespace separation: id.*, x.* (decision time), y.* (outcome labels), meta.*.
- Manifest-based enforcement: Every x.* feature must exist in FEATURE_MANIFEST (decision_time_only=True).
- validate_no_leakage enforces known_at_timestamp <= candidate_created_at and manifest separation.
- Missing values remain None (never substituted with 0 or mean).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional, Set, Tuple

SCHEMA_VERSION = "2.6"
BUILDER_VERSION = "2.6.0"


@dataclass(frozen=True)
class FeatureManifestItem:
    name: str
    description: str
    source_type: str
    unit: str
    decision_time_only: bool = True
    aggregation_rule: str = "EXACT"


@dataclass(frozen=True)
class LabelManifestItem:
    name: str
    description: str
    source_type: str
    censoring_behavior: str
    ambiguity_behavior: str


# Canonical Feature Manifest (x.* fields)
FEATURE_MANIFEST: Dict[str, FeatureManifestItem] = {
    "candidate_structural_entry": FeatureManifestItem("candidate_structural_entry", "Structural entry price", "CANDIDATE", "PRICE", True, "EXACT"),
    "candidate_structural_stop": FeatureManifestItem("candidate_structural_stop", "Structural stop loss price", "CANDIDATE", "PRICE", True, "EXACT"),
    "candidate_structural_target": FeatureManifestItem("candidate_structural_target", "Optional structural take-profit price", "CANDIDATE", "PRICE", True, "EXACT"),
    "candidate_risk_distance": FeatureManifestItem("candidate_risk_distance", "Absolute risk distance |entry - stop|", "CANDIDATE", "PRICE_DIFF", True, "EXACT"),
    "candidate_target_distance": FeatureManifestItem("candidate_target_distance", "Absolute target distance |target - entry|", "CANDIDATE", "PRICE_DIFF", True, "EXACT"),
    "mtf_m15_confirmation_present": FeatureManifestItem("mtf_m15_confirmation_present", "Flag if M15 evidence was present prior to candidate", "MTF_TRACE", "BOOLEAN", True, "EXACT"),
    "mtf_m3_refinement_present": FeatureManifestItem("mtf_m3_refinement_present", "Flag if M3 refinement evidence was present prior to candidate", "MTF_TRACE", "BOOLEAN", True, "EXACT"),
    "fvg.gap_size": FeatureManifestItem("fvg.gap_size", "Fair value gap absolute size", "FVG", "PRICE_DIFF", True, "EXACT"),
    "fvg.gap_to_atr_ratio": FeatureManifestItem("fvg.gap_to_atr_ratio", "Fair value gap size to ATR ratio", "FVG", "RATIO", True, "EXACT"),
    "fvg.middle_candle_range": FeatureManifestItem("fvg.middle_candle_range", "Middle candle high - low", "FVG", "PRICE_DIFF", True, "EXACT"),
    "fvg.middle_candle_body": FeatureManifestItem("fvg.middle_candle_body", "Middle candle |close - open|", "FVG", "PRICE_DIFF", True, "EXACT"),
    "fvg.displacement_range": FeatureManifestItem("fvg.displacement_range", "Displacement candle range", "FVG", "PRICE_DIFF", True, "EXACT"),
    "fvg.displacement_body": FeatureManifestItem("fvg.displacement_body", "Displacement candle body", "FVG", "PRICE_DIFF", True, "EXACT"),
    "fvg.source_zone_width": FeatureManifestItem("fvg.source_zone_width", "Source zone width", "FVG", "PRICE_DIFF", True, "EXACT"),
    "ob.zone_width": FeatureManifestItem("ob.zone_width", "Order block zone width", "OB", "PRICE_DIFF", True, "EXACT"),
    "ob.zone_width_to_atr": FeatureManifestItem("ob.zone_width_to_atr", "Order block zone width to ATR ratio", "OB", "RATIO", True, "EXACT"),
    "ob.source_candle_range": FeatureManifestItem("ob.source_candle_range", "Source candle range", "OB", "PRICE_DIFF", True, "EXACT"),
    "ob.source_candle_body": FeatureManifestItem("ob.source_candle_body", "Source candle body", "OB", "PRICE_DIFF", True, "EXACT"),
    "ob.impulse_candle_range": FeatureManifestItem("ob.impulse_candle_range", "Impulse candle range", "OB", "PRICE_DIFF", True, "EXACT"),
    "ob.impulse_candle_body": FeatureManifestItem("ob.impulse_candle_body", "Impulse candle body", "OB", "PRICE_DIFF", True, "EXACT"),
    "ob.displacement_distance": FeatureManifestItem("ob.displacement_distance", "Displacement distance", "OB", "PRICE_DIFF", True, "EXACT"),
    "liquidity_nearest_buy_distance": FeatureManifestItem("liquidity_nearest_buy_distance", "Distance to nearest known buy-side liquidity pool as of decision time", "LIQUIDITY", "PRICE_DIFF", True, "MIN_DISTANCE"),
    "liquidity_nearest_sell_distance": FeatureManifestItem("liquidity_nearest_sell_distance", "Distance to nearest known sell-side liquidity pool as of decision time", "LIQUIDITY", "PRICE_DIFF", True, "MIN_DISTANCE"),
}

# Canonical Label Manifest (y.* fields)
LABEL_MANIFEST: Dict[str, LabelManifestItem] = {
    "entry_touched": LabelManifestItem("entry_touched", "Boolean indicator if structural entry was touched post-candidate creation", "PATH_TELEMETRY", "PRESERVED", "EXPLICIT"),
    "outcome_state": LabelManifestItem("outcome_state", "Terminal research outcome state", "RESEARCH_OUTCOME", "PRESERVED", "EXPLICIT"),
    "clean_label": LabelManifestItem("clean_label", "Clean target/stop label (TARGET, STOP, or None)", "RESEARCH_OUTCOME", "EXCLUDED_IF_UNCERTAIN", "EXCLUDED_IF_AMBIGUOUS"),
    "mae_r": LabelManifestItem("mae_r", "Maximum Adverse Excursion in R multiples", "EXCURSION", "CENSORED_AT_END", "EXPLICIT"),
    "mfe_r": LabelManifestItem("mfe_r", "Maximum Favorable Excursion in R multiples", "EXCURSION", "CENSORED_AT_END", "EXPLICIT"),
    "mae_absolute": LabelManifestItem("mae_absolute", "Absolute Maximum Adverse Excursion price distance", "EXCURSION", "CENSORED_AT_END", "EXPLICIT"),
    "mfe_absolute": LabelManifestItem("mfe_absolute", "Absolute Maximum Favorable Excursion price distance", "EXCURSION", "CENSORED_AT_END", "EXPLICIT"),
    "is_ambiguous": LabelManifestItem("is_ambiguous", "Boolean indicator for intrabar same-candle collisions", "RESEARCH_OUTCOME", "PRESERVED", "EXPLICIT"),
    "is_censored": LabelManifestItem("is_censored", "Boolean indicator if research path was censored", "RESEARCH_OUTCOME", "EXPLICIT", "PRESERVED"),
    "censor_reason": LabelManifestItem("censor_reason", "Reason for path censoring", "RESEARCH_OUTCOME", "EXPLICIT", "PRESERVED"),
}


@dataclass(frozen=True)
class ResearchLabels:
    entry_touched: bool
    outcome_state: str
    clean_label: Optional[str] = None  # "TARGET", "STOP", or None (if AMBIGUOUS / CENSORED / UNTOUCHED)
    mae_r: float = 0.0
    mfe_r: float = 0.0
    mae_absolute: float = 0.0
    mfe_absolute: float = 0.0
    bars_to_entry_touch: Optional[int] = None
    is_ambiguous: bool = False
    is_censored: bool = False
    censor_reason: str = ""


@dataclass(frozen=True)
class ResearchRow:
    id_fields: Dict[str, Any]
    x_features: Dict[str, Any]
    y_labels: Dict[str, Any]
    meta_fields: Dict[str, Any]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        try:
            json.dumps(self.id_fields)
            json.dumps(self.x_features)
            json.dumps(self.y_labels)
            json.dumps(self.meta_fields)
        except Exception as e:
            raise ValueError(f"ResearchRow fields must be JSON-serializable: {e}")

    def to_flat_dict(self) -> Dict[str, Any]:
        """Flattens row into explicitly namespaced dictionary keys (id.*, x.*, y.*, meta.*)."""
        res: Dict[str, Any] = {}
        for k in sorted(self.id_fields.keys()):
            res[f"id.{k}"] = self.id_fields[k]
        for k in sorted(self.x_features.keys()):
            res[f"x.{k}"] = self.x_features[k]
        for k in sorted(self.y_labels.keys()):
            res[f"y.{k}"] = self.y_labels[k]
        for k in sorted(self.meta_fields.keys()):
            res[f"meta.{k}"] = self.meta_fields[k]
        return res


def validate_no_leakage(row: ResearchRow) -> bool:
    """
    Provenance & Manifest-Based Leakage Validation.
    Fails closed if:
    1. Any x.* feature is not registered in FEATURE_MANIFEST with decision_time_only=True.
    2. Any y.* label is present under x.*.
    3. Any x.* feature known_at_timestamp > candidate_created_at.
    4. Any y.* label availability timestamp < candidate_created_at.
    """
    # 1. Manifest verification for x_features
    for x_key in row.x_features.keys():
        if x_key not in FEATURE_MANIFEST:
            raise ValueError(f"Unregistered feature key under x.*: {x_key}")
        item = FEATURE_MANIFEST[x_key]
        if not item.decision_time_only:
            raise ValueError(f"Feature {x_key} is marked decision_time_only=False")
        if x_key in LABEL_MANIFEST:
            raise ValueError(f"Label manifest field {x_key} illegally present under x.*")

    # 2. Check forbidden label substrings as defense-in-depth
    forbidden_substrings = ["mae", "mfe", "outcome", "target_reached", "stop_reached", "censored", "pnl", "profit"]
    for x_key in row.x_features.keys():
        key_lower = x_key.lower()
        for forbidden in forbidden_substrings:
            if forbidden in key_lower:
                raise ValueError(f"Target leakage detected in feature key: {x_key}")

    # 3. Check timestamps: x known_at_timestamp <= candidate_created_at
    cand_created_at = row.id_fields.get("candidate_created_at")
    if cand_created_at:
        t_cand = datetime.fromisoformat(cand_created_at).replace(tzinfo=timezone.utc)
        feature_known_at = row.meta_fields.get("feature_known_at", {})
        for feat_name, known_ts in feature_known_at.items():
            if known_ts:
                t_known = datetime.fromisoformat(known_ts).replace(tzinfo=timezone.utc)
                if t_known > t_cand:
                    raise ValueError(f"Feature timing leakage: feature {feat_name} known at {known_ts} > candidate {cand_created_at}")

        label_known_at = row.meta_fields.get("label_known_at", {})
        for lbl_name, known_ts in label_known_at.items():
            if known_ts:
                t_lbl = datetime.fromisoformat(known_ts).replace(tzinfo=timezone.utc)
                if t_lbl < t_cand:
                    raise ValueError(f"Label temporal anomaly: label {lbl_name} known at {known_ts} < candidate {cand_created_at}")

    return True
