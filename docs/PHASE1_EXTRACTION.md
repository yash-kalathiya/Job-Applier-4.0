# Job Applier 4.0 Phase 1

The optional extraction command opens a public application in a fresh Playwright
browser context and captures questions without answering them. It exports a
searchable HTML report, structured JSON, raw accessibility snapshots, and a source
page screenshot. No profile or model provider is loaded.

## Run

From the Job Applier 4.0 checkout, using Python 3.12 and `uv`:

```bash
uv venv --python 3.12 .venv-phase1
uv pip install --python .venv-phase1/bin/python -r requirements-phase1.txt
.venv-phase1/bin/python -m playwright install chromium
.venv-phase1/bin/python bin/job-applier extract 'APPLICATION_URL' --out artifacts/phase1/my-capture
```

The isolated environment and Chromium are already available on this machine.
Use a new output directory for each capture. Existing evidence is never overwritten.
Add `--headed` to see the browser, `--channel chrome` to use installed Google Chrome,
or `--no-probe-options` to disable opening custom dropdowns.

Open `index.html` in the output directory. Search questions, filter warnings, expand
option lists, and inspect each question's DOM and accessibility evidence.

## How extraction works

1. Wait briefly for a stable control inventory across the page and its frames.
2. Capture frame accessibility snapshots with Playwright.
3. Read labels, attributes, constraints, grouping, visibility, current state, and
   native options from each candidate's DOM structure.
4. Capture the same locator's accessibility snapshot. Check DOM identity before
   and after capture; retain disagreements instead of scoring them away.
5. Exclude invisible helper controls, while retaining hidden file inputs with
   associated visible upload controls. Use a file group's label for the question
   when the individual control is only labeled “Attach.”
6. Open uniquely associated custom comboboxes to observe options, then press Escape
   without selecting or entering text. Record whether the value stayed unchanged.
7. Group related radios and same-name checkbox options. Keep repeated labels in
   different sections as separate question instances.
8. Save typed questions, control evidence, instructions, capture issues, and notices.

DOM and accessibility evidence join through the **same locator**, not fuzzy label
or coordinate matching. Structural paths and frame IDs are snapshot references,
not permanent question-bank IDs or guaranteed future execution targets.

## Files and contracts

- `job_applier/extraction/engine.py`: observation guard, extraction, option inspection,
  grouping, snapshot schema.
- `job_applier/extraction/dom.js`: DOM evidence collector, including open shadow roots.
- `job_applier/extraction/report.py`: escaped, self-contained HTML report.
- `job_applier/extraction/__main__.py`: browser lifecycle and artifact export.
- `requirements-phase1.txt`: optional pinned Playwright dependency.
- `tests/phase1_test.py`: real-browser tests on synthetic forms.
- `tests/fixtures/phase1.html`: labeled fixture with deliberate ambiguity and custom controls.

`questions.json` uses `job-applier.form-snapshot.v1`. A question contains its exact
text, input kind, required status (`true`, `false`, or `null` for unknown), options,
help, section, control IDs, and warnings. Each control retains DOM and accessibility
evidence, scoped locator candidates, and a capture identity. The top level includes
runtime versions, frame snapshots, form instructions, issues, notices, and metrics.

## Current boundary

- This is Phase 1 only. There is no answer mapping, question-bank write, upload,
  resume tailoring, filling, submission, or model call.
- Native select options are complete for that captured element. Custom listbox
  options are observed entries; even a two-item Yes/No list is marked incomplete
  because visibility alone cannot prove an async/virtualized list is exhaustive.
  Captures cap each custom list at 500 entries and each frame at 250 candidate controls.
- Hidden conditional branches and later pages are not explored. A later extraction
  can observe newly revealed controls, but the Phase 1 command does not reveal them
  by answering questions. Alternate file-entry actions remain context evidence.
- CAPTCHA frames are recorded as uninspected notices. Login/password controls are
  flagged; this command does not sign in or use the user's saved browser state.
- The fresh context blocks non-GET/HEAD/OPTIONS HTTP requests, form submissions,
  and submit-button clicks. This can prevent POST-backed option loading; it cannot
  guarantee that every GET request on an arbitrary website is side-effect free.
- Runtime screenshots and snapshots can contain page content. Output directories
  are private and ignored by Git. No external scripts/fonts are used by the report.
- The existing application branding and authentication remain as they were. The
  Phase 1 command and report are the first Job Applier 4.0 component in this checkout.

## Verify

```bash
.venv-phase1/bin/python tests/phase1_test.py -v
python3 tests/smoke.py
```

The browser suite checks DOM/AX label conflicts, grouped options, repeated labels,
frames, open shadow roots, hidden upload and validation helpers, conditional refresh,
custom option completeness, unchanged values, submission/network guards, HTML
escaping, search, and narrow-screen layout. The CLI uses no LLM inference; development
and debugging token usage are separate from the extraction's zero model tokens.

References: [Playwright accessibility snapshots](https://playwright.dev/python/docs/aria-snapshots),
[Playwright locators](https://playwright.dev/python/docs/locators), and the user's
[earlier Greenhouse extractor](https://github.com/yash-kalathiya/Job_application_2.0/blob/778ad40db6f89b3c7fcb430d6eb0862644bd4c78/phases/job_applier/extractor/job_form_extractor_greenhouse.py).
