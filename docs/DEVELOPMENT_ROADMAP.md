# Development Roadmap

Each phase must receive a **PASS** at its gate (see
[PROJECT_CHARTER.md](PROJECT_CHARTER.md#phase-gate-system)) before the next
phase begins. No phase may be skipped.

---

## Phase 0: Project Foundation and Governance

- **Objective:** Establish a clean, secure, testable, documented, and
  reproducible project foundation with no trading logic.
- **Inputs:** None (greenfield repository).
- **Deliverables:** Repository structure, governance docs (this roadmap,
  charter, architecture, risk policy, experiment policy, security policy,
  contributing guide), `CLAUDE.md` operating contract, minimal Python
  package skeleton, CI pipeline, `.gitignore`/`.env.example`.
- **Risks:** Scope creep into real implementation; missing a governance
  document that later phases silently assume exists.
- **Acceptance Criteria:** All required files exist with project-specific
  content; CI runs lint/type-check/test successfully; no secrets or
  credentials present anywhere in the repository; no strategy, backtest, ML,
  or MT5 code present.
- **Exit Decision:** PASS required before any data ingestion or strategy
  work begins.

## Phase 1: Data Infrastructure

- **Objective:** Reliable ingestion, normalization, validation, and storage
  of historical EURUSD price data across H1/M15/M5.
- **Inputs:** Phase 0 foundation; a chosen historical data source.
- **Deliverables:** Data ingestion scripts, normalization pipeline, data
  quality checks/reports (`reports/data_quality/`), data versioning scheme,
  unit/integration tests for the pipeline.
- **Risks:** Silent data gaps, timezone/session misalignment, look-ahead
  bias introduced at the normalization stage.
- **Acceptance Criteria:** Documented data schema; reproducible pipeline
  from raw to normalized data; automated data quality checks with passing
  results on a defined historical range; no look-ahead bias in any
  transformation.
- **Exit Decision:** PASS required before feature/backtest work begins.

## Phase 2: Backtest Core

- **Objective:** A deterministic, leakage-free backtest engine capable of
  simulating trade signals against historical data with a realistic cost
  model.
- **Inputs:** Phase 1 normalized data.
- **Deliverables:** Backtest engine, cost model (spread/commission/slippage),
  performance metrics module, engine-level tests including known-answer
  regression tests.
- **Risks:** Subtle look-ahead bias in bar-close/fill assumptions;
  unrealistic cost modeling that overstates edge.
- **Acceptance Criteria:** Engine produces identical results on repeated
  runs given identical inputs; documented fill/costing assumptions; test
  suite includes at least one adversarial look-ahead-bias regression test.
- **Exit Decision:** PASS required before any strategy logic is added.

## Phase 3: Strategy V1

- **Objective:** Implement the rule-based strategy described in
  [STRATEGY_SPEC_V1.md](STRATEGY_SPEC_V1.md) as testable, configuration-driven
  code, with all parameters explicit.
- **Inputs:** Phase 2 backtest engine; finalized Strategy V1 spec.
- **Deliverables:** Strategy module (signal generation only), parameter
  configuration files, unit tests for rule logic.
- **Risks:** Parameter overfitting during initial calibration; hidden
  coupling between strategy code and execution code.
- **Acceptance Criteria:** Strategy logic is fully deterministic and
  config-driven; no direct dependency on the Execution Layer; parameters and
  their rationale are documented.
- **Exit Decision:** PASS required before connecting strategy output to
  risk-managed backtests.

## Phase 4: Risk Engine

- **Objective:** Implement the Risk Layer per
  [RISK_POLICY.md](RISK_POLICY.md): position sizing, loss limits, exposure
  limits, guards, and the kill switch, with numeric limits explicitly
  approved by the project owner.
- **Inputs:** Phase 3 strategy signals; owner-approved numeric risk limits.
- **Deliverables:** Risk engine module, kill switch/safe-mode state machine,
  audit logging of risk decisions, unit tests covering every guard.
- **Risks:** A risk rule that can be silently bypassed by configuration;
  incomplete coverage of loss scenarios.
- **Acceptance Criteria:** Every rule in `RISK_POLICY.md` has a corresponding
  enforced check and test; kill switch verified to halt trading
  unconditionally in tests.
- **Exit Decision:** PASS required before backtests are considered
  risk-realistic.

## Phase 5: Robustness and Validation

- **Objective:** Validate Strategy V1 + Risk Engine using walk-forward
  analysis and out-of-sample testing, per
  [EXPERIMENT_POLICY.md](EXPERIMENT_POLICY.md).
- **Inputs:** Phases 2–4 complete; historical data spanning multiple
  regimes.
- **Deliverables:** Walk-forward validation framework, experiment registry
  entries for all runs, `reports/walk_forward/` outputs, documented
  in-sample/out-of-sample split methodology.
- **Risks:** Overfitting via repeated test-set reuse; cherry-picked
  reporting.
- **Acceptance Criteria:** Walk-forward results recorded for all
  experiments (including failures); no test-period data reused for
  parameter tuning; results reviewed against
  `EXPERIMENT_POLICY.md` for compliance.
- **Exit Decision:** PASS (by project owner review of results) required
  before any broker connectivity is built.

## Phase 6: MT5 Execution

- **Objective:** Build the Execution Layer's MT5 integration for order
  placement, limited to a **demo account** context.
- **Inputs:** Phase 4 risk engine; Phase 5 validated strategy.
- **Deliverables:** MT5 connector, order-placement/reconciliation logic,
  execution-layer tests (with MT5 mocked/simulated), configuration for
  demo-only credentials.
- **Risks:** Accidental live-account wiring; credential leakage; order
  duplication on reconnect.
- **Acceptance Criteria:** Execution Layer cannot be pointed at a live
  account without an explicit, separately reviewed configuration change;
  reconciliation logic tested against simulated broker responses; no
  credentials in code or logs.
- **Exit Decision:** PASS required before any shadow-mode run.

## Phase 7: Monitoring and Operations

- **Objective:** Build structured logging, alerting, and health-check
  tooling needed to safely operate shadow/demo/live modes.
- **Inputs:** Phase 6 execution layer.
- **Deliverables:** Structured logging across layers, alerting (e.g.,
  Telegram) with redaction of sensitive data, health-check/heartbeat
  tooling, operational runbook.
- **Risks:** Alert fatigue masking real incidents; secrets leaking into log
  output.
- **Acceptance Criteria:** Logs verified to contain no secrets; alerting
  tested end-to-end in a non-live context; runbook covers restart, kill
  switch, and safe-mode procedures.
- **Exit Decision:** PASS required before shadow mode begins.

## Phase 8: Shadow Mode

- **Objective:** Run the full pipeline against live market data with
  simulated (non-submitted) orders to validate real-time behavior without
  financial risk.
- **Inputs:** Phases 6–7 complete.
- **Deliverables:** Shadow-mode runner, `reports/live/` shadow-run reports,
  comparison of shadow fills vs. backtest cost-model assumptions.
- **Risks:** Real-time data issues not present in historical backtests
  (gaps, reconnects, latency); cost-model assumptions proving unrealistic.
- **Acceptance Criteria:** A defined minimum shadow-run duration completed
  with no unexplained crashes or missed signals; live cost behavior
  compared against the cost model within an owner-approved tolerance.
- **Exit Decision:** PASS (owner-approved) required before real orders are
  ever submitted, even to a demo account.

## Phase 9: Demo Trading

- **Objective:** Submit real orders to a **demo account** under full risk
  management, monitoring, and shadow-validated logic.
- **Inputs:** Phase 8 shadow-mode PASS.
- **Deliverables:** Demo-trading run reports, incident log (if any),
  reconciliation reports comparing expected vs. actual demo fills.
- **Risks:** Demo-account behavior diverging from live-account behavior
  (fill quality, latency); operational issues only visible under real order
  flow.
- **Acceptance Criteria:** A defined minimum demo-trading period completed
  with risk limits never breached, kill switch never required outside of
  deliberate tests, and reconciliation clean.
- **Exit Decision:** PASS (owner-approved) required before any live capital
  is considered.

## Phase 10: Small Live Validation

- **Objective:** Validate the system with real, small live capital under
  maximum caution.
- **Inputs:** Phase 9 demo PASS; owner's explicit, separate authorization to
  use live capital.
- **Deliverables:** Live-run reports (`reports/live/`), incident log,
  post-run review against all prior phase assumptions.
- **Risks:** Real financial loss; live-only failure modes (broker-side
  issues, execution slippage beyond model).
- **Acceptance Criteria:** Live risk limits never breached; kill switch and
  safe mode proven effective if triggered; owner reviews live results
  against demo/shadow/backtest expectations.
- **Exit Decision:** PASS (owner-approved) required before any scale-up or
  before Phase 11 research is used to change live behavior.

## Phase 11: Strategy V2 and Machine Learning Research

- **Objective:** Explore machine-learning-based strategy research as a
  successor to or complement of Strategy V1, using the validated
  infrastructure from prior phases.
- **Inputs:** All prior phases PASSed; a mature, trusted backtest and
  validation pipeline.
- **Deliverables:** ML research experiments (tracked per
  `EXPERIMENT_POLICY.md`), model evaluation reports, comparison against
  Strategy V1 baseline.
- **Risks:** Overfitting inherent to ML approaches; false confidence from
  in-sample model performance; data leakage through feature engineering.
- **Acceptance Criteria:** All ML experiments follow the same
  walk-forward/out-of-sample discipline as Phase 5; no ML model reaches
  demo/live status without repeating Phases 6–10 in full.
- **Exit Decision:** Each ML strategy candidate is gated independently
  through Phases 6–10; this phase itself has no single exit — it is an
  ongoing research track.
