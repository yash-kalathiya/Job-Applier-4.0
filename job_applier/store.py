"""Local storage. Everything lives in JOB_APPLIER_HOME (default ~/.job-applier or ~/.applytwin) so the user owns their data.

profile.json   who you are + preferences (filters, caps, auto-submit policy)
resume.json    your master resume, structured (see examples/resume.example.json)
answers.json   your application-question answer bank
job_applier.db / applytwin.db jobs found by the scrapers + applications you sent
"""
import copy
import json
import re
import os
import sqlite3
import threading
import time

HOME = (os.environ.get('JOB_APPLIER_HOME') or os.environ.get('APPLYTWIN_HOME') or
        os.path.expanduser('~/.job-applier' if os.path.exists(os.path.expanduser('~/.job-applier')) or not os.path.exists(os.path.expanduser('~/.applytwin')) else '~/.applytwin'))
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_lock = threading.Lock()


def path(*parts):
    os.makedirs(HOME, exist_ok=True)
    return os.path.join(HOME, *parts)


DEFAULT_PROFILE = {   # nothing about the person is assumed: unanswered fields stay blank and the user is asked
    "name": "", "email": "", "phone": "", "location": "", "linkedin": "", "github": "", "website": "",
    "school": "", "degree": "", "major": "", "minor": "", "gpa": "",
    "grad_month": "", "grad_year": "", "start_year": "", "class_standing": "",
    "work_authorized_us": None, "needs_sponsorship": None, "citizenship": "",
    "willing_to_relocate": None, "onsite_ok": None, "earliest_start": "",
    "over_18": None, "background_check_ok": None, "has_noncompete": None, "government_employee": None,
    "salary_expectation": "", "sms_ok": None, "ai_review_ok": None,
    "eeo": {"gender": "", "race": "", "hispanic": "", "veteran": "", "disability": "", "pronouns": ""},
    "search": {
        "kind": "",                                 # internship | co-op | new-grad | full-time (asked in setup)
        "season": "",                               # one or more terms, e.g. "Summer 2027, Fall 2027"
        "roles": [], "arrangement": [],
        "include": [], "exclude": ["phd", "mba", "master", "senior", "staff", "principal", "manager"],
        "locations": [],
        "min_fit": 65,
        "companies_priority": [], "companies_skip": [],
    },
    "apply": {
        "auto_submit": False,                       # False = agent fills, you click Submit
        "daily_limit": 40,
        "per_company_cap": 3,
        "tailor_every_resume": True,
        "template": "classic",
        "stop_on": ["password", "captcha", "arbitration", "essay>150 words", "assessment"],
        "email_codes": "notify",                    # notify = ping you; agent = your agent reads the code from your email
        "notify_desktop": True,
    },
}

DEFAULT_RESUME = {
    "basics": {"name": "", "email": "", "phone": "", "location": "", "links": [], "headline": []},
    "education": [], "experience": [], "projects": [], "research": [], "leadership": [],
    "skills": [], "awards": [], "certifications": [], "volunteering": [],
    "order": ["education", "experience", "projects", "research", "leadership", "volunteering", "skills", "certifications", "awards"],
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(name, default=None):
    p = path(name)
    if not os.path.exists(p):
        return copy.deepcopy(default)
    try:
        with open(p, encoding='utf-8-sig') as f:   # -sig: Notepad / PowerShell 5 add a byte-order mark
            data = json.load(f)
    except UnicodeDecodeError:   # written by an older version in the Windows code page; read it once, save as UTF-8
        with open(p, encoding='cp1252', errors='replace') as f:
            data = json.load(f)
        save(name, data)
    except ValueError:   # damaged (a crash mid-write on an old version): keep a copy aside and carry on with the default
        try:
            os.replace(p, f"{p}.damaged-{time.strftime('%Y%m%d-%H%M%S')}")
        except OSError:
            pass
        return copy.deepcopy(default)
    return _merge(default, data) if isinstance(default, dict) else data


def save(name, obj):
    import tempfile
    with _lock:
        # a temp file of its own: the app, the agent's MCP server and the CLI all save, sometimes at the same moment
        fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(name) + '.', suffix='.tmp', dir=os.path.dirname(path(name)))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(obj, f, indent=1, ensure_ascii=False)
            os.replace(tmp, path(name))
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    return obj


