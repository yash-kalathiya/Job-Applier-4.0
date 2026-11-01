"""Every career, end to end: five students in different fields, each in a fresh throwaway home with no API keys.

For each: import a resume, set target roles, add a relevant and an irrelevant posting, then check the queue keeps only
the relevant one, the tailored resume uses that field's rules and template and fits one page, and standard questions
get answered.

    python3 tests/e2e_careers.py
"""
import json
import os
os.environ["JOB_APPLIER_NO_TELEMETRY"] = "1"
os.environ["APPLYTWIN_NO_TELEMETRY"] = "1"   # tests never count as installs
os.environ["JOB_APPLIER_SKIP_SIGNIN"] = "1"
os.environ["APPLYTWIN_SKIP_SIGNIN"] = "1"   # no Google account in tests
import shutil
import subprocess
import sys
import tempfile

for _s in (sys.stdout, sys.stderr):   # Windows consoles default to cp1252, which can't print emoji
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PEOPLE = {
    'finance': dict(roles=['investment banking', 'finance'], resume="""Jordan Patel
jordan.patel@example.edu | (555) 410-2231 | New York, NY
EDUCATION
New York University, Stern School of Business, B.S. in Finance, Expected May 2028. GPA 3.9
EXPERIENCE
Investment Banking Summer Analyst, Hudson Advisory Partners, New York, NY. June 2026 - August 2026
- Built a DCF and comparable companies analysis for a $40M sell-side acquisition in consumer retail
- Drafted 25 pages of a confidential information memorandum and buyer outreach lists
Treasurer, Stern Investment Club. 2025 - Present
- Managed a $120K student-run equity portfolio; pitched 3 stocks to the investment committee
SKILLS
Excel, financial modeling, DCF, LBO, PowerPoint, Bloomberg Terminal, Capital IQ
""", good=('2027 Investment Banking Summer Analyst', 'Summer analysts join M&A, capital markets and coverage teams. Requirements: financial modeling, Excel, valuation (DCF, comps), strong GPA.'),
        bad=('Software Engineer Intern', 'Build distributed systems in Go and Kafka.'), field='finance', template='finance'),
    'nursing': dict(roles=['healthcare'], resume="""Maya Chen
maya.chen@example.edu | (555) 201-3344 | Austin, TX
EDUCATION
University of Texas at Austin, Bachelor of Science in Nursing, Expected May 2028. GPA 3.8
EXPERIENCE
Patient Care Technician, St. David's Medical Center, Austin, TX. June 2025 - Present
- Monitored vital signs for 12+ patients per shift on a 32-bed med-surg unit
- Assisted nurses with wound care and EHR charting in Epic
SKILLS
Epic EHR, BLS/CPR certified, phlebotomy, patient education, Spanish
""", good=('Summer 2027 Nursing Extern', 'Work alongside RNs on med-surg units. BSN students with BLS certification and Epic experience.'),
        bad=('Investment Banking Summer Analyst', 'Financial modeling and valuation.'), field='healthcare', template='harvard'),
    'design': dict(roles=['design'], resume="""Ava Thompson
ava.t@example.edu | (555) 300-1188 | Providence, RI | avathompson.design
EDUCATION
Rhode Island School of Design, BFA in Graphic Design, Expected May 2028
EXPERIENCE
Product Design Intern, Lumen Health, Boston, MA. June 2026 - August 2026
- Redesigned the patient check-in flow in Figma, cutting drop-off 18% in usability tests with 40 participants
- Built a 60-component design system used by 4 product teams
SKILLS
Figma, Adobe Illustrator, Photoshop, prototyping, user research
""", good=('Product Design Intern, Summer 2027', 'Design end-to-end experiences in Figma. Portfolio required. User research and prototyping.'),
        bad=('Audit Intern', 'Assist with financial statement audits.'), field='design', template='minimal'),
    'marketing': dict(roles=['marketing'], resume="""Sam Rivera
sam.rivera@example.edu | (555) 712-9010 | Chicago, IL
EDUCATION
University of Illinois Chicago, B.A. in Communication, Expected May 2028
EXPERIENCE
Social Media Intern, Windy City Coffee, Chicago, IL. May 2026 - August 2026
- Grew Instagram followers from 3,100 to 9,800 in 12 weeks with a weekly short-form video series
- Ran a $2K paid campaign that drove 640 app sign-ups at $3.10 each
SKILLS
Instagram, TikTok, Canva, Google Analytics, copywriting
""", good=('Marketing Intern - Summer 2027', 'Plan social media campaigns, write content, track engagement in Google Analytics.'),
        bad=('Embedded Firmware Intern', 'Write C for microcontrollers.'), field='marketing', template='modern'),
    'mechanical': dict(roles=['mechanical'], resume="""Chris Okafor
chris.okafor@example.edu | (555) 918-4420 | Atlanta, GA
EDUCATION
Georgia Institute of Technology, B.S. in Mechanical Engineering, Expected May 2028. GPA 3.6
EXPERIENCE
Manufacturing Engineering Intern, Peach State Aerospace, Marietta, GA. May 2026 - August 2026
- Redesigned a drill fixture in SolidWorks, cutting cycle time 22% across 3 production lines
- Ran tolerance stack-ups and GD&T reviews for 14 machined parts
SKILLS
SolidWorks, ANSYS, GD&T, MATLAB, 3D printing
""", good=('Mechanical Engineering Intern - Summer 2027', 'Design and test mechanical components in SolidWorks. GD&T, FEA with ANSYS.'),
        bad=('Marketing Intern', 'Run social media.'), field='hardware', template='compact'),
    'legal': dict(roles=['legal'], resume="""Priya Nair
priya.nair@example.edu | (555) 220-7781 | Washington, DC
EDUCATION
Georgetown University, B.A. in Government, Expected May 2028. GPA 3.85
EXPERIENCE
Legal Intern, DC Tenant Rights Clinic, Washington, DC. June 2026 - August 2026
- Researched 30+ housing court cases and drafted memos summarizing precedent for supervising attorneys
- Interviewed 45 tenants in English and Spanish and prepared intake files
Vice President, Pre-Law Society. 2025 - Present
SKILLS
Legal research, Westlaw, LexisNexis, writing, Spanish
""", good=('Legal Intern - Summer 2027', 'Support attorneys with legal research and writing. Westlaw experience preferred.'),
        bad=('Software Engineer Intern', 'Write Go services.'), field='legal', template='harvard'),
    'biology': dict(roles=['molecular biology'], resume="""Leo Martins
leo.martins@example.edu | (555) 880-3345 | Madison, WI
EDUCATION
University of Wisconsin-Madison, B.S. in Biology, Expected May 2028. GPA 3.7
RESEARCH
Undergraduate Researcher, Chen Lab, Department of Biochemistry. September 2025 - Present
- Ran PCR, gel electrophoresis and Western blots to study protein folding in yeast
- Presented a poster on chaperone proteins at the 2026 undergraduate research symposium
SKILLS
PCR, cell culture, Western blot, microscopy, R, GraphPad Prism
""", good=('Research Intern, Molecular Biology - Summer 2027', 'Join our lab running PCR, cell culture and protein assays.'),
        bad=('Sales Intern', 'Call prospects.'), field='science', template='harvard'),
    'journalism': dict(roles=['journalism'], resume="""Grace Kim
grace.kim@example.edu | (555) 341-6620 | Evanston, IL | gracekim.news
EDUCATION
Northwestern University, B.S. in Journalism, Expected May 2028
EXPERIENCE
Staff Reporter, The Daily Northwestern, Evanston, IL. September 2025 - Present
- Reported and wrote 42 news stories on city government, two picked up by the Chicago Tribune
- Produced a 6-episode podcast on local elections with 3,500 total listens
SKILLS
AP style, interviewing, WordPress, Adobe Premiere, Audition
""", good=('Editorial Intern, Newsroom - Summer 2027', 'Report and write stories for our newsroom. Clips required. AP style.'),
        bad=('Audit Intern', 'Assist audits.'), field='media', template='modern'),
    'architecture': dict(roles=['architecture'], resume="""Diego Alvarez
diego.alvarez@example.edu | (555) 610-2290 | Austin, TX | diegoalvarez.studio
EDUCATION
University of Texas at Austin, Bachelor of Architecture, Expected May 2029
EXPERIENCE
Architecture Intern, Hill Country Design Group, Austin, TX. June 2026 - August 2026
- Modeled a 24,000 sq ft mixed-use building in Revit and Rhino for schematic design
- Produced construction document sheets and renderings for 3 client presentations
SKILLS
Revit, Rhino, AutoCAD, Enscape, hand drafting, model making
""", good=('Architectural Design Intern, Summer 2027', 'Support project teams with Revit modeling, drawings and renderings. Portfolio required.'),
        bad=('Data Scientist Intern', 'Build models in Python.'), field='built', template='compact'),
}

