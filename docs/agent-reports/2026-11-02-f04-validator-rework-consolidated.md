# Change report: F04 Validator Rework and Truthful Completion

Date: 2026-11-02
Repository and branch: job_application_4 / main
Baseline: 8aa5ae7c5ca8835390f417603fed2c7795dc74d1 (+ pre-existing uncommitted edits in AGENTS.md, .opencode/agents/, job_applier/cli.py, untracked reports in docs/agent-reports/, untracked F01 runner files in job_applier/runner.py and tests/runner_test.py, and .opencode/work/f04-validator-review/ preserved)
Approval status: NOT APPROVED
Destination after approval: origin/main (no automatic push)

## Objective and acceptance criteria
- Objective: Prevent false `SUCCESS` attestations during pipeline validation (`validate_pipeline`) by enforcing strict required-field completeness, rejecting contradictory or uncaptured option IDs, preserving primitive falsy IDs (`0` and `False`), supporting numeric planned answers for choice controls, redacting password telemetry, and verifying execution in a hermetic Bubblewrap sandbox.
- Non-goals: Automated job application submission (forbidden by policy; runner strictly logs `Needs User`), direct live ATS submission, personal answer bank modification (deferred to provenance review), or pushing to git remote without explicit user approval.
- Measurable checks:
  1. Uncaptured option IDs cannot override contradictory planned answers.
  2. Primitive option IDs `0` and `False` are preserved across normalization, extraction, and schema adaptation.
  3. Choice controls accept numeric planned answers (`int`, `float`) without type rejection.
  4. Password values are sanitized as `[REDACTED]` in mismatch telemetry and error summaries.
  5. Hermetic Bubblewrap sandbox execution with `--clearenv` and scratch `$HOME`.
  6. 32 mock unit tests, 15 runner tests, and 34 smoke tests pass with verified red-to-green test reproduction.

## Milestones and evidence
| Milestone | Owner | Status | Actual verification/evidence |
|---|---|---|---|
| Baseline & Precheck | Orchestrator + explore | PASSED | PolyForm Strict license noted; separate user modification permission confirmed. HEAD `8aa5ae7c5ca8835390f417603fed2c7795dc74d1`. Skills `karpathy-guidelines` and `security-audit` verified. |
| F01 Truthful Status | Coder | PASSED | Runner strictly logs `Needs User` with `applied_count = 0`. 15 runner tests pass. Documented in `docs/agent-reports/2026-11-02-f01-truthful-runner-status.md`. |
| F04 Validator Rework | Coder | PASSED | `validate_pipeline.py` and `tests/validate_pipeline_test.py` updated. 32 mock tests pass hermetically. SHA-256 hashes: validator `5c70ee62344a354e4d491ccce975ed983944f14e7b29f645bbd919a081061e3a`, tests `4f56aac7e7befdcae8e5081c879282ebc7ea149f64d087e0d38ce3f5a67bc9ed`. |
| Defensive Security Review | security-reviewer | PASSED | Session `ses_e639e3713ffeHCAjif9m6b0DgX`: Zero credential leaks, password redaction confirmed, sandbox isolation verified, 0 vulnerabilities. |
| Code Quality Review | quality-reviewer | PASSED | Session `ses_e639e19a0ffeBcoMV1FBaS0dnD`: Enterprise standards and Karpathy guidelines met. Clean AST, dead import removed, surgical diff. |
| Adversarial Correctness Review | bug-reviewer | PASSED | Session `ses_e639ddd7cfferAYfwkS6m0URHw`: Red-to-green reproduction verified (3 targeted failures pre-fix, 0 failures post-fix). All edge cases hold. |
| Review Lead Consolidation | review-lead | PASSED | Session `ses_e6397967fffe2gYRsrNW4HSPRg`: Consolidated PASS across all review gates. |

## Changed files
| Path | Reason | Behavior change |
|---|---|---|
| `job_applier/validate_pipeline.py` | Repair false-success loopholes, option identity matching, primitive falsy values, numeric plans, and password telemetry. | Rejects contradictory uncaptured option IDs, normalizes primitive `0`/`False` IDs, supports `int`/`float` in choice controls, masks password telemetry with `[REDACTED]`, and removes dead import `PurePosixPath`. |
| `tests/validate_pipeline_test.py` | Add regression test coverage for all rework findings. | Preserves 29 existing mock tests; adds 3 new regression tests (`test_f04_rework_uncaptured_contradictory_id_fails`, `test_f04_rework_option_id_primitive_zero_succeeds`, `test_f04_rework_choice_numeric_planned_answer`). |
| `.opencode/work/f04-validator-review/*` | In-repo review artifacts and execution ledger. | Contains exact diffs, command transcripts with unabbreviated stdout/exits, and SHA-256 hash manifest. |

