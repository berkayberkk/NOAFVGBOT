"""Automatic feature registration.

Feature modules register their classes with `@register_feature` at import
time. Importing `forex_daytrade.features` (which imports every concrete
feature module) is therefore sufficient to populate the registry — adding a
new feature requires only a new module with one decorated class, plus one
import line in `features/__init__.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from forex_daytrade.features.base import Feature, FeatureError

_REGISTRY: dict[str, type[Feature]] = {}


class DuplicateFeatureRegistrationError(FeatureError):
    """Raised when two feature classes register under the same name."""


class UnknownFeatureError(FeatureError):
    """Raised when looking up a feature name that was never registered."""


def register_feature(cls: type[Feature]) -> type[Feature]:
    """Class decorator: register a `Feature` subclass under its `.name`."""
    name = cls.name
    if name in _REGISTRY:
        raise DuplicateFeatureRegistrationError(
            f"A feature is already registered under name {name!r} "
            f"({_REGISTRY[name].__qualname__})."
        )
    _REGISTRY[name] = cls
    return cls


def get_feature(name: str) -> type[Feature]:
    """Look up a registered feature class by name."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownFeatureError(f"No feature registered under name {name!r}.") from None


def all_features() -> Mapping[str, type[Feature]]:
    """Return a read-only view of every registered feature, in registration order."""
    return MappingProxyType(_REGISTRY)


def feature_names() -> tuple[str, ...]:
    """Return every registered feature's name, in registration order."""
    return tuple(_REGISTRY)
