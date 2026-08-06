"""Deterministic fingerprinting for research datasets.

A fingerprint is a SHA-256 hex digest that depends on exactly the inputs
the sprint's reproducibility guarantee names: the raw market data, the
feature set used, the configuration in effect, the dataset schema
version, the feature-set version, the symbol, and the timeframe. Two
builds with identical inputs across all seven always produce identical
fingerprints; changing any one of them changes the fingerprint. This is
the mechanism behind "same raw data + same feature pipeline + same
configuration must always produce the same dataset identity."

Deliberately excluded: build wall-clock time. A dataset rebuilt next week
from the same seven inputs must have the same identity as it did today —
`created_at` (see `manifest.py`) is a record of *when* a build happened,
not part of *what* it is.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

import pandas as pd

from forex_daytrade.domain.symbol import Symbol
from forex_daytrade.domain.timeframe import Timeframe
from forex_daytrade.research.version import DatasetVersion, FeatureVersion


def _hash_dataframe(df: pd.DataFrame) -> str:
    """Order- and dtype-sensitive, deterministic hash of a DataFrame's content."""
    row_hashes = pd.util.hash_pandas_object(df, index=True)
    return hashlib.sha256(row_hashes.to_numpy().tobytes()).hexdigest()


def _hash_mapping(mapping: Mapping[str, str]) -> str:
    """Deterministic hash of a string-to-string mapping, independent of key order."""
    canonical = json.dumps(dict(sorted(mapping.items())), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_feature_set(feature_names: Sequence[str]) -> str:
    """Deterministic hash of a feature-name set, independent of pipeline order.

    Feature *order* never changes what any individual feature computes
    (see the Feature Layer section of ARCHITECTURE.md), so the fingerprint
    treats `feature_names` as a set, not a sequence.
    """
    canonical = "|".join(sorted(feature_names))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_fingerprint(
    *,
    raw_data: pd.DataFrame,
    feature_names: Sequence[str],
    configuration: Mapping[str, str],
    dataset_version: DatasetVersion,
    feature_version: FeatureVersion,
    symbol: Symbol,
    timeframe: Timeframe,
) -> str:
    """Compute a deterministic SHA-256 fingerprint identifying a dataset build."""
    components = (
        _hash_dataframe(raw_data),
        _hash_feature_set(feature_names),
        _hash_mapping(configuration),
        str(dataset_version),
        str(feature_version),
        symbol.name,
        timeframe.value,
    )
    digest_input = "::".join(components).encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()