class file_lock:
    """A lock shared by every Job Applier 4.0 process (app, MCP server, CLI), for read-modify-write of a JSON file."""
    def __init__(self, name):
        self.p = path(name + '.lock')

    def __enter__(self):
        self.f = open(self.p, 'a+', encoding='utf-8')
        if os.name == 'nt':
            import msvcrt
            import time
            while True:
                try:
                    self.f.seek(0)
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(self.f.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        try:
            if os.name == 'nt':
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        finally:
            self.f.close()


def update(name, fn, default=None):
    """Read a JSON file, change it with fn, write it back, with no other process able to interleave."""
    with file_lock(name):
        cur = load(name, copy.deepcopy(default))
        new = fn(cur)
        save(name, cur if new is None else new)
        return cur if new is None else new


def next_summer():
    """The internship cycle students are recruiting for right now (from August on, it's next summer)."""
    t = time.gmtime()
    return t.tm_year + (1 if t.tm_mon >= 8 else 0)


def profile():
    p = load('profile.json', DEFAULT_PROFILE)
    p.setdefault('search', {})
    return p


LIST_FIELDS = ('bullets', 'tech', 'alts', 'coursework', 'items', 'links', 'headline', 'honors')


def clean(x):
    """Resume data from any importer or model, made safe to render: null text becomes '', null lists become [], numbers
    (a GPA of 3.86) become text, and a list that arrived as one comma-separated string is split."""
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if k in LIST_FIELDS:
                if v is None:
                    v = []
                elif isinstance(v, str):
                    v = [s.strip() for s in re.split(r'[,;]\s*' if k != 'bullets' else r'\n+', v) if s.strip()]
                out[k] = [clean(i) for i in v if i not in (None, '')] if isinstance(v, list) else v
            else:
                out[k] = clean(v)
        return out
    if isinstance(x, list):
        return [clean(i) for i in x if i is not None]
    if x is None:
        return ''
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return ('%.2f' % x).rstrip('0').rstrip('.') if isinstance(x, float) and x != int(x) else (('%.1f' % x) if isinstance(x, float) else str(x))
    return x


def resume():
    return clean(load('resume.json', DEFAULT_RESUME))


def answers():
    """Profile-backed answers always come from the current profile (so a Settings change reaches every form), then
    anything you wrote or edited yourself on top."""
    from . import answers as ans
    base = ans.default_bank(profile())
    saved = load('answers.json', None) or []
    mine = {r.get('key'): r for r in saved if r.get('source') == 'user' and r.get('key')}
    out = [mine.pop(r['key'], r) for r in base]
    keys = {r['key'] for r in base}
    return out + [r for r in saved if r.get('key') not in keys and r.get('source') == 'user'] + list(mine.values())


def companies():
    """Built-in boards + your own additions + boards discovered from job trackers (all merged, so updates reach everyone)."""
    with open(os.path.join(APP, 'data', 'companies.json'), encoding='utf-8') as f:
        out = json.load(f)
    for extra in (path('companies.json'), path('discovered.json')):
        if os.path.exists(extra):
            try:
                for k, v in json.load(open(extra, encoding='utf-8')).items():
                    out[k] = list(dict.fromkeys(out.get(k, []) + v))
            except (ValueError, OSError):
                pass
    return out


# Windows: start helper programs without a console window (the app runs in the background with pythonw; a window would
# flash up, and closing it would kill an Autopilot run)
NOWIN = {'creationflags': 0x08000000} if os.name == 'nt' else {}


SCHEMA = """
create table if not exists jobs(
  id text primary key, source text, company text, title text, location text,
  url text, apply_url text, ats text, posted text, description text,
  found_at real, fit real default 0, fit_why text, status text default 'new');
create index if not exists jobs_status on jobs(status);
create table if not exists applications(
  id integer primary key autoincrement, job_id text, company text, title text, url text,
  status text, resume_path text, notes text, at real);
create table if not exists claims(job_id text primary key, who text, at real);
create table if not exists inbox(id integer primary key autoincrement, kind text, title text, message text, url text, job_id text,
  at real, resolved real);
create table if not exists thread(id integer primary key autoincrement, job_id text, role text, text text, at real);
create index if not exists thread_job on thread(job_id);
"""


_wal = [False]


def db():
    db_file = 'job_applier.db' if os.path.exists(path('job_applier.db')) or not os.path.exists(path('applytwin.db')) else 'applytwin.db'
    con = sqlite3.connect(path(db_file), timeout=30)
    con.row_factory = sqlite3.Row
    if not _wal[0]:   # readers never wait for a writer (a scan or rescore used to freeze every page for seconds)
        try:
            con.execute('pragma journal_mode=wal')
        except sqlite3.Error:
            pass
        _wal[0] = True
    con.executescript(SCHEMA)
    return con


def rows(sql, args=()):
    with db() as con:
        return [dict(r) for r in con.execute(sql, args)]


def execute(sql, args=()):
    with _lock, db() as con:
        cur = con.execute(sql, args)
        return cur.rowcount


STATUSES = {'applied': 'Applied', 'submitted': 'Applied', 'complete': 'Applied', 'completed': 'Applied', 'done': 'Applied',
            'needs user': 'Needs User', 'needs_user': 'Needs User', 'needs you': 'Needs User', 'blocked': 'Needs User',
            'skipped': 'Skipped', 'skip': 'Skipped', 'failed': 'Failed', 'error': 'Failed', 'interview': 'Interview',
            'oa': 'OA', 'offer': 'Offer', 'rejected': 'Rejected'}

# what counts toward the daily limit and per-company cap: submitted, plus filled and waiting only for your Submit click
COUNTED = "(status='Applied' or (status='Needs User' and lower(coalesce(notes,'')) like '%ready to submit%'))"


def log_application(job_id, status, notes='', resume_path=''):
    status = STATUSES.get((status or '').strip().lower(), (status or 'Applied').strip())
    j = (rows('select * from jobs where id=?', (job_id,)) or [{}])[0]
    execute('insert into applications(job_id,company,title,url,status,resume_path,notes,at) values(?,?,?,?,?,?,?,?)',
            (job_id, j.get('company', ''), j.get('title', ''), j.get('apply_url') or j.get('url', ''),
             status, resume_path, notes, time.time()))
    execute('update jobs set status=? where id=?', (status.lower(), job_id))
    execute('delete from claims where job_id=?', (job_id,))   # logged: the claim did its job
    if status in ('Applied', 'Skipped'):   # nothing left for the user to do on this one
        execute('update inbox set resolved=? where job_id=? and resolved is null', (time.time(), job_id))
    return {"ok": True, "job": j.get('title'), "company": j.get('company'), "status": status}


def claim(job_id, who='agent'):
    """Atomic claim so two parallel agents never apply to the same job."""
    with _lock, db() as con:
        try:
            con.execute('insert into claims(job_id,who,at) values(?,?,?)', (job_id, who, time.time()))
            return True
        except sqlite3.IntegrityError:
            return False


def applied_count_today():
    start = time.time() - 86400
    return rows(f"select count(distinct job_id) n from applications where {COUNTED} and at>?", (start,))[0]['n']


def company_count(company):
    from .match import company_key
    k = company_key(company)
    return sum(r['n'] for r in rows(f"select company, count(distinct job_id) n from applications where {COUNTED} group by company")
               if company_key(r['company']) == k)
