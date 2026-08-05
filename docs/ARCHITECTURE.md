# Architecture

**Status:** Planning document for Phase 0. Describes the target layered
architecture. **None of these layers are implemented yet.** Implementation
begins in the phase where each layer is scheduled — see
[DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md).

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

### Data Layer

Responsible for ingesting raw market data, normalizing it into a canonical
internal format, validating quality (gaps, duplicates, outliers), and
persisting it under `data/raw`, `data/normalized`, and `data/metadata`. Has
no knowledge of strategy, risk, or execution concepts.

### Feature Layer

Computes derived, deterministic features (e.g., multi-timeframe indicators)
from normalized data. Pure functions of historical data only — must never
have access to future bars relative to the point being computed. Outputs are
cached under `data/features`.

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
