# forex-daytrade-system

## Project Description

`forex-daytrade-system` is a standalone research and (eventually) execution
system for intraday forex trading. The long-term goal is to build a
transparent, rule-based, risk-controlled intraday trading research pipeline
for EURUSD, beginning with an H1 market-regime view, an M15 setup, and an M5
entry, focused on the London and London–New York overlap sessions. Machine
learning is an explicit later-phase goal, not a starting point.

This repository is developed independently of any other project. It does not
reuse, import, or depend on code, data, architecture, or credentials from any
other codebase.

## Current Phase

**Phase 1 — Data Infrastructure** (implementation complete, pending
phase-gate review by the project owner).

Phase 0 established the project's structure, documentation, tooling, and
engineering rules. Phase 1 adds the data layer
(`src/forex_daytrade/data/`): MT5 historical-bar ingestion, UTC timestamp
normalization, data-quality validation, trading-session classification, and
Parquet storage with metadata. It intentionally contains **no trading
strategy, no backtest engine, no order execution, and no machine
learning** — only market-data ingestion, normalization, validation, and
storage. See [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md) for
the full phase plan, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the
Data Layer's design, and [docs/PROJECT_CHARTER.md](docs/PROJECT_CHARTER.md)
for the governing principles.

## Features

Implemented so far (Phase 1 — data layer only):

- **MT5 historical-bar ingestion** — pulls M5/M15/H1 EURUSD bars from an
  already-running, already-logged-in MetaTrader 5 terminal
  (`src/forex_daytrade/data/mt5_client.py`, `historical_loader.py`).
- **UTC timestamp normalization** — converts broker-local bar timestamps to
  UTC using a configurable broker timezone (`normalizer.py`).
- **Trading-session classification** — tags bars with the session they fall
  in (e.g. London, London–New York overlap) (`sessions.py`).
- **Data-quality validation** — checks for gaps, duplicates, and other
  integrity issues, and writes a JSON validation report
  (`validator.py`).
- **Parquet storage with metadata** — stores normalized datasets as Parquet
  alongside structured metadata for reproducibility (`storage.py`,
  `metadata.py`).
- **Typed domain model** — candles, ticks, symbols, timeframes, and sessions
  are represented as explicit, validated domain types
  (`src/forex_daytrade/domain/`).
- **Feature engineering pipeline (foundation)** — a composable pipeline for
  deriving price/return/volatility/time features
  (`src/forex_daytrade/features/`).

