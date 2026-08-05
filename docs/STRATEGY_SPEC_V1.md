# Strategy Specification V1 (Placeholder)

**Status: specification placeholder only. Not implemented. No parameter in
this document has been validated. No edge is claimed.**

This document records the intended research hypothesis for Strategy V1 so
that Phase 3 implementation has a stable reference point. It is not code,
not a backtest, and not a promise of future results.

## Hypothesis

EURUSD exhibits short-term trend-continuation behavior during the London and
London–New York overlap sessions that may be identifiable using a
multi-timeframe framework: a higher-timeframe regime filter, a
medium-timeframe pullback setup, and a lower-timeframe entry confirmation.
This is a hypothesis to be tested, not an established fact.

## Instrument and Sessions

- **Instrument:** EURUSD
- **Sessions:** London session, and the London–New York overlap window
  *(exact session boundary times are an undecided research parameter)*

## Timeframe Roles

- **H1 — Regime:** Intended to classify the broader market state (e.g.,
  trending vs. ranging) to determine whether the strategy should be active.
  Exact regime-classification method is an **undecided research parameter**.
- **M15 — Setup:** Intended to identify a pullback-style setup within the
  H1 regime direction. Exact setup definition (indicator(s), pullback
  depth/structure) is an **undecided research parameter**.
- **M5 — Entry:** Intended to provide a lower-timeframe confirmation trigger
  for entry timing within a valid M15 setup. Exact entry trigger is an
  **undecided research parameter**.

## Filters (Planned, Undecided Parameters)

- **Spread filter:** Trades should be filtered out when the current spread
  exceeds an acceptable threshold. *Threshold value: undecided.*
- **Volatility filter:** Trades should be filtered out in abnormally
  low/high volatility conditions. *Method and thresholds: undecided.*
- **News exclusion:** Planned for a later phase — the strategy should avoid
  trading around high-impact news events. *Not implemented in V1; data
  source and exclusion window are undecided.*

## Exit Rules (Planned, Undecided Parameters)

- **Time stop:** A maximum holding duration is planned to close a trade if
  neither a target nor a stop is hit within a bounded time. *Exact duration:
  undecided.*
- **Session exit:** Open positions are planned to be closed (or otherwise
  handled) at session end rather than held indefinitely outside the target
  session window. *Exact rule: undecided.*
- **Stop-loss:** A stop-loss is planned to be attached at entry and must
  never be removed or widened after entry, per the project's non-negotiable
  trading restrictions (see [../CLAUDE.md](../CLAUDE.md)). *Exact
  placement method: undecided.*

## Position Management

- **Maximum one open position at a time.** No pyramiding, no grid, no
  martingale, no averaging down — these are permanently prohibited, not
  just undecided (see [RISK_POLICY.md](RISK_POLICY.md) and
  [../CLAUDE.md](../CLAUDE.md)).

## Explicitly Undecided Research Parameters

All of the following are placeholders and must be determined through the
Phase 5 validation process, not assumed:

- H1 regime classification method and thresholds
- M15 setup definition (indicators, pullback structure/depth)
- M5 entry trigger definition
- Spread filter threshold
- Volatility filter method and thresholds
- Time-stop duration
- Session-exit precise rule and timing
- Stop-loss and (if used) take-profit placement method
- Position sizing (owned by [RISK_POLICY.md](RISK_POLICY.md), not this spec)

## Non-Claims

- This specification does not claim that the described hypothesis has a
  statistical edge.
- No backtest has been run against this specification as of Phase 0.
- Any future backtest result referencing this spec must be read alongside
  [EXPERIMENT_POLICY.md](EXPERIMENT_POLICY.md) and must not be treated as
  proof of future profitability.