RUNNER = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from job_applier import api, learn, store
spec = json.loads(sys.argv[2])
api.import_resume('resume.txt', None, spec['resume'])
p = store.profile(); p['search'].update(kind='internship', roles=spec['roles'], season='Summer 2027')
p.update(work_authorized_us=True, needs_sponsorship=False, grad_month='May', grad_year='2028')   # answered in onboarding
api.update_profile(p)
g = api.add_job('https://jobs.example.com/good-' + spec['field'], spec['good'][0], 'Acme ' + spec['field'].title(), spec['good'][1])
# the unrelated job arrives the way scanned jobs do (a job you add yourself always makes your queue)
from job_applier import sources
_b = sources.job('greenhouse', 'https://jobs.example.com/bad-' + spec['field'], 'Other Co', spec['bad'][0], 'Remote', 'https://jobs.example.com/bad-' + spec['field'],
                 'https://jobs.example.com/bad-' + spec['field'], '2026-10-01', spec['bad'][1])
store.execute('insert or replace into jobs(id,source,company,title,location,url,apply_url,ats,posted,description,found_at,fit,fit_why)'
              ' values(?,?,?,?,?,?,?,?,?,?,?,?,?)', (_b['id'], 'greenhouse', 'Other Co', spec['bad'][0], 'Remote', _b['url'], _b['url'], '', '2026-10-01',
                                                     spec['bad'][1], 0, 0, ''))
