"""Job scrapers. Every source is a public, no-login endpoint, so scanning never touches anyone's account.

  greenhouse       boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
  lever            api.lever.co/v0/postings/{company}?mode=json
  ashby            api.ashbyhq.com/posting-api/job-board/{org}
  smartrecruiters  jobs.smartrecruiters.com/sr-jobs/search  (live feed of every company, newest first)
  workday          {tenant}.{wdN}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs  (POST)
  workable         apply.workable.com/api/v3/accounts/{account}/jobs  (POST)
  recruitee        {company}.recruitee.com/api/offers
  community lists  GitHub trackers: SimplifyJobs, vanshb03 (listings.json); SpeedyApply, Northwestern FinTech quant,
                   Zapply, Simplify off-season (README tables)
  open APIs        The Muse (every field), RemoteOK, Remotive, Himalayas, Jobicy, Arbeitnow, Hacker News "Who is hiring"
  discovery        every board a tracker links to (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Recruitee)
                   is remembered and scanned whole, so one listed role brings in the company's other openings
"""
import hashlib
import os
import html
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from . import store

import threading
_disc_lock = threading.Lock()
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'

def _cycles():
    """Recruiting cycles to read, computed from today's date so the lists roll over by themselves every year:
    from August, next summer's lists are live (in Oct 2026 that's Summer 2027 and 2028); before that, this summer's."""
    t = time.gmtime()
    first = t.tm_year + (1 if t.tm_mon >= 8 else 0)
    return [first, first + 1]


def _lists():
    """Every tracker for the current cycles. Lists that don't exist yet (next year's) just return 404 and are skipped."""
    gh = 'https://raw.githubusercontent.com/'
    js = [gh + 'SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json']
    md = []
    for y in _cycles():
        js += [gh + f'SimplifyJobs/Summer{y}-Internships/dev/.github/scripts/listings.json',
               gh + f'vanshb03/Summer{y}-Internships/dev/.github/scripts/listings.json',
               gh + f'vanshb03/New-Grad-{y}/dev/.github/scripts/listings.json']
        md += [gh + f'speedyapply/{y}-SWE-College-Jobs/main/README.md', gh + f'speedyapply/{y}-AI-College-Jobs/main/README.md',
               gh + f'northwesternfintech/{y}QuantInternships/main/README.md',
               gh + f'SimplifyJobs/Summer{y}-Internships/dev/README-Off-Season.md']
    md.append(gh + 'zapplyjobs/New-Grad-Jobs/main/README.md')
    return js, md


