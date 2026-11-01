---
name: job-applier-apply
description: "Apply to jobs or internships for the user with Job Applier 4.0, end to end, in their browser. Use for 'job-applier: apply to my top N', 'apply to job <id>', 'apply to everything new at <company>', or running the job-application loop. Needs a browser the agent can drive (Claude in Chrome, computer use, or Codex browser/computer use)."
---

# Job Applier 4.0 apply loop

You are the hands; Job Applier 4.0 is the memory. Job Applier 4.0's MCP tools hold the user's vault, answers, job queue and history.
You drive the browser. Quality over speed: every application should be as good as one the user would do
themselves on a careful day.

## Setup (once per session)
1. `job_applier_get_profile`: note `apply.auto_submit`, `daily_limit`, `per_company_cap`, `stop_on`.
2. `job_applier_playbook("general")` and follow it. Keep it in mind for every job.
3. Make sure you have a browser tool. Work in your own tab or window, never in the user's existing tabs.

## For each job
1. **Pick**: `job_applier_next_jobs(n)` (or the job the user named) -> `job_applier_claim(job_id)`. Skip if not claimed.
2. **Read**: `job_applier_get_job(job_id)`. Check knockouts against the profile: graduation window, work
   authorization/sponsorship, degree level, location, citizenship/clearance. If the user clearly doesn't
   qualify, `job_applier_log_application(job_id, "Skipped", "<reason>")` and move on.
3. **Tailor** (if `apply.tailor_every_resume`):
   - `job_applier_tailor_prompt(job_id)` -> follow its instructions and write the JSON plan yourself. Choose the
     entries and bullets that prove the posting's requirements, mirror its exact terms only where the vault
     backs them, and lead with the strongest evidence.
   - `job_applier_tailor_apply(job_id, plan)` -> returns `pdf` and `tex` (LaTeX source). Check `pages == 1`, `coverage`, `rejected`. If coverage is low and
     the vault has relevant material you left out, revise the plan once. Use the returned `pdf`.
4. **Prepare answers**: Greenhouse: `job_applier_job_questions(job_id)`. Others: read the form's questions, then
   `job_applier_answer_questions([{question, options}])`. Results with `action: "write"` are open-ended questions
   (why this company, what interested you, anything else): write them yourself following `how`, never ask the user and
   never leave them blank. Anything else returned null is a fact only the user knows: collect those, ask the user ONCE
   for all of them (batch across jobs when you can), then `job_applier_save_answer` each.
5. **Fill**: open `apply_url`, `job_applier_playbook(<job.ats>)`, and fill every field. Upload the tailored PDF.
   Write every open-ended answer (required or optional) from the vault + posting, following the `how` rules from step 4.
6. **Verify**: read back every field value; fix anything empty or wrong (selects especially).
7. **Submit or hand off**:
   - `auto_submit` true: submit once, confirm the success page, `job_applier_log_application(job_id, "Applied",
     "<1-line note>", pdf)`.
   - `auto_submit` false: leave the tab on the review screen, log "Needs User" with "ready to submit", and
     tell the user which tabs are ready.
8. **Emailed verification codes** (Greenhouse and others send one after many submits):
   - `profile.apply.email_codes == "agent"`: the user has allowed you to read their email for codes. Use your email tool
     (Gmail connector, or their already-signed-in webmail in the browser), open the newest message from that company/ATS in
     the last 15 minutes, read the code, type it. Never forward, store or show codes anywhere else.
   - otherwise: `job_applier_notify(title="Code needed for <company>", message="Check your email and type it in the open tab", url, job_id)`,
     log "Needs User", leave the tab open, and move on.
9. **Only-the-user steps** (sign-in, password, account creation, CAPTCHA, arbitration, assessments, essays over ~250 words): `job_applier_notify(...)` with exactly what is needed and the URL, log "Needs User", keep the tab, continue.
10. **Coming back**: at the end of the run (and whenever the user says they handled something) call `job_applier_pending_jobs`
   and finish each one that is now unblocked, then `job_applier_log_application(..., "Applied")`.

## Between jobs
- Respect pacing in the general playbook (Greenhouse spacing, company caps).
- Every ~5 jobs, give the user a 1-line progress update.
- At the end: a short table of applied / ready for you / needs you / skipped, with links.

## Never
Type passwords. Type emailed codes unless the user turned on `email_codes: agent`. Solve CAPTCHAs. Create accounts. Invent experience, numbers, skills or
availability. Accept legal agreements for the user. Apply to a company on the skip list.