b = {"id": _b['id']}
m = api.add_job('https://jobs.example.com/mine-' + spec['field'], spec['bad'][0] + ' (mine)', 'Mine Co', spec['bad'][1])
api.rescore(force=True)
q = api.queue(50)
ids = [j['id'] for j in q['jobs']]
job = store.rows('select * from jobs where id=?', (g['id'],))[0]
t = api.tailor_apply(g['id'], None, None, 'heuristic')
ans = api.answer_questions(['Are you legally authorized to work in the United States?', 'What is your expected graduation date?'])
v = store.resume()
print(json.dumps({"vault": sum(len(v.get(k, [])) for k in ('experience', 'research', 'projects', 'leadership')), "good_in": g['id'] in ids, "bad_in": b['id'] in ids, "mine_in": m['id'] in ids,
                  "field": learn.field_for(job), "style": t.get('style'), "pages": t.get('pages'), "pdf": bool(t.get('pdf')),
                  "answers": [a.get('answer') for a in ans]}))
'''

def _stub_agents(tmp):
    """Stand-in claude/codex that report 'signed out', so tests never run the real CLIs against a throwaway HOME
    (on macOS that makes them look for a keychain that isn't there, and the system shows a pop-up)."""
    import stat
    d = os.path.join(tmp, 'stubbin')
    os.makedirs(d, exist_ok=True)
    for name in ('claude', 'codex'):
        py = os.path.join(d, name + '_stub.py')
        open(py, 'w').write("import sys, json\na = sys.argv[1:]\n"
                            "print(json.dumps({'loggedIn': False}) if a[:2] == ['auth', 'status'] else '9.9.9 (stub)' if a[:1] == ['--version'] else 'Not logged in')\n"
                            "sys.exit(0 if a[:1] in (['--version'], ['auth'], ['mcp'], ['plugin']) else 1)\n")
        if os.name == 'nt':
            open(os.path.join(d, name + '.cmd'), 'w').write(f'@"{sys.executable}" "{py}" %*\r\n')
        else:
            p = os.path.join(d, name)
            open(p, 'w').write(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n')
            os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    return d

results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok)))
    print(('\033[32mPASS\033[0m ' if ok else '\033[31mFAIL\033[0m ') + name + (f'  \033[2m{detail}\033[0m' if detail else ''))


def main():
    for who, spec in PEOPLE.items():
        tmp = tempfile.mkdtemp(prefix=f'job-applier-{who}-')
        env = {k: v for k, v in os.environ.items() if k not in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY')}
        env.update(HOME=tmp, USERPROFILE=tmp, JOB_APPLIER_HOME=os.path.join(tmp, '.job-applier'), APPLYTWIN_HOME=os.path.join(tmp, '.applytwin'))
        env['PATH'] = _stub_agents(tmp) + os.pathsep + env.get('PATH', '')
        r = subprocess.run([sys.executable, '-c', RUNNER, ROOT, json.dumps({**spec, 'field': who})], env=env, capture_output=True, text=True, timeout=600)
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            d = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            check(f'{who}: runs', False, (r.stderr or r.stdout)[-300:])
            continue
        check(f'{who}: resume imported', d['vault'] >= 1, f"{d['vault']} entries")
        check(f'{who}: relevant job queued', d['good_in'])
        check(f'{who}: unrelated job kept out', not d['bad_in'])
        check(f'{who}: a job you added stays queued after a rescore', d['mine_in'])
        check(f'{who}: field rules', d['field'] == spec['field'], d['field'])
        check(f'{who}: template', d['style'] == spec['template'], d['style'])
        check(f'{who}: one-page PDF', d['pdf'] and d['pages'] == 1)
        check(f'{who}: standard answers', all(d['answers']), ' | '.join(map(str, d['answers'])))
    bad = [n for n, ok in results if not ok]
    print(f'\n{len(results) - len(bad)}/{len(results)} passed' + (f"  failed: {', '.join(bad)}" if bad else ''))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
