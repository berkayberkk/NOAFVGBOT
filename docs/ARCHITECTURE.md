# Architecture

**Status:** Describes the target layered architecture. The **Data Layer**
is implemented as of Phase 1 (`src/forex_daytrade/data/`), alongside the
**Domain Layer** (`src/forex_daytrade/domain/`, `config/`, `types/`,
`exceptions/`) as Phase 1 foundational infrastructure. The **Feature
Layer**'s baseline generators (`src/forex_daytrade/features/`) were added
in Sprint 2, ahead of Phase 2; all layers above Feature remain
planning-only. Implementation begins in the phase where each layer is
scheduled — see [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md).

## Purpose

This document defines the intended module boundaries and dependency rules
for `forex_daytrade` so that implementation in later phases follows a
consistent, testable, and safe structure from the start.

## Planned Layered Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Monitoring Layer                    │
│        (logging, alerts, dashboards, health checks)      │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                      Analytics Layer                     │
│      (performance reports, walk-forward analysis)        │
└─────────────────────────────────────────────────────────┘
┌───────────────────────┐   ┌───────────────────────────────┐
│    Backtest Layer      │   │      Execution Layer          │
│ (research simulation)  │   │  (MT5 demo/live order flow)   │
└───────────────────────┘   └───────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                        Risk Layer                        │
│   (position sizing, limits, kill switch, safe mode)       │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                       Cost Model                         │
│        (spread, commission, slippage estimation)          │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                     Strategy Layer                       │
│         (entry/exit rules, signal generation)             │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                      Regime Layer                        │
│            (H1 market-state classification)               │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                      Feature Layer                       │
│        (derived indicators, multi-timeframe features)     │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                       Data Layer                          │
│      (ingestion, normalization, storage, validation)      │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                  State Persistence Layer                  │
│  (positions, experiment registry, run state — cross-cut)   │
└─────────────────────────────────────────────────────────┘
```

### Domain Layer

Not shown as its own box in the diagram above because it is a cross-cutting
foundation rather than a pipeline stage: it defines the shared data
structures, configuration models, and exceptions that every layer above —
including Data — is expected to eventually speak. It has no dependency on
any other layer in this codebase.

**Implemented in Phase 1** as foundational infrastructure, alongside the
Data Layer:

- `src/forex_daytrade/domain/` — pure data contracts, no pandas or MT5
  dependency, no business logic:
  - `candle.py` / `tick.py` — `Candle` (OHLCV bar) and `Tick` (bid/ask
    quote) frozen dataclasses, each validating its own invariants (OHLC
    consistency, positive prices, timezone-aware timestamps) in
    `__post_init__`.
  - `symbol.py` — `Symbol`, the tradeable-instrument contract (digits,
    point size, contract size, tick value, volume bounds); holds no broker
    connection.
  - `timeframe.py` — `Timeframe` enum, the domain layer's complete
    vocabulary (M1–D1).
  - `session.py` — `TradingSession` enum (label vocabulary only; no
    session-detection logic lives here).
  - `market_data.py` / `metadata.py` / `validation.py` — `MarketData`
    (symbol + timeframe + bars + metadata + validation report container),
    `DatasetMetadata`, and the generic `ValidationReport`/`ValidationIssue`
    contract.
  - `common.py` — small validation helpers shared by the above.
- `src/forex_daytrade/config/models.py` — `AppConfig`, a broader
  environment-variable-driven configuration contract (paths, logging,
  storage, timezone, and an MT5 settings placeholder holding no
  credentials) for future cross-layer consumers.
- `src/forex_daytrade/types/aliases.py` — shared primitive type aliases
  (`Price`, `Pips`, `Volume`, `SymbolName`).
- `src/forex_daytrade/exceptions/` — the `DomainError` hierarchy for
  domain-model invariant violations.

**Ownership rules — Domain Layer vs. Data Layer.** Following a Phase 1
integration review, each shared concept has exactly one of three
relationships to its data-layer counterpart:

| Concept | Canonical owner | Data-layer type | Relationship |
| --- | --- | --- | --- |
| Timeframe | `domain.timeframe.Timeframe` (M1–D1) | `data.types.IngestionTimeframe` (M5/M15/H1) | Ingestion-specific subtype. Deliberately restricted to the timeframes MT5 ingestion supports and carries MT5/pandas-only properties (`mt5_constant_name`, `pandas_freq`) that must never leak into the domain layer. Its `.timedelta` delegates to `domain.timeframe.Timeframe` rather than redeclaring the interval table, so bar-interval lengths have one source of truth. Named `IngestionTimeframe` (not `Timeframe`) specifically so it cannot be confused with the domain type when both are imported in the same file. |
| Trading session label | `domain.session.TradingSession` | — (none) | Fully consolidated. `data.sessions.classify_sessions` imports and returns `TradingSession` values directly; `data.types` no longer defines a session enum. |
| Validation severity | `domain.validation.Severity` | — (none) | Fully consolidated. `data.validator` imports `Severity` directly; it carries no ingestion-specific meaning that would justify a separate type. |
| Validation report/issue | `domain.validation.ValidationReport`/`ValidationIssue` (generic: issues + statistics) | `data.validator.IngestionValidationReport`/`IngestionValidationIssue` (dataset-quality-specific: symbol, timeframe, total_rows, per-issue count/sample_timestamps) | Intentionally retained, distinct shapes. The data-layer report is a richer, dataset-identity-bound QA report; forcing it onto the generic domain shape would drop fields the JSON reports under `reports/data_quality/` depend on. Renamed with an `Ingestion` prefix to prevent name collisions with the domain contract. |
| Dataset metadata | `domain.metadata.DatasetMetadata` (in-memory; `datetime` fields; no symbol/timeframe — those live on the enclosing `MarketData`) | `data.metadata.IngestionMetadata` (JSON sidecar; ISO-string timestamps; embeds symbol/timeframe) | Intentionally retained, distinct shapes. Consolidating would mean either changing the on-disk `data/metadata/*.json` sidecar schema (a stored-artifact compatibility risk) or dropping the domain type's `datetime`/no-I/O design. Renamed with an `Ingestion` prefix for the same collision-prevention reason as above. |
| Symbol identifier | `domain.symbol.Symbol` (full instrument contract: digits, point size, contract size, tick value, volume bounds) | plain `str` (`SUPPORTED_SYMBOLS: frozenset[str]`) | Intentionally not consolidated. The ingestion pipeline only ever handles a symbol *name*; it has no contract-size/tick-value data to populate a `Symbol` with. `types.aliases.SymbolName` is a transparent alias for `str` (no runtime or mypy enforcement over a bare `str`), so retyping data-layer signatures to it would be cosmetic only. |
| Configuration | `config.models.PathsConfig` / `TimezoneConfig` / `MT5SettingsPlaceholder` (nested; also owns `LoggingConfig`/`StorageConfig`, which the data layer has no reason to touch) | `data.config.DataConfig` (flat; used throughout `data/`) | Explicit adapter. `DataConfig.from_env` builds itself from the three canonical `from_env` calls above instead of re-parsing the same environment variables independently, so a given `.env` value can never be interpreted two different ways. It intentionally does not build from the full `AppConfig`, since that would also construct and validate unrelated sections (e.g. `LOG_LEVEL`) that have nothing to do with data-layer configuration. `DataConfig`'s flat public shape is preserved unchanged for compatibility with existing `data/` call sites. |

The rule of thumb: if a concept has **no ingestion-specific behavior or
storage-format constraint**, the data layer imports the domain type
directly (Session, Severity). If it has **genuine ingestion-only behavior
or an on-disk/wire format to preserve**, the data layer keeps its own
type, named or documented so it cannot be mistaken for the canonical one
(`IngestionTimeframe`, `IngestionMetadata`, `IngestionValidationReport`/
`IngestionValidationIssue`), and reuses canonical values through
delegation or composition wherever that is safe (`IngestionTimeframe.
timedelta`, `DataConfig.from_env`).

### Data Layer

Responsible for ingesting raw market data, normalizing it into a canonical
internal format, validating quality (gaps, duplicates, outliers), and
persisting it under `data/raw`, `data/normalized`, and `data/metadata`. Has
no knowledge of strategy, risk, or execution concepts.

**Implemented in Phase 1** as `src/forex_daytrade/data/`:

- `mt5_client.py` — connection-lifecycle wrapper (`initialize`/`shutdown`/
  `reconnect`/`symbol_exists`/`copy_rates_range`) around the Windows-only
  `MetaTrader5` package. No order-placement functions exist. The package is
  imported lazily (never at module import time) so this module — and its
  unit tests, which mock it — work on platforms without MT5 installed (e.g.
  Linux CI). Per the Security Boundaries below, it never supplies broker
  credentials: it only attaches to an already-running, already-logged-in
  terminal (optionally via a configured, non-secret `MT5_TERMINAL_PATH`).
- `historical_loader.py` — downloads raw bars for supported symbols
  (currently `EURUSD` only) and timeframes (`M5`/`M15`/`H1`) over a
  configurable date range.
- `normalizer.py` — converts MT5's raw `time` column (which encodes
  broker-server local time, not true UTC) into `broker_timestamp` and
  `timestamp_utc` columns using `zoneinfo`, DST-aware, based on the
  configured `MT5_BROKER_TIMEZONE`.
- `sessions.py` — classifies each UTC timestamp into `asian`, `london`,
  `new_york`, `london_newyork_overlap`, `rollover`, or `off_session` (the
  canonical `domain.session.TradingSession` values, imported directly) by
  converting to each market's local time via `zoneinfo`, so DST transitions
  (which fall on different dates in the UK/EU vs. the US) resolve correctly
  without a hardcoded UTC-offset table.
- `validator.py` — structured `IngestionValidationReport`/
  `IngestionValidationIssue` checks for empty datasets, duplicate
  timestamps, non-positive prices, OHLC inconsistency, spread anomalies,
  weekend bars, future timestamps, and missing-bar gaps (holiday/weekend
  gaps excluded). Duplicates, non-positive prices, OHLC inconsistency, and
  future timestamps are `ERROR`-severity (indicate corruption); weekend
  bars, spread anomalies, and missing-bar gaps are `WARNING`-severity
  (expected to occur legitimately) — `Severity` itself is
  `domain.validation.Severity`, imported rather than redeclared. Reports
  are written to `reports/data_quality/`.
- `storage.py` / `metadata.py` — persist one Parquet file plus one JSON
  `IngestionMetadata` sidecar per symbol/timeframe under `data/normalized`
  and `data/metadata`. This is the Phase 1 data-versioning scheme:
  ingestion overwrites both on each run, and the metadata's
  `downloaded_at` field records when each version was produced.
- `config.py` — `DataConfig`; all paths, the broker timezone, and the
  optional MT5 terminal path are environment-variable-driven (see
  `.env.example`); no path or timezone assumption is hardcoded.
  `DataConfig.from_env` is an adapter over the canonical
  `config.models.PathsConfig`/`TimezoneConfig`/`MT5SettingsPlaceholder`
  (see the Domain Layer section above) rather than an independent
  re-implementation of the same env-var parsing.

`scripts/ingest_historical_data.py` is the CLI entry point wiring the
pipeline end-to-end; it requires a running MT5 terminal and is not exercised
by unit tests, which mock the data layer instead.

### Feature Layer

Computes derived, deterministic features (e.g., multi-timeframe indicators)
from normalized data. Pure functions of historical data only — must never
have access to future bars relative to the point being computed. Outputs are
cached under `data/features`.

**Baseline generators implemented in Sprint 2** (ahead of Phase 2, since a
modular feature framework has no strategy/backtest content of its own) as
`src/forex_daytrade/features/`:

- `base.py` — the `Feature` interface every generator implements: `name`,
  `required_columns`, `generated_columns` (declared as class attributes),
  and `compute(df) -> pd.DataFrame`. `metadata()` returns a `FeatureMetadata`
  snapshot of the above plus the class's docstring as `description`.
  `validate_input`/`validate_output` enforce that a feature only ever sees
  its declared required columns and only ever returns its declared
  generated columns.
- `registry.py` — `@register_feature` is a class decorator that adds a
  `Feature` subclass to a module-level registry keyed by `.name`, raising
  `DuplicateFeatureRegistrationError` on a name collision. `get_feature`,
  `all_features`, and `feature_names` read the registry.
- `pipeline.py` — `FeaturePipeline` takes an explicit, caller-ordered
  sequence of `Feature` instances. `.run(df)` validates every feature's
  required columns are present in `df` up front (batched, so all missing
  columns are reported together), then runs each feature and merges its
  output into the result, returning `(DataFrame, FeatureReport)`.
  `FeatureReport` records which features ran, which columns they produced,
  a NaN count per generated column, and row count.
- `returns.py` / `price.py` / `volatility.py` / `time.py` — the baseline
  generators: `log_return`, `simple_return` (returns); `high_low_range`,
  `close_open_distance`, `body_size`, `upper_wick`, `lower_wick` (price
  shape); `true_range`, `rolling_std_20` (raw dispersion — no EMA/RSI/ATR/
  MACD or any indicator that bakes in a strategy decision); `hour_of_day`,
  `day_of_week`, `session_placeholder` (time). `session_placeholder`
  deliberately passes through the Data Layer's already-classified
  `session` column rather than reclassifying sessions itself — see
  `time.py`'s docstring for why.

**"No feature may know about another feature" is structurally enforced,
not just a convention:** `FeaturePipeline.run()` slices the input down to
`df[list(feature.required_columns)]` before calling `feature.compute()`,
so a feature has no way to read another feature's generated columns, or
even columns of its own input it didn't declare needing — attempting to
do so raises `KeyError` immediately. This also means **pipeline order is
safely configurable**: since no feature's output can depend on another
feature having already run, reordering a `FeaturePipeline`'s feature list
never changes what any individual feature computes.

**Extension mechanism:** adding a new feature requires (1) a new class
implementing `Feature`, decorated with `@register_feature`, in a new or
existing module under `features/`, and (2) one import line in
`features/__init__.py` (for the side effect of running the decorator) if
it's a new module — no changes to `base.py`, `registry.py`, or
`pipeline.py`. Importing `forex_daytrade.features` registers every
baseline feature as a side effect.

**Column-conflict validation:** `FeaturePipeline` raises
`DuplicateColumnError` at *construction* time if two features in the list
declare overlapping `generated_columns` (a static, declared-contract
check), and `ColumnConflictError` at *run* time if a feature's actual
output columns collide with the input DataFrame's original columns or an
earlier feature's actual output (a dynamic, contract-enforcement check —
catches a feature whose `compute()` doesn't honor what it declared).

**NaN handling is observability, not a hard failure:** `FeatureReport.
nan_counts` surfaces how many NaNs each generated column contains, but
`FeaturePipeline` never raises on NaN. Leading NaNs are the correct,
expected output for `log_return`/`simple_return` (no prior bar for the
first row) and `rolling_std_20` (fewer than 20 prior bars for the first 19
rows) — rejecting them would mean fabricating data for bars that don't
exist. Downstream layers decide how to handle NaN (e.g. drop, or require a
minimum warm-up period), not the Feature Layer itself.

**No files created for `trend.py`, `volume.py`, or a standalone
`metadata.py`:** Sprint 2's baseline feature set has no trend or volume
features (EMA/RSI/ATR/MACD-style trend indicators were explicitly out of
scope, and no volume-derived feature was specified), so those modules
would be empty; `FeatureMetadata` lives in `base.py` since it's a one-
dataclass type tightly coupled to the `Feature` interface it describes.
Add these modules when a concrete feature actually needs them.

The Feature Layer currently has no import dependency on the Data or Domain
layers: every generator operates on a plain `pd.DataFrame` and validates
against column *names* (`open`, `high`, `low`, `close`, `timestamp_utc`,
`session`, matching the Data Layer's normalized/session-augmented output
schema) rather than importing `forex_daytrade.data` or
`forex_daytrade.domain` types directly.

### Regime Layer

Classifies the current market state (e.g., trending vs. ranging on H1) using
only the Feature Layer's outputs. Produces a regime label/context consumed
by the Strategy Layer. Does not know about order execution or risk.

### Strategy Layer

Encodes entry/exit rules (M15 setup, M5 entry confirmation) as a function of
Feature Layer and Regime Layer outputs. Produces trade signals/intents only
— it does not size positions, does not manage risk, and does not talk to a
broker.

### Backtest Layer

Simulates strategy signals against historical data plus the Cost Model to
produce research results. Used only in research contexts; must never be
imported by the Execution Layer.

### Cost Model

Estimates realistic spread, commission, and slippage. Shared by the Backtest
Layer (for simulation) and the Execution/Risk layers (for pre-trade checks),
so cost assumptions stay consistent between research and live behavior.

### Risk Layer

Owns position sizing, per-trade/day/week loss limits, exposure limits,
consecutive-loss guards, and the kill switch / safe-mode state machine (see
[RISK_POLICY.md](RISK_POLICY.md)). Sits between signal generation and order
placement in both backtest and live paths, so the same risk rules govern
both.

### Execution Layer

Translates approved, risk-checked trade decisions into MT5 orders (demo or
live, per configuration). The only layer permitted to hold or use broker
credentials or place orders. Must never be imported by the Backtest Layer.

### Monitoring Layer

Structured logging, health checks, and alerting (e.g., Telegram) across all
layers. Cross-cutting; reads from other layers, does not feed decisions back
into them.

### Analytics Layer

Produces performance and walk-forward reports from backtest and live/shadow
results, written to `reports/`. Read-only with respect to other layers.

### State Persistence

Cross-cutting layer for durable run state (open positions, experiment
registry entries, kill-switch status) under `state/` and
`experiments/registry/`. Other layers depend on it for persistence; it does
not depend on strategy or execution logic.

## Dependency-Direction Rules

- Dependencies flow **upward** through the stack as drawn above: Data →
  Feature → Regime → Strategy → (Cost Model, Risk) → (Backtest |
  Execution) → Analytics/Monitoring.
- The **Domain Layer** sits beneath Data — every layer, including Data, may
  import from it, but it must never import from any other layer in this
  codebase.
- A lower layer must never import from a higher layer (e.g., the Data Layer
  must never import from Strategy).
- The **Backtest Layer** and the **Execution Layer** are siblings: neither
  may import the other. Both depend on Strategy, Cost Model, and Risk, so
  research and live paths reuse exactly the same signal and risk logic.
- The **Risk Layer** has no dependency on Backtest or Execution — it is
  called by them, not the reverse.
- State Persistence and Monitoring are cross-cutting utility layers usable
  by any layer above Data, but they must never contain strategy or risk
  decision logic themselves.

## Research/Live Separation

- Research code (Backtest Layer, `experiments/`, `notebooks/`) must never
  import from the Execution Layer or hold broker credentials.
- Live/demo code (Execution Layer) must never import from the Backtest
  Layer.
- Both share the Strategy, Cost Model, and Risk layers so that behavior
  validated in research matches behavior used live.

## Configuration Boundaries

- All environment-specific values (broker server, timeframe parameters,
  risk limits, feature flags) are supplied via the `config/` directory and
  environment variables — never hardcoded in layer implementations.
- Configuration determines *which* environment a component runs in
  (research/demo/live); it must not be used to bypass a safety control such
  as the Risk Layer's limits.

## Security Boundaries

- Only the Execution Layer may access broker credentials, and only via
  environment variables (see [SECURITY.md](SECURITY.md)).
- The Data, Feature, Regime, Strategy, Backtest, and Analytics layers must
  never require network credentials of any kind.
- Logs produced by the Monitoring Layer must never contain secrets,
  credentials, or account numbers.