def get(url, data=None, timeout=20):
    headers = {'User-Agent': UA, 'Accept': 'application/json'}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def strip_html(s):
    s = html.unescape(s or '')
    s = re.sub(r'<(br|/p|/li|/h\d)[^>]*>', '\n', s, flags=re.I)
    s = re.sub(r'<li[^>]*>', '\n- ', s, flags=re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    return re.sub(r'[ \t\r\f\v]+', ' ', re.sub(r'\n\s*\n+', '\n', s)).strip()


def jid(source, key):
    return source[:2] + '_' + hashlib.sha1(f'{source}:{key}'.encode()).hexdigest()[:12]


CO_NOISE = re.compile(r"\s*(?:[-|:(]\s*)?\b(?:early\s*careers?|careers?(?:'s)?\s*page|careers?|campus(?:\s*recruiting)?|university(?:\s*(?:job|recruiting))?s?|"
                      r"internships?|interns?|student\s*programs?|recruiting|jobs?)\b\)?\s*$", re.I)


def clean_company(name):
    # trackers decorate names ('🔥 Tesla', '⭐️ Stripe'); keep letters, numbers and normal punctuation only
    n = re.sub(r"[^\w\s&.,'()+/-]", '', name or '').strip()
    for _ in range(3):
        n2 = CO_NOISE.sub('', n).strip(' -|:')
        if n2 == n or not n2:
            break
        n = n2
    if n and n == n.lower():  # board slugs like "notion", "bedrock-robotics"
        n = ' '.join(w.capitalize() for w in re.split(r'[-_]+', n))
    return n


def job(source, key, company, title, location, url, apply_url=None, posted='', description='', ats=None):
    return {"id": jid(source, key), "source": source, "company": clean_company(company), "title": (title or '').strip(),
            "location": (location or '').strip(), "url": url, "apply_url": apply_url or url,
            "ats": ats or source, "posted": posted or '', "description": description or ''}


def greenhouse(token):
    token, _, label = token.partition('|')
    d = get(f'https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true')
    name = label or token
    try:
        name = get(f'https://boards-api.greenhouse.io/v1/boards/{token}').get('name') or name
    except Exception:
        pass
    for j in d.get('jobs', []):
        yield job('greenhouse', j['id'], name, j.get('title'), (j.get('location') or {}).get('name', ''),
                  j.get('absolute_url'), f'https://job-boards.greenhouse.io/embed/job_app?for={token}&token={j["id"]}',
                  j.get('first_published') or j.get('updated_at', ''), strip_html(j.get('content', '')))   # updated_at moves daily


def lever(company):
    company, _, label = company.partition('|')
    for j in get(f'https://api.lever.co/v0/postings/{company}?mode=json'):
        cat = j.get('categories') or {}
        desc = (j.get('descriptionPlain') or '') + '\n' + '\n'.join(
            f"{l.get('text', '')}\n{strip_html(l.get('content', ''))}" for l in j.get('lists', []))
        yield job('lever', j['id'], label or company, j.get('text'), cat.get('location', ''), j.get('hostedUrl'),
                  j.get('applyUrl'), time.strftime('%Y-%m-%d', time.gmtime((j.get('createdAt') or 0) / 1000)), desc)


def ashby(org):
    org, _, label = org.partition('|')
    d = get(f'https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true')
    for j in d.get('jobs', []):
        if not j.get('isListed', True):
            continue
        yield job('ashby', j['id'], label or org, j.get('title'), j.get('location', ''), j.get('jobUrl'),
                  j.get('applyUrl') or (j.get('jobUrl', '') + '/application'), j.get('publishedAt', ''),
                  j.get('descriptionPlain') or strip_html(j.get('descriptionHtml', '')))


def smartrecruiters_feed(keywords=('intern', 'internship', 'co-op', 'new grad', 'software engineer')):
    seen = set()
    for kw in keywords:
        d = get('https://jobs.smartrecruiters.com/sr-jobs/search?' + urllib.parse.urlencode({'keyword': kw}))
        for j in d.get('content', []):
            if j['id'] in seen:
                continue
            seen.add(j['id'])
            loc = j.get('location') or {}
            where = ', '.join(x for x in (loc.get('city'), loc.get('region'), (loc.get('country') or '').upper()) if x)
            if loc.get('remote'):
                where += ' (Remote)'
            yield job('smartrecruiters', j['id'], j['company']['name'], j.get('name'), where, j.get('applyUrl'),
                      j.get('applyUrl'), j.get('releasedDate', ''), '')


def smartrecruiters_company(company):
    company = company.partition('|')[0]
    d = get(f'https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100')
    for j in d.get('content', []):
        loc = j.get('location') or {}
        yield job('smartrecruiters', j['id'], (j.get('company') or {}).get('name', company), j.get('name'),
                  loc.get('fullLocation') or loc.get('city', ''),
                  f"https://jobs.smartrecruiters.com/{company}/{j['id']}", None, j.get('releasedDate', ''))


def _workday_search():
    """What to search Workday for: interns see internships, co-op students co-ops too, new grads early-career roles, and
    full-time searches see everything (matching filters it down afterwards)."""
    kind = (store.profile().get('search') or {}).get('kind') or 'internship'
    return {'internship': ['intern'], 'co-op': ['intern', 'co-op'], 'new-grad': ['new grad', 'university', 'early career', 'graduate'],
            'full-time': ['']}.get(kind, ['intern'])


def workday(spec, search=None):
    """spec = 'tenant.wd5/Site_Name', optionally '|Company Name' (tenant codes like 'ghr' or 'ms' aren't names)"""
    seen = set()
    for term in ([search] if search is not None else _workday_search()):
        for j in _workday(spec, term):
            if j['id'] not in seen:
                seen.add(j['id'])
                yield j


def _workday(spec, search):
    spec, _, name = spec.partition('|')
    host, site = spec.split('/', 1)
    tenant = host.split('.')[0]
    base = f'https://{host}.myworkdayjobs.com'
    off, cap = 0, 400 if search else 600   # big companies post hundreds of internships (Northrop: 1,600+)
    while off < cap:
        d = get(f'{base}/wday/cxs/{tenant}/{site}/jobs',
                {"appliedFacets": {}, "limit": 20, "offset": off, "searchText": search})
        posts = d.get('jobPostings', [])
        for p in posts:
            url = f"{base}/en-US/{site}{p.get('externalPath', '')}"
            yield job('workday', url, name or tenant.capitalize(), p.get('title'), p.get('locationsText', ''), url,
                      url + '/apply', p.get('postedOn', ''), '')
        if len(posts) < 20:
            break
        off += 20


def community():
    out, seen = [], set()
    for url in _lists()[0]:
        try:
            items = get(url, timeout=40)
        except Exception:
            continue
        for it in items:
            if not it.get('active', True) or not it.get('is_visible', True):
                continue
            key = it.get('url') or it.get('id')
            if key in seen:
                continue
            seen.add(key)
            locs = it.get('locations') or []
            out.append(job('community', key, it.get('company_name', ''), it.get('title', ''), '; '.join(locs[:3]),
                           it.get('url'), it.get('url'),
                           time.strftime('%Y-%m-%d', time.gmtime(it.get('date_posted') or it.get('date_updated') or 0)),
                           ' '.join(it.get('terms') or []) + ' ' + (it.get('sponsorship') or ''),
                           ats=detect_ats(it.get('url', ''))))
    return out



# ------------------------------------------------------------------ trackers published as tables

SKIP_LINK = re.compile(r'simplify\.jobs/(?!p/)|imgur|shields\.io|github\.com/[^/]+/[^/]+/?$|githubusercontent|speedyapply\.com/?$|#')


def _cells_md(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def _text(cell):
    cell = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', cell)
    cell = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', cell)
    return strip_html(cell).replace('**', '').replace('↳', '').strip()


def _links(cell):
    hrefs = re.findall(r'\]\((https?://[^)\s]+)\)', cell) + re.findall(r'href="(https?://[^"]+)"', cell)
    return [h for h in hrefs if not SKIP_LINK.search(h)]


QUANT_ROLES = {'QR': 'Quantitative Researcher', 'QT': 'Quantitative Trader', 'QD': 'Quantitative Developer', 'SWE': 'Software Engineer',
               'HW': 'Hardware Engineer', 'FPGA': 'FPGA Engineer', 'TRADER': 'Trader', 'RISK': 'Risk Analyst', 'OPS': 'Trading Operations'}


def table_list(url):
    """Parse a README job tracker: markdown or HTML tables, read by their header row (company / role / location / link),
    or per-company sections ('## Firm' then 'Role | Links' rows, as the quant lists do)."""
    txt = get_text(url, timeout=40)
    out, seen = [], set()

    def add(co, role, loc, link):
        if link and role and co and link not in seen:
            seen.add(link)
            out.append(job('community', link, co, role, loc, link, link, '', '', ats=detect_ats(link)))

    if '<tr' in txt:   # HTML tables (Simplify READMEs)
        last = ''
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', txt, re.S):
            cells = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
            if len(cells) < 3 or '🔒' in tr:
                continue
            co = _text(cells[0]) or last
            last = co
            add(co, _text(cells[1]), _text(cells[2]), next((h for c in cells[1:] for h in _links(c)), None))
    head, section = None, ''
    for line in txt.splitlines():
        if line.startswith('#'):
            section, head = _text(line.lstrip('#')), None
            continue
        if not line.startswith('|'):
            head = None if line.strip() else head
            continue
        cells = _cells_md(line)
        if re.match(r'^\|\s*:?-', line):
            continue
        low = [_text(c).lower() for c in cells]
        if head is None and any(w in ' '.join(low) for w in ('company', 'role', 'name', 'position', 'links', 'title', 'firm')):
            head = low
            last = ''
            continue
        if head is None or '🔒' in line or '❌' in line:
            continue
        col = lambda *names: next((i for i, h in enumerate(head) if any(n in h for n in names)), None)
        ci, ri, li = col('company', 'firm', 'employer'), col('role', 'position', 'title', 'program'), col('location')
        if ci is None and ri is None and col('name') is not None:          # 'Name' column holds the program (Zapply)
            ci = ri = col('name')
        if ci is None and section and ri is not None:                     # '## Firm' sections (quant lists)
            role = QUANT_ROLES.get(_text(cells[ri]).upper(), _text(cells[ri]))
            for label, href in re.findall(r'\[([^\]]*)\]\((https?://[^)\s]+)\)', line):
                if '✅' in label or not re.search(r'[❌🔒]', label):
                    extra = _text(label).replace('✅', '').strip()
                    add(section, f"{role}{' (' + extra + ')' if extra else ''} Intern", '', href)
            continue
        if ri is None:
            continue
        co = _text(cells[ci]) if ci is not None and ci < len(cells) else ''
        co = co or last
        last = co
        loc = _text(cells[li]) if li is not None and li < len(cells) else ''
        link = next((h for c in cells for h in _links(c)), None)
        add(co, _text(cells[ri]) if ri < len(cells) else '', loc, link)
    return out


def get_text(url, timeout=20):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')


# ------------------------------------------------------------------ open job APIs (no key, no account)

def themuse(kind='internship', pages=15):
    """The Muse covers every field (healthcare, finance, media, education, government...)."""
    levels = {'internship': ['Internship'], 'new-grad': ['Entry Level'], 'full-time': ['Entry Level', 'Mid Level']}.get(kind, ['Internship'])
    for level in levels:
        for page in range(pages):
            d = get('https://www.themuse.com/api/public/jobs?' + urllib.parse.urlencode({'level': level, 'page': page}), timeout=30)
            for j in d.get('results', []):
                url = (j.get('refs') or {}).get('landing_page')
                yield job('themuse', j['id'], (j.get('company') or {}).get('name', ''), j.get('name'),
                          '; '.join(l.get('name', '') for l in j.get('locations', [])[:3]), url, url,
                          (j.get('publication_date') or '')[:10], strip_html(j.get('contents', ''))[:6000])
            if page + 1 >= d.get('page_count', 0):
                break


def remote_boards():
    """Remote-first boards. Mostly full-time; the matcher keeps only what fits the profile."""
    feeds = []
    try:
        for j in get('https://remoteok.com/api', timeout=30)[1:]:
            feeds.append(('remoteok', j.get('id'), j.get('company'), j.get('position'), j.get('location') or 'Remote', j.get('url'),
                          j.get('apply_url') or j.get('url'), (j.get('date') or '')[:10], strip_html(j.get('description', ''))))
    except Exception:
        pass
    try:
        for j in get('https://remotive.com/api/remote-jobs', timeout=30).get('jobs', []):
            feeds.append(('remotive', j.get('id'), j.get('company_name'), j.get('title'), j.get('candidate_required_location') or 'Remote',
                          j.get('url'), j.get('url'), (j.get('publication_date') or '')[:10], strip_html(j.get('description', ''))))
    except Exception:
        pass
    try:
        for j in get('https://himalayas.app/jobs/api?limit=100', timeout=30).get('jobs', []):
            feeds.append(('himalayas', j.get('guid') or j.get('applicationLink'), j.get('companyName'), j.get('title'),
                          ', '.join(j.get('locationRestrictions') or []) or 'Remote', j.get('applicationLink'), j.get('applicationLink'),
                          '', strip_html(j.get('description', ''))))
    except Exception:
        pass
    try:
        for j in get('https://jobicy.com/api/v2/remote-jobs?count=100', timeout=30).get('jobs', []):
            feeds.append(('jobicy', j.get('id'), j.get('companyName'), j.get('jobTitle'), j.get('jobGeo') or 'Remote', j.get('url'),
                          j.get('url'), (j.get('pubDate') or '')[:10], strip_html(j.get('jobDescription', ''))))
    except Exception:
        pass
    try:
        for j in get('https://www.arbeitnow.com/api/job-board-api', timeout=30).get('data', []):
            feeds.append(('arbeitnow', j.get('slug'), j.get('company_name'), j.get('title'), j.get('location', ''), j.get('url'),
                          j.get('url'), '', strip_html(j.get('description', ''))))
    except Exception:
        pass
    for src, key, co, title, loc, url, apply, posted, desc in feeds:
        if key and title and url:
            yield job(src, key, co or '', title, loc, url, apply, posted, desc[:6000], ats=detect_ats(apply or url))


def hn_hiring():
    """This month's Hacker News 'Who is hiring?' thread: one comment per company, 'Company | Role | Location | ...'."""
    story = get('https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=5', timeout=30)
    sid = next((h['objectID'] for h in story.get('hits', []) if 'who is hiring' in h.get('title', '').lower()), None)
    if not sid:
        return
    for c in get(f'https://hn.algolia.com/api/v1/items/{sid}', timeout=60).get('children', []):
        t = c.get('text') or ''
        first = strip_html(t.split('<p>')[0])
        parts = [x.strip() for x in first.split('|')]
        if len(parts) < 2:
            continue
        roleish = re.compile(r'engineer|developer|intern|scientist|designer|analyst|manager|researcher|lead|architect|specialist|marketing|sales|ops|writer', re.I)
        role = next((x for x in parts[1:] if roleish.search(x)), parts[1])
        place = next((x for x in parts[1:] if x is not role and re.search(r'remote|onsite|hybrid|,|\b[A-Z]{2}\b', x)), '')
        links = [h for h in re.findall(r'href="([^"]+)"', t) if 'ycombinator.com' not in h]
        link = html.unescape(links[0]) if links else f"https://news.ycombinator.com/item?id={c['id']}"
        yield job('hackernews', c['id'], parts[0][:80], role[:120], place[:80], link, link,
                  (c.get('created_at') or '')[:10], strip_html(t)[:6000], ats=detect_ats(link))


# ------------------------------------------------------------------ more applicant tracking systems

def workable(account):
    account, _, label = account.partition('|')
    d = get(f'https://apply.workable.com/api/v3/accounts/{account}/jobs', {"query": "", "location": [], "department": [], "worktype": [], "remote": []})
    for j in d.get('results', []):
        loc = j.get('location') or {}
        url = f"https://apply.workable.com/{account}/j/{j['shortcode']}/"
        yield job('workable', j['shortcode'], label or account, j.get('title'), ', '.join(x for x in (loc.get('city'), loc.get('region'), loc.get('country')) if x),
                  url, url + 'apply/', j.get('published', ''), '')


def recruitee(company):
    company = company.partition('|')[0]
    for j in get(f'https://{company}.recruitee.com/api/offers/').get('offers', []):
        yield job('recruitee', j['id'], j.get('company_name') or company, j.get('title'), j.get('location', ''), j.get('careers_url'),
                  j.get('careers_apply_url') or j.get('careers_url'), (j.get('published_at') or '')[:10], strip_html(j.get('description', '')))


# ------------------------------------------------------------------ discovery: trackers point at whole boards

BOARD_PATTERNS = [
    ('greenhouse', re.compile(r'(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)')),
    ('lever', re.compile(r'jobs\.lever\.co/([\w.-]+)/')),
    ('ashby', re.compile(r'jobs\.ashbyhq\.com/([\w.%-]+)/')),
    ('workday', re.compile(r'https?://([\w-]+\.wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)/')),
    ('smartrecruiters', re.compile(r'(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)/')),
    ('workable', re.compile(r'apply\.workable\.com/([\w-]+)/')),
    ('recruitee', re.compile(r'https?://([\w-]+)\.recruitee\.com/')),
]


def discover(jobs):
    """Remember every company board the trackers link to, so the next scan reads the whole board."""
    found = {}
    for j in jobs:
        for url in {j.get('url') or '', j.get('apply_url') or ''}:
            for ats, pat in BOARD_PATTERNS:
                m = pat.search(url)
                if m:
                    token = '/'.join(m.groups()) if ats == 'workday' else urllib.parse.unquote(m.group(1))
                    if token.lower() not in ('embed', 'jobs', 'j', 'careers'):
                        co = clean_company(j.get('company') or '').replace('|', ' ').strip()
                        found.setdefault(ats, {}).setdefault(token, co)
    if not found:
        return {}
    known = store.companies()
    new = {}

    def add(cur):
        for ats, toks in found.items():
            have = {t.split('|')[0].lower() for t in known.get(ats, [])}
            fresh = {f'{t}|{co}' if co else t for t, co in toks.items() if t.lower() not in have}
            if fresh:
                new[ats] = fresh
                cur[ats] = sorted(set(cur.get(ats, [])) | fresh)
    with _disc_lock:
        store.update('discovered.json', add, {})
    return new

def forget_board(name):
    """A discovered board that no longer answers (the company moved or closed it) is dropped, so scans stay fast."""
    ats, _, token = name.partition(':')
    if not token:
        return
    with _disc_lock:
        store.update('discovered.json', lambda cur: cur.__setitem__(ats, [t for t in cur.get(ats, []) if t != token]) if ats in cur else None, {})


def detect_ats(url):
    for k, pat in (('greenhouse', 'greenhouse.io'), ('lever', 'lever.co'), ('ashby', 'ashbyhq.com'),
                   ('workday', 'myworkdayjobs.com'), ('smartrecruiters', 'smartrecruiters.com'),
                   ('icims', 'icims.com'), ('taleo', 'taleo.net'), ('oracle', 'oraclecloud.com'),
                   ('successfactors', 'successfactors'), ('eightfold', 'eightfold.ai'), ('jobvite', 'jobvite.com'),
                   ('workable', 'workable.com'), ('recruitee', 'recruitee.com'), ('bamboohr', 'bamboohr.com'),
                   ('jazzhr', 'applytojob.com'), ('breezy', 'breezy.hr'), ('rippling', 'rippling.com'), ('dover', 'dover.com'),
                   ('paylocity', 'paylocity.com'), ('ukg', 'ultipro.com'), ('adp', 'adp.com'), ('linkedin', 'linkedin.com')):
        if pat in (url or ''):
            return k
    return 'other'


def scan(sources=None, on_progress=None, workers=32):
    """Run every enabled source in parallel, score each job against the profile, upsert into database."""
    from . import match
    sources = sources or ['community', 'tables', 'themuse', 'remote', 'hackernews', 'smartrecruiters', 'greenhouse', 'lever',
                          'ashby', 'workday', 'workable', 'recruitee']
    comp = store.companies()
    tasks = []
    kind = store.profile()['search'].get('kind', 'internship')
    if 'community' in sources:
        tasks.append(('community', community, ()))
    if 'tables' in sources:
        tasks += [(f'tracker:{u.split("/")[3]}/{u.split("/")[4]}', lambda u=u: table_list(u), ()) for u in _lists()[1]]
    if 'themuse' in sources:
        tasks.append(('themuse', lambda k=kind: list(themuse(k)), ()))
    if 'remote' in sources and kind != 'internship':
        tasks.append(('remote boards', lambda: list(remote_boards()), ()))
    if 'hackernews' in sources:
        tasks.append(('hackernews', lambda: list(hn_hiring()), ()))
    if 'smartrecruiters' in sources:
        sp = store.profile()['search']
        kw = {'internship': ['intern', 'internship'], 'new-grad': ['new grad', 'entry level'], 'full-time': []}.get(sp.get('kind'), [])
        kws = tuple(dict.fromkeys(kw + [f'{r} {kw[0]}' if kw else r for r in sp.get('roles', [])[:8]] + ['co-op']))
        tasks.append(('smartrecruiters feed', lambda kws=kws: list(smartrecruiters_feed(kws)), ()))
        tasks += [(f'smartrecruiters:{c}', lambda c=c: list(smartrecruiters_company(c)), ()) for c in comp.get('smartrecruiters', [])]
    for src, fn in (('greenhouse', greenhouse), ('lever', lever), ('ashby', ashby), ('workday', workday),
                    ('workable', workable), ('recruitee', recruitee)):
        if src in sources:
            tasks += [(f'{src}:{c}', lambda fn=fn, c=c: list(fn(c)), ()) for c in comp.get(src, [])]
    prof = store.profile()
    from . import ats, tailor
    vt = ats.resume_text(store.resume())
    vault_terms = {t for t, pat in ats.PATTERNS.items() if pat.search(vt)}
    stats = {"sources": len(tasks), "done": 0, "fetched": 0, "new": 0, "matched": 0, "errors": 0}
    now = time.time()
    boards = {'greenhouse': greenhouse, 'lever': lever, 'ashby': ashby, 'workday': workday, 'smartrecruiters': smartrecruiters_company,
              'workable': workable, 'recruitee': recruitee}
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fn, *a): name for name, fn, a in tasks}
        while futs:
            done, _ = wait(futs, return_when=FIRST_COMPLETED)
            for f in done:
                name = futs.pop(f)
                stats['done'] += 1
                try:
                    jobs = f.result()
                except Exception as e:
                    stats['errors'] += 1
                    if getattr(e, 'code', None) in (404, 410):   # gone for good; a timeout or rate limit is not a reason to forget it
                        forget_board(name)
                    if on_progress:
                        on_progress(dict(stats))
                    continue
                if name == 'community' or name.startswith(('tracker:', 'hackernews')):
                    # a tracker linked to a board we don't scan yet: read the whole board in this same scan
                    for ats_name, toks in discover(jobs).items():
                        for t in toks:
                            futs[ex.submit(lambda fn=boards[ats_name], t=t: list(fn(t)))] = f'{ats_name}:{t}'
                            stats['sources'] += 1
                            stats['discovered'] = stats.get('discovered', 0) + 1
                with store.db() as con:   # short transaction per board, so the app can keep writing while a scan runs
                    _ingest(con, jobs, prof, vault_terms, stats, now)
                    _retire(con, name, jobs)
                if on_progress:
                    on_progress(dict(stats))
    return stats


