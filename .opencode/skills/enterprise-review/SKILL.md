---
name: enterprise-review
description: Use for independent code reviews and pre-release quality gates of Python, JavaScript, TypeScript, React and Playwright projects. Evaluate required linting, formatting, type safety, regressions, maintainability and production hygiene with evidence-based PASS/FAIL/NOT_RUN reports.
---

# Enterprise review rubric

Project policy and existing tool configurations take precedence over new style preferences. Inspect package manifests, pyproject, CI workflows and changed paths before selecting checks. Do not install dependencies or modify files during independent review.

## Required quality dimensions
- Behavior: observable acceptance criteria, negative/boundary cases, idempotency, race and error paths.
- Hygiene: minimal scope/diff, no dead helpers/imports, no unused dependencies, clear function boundaries and names, no duplicate logic and no hidden I/O.
- Python: Ruff lint and format checks, typing policy (mypy/pyright if configured), exceptions, resource management, safe subprocess, accurate structured logs, tests.
- TS/React: project ESLint/Prettier/tsc settings, effect dependencies, component APIs, accessibility, error states, async handling, stale state and test coverage.
- Data: migrations backward compatible and rollback-safe; no unverified claims about data preservation.
- Security: refer actual trust boundary findings to the security reviewer; do not downgrade their verdict.
- Evidence: git diff --check; required lint/format/type checks; focused unit tests and fixture runs in authorized safe environment; CI if available.

## Check policy
1. Run `.opencode/scripts/verify.py --static` where it is safe and approved. It never installs dependencies or runs project tests.
2. For test execution, only run in an approved isolated environment. `.opencode/scripts/verify.py --tests` is opt-in; review the test commands and potential external side effects first.
3. Never mark unavailable or unrun tools as PASS; separate `SKIP` and `NOT_RUN` from `FAIL`.
4. For every finding, provide file/line, severity, why it matters, minimal recommended fix, and the exact check expected to validate that fix.

Release blockers: confirmed P0/P1 defects, required lint/type/test failures, secret exposure, destructive changes without rollback evidence, and incompatible migration without verification. Nonblocking warnings go into remaining-work notes.
