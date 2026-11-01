# Change report: Phase 2 Resolution CLI & Pipeline Integration (M02)

Date: 2026-11-01
Repository and branch: job_application_4 / main
Baseline: 65cc6ab (feat(resolution): implement Phase 2 resolution engine unit tests and defensive hardening)
Approval status: APPROVED FOR MILESTONE-BY-MILESTONE PUBLISHING
Destination after approval: origin/main

## Objective and acceptance criteria
- Objective: Provide CLI entrypoint `job-applier resolve` to bridge Phase 1 extraction outputs (`questions.json`) into Phase 2 answer plans (`answers.json`), with default bank construction from local profile/vault and robust error handling.
- Non-goals: Phase 3 form filling, live employer submissions, external network mutations.
- Measurable checks:
  - `bin/job-applier resolve --help` and arguments `--bank`, `--out`, `--scope`, `--format` function cleanly.
  - Zero crashes on null/empty/malformed payloads (`{"questions": null}`).
  - Correct resolution of Yes/No choice questions in default bank without option collision.
  - Correct handling of file inputs returning `file_selection_requires_verified_local_artifact`.
  - Preservation of falsy values (`False`, `0`) in user answers.
  - Environment isolation in test suite (clean test runs without ambient `GROQ_API_KEY`).
  - 100% pass on unit and integration tests.

## Milestones and evidence
| Milestone | Owner | Status | Actual verification/evidence |
|---|---|---|---|
| M02 Implementation | coder | PASSED | Implemented `job_applier/resolution/__main__.py`, `job_applier/cli.py`, `tests/resolution_cli_test.py` (22 tests) |
| Verification | coder | PASSED | `python3 tests/resolution_cli_test.py` (22/22 PASS), `tests/smoke.py` (34/34 PASS), static verify exit code 0 |
| Security review | security-reviewer | PASSED | Cloudflare `security-audit` skill applied; 0 High/Critical findings; egress and secret safety confirmed |
| Quality review | quality-reviewer | PASSED | Enterprise review rubric applied; line widths <= 100 chars; test isolation verified |
| Bug review | bug-reviewer | PASSED | Karpathy guidelines applied; option label collisions and null payload bugs verified resolved |
| Review lead reconciliation | review-lead | PASSED | All priority rework tasks confirmed resolved; release gate cleared |

## Changed files
| Path | Reason | Behavior change |
|---|---|---|
| `job_applier/resolution/__main__.py` | CLI entrypoint for Phase 2 | Loads `questions.json`, resolves through `resolve_cascade`, formats answer plan, manages default bank from profile/vault, validates outputs. |
| `job_applier/cli.py` | Command routing | Adds `resolve` command to CLI dispatcher. |
| `tests/resolution_cli_test.py` | Unit & integration tests | 22 tests verifying CLI arguments, default bank, formatting, regression fixes, and isolated subprocess runs. |

## Checks run
| Command or manual check | Result (PASS/FAIL/NOT_RUN/NOT_AVAILABLE) | Evidence |
|---|---|---|
| `python3 tests/resolution_cli_test.py` | PASS | 22 tests passed in 0.372s |
| `python3 tests/resolution_test.py` | PASS | 48 tests passed in 0.002s |
| `python3 tests/smoke.py` | PASS | 34/34 passed |
| `python3 -m unittest tests/local_auth_test.py` | PASS | 5/5 passed |
| `python3 .opencode/scripts/verify.py --static` | PASS | `STATIC_CHECKS_PASSED_ONLY`, exit code 0 |

## Issues encountered and resolutions
| Issue | Reproduced? | Resolved? | Exact fix and proof |
|---|---|---|---|
| Boolean dropdown resolution failure in default bank (`option_labels: ['Yes', 'No']`) | Yes | Yes | Removed `'option_labels': ['Yes', 'No']` from boolean facts; let engine handle canonicalization. Verified with `test_default_bank_choice_resolution`. |
| Unhandled `IndexError` on whitespace-only name in profile | Yes | Yes | Used `name_tokens = (profile.get('name') or '').split()`. Verified with `test_whitespace_name_profile`. |
| Unhandled `TypeError` on `{"questions": null}` | Yes | Yes | Added `raw_questions = data.get('questions') ... questions = raw_questions if isinstance(raw_questions, list) else []`. Verified with `test_questions_null_value`. |
| Missing `application.resume` in default bank facts | Yes | Yes | Added `'application.resume'` to facts in `_build_bank_from_profile_and_answers`. Verified with `test_file_input_abstains_with_correct_artifact_reason`. |
| Falsy answers (`False`, `0`) dropped from answers mapping | Yes | Yes | Replaced `and val:` with `and val is not None and val != '':`. Verified with `test_falsy_answers_preserved`. |
| Test suite non-isolation (ambient `GROQ_API_KEY`) | Yes | Yes | Isolated environment variables in `setUp`/`tearDown` and subprocess calls. |

## Security and compliance
- Findings: Zero vulnerabilities. No secrets logged or printed. Local file permissions set to `0o600`.
- License/attribution status: PolyForm Strict 1.0.0 maintained.

## Approval and publication
- User authorization: "Push After Each Milestone" and "Do not wait for my approval for push just push it after verification and validation frm youur side".
- Destination: `origin/main`.
