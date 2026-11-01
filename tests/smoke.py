"""End-to-end smoke test on a throwaway JOB_APPLIER_HOME: vault -> render every template -> tailor + fact guard -> answers -> MCP."""
import json
import time, os, subprocess, sys, tempfile, time
os.environ["JOB_APPLIER_NO_TELEMETRY"] = "1"
os.environ["APPLYTWIN_NO_TELEMETRY"] = "1"   # tests never count as installs
os.environ["JOB_APPLIER_SKIP_SIGNIN"] = "1"
os.environ["APPLYTWIN_SKIP_SIGNIN"] = "1"   # no Google account in tests
for _s in (sys.stdout, sys.stderr):   # Windows consoles default to cp1252, which can't print emoji
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_HOME = tempfile.mkdtemp(prefix='job-applier-test-')
os.environ['JOB_APPLIER_HOME'] = TMP_HOME
os.environ['APPLYTWIN_HOME'] = TMP_HOME
sys.path.insert(0, ROOT)
from job_applier import api, render, store  # noqa: E402

store.save('resume.json', json.load(open(os.path.join(ROOT, 'examples', 'resume.example.json'), encoding='utf-8')))
api.update_profile(json.load(open(os.path.join(ROOT, 'examples', 'profile.example.json'), encoding='utf-8')))
ok = lambda c, m: print(('PASS ' if c else 'FAIL ') + m) or c
res = []
for t in render.TEMPLATES:
    r = api.render_resume(t)
    res.append(ok(r['pages'] == 1, f'template {t}: 1 page (score {r["score"]})'))
jd = 'Software Engineer Intern. Requirements: Python, Go, Kafka, PostgreSQL, Kubernetes, CI/CD, distributed systems, data structures.'
j = api.add_job('https://example.com/jobs/1', 'Software Engineer Intern, Summer 2027', 'Example Co', jd)
r = api.tailor_apply(j['id'], None, 'classic', 'heuristic')
res.append(ok(r['pages'] == 1 and r['coverage'] > 0, f'heuristic tailor: coverage {r["coverage"]}%'))
v = api.get_vault(); e = v['experience'][0]; i = e['id']
plan = {"experience": [{"id": i, "bullets": [{"from": i + '.0', "text": e['bullets'][0] + ' for 9 million users'},
                                            {"from": i + '.1', "text": 'Used Terraform and Kubernetes to deploy everything at scale for the team.'}]}]}
r = api.tailor_apply(j['id'], plan, 'classic')
res.append(ok(len(r['rejected']) == 2, f'fact guard blocked {len(r["rejected"])}/2 invented rewrites'))
a = api.answer_questions(['Will you now or in the future require sponsorship for employment visa status?',
                          {'question': 'Are you legally authorized to work in the United States?', 'options': ['Yes', 'No']},
                          'What is your favorite color?'])
res.append(ok(a[0]['answer'] == 'No' and a[1]['answer'] == 'Yes' and a[2]['answer'] is None, 'answer bank matches + asks on unknowns'))
p = subprocess.run([sys.executable, os.path.join(ROOT, 'bin', 'job-applier'), 'mcp'], input='\n'.join(json.dumps(x) for x in [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "job_applier_stats", "arguments": {}}}]) + '\n',
    capture_output=True, text=True, encoding='utf-8', env=os.environ, timeout=60)
lines = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
res.append(ok(len(lines) == 3 and len(lines[1]['result']['tools']) >= 20 and 'applied_today' in lines[2]['result']['content'][0]['text'],
              f'MCP server: {len(lines[1]["result"]["tools"]) if len(lines) > 1 else 0} tools'))
from job_applier import match

same = [('Tesla', '🔥 Tesla'), ('JPMorgan', 'JPMorganChase'), ('JP Morgan Chase', 'JPMorgan Chase & Co.'), ('Micron', 'Micron Technology'),
        ('Meta', 'Facebook'), ('Google', 'Alphabet Inc.'), ('Stripe', '⭐️ Stripe, Inc.')]
