# Change report: G02 Prior Employment Resolution via Resume History (Proof of Absence)

Date: 2026-11-02
Repository and branch: job_application_4 / main
Baseline: cf0fdbd43dbd1a49eb5b9241805c1e526e1e94af (+ pre-existing uncommitted edits in AGENTS.md, .opencode/agents/, job_applier/cli.py, untracked reports in docs/agent-reports/, untracked F01 runner files in job_applier/runner.py and tests/runner_test.py, and .opencode/work/ preserved)
Approval status: NOT APPROVED
Destination after approval: origin/main (no automatic push)

## Objective and acceptance criteria
- Objective: Ground prior-employment question resolution (`work.prior_employee`) strictly in the candidate's verified resume/profile work history:
  1. Enforce user directive: absence on resume proves the applicant was never employed at the target hiring company ("Proof of Absence").
  2. If the company being applied to is present in candidate work history, abstain with `status == 'needs_user'` and `reason == 'prior_employer_present_in_resume'` to prevent false negative declarations.
  3. Purge company-specific hardcoded strings (e.g. "Affirm") from default templates and fact banks.
  4. Dynamically match negative option labels across ATS formats while strictly rejecting affirmative role options (contractor, intern, co-op, apprentice, consultant, temp, etc.) from being selected as negative.
  5. Prevent general experience questions ("Have you ever worked at scale / at a startup?") from matching prior company employment.
  6. Defend against malformed banks and provider exceptions in the Qwen cascade tier.
- Non-goals: Automated job application submission (runner strictly logs `Needs User`), direct live ATS submission, personal answer bank modification beyond verified resume facts, or pushing to git remote without explicit user approval.
- Measurable checks:
  1. Question asking about an absent employer resolves to "No" / negative option with `source: 'resume_absence'`.
  2. Question mentioning an employer present on candidate resume abstains with `needs_user`.
  3. Skill and modality questions ("worked with Python", "worked remotely", "worked at scale") return `no_exact_match` and do not match `prior_employee`.
  4. Pseudo-negative options ("No, worked as a contractor", "No, completed an internship here", "No, was a co-op") are rejected and abstain.
  5. Parenthesized country dial codes like `"United States (+1)"` cleanly match country facts.
  6. 88 unit tests, 23 CLI tests, and 34 smoke tests pass deterministically.

## Milestones and evidence
| Milestone | Owner | Status | Actual verification/evidence |
|---|---|---|---|
| Discovery (G01) | Orchestrator + explore | PASSED | Documented in session `ses_e638ba716ffeON2Ysu4yZmFy0f`. Audited 6 missing required Greenhouse fields; verified prior employment failure points. |
| Implementation (G02) | Coder | PASSED | Updated `job_applier/resolution/engine.py`, `job_applier/resolution/__main__.py`, `job_applier/resolution/qwen.py`, and `tests/resolution_test.py`. Added 34 targeted tests (88 total). |
| Defensive Security Review | security-reviewer | PASSED | Session `ses_e63041bbbffe1hEeWmb4JCU65w`: Verified linear-time regexes, ReDoS safety, prompt injection boundaries, memory-pinned keys, and safe exception isolation. 0 vulnerabilities. |
| Code Quality Review | quality-reviewer | PASSED | Session `ses_e6303fedfffeaO1NFCDySCmk1k`: Verified clean AST structure, zero trailing whitespace, zero dead imports, clean index-based cascade updates. |
| Adversarial Bug Review | bug-reviewer | PASSED | Session `ses_e6303da7effeVv3UJQbNpbCsz4`: Verified that all 6 prior blockers hold, polarity inversion is eliminated, and error paths fail closed. |
| Review Lead Consolidation | review-lead | PASSED | Session `ses_e62fe3c56ffel9BpSlxV8xNXAy`: Consolidated PASS across all review gates. |

## Changed files
| Path | Reason | Behavior change |
|---|---|---|
| `job_applier/resolution/engine.py` | Add resume-grounded prior employment check, strict negative option polarity guards, deictic company pointer scoping, and safe cascade exception isolation. | Answers "No" when employer is absent from resume; abstains if employer is present; rejects affirmative contingent options; wraps `llm.match()` in try-except; normalizes parenthesized dial codes. |
| `job_applier/resolution/__main__.py` | Ingest candidate experience across resume/profile schemas (`work`, `experience`), remove hardcoded "Affirm" and generic non-temporal aliases. | Extracts `known_employers` from JSON Resume schemas; allows explicit user overrides in `answers.json`; purges machine-specific `/home/yash/...` paths. |
| `job_applier/resolution/qwen.py` | Defend fact and question option parsing against nulls, non-dicts, and missing keys. | Handles `bank['facts'] = None` and `options = None` without crashing; safely truncates options to 12 items. |
| `tests/resolution_test.py` | Add unit and regression test coverage for all G02 features and edge cases. | Expanded test suite from 54 to 88 tests covering absent employers, known employers, polarity inversion variants, stopword collisions, dial codes, and malformed banks. |

