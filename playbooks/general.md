# Applying with Job Applier 4.0: the general loop (any ATS)

Job Applier 4.0 learned these from 1,500+ real submissions. Follow them exactly; most failed applications come from a
value that *looks* filled but never registered with the page's framework.

## Before the form
1. `job_applier_next_jobs` -> pick one -> `job_applier_claim(job_id)`; if claimed:false, skip it (another agent has it).
2. `job_applier_get_job` and read the posting. Skip and `job_applier_log_application(status="Skipped")` if a hard requirement
   rules the user out (graduation window, citizenship/clearance when they lack it, degree level).
3. Tailor: `job_applier_tailor_prompt` -> write the plan -> `job_applier_tailor_apply(job_id, plan)`. Use the returned PDF.
   If any rewrites were rejected by the fact guard, that's fine; the original bullet was used.
4. `job_applier_playbook(<ats>)` for this ATS's specifics.

## Filling
- **Upload the resume first** on ATSes that parse it (Workday, SmartRecruiters, Jobvite, Paylocity, Workable,
  Rippling): parsing fills fields a few seconds later and can wipe or duplicate what you typed. Wait for the
  parse, then fix fields. On Greenhouse upload LAST (it steals keyboard focus).
- **Real input beats JS.** Many React forms ignore values set by script. Click the field (or focus it), select
  all, type, press Tab. Then read the value back with JS before moving on.
- **Keystrokes only reach the foreground tab.** Click inside the page (or take a screenshot) before typing.
- **Dropdowns:** open, read the options, click the exact option. Typing "No" can match "Yes, ... now ...";
  typing "Male" can match "Female". Never press Enter on an unmatched typeahead: on some forms Enter submits.
- **Every question:** `job_applier_answer_questions([{question, options}])`. Answers under the confidence threshold
  come back null: ask the user, then `job_applier_save_answer` so you never ask again.
- **Truthful only.** Never invent experience, skills, GPA, dates or availability. If a question asks for
  something the vault doesn't have, ask the user.
- **Optional essays** ("Why us?", "Anything else?"): write 2-4 specific sentences from the vault and the
  posting, plain language, no em dashes, no clichés. Long required essays (>150 words): ask the user first
  unless they said to draft them.

## When the user is needed
- **Emailed codes:** if `profile.apply.email_codes` is `agent`, read the newest code from that company in the user's email
  (Gmail tool, or their signed-in webmail tab) and type it. Otherwise `job_applier_notify` and move on.
- **Sign-ins, passwords, account creation, CAPTCHAs, arbitration agreements, assessments:** `job_applier_notify` with what is
  needed and the URL, log "Needs User", keep the tab open, continue with the next job. Never type a password yourself.
- At the end of every run: `job_applier_pending_jobs`, finish whatever the user unblocked.

## Submitting
- Submit only if `profile.apply.auto_submit` is true. Otherwise fill everything, stop on the review/submit
  screen, and tell the user which tab is ready.
- Click Submit ONCE. If nothing happens with no error, do not hammer it (bot detection): wait, check for a
  validation message, fix it, then retry once.
- Confirm success (confirmation URL or "Thank you"/"Application submitted" text), then immediately
  `job_applier_log_application(job_id, "Applied", notes, resume_path)`.

## Pacing
- Respect `daily_limit` and `per_company_cap` (job_applier_next_jobs already does). Many companies cap applications
  (often 2-3 per 30-60 days); a "maximum number of applications" message means stop for that company.
- Greenhouse starts demanding email codes after ~6-8 rapid submits: space Greenhouse submits 4-5 minutes
  apart and interleave other ATSes.