different = [('Meta', 'Metabase'), ('Apple', 'Applied Materials'), ('Ramp', 'Rampart')]
prof = {'search': {'kind': 'internship', 'roles': [], 'companies_skip': ['Tesla', 'JPMorgan']}}
skipped = [match.fit({'title': 'Software Engineer Intern', 'company': c, 'location': 'Austin, TX'}, prof)[0] for c in ('🔥 Tesla', 'JPMorganChase')]
res.append(ok(all(match.same_company(a, b) for a, b in same) and not any(match.same_company(a, b) for a, b in different) and skipped == [0, 0],
              'skip list matches every spelling ("🔥 Tesla", "JPMorganChase") and nothing else'))
# Windows defaults files and pipes to cp1252, which turned en dashes and apostrophes on resumes into .
# Every text-mode open() and text pipe must say UTF-8.
import glob as _g, re as _re
_bad = []
for _p in _g.glob(os.path.join(ROOT, 'job_applier', '*.py')):
    _s = open(_p, encoding='utf-8').read()
    for _m in _re.finditer(r'(?<![\w.])open\(', _s):
        _j, _d = _m.end(), 1
        while _d:
            _d += {'(': 1, ')': -1}.get(_s[_j], 0); _j += 1
        _a = _s[_m.end():_j - 1]
        if 'encoding=' not in _a and not _re.search(r"""['"][rwa]b['"]""", _a):
            _bad.append(f"{os.path.basename(_p)}:{_s.count(chr(10), 0, _m.start()) + 1}")
    _bad += [f"{os.path.basename(_p)}: text=True without encoding" for _ in _re.finditer(r'text=True(?!, encoding)', _s)]
res.append(ok(not _bad, 'every file and pipe is UTF-8 (Windows) ' + ', '.join(_bad[:5])))
from job_applier import store as _st
_st.save('enc_test.json', {"t": "June 2025 – Aug. 2025, it’s Zoë"})
res.append(ok(_st.load('enc_test.json')['t'] == "June 2025 – Aug. 2025, it’s Zoë", 'dashes and apostrophes survive a save'))
open(_st.path('enc_old.json'), 'wb').write('{"t": "a – b"}'.encode('cp1252'))
res.append(ok(_st.load('enc_old.json')['t'] == "a – b", 'old Windows-encoded files still load'))

from job_applier import answers as _an
_bank = _an.default_bank({**store.profile(), 'location': 'Gainesville, FL'})
_q = [_an.match(x, _bank) for x in ('Race/Ethnicity', 'Current location')]
res.append(ok((_q[0] or {}).get('answer') != 'Gainesville, FL' and (_q[1] or {}).get('answer') == 'Gainesville, FL',
              'Race/Ethnicity is never answered with your city'))
store.execute("insert or replace into jobs(id,source,company,title,url,apply_url,ats,found_at,fit,status) values('pend1','t','Acme','Intern','u','u','lever',0,90,'new')")
api.log_application('pend1', 'Needs User', 'sign-in needed')
_before = any(r['job_id'] == 'pend1' for r in api.pending_jobs())
api.skip_job('pend1')
res.append(ok(_before and not any(r['job_id'] == 'pend1' for r in api.pending_jobs()), 'dismissing a job that needs you clears it'))
_w = [_an.match(x, _bank) for x in ('Please tell us what interested you to apply to CFS', 'Anything else we should know?', 'How did you hear about us?')]
res.append(ok(_w[0].get('action') == 'write' and _w[1].get('action') == 'write' and _w[2].get('action') != 'write' and 'em dash' in _w[0]['how'],
              'open-ended questions get written for each job, facts still come from your answers'))