def _retire(con, name, jobs):
    """Postings that disappeared from a company's own board are closed: they leave the queue instead of staying 'new'
    forever. Only after a successful fetch that returned jobs (an empty answer may be a hiccup)."""
    ats, _, token = name.partition(':')
    if not token or not jobs or ats not in ('greenhouse', 'lever', 'ashby', 'workday', 'smartrecruiters', 'workable', 'recruitee'):
        return
    token = token.split('|')[0]
    seen = [j['id'] for j in jobs]
    ph = ','.join('?' * len(seen))
    # this exact board only ("ame" must not close "frame" or "epicgames"): its token is a whole path segment of the URL
    con.execute(f"update jobs set status='closed' where status='new' and source=? and (url like ? or url like ? or url like ?) and id not in ({ph})",
                [ats, f'%/{token}/%', f'%/{token}?%', f'%for={token}&%'] + seen)


def _ingest(con, jobs, prof, vault_terms, stats, now):
    from . import match
    for j in jobs:
        stats['fetched'] += 1
        try:
            _ingest_one(con, j, prof, vault_terms, stats, now, match)
        except Exception:   # one malformed posting (a bad date, a missing field) never aborts the scan
            stats['errors'] = stats.get('errors', 0) + 1


def _ingest_one(con, j, prof, vault_terms, stats, now, match):
    fit, why = match.fit(j, prof, vault_terms)
    cur = con.execute('select status from jobs where id=?', (j['id'],)).fetchone()
    if fit < 1:
        if cur:
            con.execute('update jobs set fit=0, fit_why=? where id=?', (why, j['id']))
        return
    if cur:
        con.execute("update jobs set fit=?, fit_why=?, company=?, description=coalesce(nullif(?,''),description), status=case when status='closed' then 'new' else status end where id=?",
                    (fit, why, j['company'], j['description'], j['id']))
        return
    stats['new'] += 1
    stats['matched'] += fit >= prof['search'].get('min_fit', 65)
    con.execute('insert into jobs(id,source,company,title,location,url,apply_url,ats,posted,description,found_at,fit,fit_why)'
                ' values(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (j['id'], j['source'], j['company'], j['title'], j['location'], j['url'], j['apply_url'],
                 j['ats'] if j['ats'] != 'community' else detect_ats(j['apply_url']), j['posted'],
                 j['description'], now, fit, why))



