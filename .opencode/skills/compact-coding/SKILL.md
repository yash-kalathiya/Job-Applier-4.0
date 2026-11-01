---
name: compact-coding
description: Use alongside the community-maintained `karpathy-guidelines` skill for implementing features, fixing bugs, refactoring and writing tests with minimal diffs, clear hypotheses and verifiable completion in `job_application_4`. This is a separate local team standard.
---

# Compact coding: small changes, measurable results

Provenance: original local adaptation inspired by Andrej Karpathy's `karpathy/autoresearch` work, especially constrained edit surfaces and measurable outcomes. Separately install `karpathy-guidelines` from `multica-ai/andrej-karpathy-skills`; that upstream skill is ALSO community-maintained, not authored by Karpathy. Official autoresearch source: https://github.com/karpathy/autoresearch .

1. Start from a concrete behavior to change and a measurable acceptance condition. If the task is a bug, name a reproducible failing case.
2. Understand only the relevant functions, callers and tests before editing. List assumptions that could change correctness.
3. Choose the smallest implementation satisfying the goal. No unrequested abstraction, compatibility scaffolding, rewrite, extra dependencies or gratuitous configurability.
4. Keep each change cohesive and reviewable: one behavior or one milestone at a time. Touch the minimum necessary files and preserve unrelated uncommitted edits.
5. Add or adjust the narrowest tests that distinguish old and intended behavior. Prefer deterministic fixtures and non-networked tests.
6. Run the permitted checks and inspect observed output. Keep a change only when evidence supports the acceptance condition; otherwise debug, revert only YOUR own specific changes safely, or mark blocked. Never run destructive Git reset/clean.
7. Log compactly: problem, change, verification command/result, remaining risk. Do not paste full logs or secrets into reports.
8. No silent feature creep. No auto-submits, external side effects, installs or pushes without task-specific human approval.