# a plan that numbers bullets from 1 (what models naturally do) must not shift or drop bullets on everyone's resumes
from job_applier import tailor as _tl
_v = _tl.ensure_ids(json.load(open(os.path.join(ROOT, 'examples', 'resume.example.json'), encoding='utf-8')))
_roles = [e for e in _v['experience'] if len(e.get('bullets', [])) >= 2 and not _tl.WEAK.search(e['bullets'][-1])][:2]
_plan = {"experience": [{"id": e['id'], "bullets": [f"{e['id']}.{i + 1}" for i in range(len(e['bullets']))]} for e in _roles]}
_res, _ = _tl.apply(_v, _plan)
_by = {r['id']: r for r in _res['experience']}
_ok1 = all(_by[e['id']]['bullets'] == e['bullets'] for e in _roles)
_plan2 = {"experience": [{"id": e['id'], "bullets": [{"from": f"{e['id']}.{len(e['bullets'])}", "text": e['bullets'][-1]}]} for e in _roles]}
_res2, _ = _tl.apply(_v, _plan2)
_by2 = {r['id']: r for r in _res2['experience']}
_ok2 = all(len(_by2[e['id']]['bullets']) >= 2 and e['bullets'][-1] in _by2[e['id']]['bullets'] for e in _roles)
res.append(ok(_ok1 and _ok2, 'bullets numbered from 1 still land right, and no role is left with fewer than 2'))
# filler never takes a line from a stronger true bullet in the same role; the plan's order among recent roles stands;
# an award already stated elsewhere isn't repeated
_r3 = {"id": "acme", "org": "Acme", "title": "Analyst", "dates": "Jan 2020 – Present",
       "bullets": ["Helped with literature review for the team.", "Built a **pandas** pipeline that cut report time **70%** across 12 desks.",
                   "Attended weekly meetings."]}
_r4 = {"id": "bigco", "org": "BigCo", "title": "Intern", "start": "Jun " + time.strftime('%Y'), "end": "Aug " + time.strftime('%Y'),
       "bullets": ["Modeled a $40M acquisition in Excel.", "Wrote 3 CIM sections."]}
_v3 = {"basics": {"name": "T"}, "education": [{"school": "State U", "honors": ["Dean's List (6 semesters)"]}],
       "experience": [_r3, _r4], "awards": ["Dean's List (6 semesters)", "CFA Research Challenge finalist"]}
_res3, _ = _tl.apply(_v3, {"experience": [{"id": "bigco"}, {"id": "acme", "bullets": ["acme.0", "acme.2"]}], "awards": [0, 1]})
_b3 = _res3['experience'][1]['bullets'] if _res3['experience'][0]['id'] == 'bigco' else []
res.append(ok(_res3['experience'][0]['id'] == 'bigco' and _r3['bullets'][1] in _b3 and _r3['bullets'][0] not in _b3
              and not _res3['awards'] and _res3['education'][0]['honors'][-1] == "CFA Research Challenge finalist",
              f'filler bullets swapped for stronger true ones, recent roles keep relevance order, no repeated awards {_b3}'))
# a rewrite and the bullet it came from never both appear; skills/awards close the page; degree lines read right
from job_applier.render import degree_line as _dl
_v5 = {"basics": {"name": "T"}, "education": [{"school": "U", "degree": "Bachelor of Science in Management", "major": "Finance"}],
       "experience": [{"id": "lab", "org": "Lab", "title": "RA", "dates": "2025", "bullets": [
           "Wrote regression tests comparing outputs to the legacy code to 1e-12 relative tolerance.",
           "Ported a 40K-line Fortran solver to C++ and CUDA, cutting runtime 9x on A100s.", "Ran nightly builds on 3 clusters."]}],
       "skills": [{"label": "Languages", "items": ["C++"]}], "order": ["skills", "education", "experience"]}
_res5, _ = _tl.apply(_v5, {"order": ["skills", "experience"], "experience": [{"id": "lab", "bullets": [
    {"from": "lab.0", "text": "Built a regression test suite comparing outputs to the legacy code to 1e-12 relative tolerance."}, "lab.1"]}]})
_b5 = _res5['experience'][0]['bullets']
res.append(ok(not any(b == _v5['experience'][0]['bullets'][0] for b in _b5) and len(_b5) >= 2 and _res5['order'][-1] == 'skills'
              and _dl(_v5['education'][0]) == 'Bachelor of Science in Management, Finance'
              and _dl({"degree": "B.S.", "major": "Physics"}) == 'B.S. in Physics',
              f'no bullet twice (rewrite + original), skills close the page, degree lines read right {_b5} {_res5["order"]}'))
# an overclaiming rewrite goes back to the user's own words; one fact never takes two lines
_orig_call = _tl.call_llm
_tl.call_llm = lambda text, timeout=600, fast=False: {"overclaims": [{"id": "0", "why": "ran vs analyzed"}]}
_rep6 = {"rewrites": [{"bullet": "x.0", "from": "Analyzed a checkout A/B test across 2.4M users.", "to": "Ran a checkout A/B test across 2.4M users."},
                      {"bullet": "x.1", "from": "Wrote dbt models replacing 9 SQL queries.", "to": "Replaced 9 SQL queries with dbt models."}], "rejected": []}