Planned in later phases (see [Roadmap](#high-level-roadmap)): backtest
engine, strategy logic, risk engine, MT5 order execution, monitoring, and
machine-learning research. None of these exist yet — do not assume any
trading or execution capability from this repository's current state.

## High-Level Roadmap

| Phase | Name |
|-------|------|
| 0 | Project Foundation and Governance |
| 1 | Data Infrastructure |
| 2 | Backtest Core |
| 3 | Strategy V1 |
| 4 | Risk Engine |
| 5 | Robustness and Validation |
| 6 | MT5 Execution |
| 7 | Monitoring and Operations |
| 8 | Shadow Mode |
| 9 | Demo Trading |
| 10 | Small Live Validation |
| 11 | Strategy V2 and Machine Learning Research |

Full detail, including objectives, deliverables, risks, and exit criteria for
each phase, lives in [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md).

## Installation

Requires Python 3.12 or later. MT5 ingestion additionally requires Windows
and a locally installed MetaTrader 5 terminal.

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -e ".[dev]"
```

## Configuration

All configuration is supplied via environment variables — never hardcode
credentials or paths in source. Copy the template and fill in local values:

```bash
cp .env.example .env
```

`.env` is git-ignored and must never be committed. Variables defined in
[.env.example](.env.example):

| Variable | Purpose |
|----------|---------|
| `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` | Reserved for Phase 6 (MT5 execution); not used by the current data layer. |
| `MT5_PATH` | Reserved for Phase 6. |
| `MT5_TERMINAL_PATH` | Optional path to `terminal64.exe` if not in the default install location. The data layer connects to an already-running, already-logged-in terminal and never supplies broker credentials itself. |
| `MT5_BROKER_TIMEZONE` | IANA timezone name your broker's MT5 server uses for bar timestamps (e.g. `Europe/Athens`). Required for correct UTC normalization; defaults to `UTC`. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Reserved for Phase 7 (alerting). |
| `DATA_RAW_DIR`, `DATA_NORMALIZED_DIR`, `DATA_METADATA_DIR` | Local filesystem paths for the data pipeline's output stages. |
| `LOG_LEVEL` | Application log verbosity (e.g. `INFO`, `DEBUG`). |
| `ENVIRONMENT` | Deployment context (e.g. `research`). |

See [docs/SECURITY.md](docs/SECURITY.md) for the full secret-management
policy and pre-push checklist.

## Usage

The current phase exposes one CLI entry point: historical-data ingestion.
It requires a running, already-logged-in MT5 terminal on Windows.

```bash
python scripts/ingest_historical_data.py --from 2024-01-01 --to 2024-06-01
```

This downloads EURUSD bars (M5/M15/H1 by default), normalizes timestamps to
UTC, classifies trading sessions, validates data quality, stores the result
as Parquet under `data/normalized/` plus metadata under `data/metadata/`,
and writes a JSON validation report under `reports/data_quality/`.

### Development Commands

```bash
# Run the test suite
pytest

# Run tests with coverage
pytest --cov=forex_daytrade

# Lint
ruff check .

# Format
ruff format .

# Type-check
mypy src
```

## Folder Structure

```
forex-daytrade-system/
├── config/                 # Runtime configuration files (no secrets)
├── data/                   # Local, git-ignored data lake
│   ├── raw/                 # Raw MT5 bars as downloaded
│   ├── normalized/           # UTC-normalized, session-tagged Parquet datasets
│   ├── features/             # Derived feature sets
│   └── metadata/             # Dataset metadata (schema, ranges, provenance)
├── docs/                   # Architecture, roadmap, policy, and spec docs
├── experiments/             # Experiment registry and results (git-ignored results)
├── notebooks/               # Research notebooks
├── reports/                 # Generated reports (data quality, backtests, live, walk-forward)
├── scripts/                 # Operational / CLI entry-point scripts
├── src/forex_daytrade/       # Application source
│   ├── config/                # Typed configuration models
│   ├── data/                  # MT5 client, ingestion, normalization, validation, storage
│   ├── domain/                 # Core domain types (candle, tick, symbol, timeframe, session)
│   ├── exceptions/             # Exception hierarchy
│   ├── features/                # Feature engineering pipeline
│   └── types/                   # Shared type aliases
├── state/                   # Runtime state (git-ignored)
├── tests/                   # Unit, integration, and regression tests
├── .env.example             # Environment variable template (placeholders only)
├── CLAUDE.md                # Binding operating contract for AI coding assistants
└── pyproject.toml           # Project metadata, dependencies, tool configuration
```

## Security Warning

This project is configured to use environment variables for all secrets
(broker credentials, API tokens, notification tokens). **Never commit a
`.env` file, credentials, account numbers, or tokens to this repository.**
See [docs/SECURITY.md](docs/SECURITY.md) for the full secret-management
policy and pre-push checklist.

## Disclaimer

- This is **research and engineering software**, not financial advice. It
  does not recommend, endorse, or execute any specific trade for any reader.
- **No profitability is guaranteed.** Nothing in this repository — including
  any future backtest, walk-forward result, or research note — constitutes a
  claim that any strategy is or will be profitable.
- The system is not permitted to trade on a live account until it has passed
  through shadow mode and demo trading, per
  [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md), with explicit
  human approval at each phase gate.
- Forex trading carries a high level of risk and may not be suitable for all
  investors. Past performance, backtested or otherwise, is not indicative of
  future results.
