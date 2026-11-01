---
name: job-applier-history
description: Find every job the user already applied to by reading their application confirmation emails, and record them in Job Applier 4.0 so it never applies twice. Use for "import what I already applied to", "check my email for applications", "find my past applications", or before a first Autopilot run.
---

# Find past applications in email

Goal: every role the user already applied to goes into Job Applier 4.0 with `job_applier_import_applied`, so it is skipped
forever (even if a later scan finds it again). Truthful only: record what an email shows, never guess.

## 1. Open their email in your browser
- Use the browser set up for you (Playwright, or Claude in Chrome). Open Gmail (mail.google.com), Outlook
  (outlook.live.com / outlook.office.com) or the school's webmail, whichever the user uses (ask once if unclear).
- If you see a sign-in page: do NOT type a password. `job_applier_notify("Sign in to your email in your agent's browser",
  "<url>")`, tell the user, and wait for them to say they're signed in. Then continue.

## 2. Search the last 12 months for confirmations
Run each search (Gmail syntax shown; Outlook search accepts the plain phrases) and work through every result page:
- `"thank you for applying" newer_than:1y`
- `"application received" OR "we received your application" OR "thanks for your application" newer_than:1y`
- `"your application" (submitted OR received OR "has been") newer_than:1y`
- `from:(greenhouse.io OR lever.co OR ashbyhq.com OR myworkday.com OR myworkdayjobs.com OR icims.com OR smartrecruiters.com OR jobvite.com OR successfactors.com OR taleo.net OR workable.com OR rippling.com OR handshake) newer_than:1y`
- `from:jobs-noreply@linkedin.com "your application was sent" newer_than:1y`

## 3. Read company and role
- From the subject or first lines: "Thank you for applying to <Role> at <Company>", "Your application for <Role>",
  "<Company> | Application received". Company is often the sender name ("Stripe Recruiting" -> Stripe).
- Status: rejections ("we've decided to move forward with other candidates") still mean they applied: status
  "Rejected". Interview invites: "Interview". Otherwise "Applied".
- Skip newsletters, job alerts ("jobs you may like"), and anything that isn't about an application they submitted.
- If the role isn't stated, use the most specific title the email gives (e.g. "Software Engineering Internship").

## 4. Record in batches
Call `job_applier_import_applied(items=[{company, title, url?, date?, status?}], source="email")` every ~25 emails.
It deduplicates, so overlap is fine. Finish with a one-line summary: how many found, and how many matched jobs
already in their queue.