_res6 = {"experience": [{"bullets": [r["to"] for r in _rep6["rewrites"]]}]}
_tl.audit(_res6, _rep6)
_tl.call_llm = _orig_call
res.append(ok(_res6["experience"][0]["bullets"] == ["Analyzed a checkout A/B test across 2.4M users.", "Replaced 9 SQL queries with dbt models."]
              and len(_rep6["rejected"]) == 1 and _tl._one_per_fact([
                  "Implemented an implicit-explicit time-stepping scheme allowing 6x larger time steps",
                  "Wrote an implicit-explicit Runge-Kutta time stepper that allowed 6x larger time steps at the same accuracy",
                  "Scaled the solver to 2,048 cores on Frontera"]).__len__() == 2,
              'overclaiming rewrites revert to the vault, one fact never takes two lines'))
# trimming to one page keeps the measured, plan-chosen bullet over an unmeasured one that merely shares a keyword
from job_applier import ats as _ats
_jd7 = 'You will review code and pull requests in Python and TypeScript for developer tools.'
_res7 = {"projects": [{"bullets": ["Merged **5 PRs** into kubernetes/kubectl, including a fix for events sorting and clearer selector errors.",
                                   "Reviewed pull requests and triaged open issues as part of SIG CLI."]}]}
_w7 = _tl.trim_worth(_res7, _ats.keywords(_jd7), _jd7)
res.append(ok(_w7(_res7["projects"][0]["bullets"][0]) > _w7(_res7["projects"][0]["bullets"][1]), 'trimming keeps measured results over keyword-only lines'))
# real form questions that used to get the wrong answer
_pb = _an.default_bank({'name': 'Maya Chen', 'location': 'Austin, TX', 'grad_month': 'May', 'grad_year': '2028', 'major': 'Computer Science',
                        'work_authorized_us': True, 'needs_sponsorship': True, 'government_employee': False, 'willing_to_relocate': True})
_cases = {'Preferred First Name': 'Maya', 'Graduation Year': '2028', 'Major': 'Computer Science', 'Last Name': 'Chen',
          'How did you hear about this job? (Referral, LinkedIn, Other)': 'Company careers website',
          'Are you authorized to work in the US without the need for employer sponsorship, now or in the future?': 'No',
          'Are you a current or former employee of the U.S. government?': 'No'}
_bad = {q: _an.match(q, _pb).get('answer') for q, want in _cases.items() if _an.match(q, _pb).get('answer') != want}
_arb = _an.match('I agree to the Mutual Arbitration Agreement', _pb).get('answer')
_essay = _an.match('Please describe any major challenges you faced', _pb).get('action')
res.append(ok(not _bad and _arb is None and _essay == 'write', f'real form questions get the right answer {_bad or ""}'))
# messages to the twin: only clear, short phrasings act instantly; everything else goes to the agent
_it = {'did you submit this?': 'status', 'I submitted it': 'applied', 'skip it': 'skip', 'submit it': 'submit',
       'Done, I signed in. Finish it': None, 'I applied the change, now resubmit': None, "don't skip it, finish it": None,
       'remove this bullet from the resume and refill': None}
_wrong = {m: api.intent(m) for m, want in _it.items() if api.intent(m) != want}
res.append(ok(not _wrong, f'messages to the twin are never misread {_wrong or ""}'))
# limits, skip list and statuses hold everywhere the agent can go
p0 = store.profile()
api.update_profile({**p0, 'search': {**p0['search'], 'companies_skip': ['Skipco']}, 'apply': {**p0['apply'], 'daily_limit': 1}})
for _jid, _co in (('lim1', 'Skipco Inc'), ('lim2', 'Okco'), ('lim3', 'Okco2')):
    store.execute("insert or replace into jobs(id,source,company,title,url,apply_url,ats,found_at,fit,status) values(?,?,?,?,?,?,?,?,?,'new')",
                  (_jid, 't', _co, 'Software Intern', 'https://x/' + _jid, 'https://x/' + _jid, 'lever', 0, 95))
