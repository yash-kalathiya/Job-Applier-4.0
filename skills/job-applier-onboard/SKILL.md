---
name: job-applier-onboard
description: "Set a user up with Job Applier 4.0, the job-search autopilot. Use when the user says 'set me up with job-applier', wants to import their resume / LinkedIn / brain dump into Job Applier 4.0, build or fill their Career Vault, or set their job preferences and application answers."
---

# Onboard a user onto Job Applier 4.0

Goal: a Career Vault so complete that Job Applier 4.0 can build a top-tier, tailored one-page resume for any posting,
plus a profile and answer bank complete enough that applications rarely need the user. The Job Applier 4.0 MCP tools
(`job_applier_*`) do the storage; you do the interviewing and writing.

## 1. Check where they are
Call `job_applier_setup_status`. Skip finished steps. Tell the user in one line what you're about to do.

## 2. Gather everything (the "dump")
Ask for all of it at once, then work silently:
- Every resume version they have (PDF/DOCX path; read it), their LinkedIn URL or a "Save to PDF" export,
  GitHub, personal site, Devpost, published papers.
- Also `job_applier_get_dump` (text they pasted in the app's Resume Studio).
Read every source. Do not ask questions you can answer from the files.

## 3. Build the vault (`job_applier_save_vault`)
Structure: `basics` (name, email, phone, city/state, links[{label,url}], optional headline tags),
`education[]`, `experience[]`, `projects[]`, `research[]`, `leadership[]`, `skills[{label,items}]`, `awards[]`,
`order`. Bullets use light markdown: `**bold**` and `[text](url)`.

The vault is a SUPERSET, not a resume:
- Keep EVERY role, project, award, paper and skill from every source, newest first.
- 4-8 bullets per significant role is good: the tailor chooses 2-4 per job. Different angles on the same work
  (scale, tech, leadership, result) are valuable; duplicates are not.
- Rewrite weak bullets into the XYZ form (result, measure, method), past tense, strong verb, 80-200 chars,
  **bold** the 1-3 most impressive facts. Keep every fact exactly; never add numbers, tools or claims.
- Missing numbers are the #1 weakness. Collect the bullets that lack a number and ask the user for them in ONE
  batched question ("roughly how many users / how much faster / what %?"). Estimates they can defend are fine.
- Skills: group into 3-6 labeled lines (Languages, Frameworks, Tools/Infra, AI/ML, Data, Hardware...). Only
  skills they have actually used; it's fine to ask "have you used X in a project?" for borderline items.

Show the user a compact summary (counts + 3 of the improved bullets, before/after) and save.

## 4. Profile (`job_applier_update_profile`)
Fill from the resume: name, email, phone, location, school, degree, major, grad month/year, GPA, links.
Then ask ONE batched question for what files can't tell you:
- Work authorization in the US? Will they need sponsorship now or later? Citizenship (only if they want
  government/defense roles)?
- What they want: internship / new grad / full-time; season (e.g. "Summer 2027"); roles; locations; remote ok?
- Dream companies (priority) and companies to never apply to (skip).
- Agent permissions: may Job Applier 4.0 submit on its own (`apply.auto_submit`), or stop at the review screen? Daily
  limit? Max applications per company?
- Optional EEO answers (or "decline").

## 5. Answer bank
The bank is derived from the profile. Ask for anything commonly asked that is still blank (earliest start
date, salary expectation stance, how they heard). Save with `job_applier_save_answer`.

## 6. Resume look
Call `job_applier_templates`, recommend one for their field (Jake's Classic for SWE/quant, Harvard or Finance
One-Pager for finance/consulting, Sans Minimal for big tech/new grad) and render it with
`job_applier_render_resume`. Share the PDF path and the ATS lint results; fix any failed checks with them.

## 7. First scan
`job_applier_scan_jobs` (1-3 min), then `job_applier_list_jobs(limit=15)` and show a short table: fit, company, title,
location. Tell them: "Say *job-applier: apply to my top 10* whenever you want me to start." Remind them they can
also open the app: `job-applier app` (http://localhost:4747).
