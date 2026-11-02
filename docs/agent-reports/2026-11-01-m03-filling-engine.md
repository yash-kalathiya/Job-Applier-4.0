# Change report: M03 Form Filling Engine & Pipeline Hardening

Date: 2026-11-01
Repository and branch: job_application_4 / main
Baseline: 3ee60f0315c9645eaa8f8d70ec8fd93cf61cca61
Approval status: APPROVED FOR PUBLICATION
Destination after approval: origin/main

## Goal and boundaries
- Implement Phase 3 form filling engine (`job_applier/filling/`) with observation guard, strict DOM readback, and submit prevention.
- Propagate form/frame/control identity through extraction and resolution to ensure zero wrong-target mutations.
- Implement dependency-free atomic safe I/O (`job_applier/safe_io.py`) using Linux directory descriptors and atomic link/replace.
- Preflight validation of complete plan schema before browser launch.
- Non-goals: live employer submission, credential automation, CAPTCHA bypass during testing.
- Boundaries: all testing executed in local synthetic fixtures and ephemeral loopback servers.

## Milestones and evidence
| Milestone | Owner | Status | Evidence |
|---|---|---|---|
| M03 Implementation & Repairs | coder | PASSED | Repaired F1–F9: radio form ownership (`el.form`), frame identity (`element_id`), dynamic combobox re-resolution, native select readback, live ARIA legal semantics, safe I/O. |
| Verification (Clean Environment) | coder / validator | PASSED | 214/214 tests executed in `bwrap` network namespace isolated sandbox (repo mounted read-only, clean environment). Zero failures. |
| Security Assessment | security-reviewer | PASSED | Confirmed no High/Critical vulnerabilities. Mutation HTTP methods (POST/PUT/DELETE/PATCH) and submit events blocked. |
| Safe I/O Validation | test suite | PASSED | Verified atomic no-clobber, directory descriptor pinning against ancestor replacement, symlink refusal across all 3 CLIs. |
| Synthetic E2E Execution | pipeline test | PASSED | 6/6 target fields filled and verified in primary form; non-targets in secondary forms and child frames verified untouched. |

## Changed files
| Path | Reason | Behavior change |
|---|---|---|
| `job_applier/safe_io.py` | Secure atomic evidence output | Descriptor-based traversal (`O_DIRECTORY \| O_NOFOLLOW`), atomic `os.link` / `os.replace`, `0700` leaf dirs, `0600` files, symlink refusal. |
| `job_applier/filling/engine.py` | Form filling engine & observation guard | Intercepts mutating requests/submits; enforces native `.form` ownership and captured DOM IDs; validates combobox submitted mapping; checks live ARIA legal context; verifies live DOM values. |
| `job_applier/filling/__main__.py` | CLI entrypoint `job-applier fill` | Preflight plan schema validation before browser launch; structured JSON error output; safe I/O evidence writing. |
| `job_applier/filling/__init__.py` | Package exports | Exports `SCHEMA_VERSION`, `fill_form`, `install_observation_guard`, `validate_answers_plan`. |
| `job_applier/cli.py` | Command routing | Adds `fill` command dispatching to `job_applier.filling.__main__.main`. |
| `job_applier/extraction/dom.js` | Form ownership capture | Uses `element.form \|\| element.closest('form')` for native form association. |
| `job_applier/extraction/engine.py` | Identity propagation | Preserves native `dom['type']`, `form_id`, locator candidates, and frame descriptors in questions. |
| `job_applier/extraction/__main__.py` | Safe I/O integration | Routes all extraction artifacts (`questions.json`, `index.html`, etc.) through `safe_io`. |
| `job_applier/resolution/engine.py` | Resolution metadata preservation | Preserves targeting metadata (`frame_descriptor`, `locator_scope`, `control_metadata`) across all answer statuses. |
| `job_applier/resolution/__main__.py` | Degree qualification restriction & Safe I/O | Removes broad degree family aliases (exact matching only); integrates `safe_io`. |
| `tests/filling_guard_test.py` | Filling & safety test suite | 82 unit and safety regression tests. |
| `tests/pipeline_test.py` | 3-CLI end-to-end pipeline test | 14 integration tests using loopback GET mutation collector and wrong-target mutation oracle. |
| `tests/fixtures/greenhouse.html` | Synthetic Greenhouse fixture | Greenhouse form with required/optional fields, combobox, radio group, select, file input. |
| `tests/fixtures/pipeline.html` | Synthetic multi-form fixture | Multi-form test fixture with duplicate labels across forms, external `form=` inputs, and iframe. |
| `tests/resolution_test.py` | Resolution engine unit tests | 54 unit tests for matching, degree qualification exactness, and safe I/O. |
| `tests/resolution_cli_test.py` | Resolution CLI unit tests | 23 unit tests for CLI argument parsing and symlink refusal. |

## Checks run
| Command | Result | Evidence |
|---|:---:|---|
| `.venv-phase1/bin/python tests/pipeline_test.py` | PASS | 14/14 tests passed in 22.25s |
| `.venv-phase1/bin/python tests/filling_guard_test.py` | PASS | 82/82 tests passed in 38.65s |
| `.venv-phase1/bin/python tests/phase1_test.py` | PASS | 7/7 tests passed in 3.13s |
| `python3 tests/resolution_cli_test.py` | PASS | 23/23 tests passed in 1.04s |
| `python3 tests/resolution_test.py` | PASS | 54/54 tests passed in 0.13s |
| `python3 tests/smoke.py` | PASS | 34/34 passed in 23.49s |
| `python3 .opencode/scripts/verify.py --static` | PASS | `STATIC_CHECKS_PASSED_ONLY`, exit code 0 |

## Issues resolved
1. **Radio Form Ownership**: Enforces native `el.form` to reject elements re-associated via `form="..."` or moved to another form before click.
2. **Captured Owner Absence**: Controls captured without a form reject newly acquired form owners.
3. **Native Select Focus Re-order**: Re-evaluates live options after focus and selects by value rather than stale index.
4. **Combobox Verification**: Rejects unsupported comboboxes lacking named hidden inputs; validates both hidden value and display text; rejects empty hidden values.
5. **Dynamic Option Filtering**: Re-evaluates live options after search typing; matches by ID/label/value rather than preflight index.
6. **Live ARIA Legal Semantics**: Inspects all associated labels, ancestor fieldsets, and ARIA references; skips agreements unchanged regardless of review flag.
7. **Safe I/O Overhaul**: Pinned directory descriptors (`O_DIRECTORY | O_NOFOLLOW`), atomic `os.link` no-clobber, atomic `os.replace` overwrite, symlink refusal across all 3 CLIs.
8. **Preflight Plan Validation**: Rejects malformed plans before browser launch with structured JSON errors.
9. **Real CLI Mutation Oracle**: Loopback GET mutation collector verifies exact states across main and iframe documents; detects injected wrong-target mutations.

## Limitations
- GET/HEAD/OPTIONS requests and pre-existing WebSocket connections are not blocked by the client-side observation guard. Testing must remain restricted to local synthetic fixtures.
- Live ATS platforms with non-standard canvas widgets or closed shadow roots require specialized adapters.

## Publication
- Approved for publication to `origin/main`.