## Checks run
| Command or manual check | Result (PASS/FAIL/NOT_RUN/NOT_AVAILABLE) | Evidence |
|---|---|---|
| `bwrap --clearenv --unshare-net ... python3 -m unittest ... ValidatePipelineMockTests` (pre-fix) | PASS (reproduced failures) | Exit code 1; 3 failures reproduced on unmodified validator. |
| `bwrap --clearenv --unshare-net ... python3 -m unittest ... ValidatePipelineMockTests` (post-fix) | PASS | Exit code 0; 32/32 mock tests passed in 0.092s. |
| `bwrap --clearenv --unshare-net ... python3 tests/runner_test.py` | PASS | Exit code 0; 15/15 runner tests passed in 0.016s (F01 untouched). |
| `bwrap --clearenv --unshare-net ... python3 tests/smoke.py` | PASS | Exit code 0; 34/34 smoke tests passed in clean ephemeral environment. |
| `python3 -m py_compile job_applier/validate_pipeline.py tests/validate_pipeline_test.py` | PASS | Exit code 0; clean AST syntax compilation. |
| `git diff --check` | PASS | Exit code 0; zero whitespace or conflict markers. |
| `command -v ruff` | NOT_AVAILABLE | Ruff not installed in execution environment. |
| Static typing (`mypy` / `pyright`) | NOT_AVAILABLE | Not configured in repository environment. |
| Live ATS browser automation | NOT_RUN | Offline sandbox review mandate; gated pending Greenhouse dry-run. |

## Issues encountered and resolutions
| Issue | Reproduced? | Resolved? | Exact fix and proof |
|---|---|---|---|
| 1. Uncaptured option contradictory `selected_option['id']` accepted | Yes | Yes | `validate_pipeline.py:478-510`: Validated `s_id` against `s_lbl`, `s_val`, and `planned` intent; contradictory `s_id` fails satisfaction. Proof: `test_f04_rework_uncaptured_contradictory_id_fails`. |
| 2. Option ID primitive `0` and `False` coerced to `''` | Yes | Yes | `validate_pipeline.py:88-115, 124-157`: Implemented `_normalize_opt_id` and `_validate_answers_plan_adapted` to preserve `'0'` and `'false'`. Proof: `test_f04_rework_option_id_primitive_zero_succeeds`. |
| 3. Choice controls numeric planned answers rejected | Yes | Yes | `validate_pipeline.py:117-122, 306-308`: Type guard permits `(str, bool, int, float)` and normalizes via `_normalize_choice_planned`. Proof: `test_f04_rework_choice_numeric_planned_answer`. |
| 4. Unused import `PurePosixPath` | Yes | Yes | `validate_pipeline.py:16`: Removed dead import. Verified via AST compilation. |
| 5. Password telemetry leakage in mismatch messages | Yes | Yes | `validate_pipeline.py:256-280, 1194-1231`: Masked password values with `[REDACTED]` in mismatch telemetry and error summaries. |
| 6. Non-hermetic sandbox execution in evidence | Yes | Yes | Re-executed all tests inside `bwrap --clearenv --unshare-net` with scratch `$HOME` and `$TMPDIR`. Verified in `exactwrappercommands_stdout_exits.txt`. |

## Outstanding issues, tradeoffs, follow-up work
- Personal Answer Bank: User confirmed employment history is complete (resume absence proves never employed). Vault and personal bank answers must be updated to align with verified facts before full runs.
- Greenhouse Target: Next operational step is a focused, monitored dry-run against Greenhouse job postings, stopping at review screen (`auto_submit = False`).
- Workday Target: Workday adapter discovery and verification deferred until Greenhouse validation succeeds.

## Security and compliance
- Findings, unresolved source evidence and data/privacy boundaries: Zero security vulnerabilities identified. Form passwords and verified values are strictly redacted in error strings and summary output.
- License/attribution status: PolyForm Strict 1.0.0; user confirmed separate rights to modify and publish repository.

## Approval and publication
- User-approved target and scope (fill only after approval): PENDING
- Git commit (fill only after successful commit): PENDING
- Remote verification (fill only after successful push): PENDING
