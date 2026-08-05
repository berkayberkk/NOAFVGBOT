# Risk Policy (Planning Document)

**Status:** planning document for Phase 0. Defines the *sections and rules*
the Risk Layer must implement in Phase 4. **Exact numerical limits are not
set in this document and must be explicitly approved by the project owner
before execution development (Phase 6) begins.**

## Position Sizing

- Position size must be derived from an approved risk-per-trade rule (e.g.,
  a fraction of account equity), never from a fixed lot size chosen ad hoc.
- Position sizing must never increase after a loss (no martingale, no
  loss-doubling — see [../CLAUDE.md](../CLAUDE.md)).
- Sizing method and exact parameters: **to be approved in Phase 4.**

## Maximum Trade Risk

- Every trade must have a predefined maximum loss, enforced via a
  stop-loss set at entry and never removed or widened afterward.
- Maximum risk per trade (e.g., as a percentage of equity): **undecided,
  owner approval required.**

## Daily Loss Limit

- Trading must halt for the remainder of the trading day once a defined
  daily loss threshold is reached.
- Exact threshold: **undecided, owner approval required.**

## Weekly Loss Limit

- Trading must halt for the remainder of the trading week once a defined
  weekly loss threshold is reached.
- Exact threshold: **undecided, owner approval required.**

## Maximum Open Exposure

- A hard cap on total simultaneous exposure (consistent with the "maximum
  one open position" rule in [STRATEGY_SPEC_V1.md](STRATEGY_SPEC_V1.md) for
  V1) must be enforced by the Risk Layer independent of strategy logic.
- Exact cap: **undecided, owner approval required.**

## Maximum Number of Trades

- A cap on the number of trades opened per day (and/or per week) must be
  enforced to prevent runaway or malfunctioning signal generation from
  over-trading.
- Exact limits: **undecided, owner approval required.**

## Consecutive-Loss Guard

- After a defined number of consecutive losing trades, the system must
  pause trading and require explicit review before resuming.
- Exact threshold: **undecided, owner approval required.**

## Spread Guard

- Trades must be blocked when the live spread exceeds an approved maximum,
  independent of the strategy's own spread filter (defense in depth).
- Exact threshold: **undecided, owner approval required.**

## Slippage Guard

- Orders must be checked against an approved maximum acceptable slippage;
  fills outside tolerance must be flagged and reviewed, not silently
  accepted.
- Exact tolerance: **undecided, owner approval required.**

## Stale-Data Guard

- The system must detect when incoming market data has stopped updating
  within an expected interval and must refuse to trade (or must flatten
  positions per policy) on stale data.
- Exact staleness threshold: **undecided, owner approval required.**

## Connection-Loss Guard

- Loss of connectivity to the data feed or broker must trigger a defined
  safe response (e.g., halt new entries, alert, and — per policy — manage
  any open position) rather than silent inaction.
- Exact behavior: **undecided, owner approval required.**

## Reconciliation Failure

- Positions and orders reported by the broker must be reconciled against
  the system's internal state on a regular basis. A mismatch must halt new
  trading and raise an alert until resolved.
- Exact reconciliation frequency and resolution procedure: **undecided,
  owner approval required.**

## Kill Switch

- A kill switch must exist that immediately and unconditionally prevents
  any new order submission, independent of strategy or risk-layer state.
- The kill switch must be testable in isolation and must default to a safe
  (disabled-trading) state on any ambiguous condition.
- Activation/deactivation procedure: **to be defined in Phase 4/6.**

## Safe Mode

- A safe mode must exist as a degraded operating state (e.g., no new
  entries, manage-existing-positions-only) distinct from full halt via the
  kill switch, for handling non-critical anomalies.
- Entry/exit criteria for safe mode: **to be defined in Phase 4/6.**

## Restart Behavior

- On restart, the system must reconcile with the broker before taking any
  action, and must never assume a clean/no-position state without
  verification.
- Exact restart procedure: **to be defined in Phase 6/7.**

## Manual Override

- The project owner must always be able to manually halt trading, close
  positions, or override an automated decision through a documented,
  auditable mechanism.
- Exact override interface: **to be defined in Phase 6/7.**

## Audit Logging

- Every risk-relevant decision (size calculated, limit breached, kill
  switch triggered, override used) must be logged in a structured,
  append-only, and reviewable format, without ever logging secrets or
  credentials.

## Approval Requirement

No numeric value in this policy (risk-per-trade, loss limits, exposure caps,
trade counts, guard thresholds) may be used in code until it has been
explicitly reviewed and approved by the project owner, and that approval is
recorded (e.g., in the relevant PR or an experiment/decision record).
