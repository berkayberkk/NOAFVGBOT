"""Unit tests for forex_daytrade.data.config."""

from pathlib import Path

from forex_daytrade.data.config import DataConfig


def test_from_env_defaults_with_empty_mapping() -> None:
    config = DataConfig.from_env({})
    assert config.raw_dir == Path("data/raw")
    assert config.normalized_dir == Path("data/normalized")
    assert config.metadata_dir == Path("data/metadata")
    assert config.broker_timezone == "UTC"
    assert config.mt5_terminal_path is None


def test_from_env_overrides() -> None:
    env = {
        "DATA_RAW_DIR": "/custom/raw",
        "DATA_NORMALIZED_DIR": "/custom/normalized",
        "DATA_METADATA_DIR": "/custom/metadata",
        "MT5_BROKER_TIMEZONE": "Europe/Athens",
        "MT5_TERMINAL_PATH": "C:/MT5/terminal64.exe",
    }
    config = DataConfig.from_env(env)
    assert config.raw_dir == Path("/custom/raw")
    assert config.normalized_dir == Path("/custom/normalized")
    assert config.metadata_dir == Path("/custom/metadata")
    assert config.broker_timezone == "Europe/Athens"
    assert config.mt5_terminal_path == "C:/MT5/terminal64.exe"


def test_from_env_blank_terminal_path_is_none() -> None:
    config = DataConfig.from_env({"MT5_TERMINAL_PATH": ""})
    assert config.mt5_terminal_path is None
