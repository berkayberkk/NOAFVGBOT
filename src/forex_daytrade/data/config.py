"""Configuration for the data layer, driven entirely by environment variables.

No path or timezone assumption is hardcoded in the data layer itself; see
`.env.example` for the recognized variables and their defaults.

`DataConfig` keeps its historical flat shape (used throughout
`forex_daytrade.data`), but `from_env` is an explicit adapter over the
canonical `forex_daytrade.config.models` pieces (`PathsConfig`,
`TimezoneConfig`, `MT5SettingsPlaceholder`) instead of an independent
re-implementation of the same env-var parsing — see the Domain Layer
section of ARCHITECTURE.md. It deliberately does not build from the full
`AppConfig`, since that would also construct and validate unrelated
sections (e.g. `LOG_LEVEL` via `LoggingConfig`) that have nothing to do
with data-layer configuration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from forex_daytrade.config.models import MT5SettingsPlaceholder, PathsConfig, TimezoneConfig


@dataclass(frozen=True)
class DataConfig:
    """Runtime configuration for data ingestion, storage, and normalization."""

    raw_dir: Path
    normalized_dir: Path
    metadata_dir: Path
    broker_timezone: str
    mt5_terminal_path: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> DataConfig:
        """Build a `DataConfig` from environment variables (or a provided mapping)."""
        paths = PathsConfig.from_env(env)
        timezone = TimezoneConfig.from_env(env)
        mt5 = MT5SettingsPlaceholder.from_env(env)
        return cls(
            raw_dir=paths.data_raw_dir,
            normalized_dir=paths.data_normalized_dir,
            metadata_dir=paths.data_metadata_dir,
            broker_timezone=timezone.broker_timezone,
            mt5_terminal_path=mt5.terminal_path,
        )
