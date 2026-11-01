"""MCP server (stdio, JSON-RPC 2.0, no dependencies). Gives Claude Code / Codex the tools to run the whole pipeline:
find jobs, read them, tailor a resume, answer questions, pull the per-ATS playbook, claim and log applications.
The agent does the browser part with its own computer-use / browser tools.
"""
import json
import os
import sys
import traceback

from . import api, store

S = lambda **props: {"type": "object", "properties": props}
STR, NUM, BOOL = {"type": "string"}, {"type": "number"}, {"type": "boolean"}

TOOLS = [
    ("job_applier_setup_status", "Onboarding checklist: what the user still needs to set up (profile, vault, search prefs, Chrome).", S(), lambda a: api.setup_status()),
    ("job_applier_get_profile", "The user's profile: contact, school, grad date, work authorization, EEO answers, search filters, apply policy (auto_submit, daily_limit, per_company_cap, stop_on).", S(), lambda a: api.get_profile()),
    ("job_applier_update_profile", "Deep-merge a patch into the profile, e.g. {\"search\": {\"roles\": [\"software engineer\"]}}.", S(patch={"type": "object"}), lambda a: api.update_profile(a.get('patch', {}))),
    ("job_applier_get_vault", "The Career Vault: every experience, project, bullet, skill and award the user has (more than fits on one page). Entries have ids; bullet n of entry X is 'X.n'.", S(), lambda a: api.get_vault()),
    ("job_applier_save_vault", "Replace the whole Career Vault (JSON Resume-like: basics, education, experience[{org,title,location,start,end,url,bullets[]}], projects[{name,tagline,tech[],date,url,bullets[]}], research[{title,venue,url,role}], leadership[], skills[{label,items[]}], awards[], order[]). Use after structuring a brain dump. Never invent facts.", S(vault={"type": "object"}), lambda a: api.save_vault(a['vault'])),
    ("job_applier_get_dump", "The raw brain dump text the user pasted (old resumes, LinkedIn export, notes) that still needs structuring into the vault.", S(), lambda a: {"text": api.get_dump()}),
    ("job_applier_scan_jobs", "Scrape every enabled source (SimplifyJobs lists, SmartRecruiters live feed, ~500 Greenhouse/Lever/Ashby/Workday boards) and score fit. Takes 1-3 minutes.", S(sources={"type": "array", "items": STR}), lambda a: api.scan(a.get('sources'))),
    ("job_applier_list_jobs", "Search found jobs. status: new|applied|skipped|all. order: fit|new.", S(query=STR, status=STR, min_fit=NUM, limit=NUM, order=STR), lambda a: api.list_jobs(a.get('query', ''), a.get('status', 'new'), a.get('min_fit'), a.get('limit', 50), None, a.get('order', 'fit'))),
    ("job_applier_queue", "The full apply queue: every open role that fits the user, dream companies first, then by fit (respects caps and skip list). Returns total, dream count and the first n jobs.", S(n=NUM), lambda a: api.queue(int(a.get('n', 50)), for_agent=True)),
    ("job_applier_import_resume", "Import a resume or any career text into the vault (parses sections, entries and bullets; merges with what's there). Pass text, or name + base64 data for a PDF/DOCX/TEX file.", S(text=STR, name=STR, data=STR), lambda a: api.import_resume(a.get('name', ''), a.get('data'), a.get('text'))),
    ("job_applier_next_jobs", "The apply queue: best unapplied matches, respecting the daily limit and per-company caps. Start every apply session here.", S(n=NUM), lambda a: api.next_jobs(int(a.get('n', 10)))),
    ("job_applier_get_job", "Full job record including the description (fetched on demand).", S(job_id=STR), lambda a: api.get_job(a['job_id'])),
    ("job_applier_import_applied", "Record jobs the user ALREADY applied to outside Job Applier 4.0 (found in their confirmation emails, a tracker, or told to you), so they are never applied to again, even if they appear in a later scan. items: [{company, title, url?, date?, status?}]. Only record what you actually saw.",
     {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"company": STR, "title": STR, "url": STR, "date": STR, "status": STR}, "required": ["company", "title"]}}, "source": STR}, "required": ["items"]},
     lambda a: api.import_applied(a.get('items') or [], a.get('source') or 'email')),
    ("job_applier_add_job", "Track a job by URL (and optional pasted description) that the scrapers did not find.", S(url=STR, title=STR, company=STR, description=STR), lambda a: api.add_job(a['url'], a.get('title', ''), a.get('company', ''), a.get('description', ''))),
    ("job_applier_job_questions", "Greenhouse only: the application's questions with suggested answers from the bank, before opening the form.", S(job_id=STR), lambda a: api.job_questions(a['job_id'])),
    ("job_applier_ats_report", "ATS report: posting keyword coverage (matched/missing hard skills) + resume lint. Pass job_id or jd_text; omit both to lint the vault.", S(job_id=STR, jd_text=STR), lambda a: api.ats_report(a.get('job_id'), a.get('jd_text'))),
    ("job_applier_tailor_prompt", "Returns the expert tailoring prompt for a job (vault + posting + rules). Write the JSON plan it asks for, then call job_applier_tailor_apply.", S(job_id=STR), lambda a: api.tailor_prompt(a['job_id'])),
    ("job_applier_tailor_apply", "Build the tailored one-page PDF for a job. Pass your plan from job_applier_tailor_prompt (best), or omit plan for the automatic heuristic. Returns pdf path, ATS coverage, rejected rewrites (fact guard).", S(job_id=STR, plan={"type": "object"}, template=STR), lambda a: api.tailor_apply(a['job_id'], a.get('plan'), a.get('template'), 'agent' if a.get('plan') else 'heuristic')),
    ("job_applier_render_resume", "Render the master (untailored) resume or a quick heuristic tailor (job_id) in a template: classic, harvard, modern, banking, finance, minimal, compact, accent.", S(template=STR, job_id=STR), lambda a: api.render_resume(a.get('template'), a.get('job_id'))),
    ("job_applier_templates", "List resume templates and what each is best for.", S(), lambda a: api.templates()),
    ("job_applier_answer_questions", "Answer application questions from the user's bank. questions: strings or {question, options[]}. Answers with confidence < 0.45 come back null: ask the user, then job_applier_save_answer.", S(questions={"type": "array"}, job_id=STR), lambda a: api.answer_questions(a.get('questions', []), a.get('job_id'))),
    ("job_applier_save_answer", "Save a new or corrected answer so the user is never asked again.", S(question=STR, answer=STR, key=STR), lambda a: api.save_answer(a['question'], a['answer'], a.get('key'))),
    ("job_applier_playbook", "Step-by-step fill guide and gotchas for an ATS: greenhouse, lever, ashby, workday, smartrecruiters, icims, linkedin, general.", S(ats=STR), lambda a: {"playbook": api.playbook(a.get('ats', 'general'))}),
    ("job_applier_claim", "Atomically claim a job before applying so parallel agents never double-apply. Returns claimed:false if taken.", S(job_id=STR), lambda a: api.claim(a['job_id'], who=os.environ.get('JOB_APPLIER_RUN_ID') or os.environ.get('APPLYTWIN_RUN_ID', 'agent'))),
    ("job_applier_log_application", "Record what happened: right after submitting (Applied | Needs User | Skipped | Failed), and later when the user hears back (Interview | Offer | Rejected). Outcomes teach Job Applier 4.0 what works for this user.", S(job_id=STR, status=STR, notes=STR, resume_path=STR), lambda a: api.log_application(a['job_id'], a.get('status', 'Applied'), a.get('notes', ''), a.get('resume_path', ''))),
    ("job_applier_remember", "Learn a lasting preference from the user and apply it to every future resume: note (free text like 'keep it formal' or 'never mention my GPA'), pin (entry id or bullet id 'x.n' to always include), avoid (id to never include), or field+template (preferred template for a field).", S(note=STR, pin=STR, avoid=STR, field=STR, template=STR), lambda a: api.remember(a.get('note'), a.get('pin'), a.get('avoid'), a.get('field'), a.get('template'))),
    ("job_applier_forget", "Remove a stored preference (note, pin or avoid).", S(note=STR, pin=STR, avoid=STR), lambda a: api.forget(a.get('note'), a.get('pin'), a.get('avoid'))),
    ("job_applier_insights", "What Job Applier 4.0 has learned about this user: stored preferences, interview rate by field and template, bullets that won interviews. Log outcomes (Interview, Offer, Rejected) with job_applier_log_application to feed it.", S(), lambda a: api.insights()),
    ("job_applier_notify", "Tell the user something needs them RIGHT NOW (emailed code, sign-in, CAPTCHA, a question only they can answer). Sends a desktop notification and adds it to their in-app inbox. Then log Needs User and move on to the next job.", S(title=STR, message=STR, url=STR, job_id=STR, kind=STR), lambda a: api.notify(a.get('title', 'Needs you'), a.get('message', ''), a.get('url', ''), a.get('job_id', ''), a.get('kind', 'needs_you'))),
    ("job_applier_reply", "Answer the user about ONE application (they wrote to you about it in the app). One or two plain sentences: what you did, and what they still need to do. Shown under that application in Needs you.", S(job_id=STR, text=STR), lambda a: api.reply(a['job_id'], a['text'])),
    ("job_applier_inbox", "Open items waiting on the user (and whether they were resolved).", S(), lambda a: api.inbox()),
    ("job_applier_pending_jobs", "Jobs you stopped on for the user that are not finished. Check at the end of a run and finish the ones the user has unblocked (e.g. they signed in).", S(), lambda a: api.pending_jobs()),
    ("job_applier_stats", "Counts: matched jobs, applied today / this week, statuses.", S(), lambda a: api.stats()),
]
BY = {t[0]: t for t in TOOLS}
# Also support legacy applytwin_* names so backwards compatibility is preserved
for t in TOOLS:
    BY[t[0].replace('job_applier_', 'applytwin_')] = t


