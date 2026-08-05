"""Sanity tests for the forex_daytrade package skeleton (Phase 0)."""

import re

import forex_daytrade
from forex_daytrade.version import __version__


def test_package_imports() -> None:
    assert forex_daytrade is not None


def test_version_is_defined() -> None:
    assert isinstance(__version__, str)
    assert __version__ != ""


def test_version_follows_semver_shape() -> None:
    assert re.match(r"^\d+\.\d+\.\d+$", __version__)


def test_package_exposes_version_in_all() -> None:
    assert "__version__" in forex_daytrade.__all__
