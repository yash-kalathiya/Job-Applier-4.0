# Change report: Milestone M04 Pipeline Validator & Live Greenhouse Execution

Date: 2026-11-01
Repository and branch: job_application_4 / main
Baseline: e03c3fedd638f8d0599637d102e9a3e41624251e (feat(filling): implement Playwright form filling engine, strict DOM readback, and safe IO (M03))
Approval status: APPROVED FOR PUBLICATION
Destination after approval: origin/main

## Goal and boundaries
- Implement step-by-step pipeline validator (`job_applier/validate_pipeline.py`) checking:
  1. Fetched (Phase 1 extraction captures > 0 questions).
  2. Answered (Phase 2 resolution creates valid answer plan).
  3. Filled (Phase 3 filling engine populates fields with verified DOM readbacks).
  4. Submit blocked (verifies 0 form submissions occur).
  5. Screenshot captured and stored to disk.
- Live Greenhouse execution on Affirm job posting:
  `https://job-boards.greenhouse.io/embed/job_app?for=affirm&token=8039471003`
- Boundaries: Submit button was strictly intercepted and blocked by the observation guard; 0 live applications were submitted to the employer.

## Milestones and evidence
| Milestone | Owner | Status | Evidence |
|---|---|---|---|
| M04 Validator Implementation | coder | PASSED | Implemented `job_applier/validate_pipeline.py`, wired into `job_applier/cli.py`, created `tests/validate_pipeline_test.py` (4 tests). |
| Live Greenhouse Run | coder | PASSED | Executed against `https://job-boards.greenhouse.io/embed/job_app?for=affirm&token=8039471003`. Result: `status: SUCCESS`, 23 questions fetched, 15 ready answers filled & verified, 0 failed, 0 submits, screenshot saved. |
| Resolution & DOM Hardening | coder | PASSED | Added templates for prior employment, job discovery source, state, country, gender, and split sponsorship; supported Greenhouse React-Select live options. |
| Verification Test Suite | coder | PASSED | All unit and regression tests pass (82 filling guard tests, 14 pipeline tests, 7 phase 1 tests, 4 validate pipeline tests, 34 smoke tests, 54 resolution tests). |

## Changed files
| Path | Reason | Behavior change |
|---|---|---|
| `job_applier/validate_pipeline.py` | Pipeline validator tool | Automates fetch -> answer -> fill -> validate steps, verifies DOM values, produces `validation_summary.json`. |
| `job_applier/cli.py` | CLI routing | Adds `validate-pipeline` command to CLI dispatcher. |
| `job_applier/filling/engine.py` | Live Greenhouse combobox & ARIA compatibility | Handles placeholder `aria-describedby` IDs, transient detached frames, and live React-Select option selection. |
| `job_applier/resolution/__main__.py` | Question template expansion | Added templates and aliases for prior employee, source, state (California), country (US), gender, and resume auto-detection. |
| `job_applier/resolution/engine.py` | Keyword & alias matching | Reviewed rules for prior employment, source, split US sponsorship, and dialing code options. |
| `tests/validate_pipeline_test.py` | Unit tests | 4 integration tests verifying pipeline validation against synthetic fixtures and CLI invocation. |

## Checks run
| Command | Result | Evidence |
|---|:---:|---|
| `.venv-phase1/bin/python tests/validate_pipeline_test.py` | PASS | 4/4 passed in 16.07s |
| `.venv-phase1/bin/python tests/filling_guard_test.py` | PASS | 82/82 passed |
| `.venv-phase1/bin/python tests/pipeline_test.py` | PASS | 14/14 passed |
| `.venv-phase1/bin/python tests/phase1_test.py` | PASS | 7/7 passed |
| `python3 tests/smoke.py` | PASS | 34/34 passed |
| `.venv-phase1/bin/python tests/resolution_test.py` | PASS | 54/54 passed |
| `python3 tests/resolution_cli_test.py` | PASS | 23/23 passed |
| `python3 .opencode/scripts/verify.py --static` | PASS | `STATIC_CHECKS_PASSED_ONLY`, exit code 0 |

## Live Demonstration Results (Affirm Greenhouse)
- Target URL: `https://job-boards.greenhouse.io/embed/job_app?for=affirm&token=8039471003`
- Extraction: 23 questions extracted
- Resolution: 15 ready answers mapped to candidate profile
- Filling: 15 fields filled and verified via live DOM readback:
  1. First Name: `"Yash"`
  2. Last Name: `"Kalathiya"`
  3. Email: `"kalathiyayash164@gmail.com"`
  4. Country: `"United States +1"`
  5. Phone: `"(408) 387-2107"`
  6. LinkedIn Profile: `"linkedin.com/in/yashkalathiya"`
  7. Preferred Name: `"Yash"`
  8. Do you require immigration sponsorship to work for Affirm in the United States?: `"Yes"`
  9. Will you require immigration sponsorship at any point in the future...?: `"Yes"`
  10. Which U.S. State or Canadian Province do you reside in?: `"California"`
  11. How did you first learn about Affirm as an employer?: `"LinkedIn"`
  12. Have you previously been employed at Affirm for any length of time?: `"I have not previously been employed at Affirm"`
  13. GitHub: `"github.com/yash-kalathiya"`
  14. Portfolio: `"yash-kalathiya.github.io"`
  15. How do you identify? (gender identity): `"Male"`
- Submissions: 0 submit button clicks, 0 network mutations (snowplow tracking POST requests blocked).
- Stored Screenshot: `/tmp/opencode/live_greenhouse_affirm/screenshot.png` (524,283 bytes).

## Publication
- Approved for publication to `origin/main`.
