"""Unit tests for forex_daytrade.config.models."""

from pathlib import Path

import pytest

from forex_daytrade.config.models import (
    AppConfig,
    LoggingConfig,
    MT5SettingsPlaceholder,
    PathsConfig,
    StorageConfig,
    TimezoneConfig,
)


def test_paths_config_from_env_defaults() -> None:
    config = PathsConfig.from_env({})
    assert config.data_raw_dir == Path("data/raw")
    assert config.data_normalized_dir == Path("data/normalized")
    assert config.data_metadata_dir == Path("data/metadata")
    assert config.reports_dir == Path("reports")
    assert config.state_dir == Path("state")


def test_paths_config_from_env_overrides() -> None:
    config = PathsConfig.from_env(
        {"DATA_RAW_DIR": "custom/raw", "REPORTS_DIR": "custom/reports"}
    )
    assert config.data_raw_dir == Path("custom/raw")
    assert config.reports_dir == Path("custom/reports")


def test_paths_config_equality() -> None:
    assert PathsConfig.from_env({}) == PathsConfig.from_env({})


def test_logging_config_default_level() -> None:
    assert LoggingConfig().level == "INFO"


def test_logging_config_rejects_invalid_level() -> None:
    with pytest.raises(ValueError, match="level"):
        LoggingConfig(level="NOT_A_LEVEL")


def test_logging_config_from_env() -> None:
    assert LoggingConfig.from_env({"LOG_LEVEL": "DEBUG"}).level == "DEBUG"


def test_storage_config_default_backend() -> None:
    assert StorageConfig().backend == "local"


def test_storage_config_from_env() -> None:
    assert StorageConfig.from_env({"STORAGE_BACKEND": "remote"}).backend == "remote"


def test_timezone_config_defaults() -> None:
    config = TimezoneConfig()
    assert config.broker_timezone == "UTC"
    assert config.application_timezone == "UTC"


def test_timezone_config_from_env() -> None:
    config = TimezoneConfig.from_env({"MT5_BROKER_TIMEZONE": "Europe/Athens"})
    assert config.broker_timezone == "Europe/Athens"


def test_mt5_settings_placeholder_defaults_to_none() -> None:
    assert MT5SettingsPlaceholder().terminal_path is None


def test_mt5_settings_placeholder_from_env() -> None:
    config = MT5SettingsPlaceholder.from_env({"MT5_TERMINAL_PATH": "/path/to/terminal"})
    assert config.terminal_path == "/path/to/terminal"


def test_mt5_settings_placeholder_holds_no_credential_fields() -> None:
    field_names = set(MT5SettingsPlaceholder.__dataclass_fields__)
    assert field_names == {"terminal_path"}


def test_app_config_from_env_assembles_all_sections() -> None:
    config = AppConfig.from_env({})
    assert isinstance(config.paths, PathsConfig)
    assert isinstance(config.logging, LoggingConfig)
    assert isinstance(config.storage, StorageConfig)
    assert isinstance(config.timezone, TimezoneConfig)
    assert isinstance(config.mt5, MT5SettingsPlaceholder)


def test_app_config_is_frozen() -> None:
    config = AppConfig.from_env({})
    with pytest.raises(AttributeError):
        config.paths = PathsConfig.from_env({})  # type: ignore[misc]


def test_app_config_equality() -> None:
    assert AppConfig.from_env({}) == AppConfig.from_env({})
