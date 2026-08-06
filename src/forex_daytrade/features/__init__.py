"""Feature engineering layer: a modular, composable feature-generation
framework (see the Feature Layer section of ARCHITECTURE.md).

Importing this package registers every baseline feature with
`forex_daytrade.features.registry` as a side effect — adding a new feature
requires only a new module with one `@register_feature`-decorated class,
plus one import line below.
"""

# Imported for registration side effects only — each module registers its
# own classes at import time via the `@register_feature` decorator.
from forex_daytrade.features import price as _price  # noqa: F401
from forex_daytrade.features import returns as _returns  # noqa: F401
from forex_daytrade.features import time as _time  # noqa: F401
from forex_daytrade.features import volatility as _volatility  # noqa: F401
from forex_daytrade.features.base import (
    Feature,
    FeatureError,
    FeatureMetadata,
    MissingRequiredColumnsError,
    UnexpectedOutputColumnsError,
)
from forex_daytrade.features.pipeline import (
    ColumnConflictError,
    DuplicateColumnError,
    FeaturePipeline,
    FeatureReport,
)
from forex_daytrade.features.registry import (
    DuplicateFeatureRegistrationError,
    UnknownFeatureError,
    all_features,
    feature_names,
    get_feature,
    register_feature,
)

__all__ = [
    "ColumnConflictError",
    "DuplicateColumnError",
    "DuplicateFeatureRegistrationError",
    "Feature",
    "FeatureError",
    "FeatureMetadata",
    "FeaturePipeline",
    "FeatureReport",
    "MissingRequiredColumnsError",
    "UnexpectedOutputColumnsError",
    "UnknownFeatureError",
    "all_features",
    "feature_names",
    "get_feature",
    "register_feature",
]
