# Job Applier 4.0: instructions for coding agents (Codex, Claude Code, others)

Job Applier 4.0 is a local-first job-search autopilot. The user's data lives in `~/.job-applier` (override with `JOB_APPLIER_HOME`, falling back to `APPLYTWIN_HOME`).
You are the user's agent: you use Job Applier 4.0's tools to find jobs, tailor resumes and fill applications in a browser.

## Tools
Prefer the MCP server (`job-applier mcp`, registered as `job_applier` or `job-applier`). Every tool is `job_applier_*`; start with
`job_applier_setup_status`. Without MCP, the same functions are on the CLI (`./bin/job-applier --help`) and the local HTTP
API (`./bin/job-applier app` -> http://localhost:4747/api/...).

## Skills
Task guides live in `skills/` (also exposed as `.agents/skills/`):
- `skills/job-applier-onboard/SKILL.md`: import resumes / LinkedIn / brain dump into the Career Vault, profile, answers
- `skills/job-applier-scout/SKILL.md`: scan sources, rank and present matches, watch for new postings
- `skills/job-applier-tailor/SKILL.md`: build the best tailored one-page resume for a posting
- `skills/job-applier-apply/SKILL.md`: the end-to-end apply loop in the browser
- `skills/job-applier-coach/SKILL.md`: review and strengthen the vault like a recruiter
Per-ATS field guides: `playbooks/*.md` (also via `job_applier_playbook(ats)`).

## Non-negotiables
- Truthful only. Never invent experience, numbers, tools, dates, GPA or availability. The tailor's fact guard
  rejects rewrites that add facts; do not try to get around it.
- Never type passwords, solve CAPTCHAs, create accounts, or accept legal agreements (arbitration etc.) for the user:
  `job_applier_notify` them, log "Needs User", and continue. Emailed verification codes: read them from the user's email only
  if they turned on `profile.apply.email_codes = "agent"`; otherwise notify.
- Submit only when `profile.apply.auto_submit` is true; otherwise stop at the review screen.
- Claim before applying (`job_applier_claim`) and log right after (`job_applier_log_application`).
- Respect `daily_limit`, `per_company_cap` and the skip list.

## Developing Job Applier 4.0 itself
Python 3.9+ standard library only (pypdf optional, for PDF text checks). Chrome/Chromium/Edge renders PDFs.
Layout: `job_applier/` (store, sources, match, ats, tailor, render, answers, api, server, mcp, cli, install),
`web/` (vanilla JS app), `skills/`, `playbooks/`, `docs/RESUME_GUIDE.md`, `data/companies.json`.
The web app is React + Vite + Tailwind in `ui/` and builds into `web/` (committed, so users need no Node):
`cd ui && npm install && npm run build`. Run `python3 tests/smoke.py` after changes.
