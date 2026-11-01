---
name: job-applier-scout
description: "Find jobs and internships with Job Applier 4.0. Use for 'job-applier: scan', 'find me internships', 'what's new', 'show my top matches', 'watch for new postings', or questions about which companies are hiring for the user's target roles."
---

# Scout jobs with Job Applier 4.0

1. `job_applier_scan_jobs` (scrapes the SimplifyJobs / community lists, the SmartRecruiters live feed, and ~500
   Greenhouse, Lever, Ashby and Workday boards; 1-3 minutes). Report new / matched counts.
2. `job_applier_list_jobs(limit=25, order="fit")` (or `order="new"` for "what's new"). Present a compact table:
   fit | company | title | location | ATS | job_id. Group by company when one company has many.
3. Point out the standouts: priority companies, postings under 24 hours old, anything with fit >= 85.
4. If results look wrong (too few, wrong roles, wrong level), adjust `search` in the profile with
   `job_applier_update_profile` (roles, include/exclude, locations, kind, season, min_fit) and rescan. Explain the change.
5. Offer next steps: "apply to the top N" (job-applier-apply) or "tailor for <id>" (job-applier-tailor).

## Watching
For "tell me the moment X posts": the user can run `job-applier watch --every 120` in a terminal (it polls the
fastest sources and sends a desktop notification). For a company Job Applier 4.0 doesn't scrape yet, find its careers
page; if it's on Greenhouse/Lever/Ashby/SmartRecruiters/Workday, add the board slug to `~/.job-applier/companies.json`
(copy the shipped `data/companies.json` there first) and rescan.
