"""Research Dataset layer: a reproducible, fingerprinted dataset system
(see the Research Dataset Layer section of ARCHITECTURE.md).

Given the same raw data, the same feature pipeline, and the same
configuration, `DatasetBuilder` always produces a `ResearchDataset` with
the same `hash`. No trading logic, signals, backtesting, execution, risk,
or machine learning lives here — this layer's only concern is dataset
identity and reproducibility.
"""

from forex_daytrade.research.builder import (
    DATASET_SCHEMA_VERSION,
    GENERATOR_VERSION,
    DatasetBuilder,
    DatasetBuildError,
    DatasetBuildResult,
)
from forex_daytrade.research.dataset import InvalidResearchDatasetError, ResearchDataset
from forex_daytrade.research.fingerprint import compute_fingerprint
from forex_daytrade.research.manifest import DatasetManifest, InvalidManifestError
from forex_daytrade.research.splits import (
    DatasetSplit,
    InvalidSplitError,
    SplitKind,
    chronological_train_validation_test_split,
)
from forex_daytrade.research.validator import validate_research_dataset
from forex_daytrade.research.version import (
    DatasetVersion,
    FeatureVersion,
    GeneratorVersion,
    InvalidVersionError,
    SemanticVersion,
)

__all__ = [
    "DATASET_SCHEMA_VERSION",
    "GENERATOR_VERSION",
    "DatasetBuildError",
    "DatasetBuildResult",
    "DatasetBuilder",
    "DatasetManifest",
    "DatasetSplit",
    "DatasetVersion",
    "FeatureVersion",
    "GeneratorVersion",
    "InvalidManifestError",
    "InvalidResearchDatasetError",
    "InvalidSplitError",
    "InvalidVersionError",
    "ResearchDataset",
    "SemanticVersion",
    "SplitKind",
    "chronological_train_validation_test_split",
    "compute_fingerprint",
    "validate_research_dataset",
]