store.execute("delete from applications where at > ?", (time.time() - 86400,))
_q = [j['company'] for j in api.queue(50)['jobs']]
_skipped = 'Skipco Inc' not in _q and api.claim('lim1')['claimed'] is False
api.log_application('lim2', 'submitted')
_canon = store.rows("select status from applications where job_id='lim2'")[0]['status'] == 'Applied'
_limited = api.next_jobs(5)['jobs'] == [] and api.claim('lim3')['claimed'] is False and api.queue(5, for_agent=True)['jobs'] == []
store.claim('lim3'); api.release_claims()
_released = api._latest('lim3')['status'] == 'Needs User'
api.update_profile(p0)
res.append(ok(_skipped and _canon and _limited and _released, f'skip list, daily limit, statuses and unfinished claims hold ({_skipped}, {_canon}, {_limited}, {_released})'))
# a thin plan never ships a half-empty page: the tailor adds the user's next best true bullets until the page is full
_thin = {"experience": [{"id": _v['experience'][0]['id'], "bullets": [f"{_v['experience'][0]['id']}.0"]}], "projects": [], "leadership": []}
_tr = _tl.tailor(store.load('resume.json'), {'id': 'fill', 'title': 'Software Engineer Intern', 'company': 'Acme'},
                 'Python distributed systems backend APIs', plan=_thin, style='classic')
res.append(ok(_tr['pages'] == 1 and len(_tr['added']) >= 2, f"thin plans are filled to a full page ({len(_tr['added'])} added)"))
# importing without AI: job titles aren't headings, wrapped lines stay in their bullet, any bullet style (or none) works
from job_applier import importer as _imp
_txt = '''Jordan Lee
(555) 123-4567 | jordan@ufl.edu
Experience
Acme Corp Jun 2025 – Aug 2025
Software Engineering Intern Remote
• Built a payments API in Go serving 2M requests per day, cutting p99 latency by 30% across
the checkout flow launched in 2025
• Wrote integration tests in Python
UF Machine Learning Lab Jan 2025 – Present
Research Assistant
• Trained a ResNet model on 50K images reaching 92% accuracy
Projects
Ledgerly | TypeScript, Next.js
• Built an expenses app with 2,000 users
Tinydb | Rust
• Implemented an LSM-tree store at 180K writes/sec
'''
_shapes = []
for _t in (_txt, _txt.replace('• ', '➢ '), _txt.replace('• ', '')):
    _p = _imp.parse(_t)
    _shapes.append(([(e.get('org'), len(e.get('bullets', []))) for e in _p['experience']], [(e.get('name'), len(e.get('bullets', []))) for e in _p['projects']]))
_want = ([('Acme Corp', 2), ('UF Machine Learning Lab', 1)], [('Ledgerly', 1), ('Tinydb', 1)])
res.append(ok(all(sh == _want for sh in _shapes), f'resumes import right with any bullet style {[sh for sh in _shapes if sh != _want][:1]}'))
# job finding: US vs abroad, roles that are the same vs different, internships the default excludes used to kill
from job_applier import match as _m
_places = {'Bengaluru, IN': 'foreign', 'Indianapolis, IN': 'us', 'Tel Aviv, IL': 'foreign', 'Berlin, DE': 'foreign',
           'Cambridge, United Kingdom': 'foreign', 'Cambridge, MA': 'us', 'New York, NY or Toronto, ON': 'us', '2 Locations': 'unknown',
           'Vancouver, WA': 'us', 'Toronto, ON': 'foreign', 'Amsterdam, NH, NL': 'foreign', 'Toronto, ON, CA': 'foreign', 'San Jose, CA': 'us'}
_pl = {k: _m.place(k) for k, want in _places.items() if _m.place(k) != want}
_same = api.role_key('Acme', 'Software Engineer Intern - New York') == api.role_key('Acme', 'Software Engineering Internship - Seattle')
_diff = api.role_key('Acme', 'Intern - Software Engineering') != api.role_key('Acme', 'Intern - Investment Banking')
_P = {'search': {'kind': 'internship', 'exclude': ['master', 'manager', 'senior'], 'roles': []}}
_kept = all(_m.fit({'title': t, 'company': 'X'}, _P)[0] > 0 for t in ('Product Manager Intern', 'Software Engineer Intern, Mastercard Send',
                                                                     'Software Engineer Intern - Undergraduate Students Only'))
