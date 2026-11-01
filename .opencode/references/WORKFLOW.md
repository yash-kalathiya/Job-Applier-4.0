# Multi-agent delivery protocol

The primary orchestrator must use this gated process and make evidence explicit. All statuses begin NOT_STARTED.

| Gate | Owner | Checkable exit condition |
|---|---|---|
| G0 Baseline | Orchestrator + explore | Actual `job_application_4` repository, branch, changes and license/reuse basis identified; current user changes preserved; external `karpathy-guidelines` and `security-audit` verified installed. |
| G1 Spec | Orchestrator | Goal, non-goals, failure behavior, interface constraints and milestone test criteria are written. |
| G2 Implementation | Coder | Scoped files changed using both `karpathy-guidelines` and `compact-coding`; new/changed behavior demonstrated; regression tests added where appropriate. |
| G3 Verification | Coder + quality reviewer | Exact lint/type/test commands and observed exit/result documented; unrun checks explained. |
| G4 Independent audit | Security, quality, bug reviewers | Same diff/ref reviewed separately, findings evidence-backed with scope and gaps. |
| G5 Consolidation | Review lead + orchestrator | Blocking issues fixed and re-reviewed or task explicitly BLOCKED. |
| G6 Documentation | Orchestrator | Report in docs/agent-reports/ covers objective, diffs, issues, solutions, evidence and remaining tasks. |
| G7 Approval | Human | Explicit approval for the reviewed changes and exact destination remote/branch, AFTER report presented. |
| G8 Publish | Publisher | Only approved paths committed; normal Git push completed and remotely verified. |

For every task maintain in current session or `.opencode/work/<task-id>.md`:
```
Milestone: M01
Owner: coder
Dependencies: G0, G1
Paths: ...
Acceptance: ... (observable)
Check command / manual observation: ...
Evidence: exit code, assertion summary, changed file paths
Status: NOT_STARTED | IN_PROGRESS | PASSED | BLOCKED
```

Parallelism: independent read-only review agents may run at once after the same stable code revision. The coding agent is the ONLY source writer; orchestrator is the only documentation writer. If reviewers run at different refs, discard their combined verdict and rerun as needed.

Approval: No push, commit, merge, tag or externally visible app-side effect until the user explicitly authorizes the exact action. No automatic retry of an uncertain employer submission. Even after publishing, application submissions require independent approval.

Review evidence taxonomy: PASS (ran and passed), FAIL (ran and failed), NOT_RUN (was not executed), NOT_AVAILABLE (missing tool), NEEDS_VALIDATION (insufficient evidence). Never use PASS for inference alone.

Release report format: use `docs/agent-reports/TEMPLATE.md`, fill a dated copy, and add it to the reviewed diff before approval. Re-review if that docs change materially impacts generated code or distribution artifacts.