def reply(i, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": i}
    msg.update({"error": error} if error else {"result": result})
    sys.stdout.write(json.dumps(msg, default=str) + '\n')
    sys.stdout.flush()


STEPS = {'claim': 'Opening the posting', 'get_job': 'Opening the posting', 'tailor_prompt': 'Tailoring your resume',
         'tailor_apply': 'Tailoring your resume', 'render_resume': 'Tailoring your resume', 'ats_report': 'Checking your resume',
         'playbook': 'Filling the application', 'answer_questions': 'Filling the application', 'job_questions': 'Filling the application',
         'save_answer': 'Filling the application', 'notify': 'Asking you something', 'log_application': 'Logging it',
         'next_jobs': 'Picking the next job', 'queue': 'Picking the next job', 'pending_jobs': 'Picking the next job'}


def _activity(name, args):
    """What the agent is doing right now, for the Autopilot page (and the stuck-run timer)."""
    try:
        import time
        step_name = (name or '').replace('job_applier_', '').replace('applytwin_', '')
        step = STEPS.get(step_name)
        cur = store.load('activity.json', {}) or {}
        if not step:
            store.save('activity.json', {**cur, "at": time.time()})
            return
        job = args.get('job_id') or (cur.get('job_id') if step not in ('Picking the next job',) else '')
        store.save('activity.json', {"step": step, "job_id": job or '', "at": time.time()})
    except Exception:
        pass


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        m, i = req.get('method'), req.get('id')
        if i is None:
            continue  # notification
        if m == 'initialize':
            reply(i, {"protocolVersion": req.get('params', {}).get('protocolVersion', '2025-06-18'),
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "job-applier", "version": "4.0.0"},
                      "instructions": "Job Applier 4.0 runs the user's job search. Start with job_applier_setup_status. To apply: job_applier_next_jobs -> "
                                      "job_applier_claim -> job_applier_get_job -> job_applier_tailor_prompt/job_applier_tailor_apply -> job_applier_playbook(ats) -> "
                                      "fill the form in the browser using job_applier_answer_questions -> submit only if profile.apply.auto_submit "
                                      "-> job_applier_log_application. Never type passwords, solve CAPTCHAs, create accounts or invent facts."})
        elif m == 'ping':
            reply(i, {})
        elif m == 'tools/list':
            reply(i, {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s, _ in TOOLS]})
        elif m == 'tools/call':
            p = req.get('params', {})
            t = BY.get(p.get('name'))
            if not t:
                reply(i, error={"code": -32602, "message": "unknown tool"})
                continue
            try:
                _activity(p.get('name'), p.get('arguments') or {})
                out = t[3](p.get('arguments') or {})
                reply(i, {"content": [{"type": "text", "text": json.dumps(out, default=str, ensure_ascii=False)[:180000]}]})
            except Exception as e:
                reply(i, {"content": [{"type": "text", "text": f"error: {e}\n{traceback.format_exc()[-800:]}"}], "isError": True})
        else:
            reply(i, error={"code": -32601, "message": f"method not found: {m}"})


if __name__ == '__main__':
    main()
