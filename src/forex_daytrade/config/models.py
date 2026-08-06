"""Application-wide configuration models, driven entirely by environment variables.

`forex_daytrade.data.config.DataConfig` remains the data layer's own,
already-wired configuration (paths + broker timezone + MT5 terminal path)
and is unchanged by this module. `AppConfig` here is the domain layer's
broader configuration contract, intended for future cross-layer consumers
(logging setup, feature/regime/strategy config, etc.) as those layers are
built. No path or timezone assumption is hardcoded; see `.env.example` for
recognized variables and their defaults.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


@dataclass(frozen=True, slots=True)
class PathsConfig:
    """Filesystem locations used across layers. All configurable, none hardcoded."""

    data_raw_dir: Path
    data_normalized_dir: Path
    data_metadata_dir: Path
    reports_dir: Path
    state_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> PathsConfig:
        source = os.environ if env is None else env
        return cls(
            data_raw_dir=Path(source.get("DATA_RAW_DIR", "data/raw")),
            data_normalized_dir=Path(source.get("DATA_NORMALIZED_DIR", "data/normalized")),
            data_metadata_dir=Path(source.get("DATA_METADATA_DIR", "data/metadata")),
            reports_dir=Path(source.get("REPORTS_DIR", "reports")),
            state_dir=Path(source.get("STATE_DIR", "state")),
        )


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """Application logging configuration."""

    level: str = "INFO"

    def __post_init__(self) -> None:
        if self.level.upper() not in _VALID_LOG_LEVELS:
            raise ValueError(
                f"LoggingConfig.level must be one of {sorted(_VALID_LOG_LEVELS)}, "
                f"got {self.level!r}."
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LoggingConfig:
        source = os.environ if env is None else env
        return cls(level=source.get("LOG_LEVEL", "INFO"))


@dataclass(frozen=True, slots=True)
class StorageConfig:
    """Placeholder for future storage-backend selection (e.g. local vs. remote)."""

    backend: str = "local"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> StorageConfig:
        source = os.environ if env is None else env
        return cls(backend=source.get("STORAGE_BACKEND", "local"))


@dataclass(frozen=True, slots=True)
class TimezoneConfig:
    """Timezone assumptions used for broker-data normalization and display."""

    broker_timezone: str = "UTC"
    application_timezone: str = "UTC"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> TimezoneConfig:
        source = os.environ if env is None else env
        return cls(
            broker_timezone=source.get("MT5_BROKER_TIMEZONE", "UTC"),
            application_timezone=source.get("APPLICATION_TIMEZONE", "UTC"),
        )


@dataclass(frozen=True, slots=True)
class MT5SettingsPlaceholder:
    """Placeholder for future (Phase 6+) MT5 execution settings.

    No credentials are represented here or anywhere in this module. Per
    CLAUDE.md's Security Rules, broker credentials are supplied via
    environment variables directly to the Execution Layer only, never
    modeled as a config-layer dataclass field.
    """

    terminal_path: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> MT5SettingsPlaceholder:
        source = os.environ if env is None else env
        return cls(terminal_path=source.get("MT5_TERMINAL_PATH") or None)


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Aggregate application configuration, assembled from environment variables."""

    paths: PathsConfig
    logging: LoggingConfig
    storage: StorageConfig
    timezone: TimezoneConfig
    mt5: MT5SettingsPlaceholder

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AppConfig:
        source = os.environ if env is None else env
        return cls(
            paths=PathsConfig.from_env(source),
            logging=LoggingConfig.from_env(source),
            storage=StorageConfig.from_env(source),
            timezone=TimezoneConfig.from_env(source),
            mt5=MT5SettingsPlaceholder.from_env(source),
        )
