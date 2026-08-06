"""Unit tests for the forex_daytrade.domain package's public exports."""

import forex_daytrade.domain as domain_pkg


def test_all_exported_names_are_importable() -> None:
    for name in domain_pkg.__all__:
        assert hasattr(domain_pkg, name)