def fetch_description(j):
    """Fill in a missing job description on demand (SmartRecruiters / Workday / community rows)."""
    if j.get('description') and len(j['description']) > 400:
        return j['description']
    url = j.get('url') or ''
    try:
        m = re.search(r'jobs\.smartrecruiters\.com/([^/]+)/(\d+)', url)
        if m:
            d = get(f'https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings/{m.group(2)}')
            secs = (d.get('jobAd') or {}).get('sections') or {}
            text = '\n'.join(strip_html((secs.get(k) or {}).get('text', '')) for k in
                             ('companyDescription', 'jobDescription', 'qualifications', 'additionalInformation'))
        elif 'myworkdayjobs.com' in url:
            m = re.match(r'https://([^/]+)/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)(/job/.+)', url)
            host, site, ext = m.groups()
            tenant = host.split('.')[0]
            d = get(f'https://{host}/wday/cxs/{tenant}/{site}{ext}')
            text = strip_html((d.get('jobPostingInfo') or {}).get('jobDescription', ''))
        else:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read().decode('utf-8', 'replace')
            m = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.){200,})"', raw)  # JSON-LD JobPosting
            text = strip_html(json.loads('"' + m.group(1) + '"')) if m else strip_html(raw)[:12000]
    except Exception:
        return j.get('description') or ''
    if text:
        store.execute('update jobs set description=? where id=?', (text, j['id']))
    return text
