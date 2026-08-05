# Project Charter

## Mission

Build a robust, transparent, and risk-controlled intraday forex research and
execution system — starting with a rule-based approach on EURUSD, validated
through rigorous backtesting and staged deployment, before any machine
learning or live capital is involved.

## Project Scope

**In scope (across the full roadmap):**

- Python-based research and infrastructure
- Historical and (later) live market data ingestion for EURUSD
- Multi-timeframe technical analysis (H1 regime, M15 setup, M5 entry)
- Realistic cost modeling (spread, commission, slippage)
- A rule-based strategy, backtested with walk-forward validation
- A risk-management layer with hard limits and a kill switch
- MetaTrader 5 integration for demo and, eventually, small live execution
- Shadow-mode and demo-mode validation before any live trading
- Monitoring, logging, and operational tooling
- Later-phase machine learning research, built on top of the validated
  rule-based baseline

**Out of scope for Phase 0:**

- Any strategy logic, indicator, or signal implementation
- Any backtest engine
- Any MT5 connection or order execution
- Any machine learning model
- Any live or demo trading

## Initial Instrument and Timeframe Plan

- **Instrument:** EURUSD (first and only instrument until proven otherwise)
- **Regime timeframe:** H1
- **Setup timeframe:** M15
- **Entry timeframe:** M5
- **Sessions:** London, and the London–New York overlap

These are long-term planning parameters, not commitments implemented in
Phase 0.

## Research Principles

- No look-ahead bias and no future data leakage, ever.
- Time-series-aware validation only — no random train/test splitting.
- Every experiment is reproducible: fixed data version, strategy version,
  cost assumptions, and parameters, all recorded (see
  [EXPERIMENT_POLICY.md](EXPERIMENT_POLICY.md)).
- Costs (spread, commission, slippage) must be modeled realistically before
  any performance claim is made.
- Failed experiments are kept, not deleted, to prevent survivorship bias in
  the project's own research record.
- No cherry-picking of results and no undocumented parameter search.

## Safety Principles

- Strict, explicit risk management at every stage (see
  [RISK_POLICY.md](RISK_POLICY.md)).
- No martingale, grid trading, averaging down, or loss-doubling in any form.
- Stop-losses are never removed or widened after entry.
- A kill switch and safe mode are required before any live connectivity is
  built.
- Progression is strictly staged: research → backtest → walk-forward
  validation → shadow mode → demo trading → small live validation. No phase
  may be skipped.
- No profitability claim is ever based solely on in-sample results.

## Explicit Non-Goals

- This project does not aim to be a general-purpose trading platform or
  multi-asset system in its initial phases.
- This project does not aim to guarantee profitability — no such guarantee
  is possible or implied at any phase.
- This project is not financial advice, and its outputs are not intended for
  use by anyone other than its own operator for personal research purposes.
- This project does not reuse or depend on any other project's code, data,
  or infrastructure (see the SOLINT separation rule in
  [../CLAUDE.md](../CLAUDE.md)).
- This project does not aim to remove human judgment from go/no-go decisions
  at phase gates — automation supports the decision, it does not make it.

## Stakeholder and Decision Model

- **Owner/Operator:** the project owner is the sole stakeholder, final
  decision-maker, and the only party authorized to approve phase-gate
  transitions, numeric risk limits, and live-account deployment.
- **Claude Code / AI assistant:** acts as engineering and research support
  under the operating contract in [../CLAUDE.md](../CLAUDE.md). It may
  propose, implement, and test changes, but may not unilaterally decide to
  advance a phase gate, weaken a safety control, or deploy to a live
  account.
- All architecturally significant decisions are recorded in
  [ARCHITECTURE.md](ARCHITECTURE.md) or a dedicated decision record as the
  project matures.

## Phase Gate System

Every phase in [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) ends with an
explicit gate decision, made by the project owner:

- **PASS** — Acceptance criteria are met. The next phase may begin.
- **REWORK** — Acceptance criteria are not met, but the phase's approach is
  sound. Specific deficiencies must be listed and addressed before the gate
  is re-evaluated.
- **REJECT** — The phase's approach is not sound. The phase must be
  redesigned, not patched, before proceeding.

No phase may begin before the prior phase has received a PASS.
