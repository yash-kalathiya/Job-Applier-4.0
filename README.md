# Job Applier 4.0

[![Star Job Applier 4.0](https://img.shields.io/github/stars/yash-kalathiya/Job-Applier-4.0?style=social)](https://github.com/yash-kalathiya/Job-Applier-4.0)

> **Free for every student.** If Job Applier 4.0 helps you, please ⭐ star this repo. It's how other students find it.

**Your job search on autopilot.** Job Applier 4.0 finds internships and jobs across thousands of company career pages,
builds a fact-checked resume tuned to each posting, and lets your own Claude Code or Codex fill out the
applications in your browser, on the plan you already pay for. No API keys.

Your data stays on your computer in your local environment.

Built from a real search: 1,500+ applications across Greenhouse, Lever, Ashby, Workday, SmartRecruiters,
iCIMS and LinkedIn, with everything learned there turned into code and agent playbooks.

## What it does

| | |
|---|---|
| **Finds jobs** | One scan reads the community trackers (SimplifyJobs, vanshb03, SpeedyApply, Northwestern FinTech quant, Zapply, Simplify off-season), The Muse (every field), Hacker News "Who is hiring", remote boards (RemoteOK, Remotive, Himalayas, Jobicy, Arbeitnow), the SmartRecruiters live feed, and 650+ Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable and Recruitee boards across tech, finance, consulting, healthcare, energy, consumer and media. Every board a tracker links to is discovered and read whole. Each posting is scored for fit: role (any field, typed freely), level, cycle, location, graduation window, sponsorship, and how much of the posting your experience covers. |
| **Knows what you applied to** | Import a CSV from Simplify, Huntr, Teal, Notion or a Google Sheet; the same role at the same company is never applied to twice, however a board titles it. |
| **Career Vault** | Dump everything: every job, project, paper, award and skill, with as many versions of each bullet as you like. Your agent turns old resumes, LinkedIn exports and notes into the vault. |
| **Tailors every resume** | For each posting, Job Applier 4.0 picks your most relevant roles and bullets, orders them for that reader, mirrors the posting's exact terms only where your vault proves them, and fits one page. A **fact guard** rejects any rewrite that adds a number, tool, scale or claim that the same entry doesn't contain. |
| **8 resume templates** | Jake's Classic, Harvard Traditional, Finance One-Pager, Awesome Modern, Banking, Sans Minimal, Compact Engineering, Accent Bar. All are single-column real text, so every ATS parses them. |
| **ATS check** | Keyword coverage of the posting's hard skills (requirements section weighted 2x) plus a lint for the things recruiters skim for: quantified bullets, action verbs, length, contact line, one page, clean text extraction. |
| **Answer bank** | One truthful answer for each of the ~40 questions every application asks, matched to any wording. The agent only asks you about genuinely new questions, once. |
| **Applies for you** | Your Claude Code or Codex runs the loop: claim the job, tailor, open the form, follow Job Applier 4.0's playbook for that ATS, answer from the bank, upload the PDF, then submit (if you allow it) or stop on the review screen for you. |
| **Guardrails** | Never types passwords or codes, never solves CAPTCHAs or creates accounts, never accepts arbitration agreements, never invents facts. Daily limit and per-company caps. |

## Install & Run

From a clone of this repository:

```bash
./install.sh
```

Or run the CLI directly:

```bash
python3 bin/job-applier app
```

It opens the app at http://localhost:4747.

**No API keys.** Job Applier 4.0 runs on the Claude Code or Codex plan you already pay for: resume tailoring, imports and the
apply loop all go through your own `claude` or `codex` command line. You need:

- Python 3.9+ and Node.js (Node lets your agent drive a browser)
- Claude Code (`npm i -g @anthropic-ai/claude-code`, then `claude` and `/login`) or Codex (`npm i -g @openai/codex`, then `codex login`)

Check everything with `python3 bin/job-applier doctor`.

## Use it

In **Claude Code** or **Codex**:

- `set me up with job-applier`: imports your resumes and LinkedIn, builds your vault, asks about your preferences
- `job-applier: scan and show my top 20`
- `job-applier: tailor my resume for <job id or URL> and explain the choices`
- `job-applier: apply to my top 10`
- `job-applier: review my resume like a recruiter`

The agent needs a browser it can drive: Claude in Chrome or computer use for Claude Code, or the browser /
computer-use tools in Codex.

In the **app** (`./bin/job-applier app`): Home (scan, stats, setup checklist), Jobs (every match with fit, keyword
coverage and one-click tailored resumes), Resume Studio (vault editor with live preview, template gallery and
resume check), Answers, Applications, Profile & Search (filters and agent permissions), Agents (setup).

The **CLI** works without any agent:
- `job-applier scan`
- `job-applier jobs`
- `job-applier tailor JOB_ID`
- `job-applier render --template harvard`
- `job-applier ats JOB_ID`
- `job-applier watch --every 120` (desktop notification the moment a match posts)

## How tailoring works

1. The posting's hard skills are extracted from a 250+ term lexicon, with the requirements section weighted 2x.
2. **Agent mode** (best): your Claude/Codex gets `job_applier_tailor_prompt`, which contains your vault, the posting
   and the rules in [docs/RESUME_GUIDE.md](docs/RESUME_GUIDE.md), and returns a plan (which entries, which bullets,
   truthful rewrites, skills order).
3. **API mode**: set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` and the app does the same on its own.
4. **Heuristic mode** (no AI): ranks entries and bullets by keyword overlap and impact.
5. The fact guard checks every rewrite. The renderer shrinks type slightly, then trims the least relevant bullets
   until the resume fits one page.

## Your data

Everything lives in `~/.job-applier` (set `JOB_APPLIER_HOME` to move it): `profile.json`, `resume.json` (the vault),
`answers.json`, `job_applier.db` (jobs and applications) and `resumes/` (every tailored PDF). Add companies to scan in
`~/.job-applier/companies.json` (start from `data/companies.json`).

## The app

`./bin/job-applier app` opens it at http://localhost:4747. First run walks you through it: drop your resume (PDF, Word,
LaTeX or text; no AI needed to parse it), answer five questions (role type, roles, dream companies, locations, work
authorization), and it builds your queue live. Then: **Home** (your matches, live feed), **Jobs** (every match with
keyword coverage and a one-click tailored resume), **Resume** (edit your vault right on the page; Write / Check /
Style), **Answers**, **Applications** (drag cards when you hear back; your twin learns from it), **Autopilot** (your
queue, dream companies first, and a Start button that runs Claude Code or Codex through it), ⌘K for everything.

Every tailored resume is also written as LaTeX (`.tex`, Jake's Resume layout). Pick the **LaTeX** template to have
the PDF typeset by your TeX engine (tectonic, lualatex, xelatex or pdflatex).

## For developers

Python standard library only (`pypdf` is optional, for PDF text checks). `job_applier/` has the store, sources,
match, ats, tailor, render, answers, api, server, mcp and cli modules; `web/` is vanilla JS. Skills are in
`skills/`, ATS playbooks in `playbooks/`, agent instructions in [AGENTS.md](AGENTS.md).
Run `python3 tests/smoke.py`.

## License

Copyright (c) 2026 Job Applier 4.0 Authors. Job Applier 4.0 is licensed under the [PolyForm Strict License 1.0.0](LICENSE): you may
install and run it for any noncommercial purpose, but you may not copy, modify, redistribute or sell it, or build other
works from it. For any other use, ask first.
Bundled third-party code (`job_applier/_vendor/pypdf`) stays under its own BSD license.
