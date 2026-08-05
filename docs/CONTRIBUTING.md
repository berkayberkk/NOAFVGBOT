# Contributing

## Branch Naming

- `main` — stable, reviewed code only. No direct commits.
- `develop` — integration branch for completed features/fixes.
- `feature/<short-description>` — new functionality (e.g.,
  `feature/data-ingestion-pipeline`).
- `fix/<short-description>` — bug fixes (e.g., `fix/gap-detection-off-by-one`).
- `research/<short-description>` — research experiments that may not ship
  as production code (e.g., `research/regime-classifier-v2`).

Branch off `develop` unless fixing a critical issue directly affecting
`main`.

## Commit Style

- Small, focused commits — one logical change per commit.
- Imperative mood subject line (e.g., "Add data quality report generator",
  not "Added" or "Adds").
- Reference the relevant phase or doc when it adds clarity (e.g., "Phase 1:
  add M15 resampling").
- No unrelated changes bundled into a commit.

## Pull Request Expectations

- PRs target `develop` (or `main` only for release-style merges from
  `develop`).
- Use `.github/pull_request_template.md`.
- Describe *why*, not just *what* — link to the relevant roadmap phase or
  doc.
- Keep PRs scoped to a single feature/fix/research task.

## Test Requirements

- New behavior requires unit tests; cross-module behavior requires
  integration tests.
- All tests must be deterministic (fixed seeds, no live network calls, no
  wall-clock dependence).
- No test may be deleted or weakened solely to make CI pass — see
  [../CLAUDE.md](../CLAUDE.md).
- Full test suite must pass locally before opening a PR.

## Documentation Requirements

- Any change to architecture, risk policy, strategy spec, or experiment
  policy must update the corresponding doc in `docs/` in the same PR.
- New modules should include a brief module-level docstring explaining
  purpose (not restating the code).

## Code Review Checklist

- [ ] Change is scoped to the stated task; no unrelated refactoring.
- [ ] Follows the layered architecture and dependency rules in
      [ARCHITECTURE.md](ARCHITECTURE.md).
- [ ] Type hints present; `mypy` passes.
- [ ] `ruff` passes with no new suppressions added without justification.
- [ ] Tests added/updated and passing.
- [ ] No hardcoded parameters that should be config-driven.
- [ ] No trading-restriction violation (see
      [../CLAUDE.md](../CLAUDE.md) Section 5).
- [ ] Relevant documentation updated.

## Security Review Checklist

- [ ] No secret, credential, token, or account number in the diff.
- [ ] No `.env` file staged.
- [ ] No real or realistic-looking secret added to `.env.example`.
- [ ] No data, state, report, or log artifact staged that should be
      git-ignored.
- [ ] Logging in the diff does not print secrets or full environment
      variable dumps.
- [ ] Any new dependency is reviewed for necessity and provenance.

## Definition of Done

A contribution is done only when:

- It satisfies the task's acceptance criteria and nothing beyond its scope.
- All tests (new and existing) pass, and lint/type-check are clean.
- Documentation affected by the change is updated.
- The code review and security review checklists above are satisfied.
- Changed files and test results are reported in the PR description.
