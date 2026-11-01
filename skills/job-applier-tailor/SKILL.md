---
name: job-applier-tailor
description: "Build the best possible tailored one-page resume for a specific job with Job Applier 4.0, from the user's Career Vault. Use for 'job-applier: tailor my resume for <job/url>', 'make my resume fit this posting', or when the user pastes a job description and wants a resume for it."
---

# Tailor a resume with Job Applier 4.0

1. Get the job: a Job Applier 4.0 `job_id`, or `job_applier_add_job(url, title, company, description)` for a pasted posting
   (paste the description text when you can: it makes tailoring far better).
2. `job_applier_ats_report(job_id)` to see the vault's raw coverage and which hard skills are missing.
3. `job_applier_tailor_prompt(job_id)` and write the plan like a top recruiter in this field would:
   - **Top third wins.** The first role and its first bullet must hit the posting's #1 requirement.
   - **Fill one page with the strongest material.** A student resume is usually 4-6 entries and 14-18 bullets:
     the current/most relevant roles get 2-4 bullets, projects and leadership 1-2. A half-empty page reads as thin;
     Job Applier 4.0 tops up empty space with the next-best true bullets, and trims the weakest lines if it overflows.
   - **Use the bullet ids exactly as the vault shows them** (`"drift.0"`, `"drift.1"`, ...). A rewrite is
     `{"from": "<id>", "text": "<rewritten bullet>"}`; a bullet kept as-is is just its id. Awards are by number,
     counting from 0, or by their exact text.
   - **Mirror vocabulary truthfully.** If the posting says "distributed systems" and the bullet describes a sharded
     service, say it. Never add a tool, number, scale or claim that the same vault entry does not contain: the fact
     checker rejects it, and a number must keep its meaning ("40K events/sec" is never "40K users").
   - **Every bullet**: past-tense action verb first (present tense for a current role), one result, ideally a
     number, under two lines. No "responsible for", no filler.
   - **Skills**: reorder lines and items so the posting's terms lead; keep the user's own labels.
   - Template: `job_applier_templates`; finance/consulting -> `finance` or `harvard`, else the user's default.
4. `job_applier_tailor_apply(job_id, plan, template)`, then check what came back:
   - `pages` is 1.
   - `rejected`: rewrites the fact checker refused, each with the reason. Fix them (closer to the original wording,
     no new facts) and apply again; never leave strong material out because a rewrite was refused.
   - `dropped`: lines trimmed to fit. If something important was dropped, cut a weaker bullet instead and re-apply.
   - `added`: bullets Job Applier 4.0 used to fill empty space. If one is a poor fit, choose a better one yourself.
   - `coverage`: aim for 70%+ of the hard skills the vault can support.
   Revise until all of that is right (usually once).
5. Report: the PDF path, coverage before -> after, the 3 most important choices you made, and the missing
   hard skills as an honest "to learn or to add if you've done it" list. Ask if they have done any of those
   (if yes, add to the vault with `job_applier_get_vault` + `job_applier_save_vault`, then re-tailor).
