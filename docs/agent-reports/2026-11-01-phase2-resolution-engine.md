# Change report: Phase 2 Resolution Engine Unit Tests & Hardening

Date: 2026-11-01
Repository and branch: job_application_4 / main
Baseline: f0bdf53 (Job Applier 4.0: Initial commit)
Pre-existing uncommitted edits preserved:
- `.opencode/agents/coder.md` (model configuration)
- `.opencode/agents/orchestrator.md` (model configuration and shell permission limits)
Approval status: NOT APPROVED FOR PUBLICATION (local development report)
Destination after approval: origin/main (no automatic push; push withheld per policy)

## Objective and acceptance criteria
- Objective: Provide complete, hermetic unit test coverage and robust edge-case hardening for Phase 2 question resolution (`job_applier/resolution/engine.py`).
- Non-goals: Form filling (Phase 3), browser automation, real employer submissions, network calls, external LLM calls during tests.
- Measurable checks:
  - 100% pass on normalized exact matching, reviewed keyword rules (US visa sponsorship), option identification, abstention on label conflicts, missing labels, and option changes.
  - Zero crashes on null/missing options, warnings, sections, and scopes.
  - Halt cascade progression for blocked warnings, preventing leakage to semantic and LLM tiers.
  - Preserve caller-supplied abstention reasons and custom boolean option labels.
  - Execution of unit test suite without external dependencies.
  - Preserved baseline repository smoke tests (34/34 passing).

## Milestones and evidence
| Milestone | Owner | Status | Actual verification/evidence |
|---|---|---|---|
| M00 Baseline/license | orchestrator | PASSED | PolyForm Strict 1.0.0 identified; external skills verified via `python3 .opencode/scripts/check_team.py --external` |
| M01 Implementation | coder | PASSED | Created `tests/resolution_test.py` (48 unit tests); hardened `job_applier/resolution/engine.py` |
| Verification | coder | PASSED | `python3 tests/resolution_test.py` (48/48 PASS), `python3 tests/smoke.py` (34/34 PASS), static verify exit code 0 |
| Security review | security-reviewer | PASSED | Cloudflare `security-audit` skill loaded; 0 vulnerabilities; trust boundaries and prompt injection defenses confirmed |
| Quality review | quality-reviewer | PASSED | Enterprise review loaded; line wrapping <100 chars, `sys.path` bootstrapping verified, 0 dead code |
| Bug review | bug-reviewer | PASSED | Karpathy guidelines applied; verified null-safety, mixed-batch cascade isolation, and deterministic signatures |
| Review lead reconciliation | review-lead | PASSED | Reconciled findings across two review cycles; approved rework resolution |

## Changed files
| Path | Reason | Behavior change |
|---|---|---|
| `job_applier/resolution/engine.py` | Defect remediation & edge-case hardening | • Null-safe `normalize(None)` returning `''`.<br>• Guard `section=None` in `eligible()` and `pending_questions()`.<br>• Guard `warnings=None` across matching and rendering.<br>• Null-safe option item traversal and option label normalization.<br>• Cascade halting on `BLOCKED_WARNINGS`: skips semantic search and restricts LLM result updating to `unresolved_ids`, preserving `'exact'` tier and blocked reasons in mixed batches.<br>• Retains custom `option_labels` on boolean facts alongside `'Yes'` / `'No'`.<br>• Preserves caller-supplied abstention reason when `fact_key` is null.<br>• Null-safe `scope or ''` in `pending_questions` signature join.<br>• Guard empty question text in `exact_match`. |
| `tests/resolution_test.py` | Unit test suite & regression suite | 48 hermetic unit tests covering `normalize`, `eligible`, `exact_match`, `abstain`, `render`, `resolve_exact`, `resolve_semantic`, `resolve_cascade`, `pending_questions`, and dedicated `TestRegressionReviewFixes`. |

## Checks run
| Command or manual check | Result (PASS/FAIL/NOT_RUN/NOT_AVAILABLE) | Evidence |
|---|---|---|
| `python3 tests/resolution_test.py` | PASS | Ran 48 tests in 0.002s, OK |
| `python3 tests/smoke.py` | PASS | 34/34 passed |
| `python3 .opencode/scripts/verify.py --static` | PASS | `STATIC_CHECKS_PASSED_ONLY`, exit code 0 |
| `python3 -m unittest tests/local_auth_test.py` | PASS | 5/5 passed |
| `.venv-phase1/bin/python -m unittest tests/phase1_test.py` | PASS | 7/7 passed |
| `node --test skills/security-audit/*.test.cjs` | PASS | 65/65 passed across schema and ledger validators |
| `python3 .opencode/scripts/check_team.py --external` | PASS | 7 agents, 2 local skills, 2 external skills all PASS |

## Issues encountered and resolutions
| Issue | Reproduced? | Resolved? | Exact fix and proof |
|---|---|---|---|
| Standalone `python3 tests/resolution_test.py` failed with `ModuleNotFoundError` | Yes | Yes | Added `sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))` to `tests/resolution_test.py`. Verified direct execution passes. |
| Mixed-batch cascade tier corruption: blocked questions overwritten to `tier: 'qwen'` | Yes | Yes | Scoped LLM prediction updates in `resolve_cascade()` to `unresolved_ids = {q['id'] for q in unresolved}`. Verified via `test_cascade_halts_on_blocked_warnings_with_unresolved_sibling`. |
| Fatal crash `TypeError: Value after * must be an iterable, not NoneType` on `'option_labels': None` | Yes | Yes | Replaced `*fact.get('option_labels', [])` with `*(fact.get('option_labels') or [])` in `render()`. Verified via `test_null_option_labels_in_fact_does_not_crash`. |
| Fatal crash `TypeError` on `scope=None` in `pending_questions` | Yes | Yes | Sanitized `scope` with `scope or ''` in signature join. Verified via `test_pending_questions_null_scope`. |
| Empty / whitespace question matching empty bank alias | Yes | Yes | Added early return `if not text: return None, 'no_exact_match'` in `exact_match()`. Verified via `test_blank_question_does_not_match_empty_alias`. |
| `normalize(None)` returning string `'none'` | Yes | Yes | Added `if text is None: return ''` in `normalize()`. Verified via `test_section_none_does_not_match_none_substring`. |

## Outstanding issues, tradeoffs, follow-up work
- Next safe milestone: Milestone M02 (`job-applier resolve` CLI command and snapshot schema validation pipeline).
- Phase 3 form filling: Design and implement Playwright form filling engine with strict submission interception and synthetic Greenhouse HTML fixtures (`tests/fixtures/greenhouse.html`).
- External model integration: FastEmbed embedding models and Groq/Qwen gateways should receive dedicated mocked integration tests (Milestone M03).

## Security and compliance
- Findings: Zero exploitable vulnerabilities identified by `security-reviewer`.
- Data/privacy boundaries: No employer submissions, no network egress during unit testing, no credentials stored or leaked.
- License/attribution status: PolyForm Strict 1.0.0 notice maintained. No third-party restricted code was copied or incorporated.

## Approval and publication
- User-approved target and scope: NONE (changes held locally; no push or commit requested).
- Git commit: None (uncommitted working tree).
- Remote verification: Push withheld per strict human approval requirements.
