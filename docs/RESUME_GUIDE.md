# The Job Applier 4.0 resume guide

Distilled from the r/cscareerquestions wiki, Harvard OCS and MIT CAPD guides, Google's "XYZ" advice, recruiter
interviews, and how Greenhouse / Lever / Workday / iCIMS / Ashby actually parse and search resumes. Job Applier 4.0's
tailoring prompt, fact guard and ATS lint all follow these rules.

## What a recruiter does with your resume
1. **6 to 10 seconds on the first pass.** They read the top third: name, school and grad date, the first two roles,
   and anything bold. If nothing there matches the posting, they stop.
2. **Keyword search inside the ATS.** Recruiters filter by knockout answers (work authorization, sponsorship,
   graduation date, location), then search candidates for terms like `"React" AND "AWS"`. A resume without the
   posting's hard skills does not show up, however good it is.
3. **The deep read happens after the screen.** That is when depth, links and projects get you the interview.

So the resume has to (a) parse cleanly, (b) contain the posting's exact hard-skill terms, in context, and
(c) put the strongest, most relevant evidence in the first third.

## Structure
- **One page** for students and anyone with under about 10 years of experience. Two pages after that.
- **Single column.** No tables, text boxes, sidebars, icons or photos. Nothing in the PDF header or footer.
- **Order for students:** Education, Experience, Projects, Skills, then Leadership and Awards. Lead with Projects
  instead of Experience when the projects are clearly stronger for this role.
- **Order for experienced candidates:** Experience, Projects, Skills, Education.
- **Within a section:** reverse-chronological, but drop entries that do not help this posting.
- **Header:** Name, then phone | email | city, ST | linkedin.com/in/x | github.com/x | site. Spell links out as text.
- **Headings:** standard names only (Education, Experience, Projects, Skills, Research, Leadership, Awards). Parsers
  key on them.
- **Dates:** one format everywhere (`Jun 2025 – Aug 2025`, `Present`), right-aligned.
- **Education:** degree, major, expected graduation month and year. Include GPA if it is 3.3 or higher. Coursework
  only while it is your strongest signal (freshman and sophomore year).

## Bullets: the part that gets interviews
- **XYZ formula:** *Accomplished [X], as measured by [Y], by doing [Z].* Lead with the result, then how.
  - Weak: "Worked on the backend for the payments team."
  - Strong: "Cut checkout p99 latency 38% (410 to 255 ms) by moving fraud scoring to an async Kafka consumer."
- **Start with a strong past-tense verb** (present tense only for a current role): Built, Shipped, Designed,
  Architected, Automated, Reduced, Scaled, Optimized, Led, Launched, Debugged, Benchmarked, Modeled, Deployed.
- **Quantify at least 60% of bullets:** users, requests per second, latency, %, $, time saved, rank, accuracy,
  number of teams that adopted it. Estimates are fine when you can defend them.
- **1 to 2 lines (80 to 200 characters).** 2 to 4 bullets for a relevant role, 1 to 3 per project.
- **Put the tech in context**, not only in Skills: "...with PyTorch on 8 A100s", "...in Rust (Tauri)".
- **Bold 1 to 3 facts per entry**: the things you would want a skimmer to see (scale, a famous name, a win).
- **Never:** "Responsible for", "Helped with", "Worked on", "Various", first-person pronouns, buzzwords, or the
  same opening verb more than twice.

## Tailoring for each posting (what Job Applier 4.0 automates)
1. **Pull the posting's hard skills**, weighting the requirements section above the company blurb.
2. **Choose from the vault:** the 3 to 6 most relevant roles and projects, and inside each the bullets that prove the
   posting's requirements. Relevance beats recency when they conflict, but keep the most recent role.
3. **Mirror the posting's exact words where the vault proves them.** If it says "CI/CD" and you built "GitHub
   Actions pipelines", write "CI/CD (GitHub Actions)". If it says "distributed systems" and you built a sharded
   queue, say so. Never add a skill the vault cannot back: it will come up in the interview.
4. **Reorder the Skills lines and items** so the posting's terms come first.
5. **Fit one page:** shrink type slightly first, then cut the least relevant bullets, never the strongest.
6. **Target 70% or more coverage of the posting's hard skills.** The rest is a learning list, not a resume edit.

## By field
- **SWE:** projects with links and real users; scale numbers; languages and frameworks named in bullets; GitHub.
- **ML / AI:** dataset and model sizes, metrics (accuracy, F1, latency), papers and venues, compute used.
- **Quant / trading:** math and competitions (Putnam, USAMO, ICPC, Kaggle), probability, C++/Python speed work,
  backtests stated honestly (live versus paper).
- **Hardware / robotics:** the hardware platform, test results, tools (Altium, oscilloscopes, ROS), what flew or drove.
- **Finance / IB / consulting:** the Harvard or Finance One-Pager template, GPA and test scores up top, deal and
  valuation work, leadership, and an "Additional" line for skills, certifications and interests.
- **Product:** shipped outcomes, user metrics, cross-functional work.

## ATS safety checklist (Job Applier 4.0's lint)
- One page; single column; real text (no images); no ligature glyphs in the extracted text.
- Email, phone and LinkedIn in the body header; GitHub for technical roles.
- Standard headings; consistent dates; graduation date present.
- At least 60% quantified bullets; at least 70% start with action verbs; none over about 2 lines; no filler.
- Hard-skill coverage of the posting at 70% or more, with the skills inside bullets as well as in Skills.
- File name `First_Last_Resume.pdf`, under 1 MB.

## Templates and when to use them
| Template | Use for |
|---|---|
| Jake's Classic | SWE, quant, research (the most familiar look to tech recruiters) |
| Harvard Traditional | Finance, consulting, government, any conservative reader |
| Finance One-Pager | IB, asset management, trading desks |
| Awesome Modern | Startups, product, design-adjacent roles |
| Banking | Business, fintech, generalist roles |
| Sans Minimal | Big tech, new grad, a clean modern read |
| Compact Engineering | Lots of strong content: hardware, robotics, research-heavy |
| Accent Bar | Data and AI roles where a little color helps you stand out (still ATS-safe) |