_roles = _m.role_hit('software engineering', 'software developer intern') and not _m.role_hit('machine learning', 'aircraft maintenance intern')
res.append(ok(not _pl and _same and _diff and _kept and _roles, f'job matching: places, same/different roles, excludes, role words {_pl or ""}'))
# a posting that disappeared from its company's board leaves the queue; one bad posting never stops a scan
from job_applier import sources as _src
for _i in ('g1', 'g2'):
    store.execute("insert or replace into jobs(id,source,company,title,url,apply_url,ats,found_at,fit,status) values(?,?,?,?,?,?,?,?,?,'new')",
                  (_i, 'greenhouse', 'Gco', 'Intern ' + _i, f'https://boards.greenhouse.io/gco/jobs/{_i}', '', 'greenhouse', 0, 90))
with store.db() as _con:
    _src._retire(_con, 'greenhouse:gco', [{'id': 'g1'}])
    _st = {'fetched': 0, 'new': 0, 'matched': 0}
    _src._ingest(_con, [{'id': 'bad'}], store.profile(), set(), _st, 0)   # missing fields: skipped, not fatal
_closed = {r['id']: r['status'] for r in store.rows("select id, status from jobs where id in ('g1','g2')")}
res.append(ok(_closed == {'g1': 'new', 'g2': 'closed'}, f'closed postings leave the queue {_closed}'))
# regressions found in review: board-name collisions, rescans, BOM files, share-your-link questions, co-op seasons, imports
store.execute("insert or replace into jobs(id,source,company,title,url,apply_url,ats,found_at,fit,status) values('e1','greenhouse','Epic','Intern','https://boards.greenhouse.io/epicgames/jobs/1','','greenhouse',0,90,'new')")
with store.db() as _con:
    _src._retire(_con, 'greenhouse:ame', [{'id': 'zz'}])
    _st = {'fetched': 0, 'new': 0, 'matched': 0, 'errors': 0}
    _src._ingest(_con, [{'id': 'e1', 'source': 'greenhouse', 'company': 'Epic', 'title': 'Software Engineer Intern', 'location': 'Cary, NC',
                         'url': 'https://boards.greenhouse.io/epicgames/jobs/1', 'apply_url': '', 'ats': 'greenhouse', 'posted': '', 'description': 'x'}],
                  store.profile(), set(), _st, 0)
_epic = store.rows("select status from jobs where id='e1'")[0]['status']
open(store.path('bom.json'), 'w', encoding='utf-8-sig').write('{"a": 1}')
_bom = store.load('bom.json', {}).get('a') == 1
_share = _an.match('Please share your LinkedIn profile URL', _an.default_bank({'linkedin': 'linkedin.com/in/x'})).get('answer') == 'linkedin.com/in/x'
_coop = _m.fit({'title': 'Software Engineer Co-op - Fall 2026', 'company': 'X'}, {'search': {'kind': 'co-op', 'season': '', 'roles': []}})[0] > 0
_imp2 = _imp.parse('''Sam Park
sam@x.edu
Experience
Stripe, San Francisco, CA
Backend Engineering Intern, Jun 2025 – Aug 2025
• Shipped a dashboard for 12 teams
Acme, Austin, TX
Data Intern, Jan 2025 – May 2025
• Cleaned 3 years of sales data
''')
_orgs = [e.get('org') for e in _imp2['experience']]
res.append(ok(_epic == 'new' and _st['errors'] == 0 and _bom and _share and _coop and _orgs[:2] == ['Stripe', 'Acme'],
              f'review regressions stay fixed (board {_epic}, rescan errors {_st["errors"]}, bom {_bom}, share {_share}, co-op {_coop}, import {_orgs})'))
from job_applier import telemetry as _tm
res.append(ok(not _tm.enabled() and _tm.ping() is False and len(_tm.install_id()) == 36, 'install count is off in tests and uses only a random ID'))

print(f'\n{sum(res)}/{len(res)} passed')
sys.exit(0 if all(res) else 1)