## Checks run
| Command or manual check | Result (PASS/FAIL/NOT_RUN/NOT_AVAILABLE) | Evidence |
|---|---|---|
| `python3 -m unittest tests/resolution_test.py -v` | PASS | 88/88 tests passed in 0.023s. |
| `python3 tests/resolution_cli_test.py` | PASS | 23/23 tests passed in 0.388s. |
| `python3 tests/smoke.py` | PASS | 34/34 assertions passed in clean ephemeral environment. |
| `python3 -m unittest discover -s tests -p validate_pipeline_test.py -k ValidatePipelineMockTests -v` | PASS | 32/32 mock pipeline validation tests passed. |
| `python3 tests/runner_test.py` | PASS | 15/15 queue runner tests passed. |
| `python3 -m py_compile job_applier/resolution/*.py tests/resolution_test.py` | PASS | Clean AST syntax compilation across all modified files. |
| `git diff --check` | PASS | 0 whitespace or formatting errors. |
| `ruff` | NOT_AVAILABLE | Ruff not installed in execution environment. |
| `mypy` / `pyright` | NOT_AVAILABLE | Not configured in repository environment. |
| Live ATS browser automation | NOT_RUN | Offline sandbox review mandate; gated pending Greenhouse dry-run. |

## Issues encountered and resolutions
| Issue | Reproduced? | Resolved? | Exact fix and proof |
|---|---|---|---|
| 1. Hardcoded "Affirm" strings in templates and default bank facts | Yes | Yes | Removed "Affirm" strings from `DEFAULT_TEMPLATES` and `option_labels`; generalized to dynamic employer and negative option matching. |
| 2. Over-broad keyword matching on general experience questions ("worked at scale / startup") | Yes | Yes | `engine.py:82-140`: Required deictic pointer (`this company`, `our company`, `here`) or known employer; explicitly rejected skills and modalities. Proof: `test_general_experience_questions_do_not_match_prior_employee`. |
| 3. Polarity inversion on affirmative options ("No, worked as a contractor", "No, completed an internship here") | Yes | Yes | `engine.py:251-327`: Implemented multi-tier affirmative exclusion covering contractors, interns, co-ops, apprentices, consultants, and temps. Proof: `test_negative_option_guard_rejects_internship_and_apprentice_variants` and `test_negative_option_guard_rejects_hyphenated_coop_and_subcontractor`. |
| 4. Stopwords collision from suffix stripping ("The Company" -> "the") | Yes | Yes | `engine.py:15-19, 120-123, 222-225`: Expanded `EMPLOYER_STOPWORDS` and discarded standalone stopword candidates from question scanning. Proof: `test_resume_with_the_company_does_not_abstain_on_standard_question`. |
| 5. JSON Resume top-level `work` key omitted | Yes | Yes | `__main__.py:241-268`: Ingested `resume.get('work')` alongside `resume.get('experience')`. Proof: `test_standard_json_resume_work_key_extracted`. |
| 6. Crash hazards in `qwen.py` and `engine.py` on null facts / options | Yes | Yes | Defensively guarded `(bank.get('facts') or {})`, `_format_q()`, and wrapped `llm.match()` in try-except. Proof: `test_qwen_match_handles_none_and_malformed_facts` and `test_cascade_handles_crashing_llm`. |

## Outstanding issues, tradeoffs, follow-up work
- Non-blocking P2 observations:
  - Container fact type assertion in `qwen.py:47` (if `facts` is passed as a list).
  - Trailing whitespace inside country dial code labels (`"United States (+1) "`).
  - Missing `model` instance attribute on `QwenMatcher` for exception telemetry.
- Next Operational Steps:
  - G03: Resume file attachment resolution in `engine.py:render` (safely resolving confirmed local PDF paths).
  - G04: Preferred name & Pronouns schema mapping in Phase 2 templates & bank.
  - G05: Monitored dry-run against the live Affirm Greenhouse application stopping strictly at review screen (`auto_submit = False`).

## Security and compliance
- Attestation integrity: Candidate experience is read strictly from local storage (`resume.json` / `profile.json`). Absence proves "No" only per explicit user confirmation that resume contains complete history. If candidate worked at the company, resolution strictly abstains.
- Secrets & privacy: No PII, passwords, or candidate work histories are leaked into error messages or transmitted over external networks. `safe_io` enforces mode `0600` and symlink refusal.
- License status: PolyForm Strict 1.0.0; user confirmed separate rights to modify and publish repository.

## Approval and publication
- User-approved target and scope (fill only after approval): PENDING
- Git commit (fill only after successful commit): PENDING
- Remote verification (fill only after successful push): PENDING
