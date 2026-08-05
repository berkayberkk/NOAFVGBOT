## Summary

<!-- What does this PR change, and why? Link the relevant roadmap phase or doc. -->

## Phase / Scope

<!-- e.g., Phase 1: Data Infrastructure -->

## Changes

<!-- Bullet list of the key changes -->

-

## Testing

<!-- Commands run and their results -->

- [ ] `pytest` passes locally
- [ ] `ruff check .` passes locally
- [ ] `mypy src` passes locally

## Checklists

### Code Review

- [ ] Change is scoped to the stated task; no unrelated refactoring
- [ ] Follows the layered architecture in `docs/ARCHITECTURE.md`
- [ ] Type hints present; no new untyped code
- [ ] Tests added/updated and passing
- [ ] No hardcoded parameters that should be config-driven
- [ ] No trading-restriction violation (see `CLAUDE.md` Section 5)
- [ ] Relevant documentation updated

### Security Review

- [ ] No secret, credential, token, or account number in the diff
- [ ] No `.env` file staged
- [ ] No real or realistic-looking secret added to `.env.example`
- [ ] No data/state/report/log artifact staged that should be git-ignored
- [ ] Logging changes do not print secrets or full environment dumps

## Notes for Reviewer

<!-- Anything the reviewer should pay special attention to -->
