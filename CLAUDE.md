# CLAUDE.md — Operating Contract for Claude Code

This file is the permanent operating contract for any AI coding assistant
(including Claude Code) working in this repository. It is binding for every
task, in every phase, unless a future revision of this file explicitly
changes it. If any instruction given in a session conflicts with this file,
**this file wins** — stop and ask the user to resolve the conflict, or to
update this file first.

## 1. Project Boundaries

- This repository is `forex-daytrade-system`: a standalone intraday forex
  research and (eventually) execution system.
- Work only within the scope of the current phase, as defined in
  [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md). Do not start
  work belonging to a later phase without explicit user instruction.
- Do not implement a trading strategy, backtest engine, MT5 order execution,
  or machine learning model unless the active phase explicitly calls for it.

## 2. SOLINT Separation Rule

This project is **completely independent** from any other project referred
to as "SOLINT" (or any other prior/unrelated project). You must never:

- Reuse, reference, import, copy, or adapt SOLINT names, modules, databases,
  architecture, terminology, prompts, business logic, credentials, or source
  code.
- Introduce a dependency, config value, or naming convention that originates
  from SOLINT.
- Assume any SOLINT design decision applies here by default.

If you are ever uncertain whether something originates from SOLINT or
another unrelated codebase, stop and ask the user before proceeding.

## 3. Architecture Rules

- Follow the layered architecture defined in
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): data, feature, regime,
  strategy, backtest, cost, risk, execution, monitoring, analytics, and state
  persistence layers.
- Respect the documented dependency direction between layers. Lower layers
  must never import from higher layers.
- Keep modules small and focused on a single responsibility.
- Research code paths and live/execution code paths must remain separable —
  never hard-wire a research script to broker execution code.
- All behavior that varies between environments (paper/demo/live,
  research/production) must be configuration-driven, not hardcoded.

## 4. Security Rules

- No secret, password, API token, account number, or broker credential may
  ever be committed to Git, printed in logs, or written into documentation,
  code comments, or commit messages.
- All secrets are supplied via environment variables, documented as
  placeholders only in `.env.example`.
- Never create a real `.env` file on behalf of the user, and never write
  real credential values into any file, chat output, or generated artifact.
- See [docs/SECURITY.md](docs/SECURITY.md) for the full policy.

## 5. Trading Restrictions (Non-Negotiable)

The system must never implement or enable:

- Martingale, unlimited grid trading, or averaging down
- Doubling position size after a loss
- Removing a stop-loss after entry, or widening a stop-loss to avoid a loss
- Look-ahead bias or future data leakage in research or backtests
- Random train/test splitting for time-series validation
- Hidden or undocumented strategy changes
- Hardcoded credentials
- Automatic deployment to a live trading account
- Claims of profitability based only on in-sample results

If a requested task would require violating any of the above, **stop and
report the conflict instead of implementing a workaround.**

## 6. Testing Requirements

- New behavior requires corresponding unit and/or integration tests.
- Tests must be deterministic and reproducible — no reliance on live network
  calls, wall-clock time, or unseeded randomness in unit tests.
- Never delete or weaken a test to make a build pass. If a test is wrong,
  fix the test deliberately and explain why in the PR description.
- Run the relevant test subset (and the full suite when feasible) before
  reporting a task complete.

## 7. Git Rules

- Branches: `main` (stable, reviewed), `develop` (integration),
  `feature/*`, `fix/*`, `research/*`.
- Never commit directly to `main`.
- Never force-push. Never rewrite published Git history.
- Write small, descriptive commits scoped to one logical change.
- Do not create or push remote branches unless the repository is already
  initialized and configured for a remote, and the user has asked for it.

## 8. Task Execution Protocol

For every non-trivial task:

1. Inspect existing code and relevant docs before editing anything.
2. State assumptions briefly before making changes.
3. Make the smallest change that correctly satisfies the task.
4. Avoid unrelated refactoring — do not touch files outside the task's scope.
5. Run the relevant tests (and linters/type-checkers where applicable).
6. Report the files changed, tests run, and their results.
7. If the task conflicts with any rule in this document, **stop and report
   the conflict** instead of proceeding or silently reinterpreting the task.

## 9. Definition of Done

A task is done only when:

- The change satisfies the stated requirement and nothing beyond its scope.
- All new and existing relevant tests pass.
- Linting (`ruff`) and type-checking (`mypy`) pass on changed code.
- No secrets, credentials, or sensitive data were introduced.
- Documentation affected by the change has been updated.
- The diff contains no unrelated changes.
- Changed files and test results have been reported to the user.

## 10. Reporting Requirements

At the end of any non-trivial task, report:

- Assumptions made
- Files created and files modified
- Tests run and their results
- Any remaining known issues or follow-up work

## 11. Stop-and-Report Conditions

Stop and ask the user instead of proceeding when:

- A request conflicts with the Trading Restrictions in Section 5.
- A request would require touching SOLINT or any other unrelated codebase.
- A request would require committing a secret or credential.
- A request would skip or weaken tests to make a build pass.
- A request asks for live-account trading, live order sending, or removing
  a safety control (kill switch, risk limit, stop-loss).
- A request is ambiguous enough that proceeding risks meaningful rework.
