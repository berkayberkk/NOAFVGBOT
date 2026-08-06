# forex-daytrade-system

## Project Purpose

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

Requires Python 3.12 or later.

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -e ".[dev]"
```

Copy the environment template and fill in local values (never commit this
file):

```bash
cp .env.example .env
```

## Development Commands

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

## Security Warning

This project is configured to use environment variables for all secrets
(broker credentials, API tokens, notification tokens). **Never commit a
`.env` file, credentials, account numbers, or tokens to this repository.**
See [docs/SECURITY.md](docs/SECURITY.md) for the full secret-management
policy and pre-push checklist.

## Disclaimers

- This is **research and engineering software**, not financial advice. It
  does not recommend, endorse, or execute any specific trade for any reader.
- **No profitability is guaranteed.** Nothing in this repository — including
  any future backtest, walk-forward result, or research note — constitutes a
  claim that any strategy is or will be profitable.
- The system is not permitted to trade on a live account until it has passed
  through shadow mode and demo trading, per
  [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md), with explicit
  human approval at each phase gate.
