"""Per-job resume tailoring from the Career Vault.

The vault (resume.json) holds EVERYTHING the user has done: more roles, projects and bullets than fit on a page,
with as many alternate phrasings per bullet as they like. Tailoring = pick the strongest, most relevant subset,
order it for this posting, mirror the posting's vocabulary only where the vault already proves it, fit one page.

Three ways to tailor, same output:
  heuristic  no AI at all: ranks entries/bullets by posting keyword overlap        (always available)
  agent      Claude Code / Codex writes the plan from prompt()                     (best quality, uses your plan)
  api        an LLM writes the plan: the user's own Claude Code / Codex subscription, or an API key if one is set

The fact guard rejects any rewrite that adds numbers, names, links or skills that are not in the vault.
"""
import copy
import json
import os
import re

from . import ats

GUIDE = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', 'RESUME_GUIDE.md'), encoding='utf-8').read() \
    if os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', 'RESUME_GUIDE.md')) else ''
ENTRY_SECS = ('experience', 'projects', 'leadership', 'volunteering')


def slug(s):
    return re.sub(r'[^a-z0-9]+', '', (s or '').lower())[:14] or 'x'


def ensure_ids(v):
    """Give every entry a stable id so plans can reference it ('acme', 'acme.0' = first bullet)."""
    used = set()
    for sec in ENTRY_SECS + ('research',):
        for e in v.get(sec, []):
            if not e.get('id'):
                base = slug(e.get('org') or e.get('name') or e.get('title'))
                i, n = base, 2
                while i in used:
                    i, n = f'{base}{n}', n + 1
                e['id'] = i
            used.add(e['id'])
    return v


def words(s):
    return set(re.findall(r'[A-Za-z][A-Za-z0-9+#.\-]*[A-Za-z0-9+#]|[A-Za-z]', s))


def nums(s):
    return set(re.findall(r'\d+(?:[.,]\d+)?', s))


def vault_text(v):
    return json.dumps(v, ensure_ascii=False)


MAGNITUDE = re.compile(r'\b(thousand|million|billion|trillion|\d+[kmb]\b|\d+x\b|percent)', re.I)


IRREGULAR_PAST = set('''ran led built won wrote made grew taught drove began held found took gave cut set sold spent brought bought
chose drew flew fought kept lost met paid rode rose saw sent shot spoke stood struck thought threw understood wore became
broke dealt fed felt hit hung knew laid left lent let meant put read sought shut sat slept split spread stuck swept told
withdrew undertook oversaw overcame upheld'''.split())


def _forms(w):
    """Inflections of a verb, to recognise 'Ship' as 'shipped' or 'Build' as 'built' in the vault."""
    irregular = {'build': ['built'], 'lead': ['led'], 'run': ['ran'], 'write': ['wrote', 'written'], 'win': ['won'],
                 'make': ['made'], 'drive': ['drove'], 'teach': ['taught'], 'grow': ['grew'], 'find': ['found'],
                 'take': ['took'], 'give': ['gave'], 'hold': ['held'], 'cut': ['cut'], 'set': ['set'], 'begin': ['began']}
    out = {w + 'ed', w + 'd', w + 's', w + 'es', w + 'ing', w + w[-1:] + 'ed', w + w[-1:] + 'ing', w[:-1] + 'ied',
           w[:-1] + 'ing', w[:-1] + 'ed'} | set(irregular.get(w, []))
    return out


def check_rewrite(orig, new, vault_txt, jd, entry_txt=None):
    """Return None if the rewrite is truthful, else the reason it was rejected.
    entry_txt = all text of the same role/project: new numbers and tools must come from THAT entry."""
    o, n = ats.plain(orig), ats.plain(new)
    scope = ats.plain(entry_txt or orig)
    if len(n) < 25:
        return 'too short'
    if len(n) > max(240, len(o) + 40):   # length is about fitting two lines, not truth: facts are checked below
        return 'longer than two lines'
    extra_nums = nums(n) - nums(scope)
    if extra_nums:
        return 'adds numbers not in this entry: ' + ', '.join(sorted(extra_nums))
    # a number keeps its meaning: "40K events/sec" can't become "40K users"
    for num, unit in re.findall(r'(\d[\d,.]*\+?(?:\s*[kKmMbB%](?![A-Za-z]))?)\s*\+?\s*([A-Za-z][a-z]{2,})', n):
        key = re.escape(num.strip()) + r'\s*\+?\s*'
        if unit.lower() in ('to', 'and', 'the', 'of', 'in', 'on', 'at', 'per', 'for', 'by', 'from', 'with'):
            continue
        before = re.search(r'([A-Za-z][\w.+#-]*)\s+' + re.escape(num.strip()), n)
        if before and re.search(re.escape(before.group(1)) + r'\s+' + re.escape(num.strip()), scope):
            continue   # a version or a name with a number ("Ubuntu 24.04", "Python 3.12"), same as in the original
        if not re.search(key + r'(?:[A-Za-z-]+\s+){0,2}' + re.escape(unit[:5]), scope, re.I) and \
                not re.search(re.escape(unit[:5]) + r'[a-z]*\s+(?:of\s+)?' + re.escape(num.strip()), scope, re.I):
            return f'uses {num.strip()} for {unit}, but in this entry it counts something else'
    mags = {x.lower() for x in MAGNITUDE.findall(n)} - {x.lower() for x in MAGNITUDE.findall(scope)}
    if mags:
        return 'adds a scale claim not in this entry: ' + ', '.join(sorted(mags))
    for term, pat in ats.PATTERNS.items():
        if term not in ats.SOFT and pat.search(n) and not pat.search(scope):
            return f'claims {term}, which this entry never mentions'
    vw = words(vault_txt)
    stems = {w[:6].lower() for w in vw if len(w) >= 6}
    vlow = {w.lower() for w in vw}
    caps = {w for w in words(n) - vw if w[0].isupper() and w.lower() not in vlow and w.lower() not in ats.ACTION_VERBS}
    caps = {w for w in caps if not (len(w) >= 6 and w[:6].lower() in stems)}
    # a capitalized verb that starts a bullet ("Ship", "Lead") is the same word as "shipped"/"leading" in the vault,
    # and an acronym already inside a vault word ("OS" in macOS/iOS) is not a new name
    first = (re.findall(r'[A-Za-z][\w-]*', n) or [''])[0]
    caps = {w for w in caps if not (w == first and re.search(r'(ed|ied)$', w.lower()))}   # "Converted ...": a verb, not a name
    caps = {w for w in caps if not any(f in vlow for f in _forms(w.lower())) and w.lower() not in IRREGULAR_PAST
            and not (w.isupper() and any(x.endswith(w) and x != w for x in vw))
            and not ('-' in w and w.split('-')[0].lower() in vlow)}
    if caps:
        return 'adds names/tools not in your vault: ' + ', '.join(sorted(caps))
    jdw = {w.lower() for w in words(jd)}
    stuffed = {w for w in {x.lower() for x in words(n)} - vlow if w in jdw and not (len(w) >= 6 and w[:6] in stems)}
    stuffed -= ats.ACTION_VERBS | {'and', 'the', 'for', 'with', 'to', 'of', 'in', 'on', 'a', 'an', 'by', 'via', 'using', 'across'}
    if len(stuffed) > 1:
        return 'stuffs posting keywords the vault does not back: ' + ', '.join(sorted(stuffed))
    for link in re.findall(r'\]\(([^)]+)\)', orig):
        if link not in new:
            return 'dropped a link'
    if re.search('[–—]', n) and not re.search('[–—]', o):
        return 'adds dashes'
    return None


# ---------------------------------------------------------------- heuristic tailor (no AI)

IMPACT = re.compile(r'\b(1st|2nd|3rd|first place|second place|winner|won|finalist|champion|gold|top \d+%?|1 of \d+|'
                    r'published|first author|patent|acquired|funded|raised|record|co-?founder|founded|founding|'
                    r'\d[\d,.]*\+?\s*(?:k\s*)?(?:users|customers|downloads|members|students|teams))\b', re.I)
# bullets a recruiter skips: no scope, no result, chores. Never kept when the same entry has a stronger true one unused.
WEAK = re.compile(r'^\W*(help(ed|s|ing)?|assist(ed|s|ing)?|attend(ed|s)?|participat(ed|es)|complet(ed|es) (training|onboarding)|'
                  r'responsible for|worked on|did|cleaned|created some|made some|was part of|took part|shadow(ed|s)|learn(ed|s|ing)|'
                  r'maintain(ed|s)? (shop|lab|the)|answer(ed|s) (customer )?questions|present(ed|s) (my |our |a |the )?final|'
                  r'organiz(ed|es) (events|socials)|supported (vehicle )?teardowns|gained|exposed to|familiariz)\b'
                  r'|\b(ITAR|safety|compliance|onboarding|orientation) training\b|\bintern (events?|socials?)\b|'
                  r'\bagile ceremonies\b|\bad[- ]hoc requests\b', re.I)


def weak(b):
    """Filler a recruiter skips: a chore or vague verb, or a short line with no number ('Graded homework.', 'Made the slides.')."""
    t = ats.plain(b)
    return bool(WEAK.search(t) or (len(t) < 48 and not re.search(r'\d', t)) or
                re.match(r'^\W*(grad(ed|es|ing)|read papers|sold|ran (philanthropy|events?)|made the)\b', t, re.I))


def strength(b, kws=()):
    """How hard a bullet works on the page: a measured result and the posting's words count, filler and chores don't."""
    t = ats.plain(b)
    return ((3 if re.search(r'\d', t) else 0) + (2 if IMPACT.search(t) else 0) + min(len(t), 160) / 80
            + (_kw_score(t, kws) if kws else 0) - (6 if weak(t) else 0))


def _upgrade(bl, src, avoid, kws, least=1):
    """Swap each weak bullet for the entry's strongest unused one (a real, unchosen vault bullet), never adding length."""
    used = set(bl)
    spare = sorted((b for i, b in enumerate(src.get('bullets', [])) if b not in used and f"{src['id']}.{i}" not in avoid
                    and not weak(b) and not any(_closest([b], x)[1] > 0.5 for x in bl)),
                   key=lambda b: -strength(b, kws))
    out = []
    for b in bl:
        t = ats.plain(b)
        if spare and weak(t) and strength(spare[0], kws) > strength(b, kws):
            out.append(spare.pop(0))
        elif spare and not re.search(r'\d', t) and re.search(r'\d', ats.plain(spare[0])) and strength(spare[0], kws) >= strength(b, kws) + 3:
            out.append(spare.pop(0))   # the entry's measured result beats an unmeasured line
        else:
            out.append(b)
    keep = [b for b in out if not (weak(b) and not re.search(r'\d', ats.plain(b)))]   # measured lines stay
    return keep if len(keep) >= least else out


OLD = re.compile(r'\b(high school|middle school|secondary school)\b', re.I)  # or set "high_school": true on a vault entry


def _kw_score(text, kws):
    s = 0.0
    for term, w, _ in kws:
        if ats.PATTERNS[term].search(text):
            s += w
    return s


def heuristic_plan(v, jd, max_bullets=None, title='', ctx=None):
    v = ensure_ids(copy.deepcopy(v))
    ctx = ctx or {}
    pins, avoid, wins = set(ctx.get('pins', [])), set(ctx.get('avoid', [])), set(ctx.get('winning_bullets', []))
    kws = ats.keywords(jd)
    max_bullets = max_bullets or {'experience': 3, 'projects': 2, 'leadership': 1, 'volunteering': 1}
    plan = {"order": [], "bullets": {}, "skills": [], "headline": v.get('basics', {}).get('headline', [])}
    from .match import ROLE_SYNONYMS
    head = (title or jd[:160]).lower()
    want = [r for r, syn in ROLE_SYNONYMS.items() if any(re.search(r'\b' + re.escape(x), head) for x in syn)]

    def role_fit(text):
        t = text.lower()
        if not want:
            return 0
        if any(re.search(r'\b' + re.escape(x), t) for r in want for x in ROLE_SYNONYMS[r]):
            return 2.0
        return -1.0 if any(re.search(r'\b' + re.escape(x), t) for r, syn in ROLE_SYNONYMS.items() if r not in want for x in syn) else 0
    sec_rel = {}
    for sec in ENTRY_SECS:
        ranked, items = [], v.get(sec, [])
        texts = [ats.plain(' '.join([e.get('title', ''), e.get('org', ''), e.get('name', ''), e.get('tagline', ''),
                                     ' '.join(e.get('tech', []))] + e.get('bullets', []))) for e in items]
        kw_max = max([_kw_score(t, kws) for t in texts] + [1])
        for idx, e in enumerate(items):
            raw = ' '.join([e.get('tagline', '')] + e.get('bullets', []))
            # relevance to this posting (0-6) + impact a recruiter sees (0-3) + recency (vault order is newest first, 0-2)
            impact = min(3.0, 0.4 * raw.count('**') / 2 + 1.5 * len(IMPACT.findall(raw)) + 0.15 * len(nums(raw)))
            rel = (6 * _kw_score(texts[idx], kws) / kw_max + impact + 2 * (1 - idx / max(1, len(items)))
                   + role_fit(' '.join([e.get('title', ''), e.get('org', ''), e.get('name', '')] + e.get('bullets', []))))
            if e.get('high_school') or OLD.search(texts[idx]):
                rel -= 2.5
            if e['id'] in avoid:
                continue
            if e['id'] in pins:
                rel += 100  # the user said: always include this
            rel += 1.5 * sum(b in wins for b in e.get('bullets', []))
            bl = sorted(range(len(e.get('bullets', []))), key=lambda i: -(_kw_score(ats.plain(e['bullets'][i]), kws)
                                                                             + (0.6 if re.search(r'\d', e['bullets'][i]) else 0)
                                                                             + 0.3 * e['bullets'][i].count('**') / 2
                                                                             + (2 if e['bullets'][i] in wins else 0)
                                                                             + (100 if f"{e['id']}.{i}" in pins else 0)
                                                                             - (100 if f"{e['id']}.{i}" in avoid else 0)
                                                                             - i * 0.25))
            ranked.append((rel, e['id'], bl[:max_bullets.get(sec, 2)]))
        ranked.sort(key=lambda x: -x[0])
        keep = ranked[:{'experience': 6, 'projects': 4, 'leadership': 3, 'volunteering': 2}[sec]]
        plan[sec] = [{"id": i, "bullets": [f'{i}.{b}' for b in sorted(bl)]} for _, i, bl in keep]
        sec_rel[sec] = sum(r for r, _, _ in keep[:3])
    lines = []
    for s in v.get('skills', []):
        items = sorted(s.get('items', []), key=lambda it: -_kw_score(it, kws))
        lines.append({"label": s.get('label'), "items": items[:16], "rel": _kw_score(' '.join(items), kws)})
    lines.sort(key=lambda s: -s['rel'])
    keep = [l for l in lines if l['rel'] > 0][:5] or lines[:3]
    if len(keep) < 3:
        keep += [l for l in lines if l not in keep][:3 - len(keep)]
    for l in keep:
        l.pop('rel')
    plan['skills'] = keep
    field_order = (ctx.get('rules') or {}).get('order')
    base = [s for s in (field_order or v.get('order') or []) if s != 'education']
    base += [s for s in (v.get('order') or []) if s not in base and s != 'education']
    if sec_rel.get('projects', 0) > sec_rel.get('experience', 0) * 1.3 and 'projects' in base and 'experience' in base:
        base.remove('projects')
        base.insert(base.index('experience'), 'projects')
    plan['order'] = ['education'] + base
    plan['notes'] = f"{ctx.get('field', 'general')} resume: " + (ctx.get('rules') or {}).get('emphasize', '')
    return plan


# ---------------------------------------------------------------- agent / LLM tailor

def prompt(v, job, jd, ctx=None):
    v = ensure_ids(copy.deepcopy(v))
    ctx = ctx or {}
    rules = ctx.get('rules') or {}
    you = ''
    if ctx.get('notes'):
        you += 'THE CANDIDATE TOLD US (always follow):\n' + '\n'.join('- ' + n for n in ctx['notes']) + '\n'
    if ctx.get('pins'):
        you += 'ALWAYS INCLUDE these entries/bullets: ' + ', '.join(ctx['pins']) + '\n'
    if ctx.get('avoid'):
        you += 'NEVER INCLUDE: ' + ', '.join(ctx['avoid']) + '\n'
    if ctx.get('winning_bullets'):
        you += 'BULLETS THAT GOT THIS CANDIDATE INTERVIEWS BEFORE (prefer them when relevant):\n' + '\n'.join('- ' + b for b in ctx['winning_bullets'][:8]) + '\n'
    return f"""You are an elite recruiter and resume writer for the {ctx.get('field', 'general')} field. Make this candidate read as the obvious
hire for THIS specific posting, on ONE page, using ONLY facts in their Career Vault. The vault holds more than fits; your job
is to choose and to frame.

FIRST, POSITION (think it through before writing anything):
1. What does this hiring manager screen for, in order? Name the top 3 requirements from the posting.
2. What one-line story makes this candidate the obvious fit for exactly this role? (e.g. "a quant researcher who ships
   production ML systems", "a robotics engineer who has run real hardware end to end").
3. Which 2-3 entries prove that story best, and which single bullet proves requirement #1?
THEN BUILD THE PAGE AROUND IT so a recruiter skimming for 6 seconds sees those three things in the top third:
- The first entry in the first section, and its first bullet, prove requirement #1.
- Headline tags lead with the identity this role wants (choose and reorder from the vault's headline list).
- Frame every bullet in this role's language without changing a fact: the same work reads as latency and systems for a
  quant/infra role, as perception and models for an ML role, as hardware and validation for a robotics role.
- Skills: the line and the items this role cares about come first.

RULES (hard):
- Never invent: no new numbers, employers, tools, skills, titles, dates, awards or links. A fact guard rejects violations.
- REWRITE every bullet you keep into its strongest truthful form for THIS posting: lead with the result, mirror the
  posting's exact terms where the bullet already proves them, cut filler, keep every fact. Keep **bold** on the 1-3
  most impressive facts per entry. No em/en dashes. No first person.
- Each bullet: past-tense action verb first (present tense for current roles), 80-200 characters, ideally a number.
- Fill one page with the strongest material: usually 4-6 entries and 14-18 bullets. 2-4 bullets per relevant role, 1-2 per
  project or leadership entry; drop entries that do not help this posting.
- Every entry you keep shows its single most impressive measured result (the bullet with the biggest number, scale or
  outcome), even if its wording is less on-topic: reframe it for this role rather than dropping it.
- Never spend a line on filler ("helped with", "attended", "participated in", trainings, ad-hoc requests, intern events,
  generic duties) when the vault has a stronger true bullet for that entry or a stronger entry left out.
- No fact twice: an honor in education is not repeated in awards, a placement in a bullet is not repeated in awards.
- No orphan section: a section with one entry and one short bullet either earns a second bullet or gives way to a
  stronger entry.
- A rewrite never adds a purpose, audience, scope, tool or outcome the vault does not state ("to feed the production
  model", "for the growth team", "before production runs", "validated" for "reduced data"). Reframe with the vault's own
  facts; if the honest version is less on-topic, keep it honest.
- Refer to bullets by the exact ids shown in the vault ("drift.0"). A number keeps its meaning ("40K events/sec" never
  becomes "40K users").
- Order sections for this reader. Ideal order for this field: {', '.join(rules.get('order', []))}.
- What hiring managers in this field look for first: {rules.get('emphasize', 'the posting requirements and measurable results')}.
{you}

OUTPUT: only a JSON object:
{{"headline": [2-4 short identity tags for THIS role: the vault's headline tags, or new ones built only from words in the vault
                ("Avionics Hardware", "Recommender Systems"); the role's identity first],
  "order": ["education", "experience", "projects", ...],
  "experience": [{{"id": "<entry id>", "bullets": ["<id>.<n>" or {{"from": "<id>.<n>", "text": "<reworded bullet>"}}]}}],
  "projects": [same shape], "leadership": [same shape],
  "research": ["<research id>", ...], "awards": [<indexes>],
  "skills": [{{"label": "...", "items": [subset/reorder of that label's items]}}],
  "positioning": "the one-line story from step 2",
  "requirements": ["requirement 1", "requirement 2", "requirement 3"],
  "notes": "one line on the strategy"}}

RESUME WRITING GUIDE (follow it):
{GUIDE[:6000]}

POSTING: {job.get('title', '')} at {job.get('company', '')} ({job.get('location', '')})
{jd[:9000]}

CAREER VAULT (entry ids are the "id" fields; every bullet is shown with its exact id, like "drift.0": use those ids as given.
"posting_fit" on each entry and "fit" on each bullet measure how much of THIS posting's vocabulary they share: start from the
high ones, lead with them, and give a low one page space only when it is the candidate's best proof of something the posting
needs. Retail, food service and unrelated part-time jobs go only if nothing stronger is left):
{_vault_for_prompt(v, jd=jd)}
"""


def agent_llm(text, timeout=600, fast=False):
    """Run one prompt on the user's own Claude Code or Codex subscription (no API key). Returns the reply text or None.
    fast: a short checking job, so Claude uses its quickest model."""
    import subprocess
    import tempfile
    from . import agents, store
    for name in agents.preferred(store.profile()):
        try:
            if name == 'claude':
                # a one-shot plan doesn't need the biggest model; Sonnet is several times faster for this
                r = subprocess.run([agents.exe('claude'), '-p', '--model', 'haiku' if fast else (os.environ.get('JOB_APPLIER_PLAN_MODEL') or os.environ.get('APPLYTWIN_PLAN_MODEL', 'sonnet')), '--output-format', 'text', '--tools', ''], input=text, capture_output=True,
                                   text=True, encoding='utf-8', errors='replace', timeout=timeout, cwd=store.HOME, **store.NOWIN)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout
                _llm_log('claude', r)
            else:
                for _ in range(8):   # each refused model is remembered, so this walk happens once per machine
                    with tempfile.NamedTemporaryFile('r', suffix='.txt', delete=False) as f:
                        out = f.name
                    cmd = [agents.exe('codex'), 'exec', '--skip-git-repo-check', '--ephemeral', '-s', 'read-only', '-o', out,
                           *agents.codex_model_args(), '-']
                    r = subprocess.run(cmd, input=text, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, cwd=store.HOME, **store.NOWIN)
                    reply = open(out, encoding='utf-8').read() if os.path.exists(out) else ''
                    if os.path.exists(out):
                        os.unlink(out)
                    if reply.strip():
                        return reply
                    _llm_log('codex', r)
                    if 'model_not_found' not in r.stdout + r.stderr or not agents.reject_model(r.stdout + r.stderr):
                        break   # anything but "that model isn't on your plan" won't be fixed by retrying; that one moves to the next model
        except Exception:
            continue
    return None


def _llm_log(name, r):
    """Why a call to the user's agent came back empty, for 'why did my resume use the built-in writer?'."""
    try:
        from . import store
        with open(store.path('llm.log'), 'a', encoding='utf-8') as f:
            f.write(f"{__import__('time').strftime('%Y-%m-%d %H:%M:%S')} {name} rc={r.returncode} {(r.stderr or r.stdout or '')[-600:]!r}\n")
    except Exception:
        pass


def call_llm(text, timeout=600, fast=False):
    key = os.environ.get('ANTHROPIC_API_KEY')
    import urllib.request
    if key:
        body = {"model": os.environ.get('JOB_APPLIER_MODEL') or os.environ.get('APPLYTWIN_MODEL', 'claude-sonnet-5-5'), "max_tokens": 6000,
                "messages": [{"role": "user", "content": text}]}
        req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=json.dumps(body).encode(),
                                     headers={'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.load(r)['content'][0]['text']
    elif os.environ.get('OPENAI_API_KEY'):
        body = {"model": os.environ.get('JOB_APPLIER_OPENAI_MODEL') or os.environ.get('APPLYTWIN_OPENAI_MODEL', 'gpt-5'), "messages": [{"role": "user", "content": text}]}
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=json.dumps(body).encode(),
                                     headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY'], 'content-type': 'application/json'})
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.load(r)['choices'][0]['message']['content']
    else:
        out = agent_llm(text, timeout=timeout, fast=fast)
        if not out:
            return None
    return _first_json(out)


def _first_json(out):
    """The first JSON object in a model's reply, even with prose or code fences around it."""
    dec = json.JSONDecoder()
    for m in re.finditer(r'\{', out or ''):
        try:
            obj, _ = dec.raw_decode(out[m.start():])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- apply a plan

def _with_bullet_ids(v):
    """The vault as the model sees it: each bullet labeled with its id, so nobody has to count (counting from 1 instead of 0
    once shifted every bullet on a resume)."""
    out = {k: v[k] for k in v if k != 'titles'}
    for sec in ENTRY_SECS:
        out[sec] = [{**e, 'bullets': [{'id': f"{e['id']}.{i}", 'text': b} for i, b in enumerate(e.get('bullets', []))]}
                    for e in v.get(sec, [])]
    return out


_COMMON = set("""a an and are as at be by for from has have in is it its of on or our that the this to we will with you your
    who what when where which while their they them using use used work working team teams role roles intern interns internship
    experience skills ability strong including include such other into about across more than also must able well new
    help helps support responsible responsibilities requirements qualifications preferred minimum summer 2026 2027 2028
    students student candidates candidate applicants year years please equal opportunity""".split())


def _jd_words(jd):
    """The posting's own vocabulary, weighted by how often it uses each word (generic and HR words left out)."""
    from collections import Counter
    c = Counter(w for w in re.findall(r'[a-z][a-z0-9+#./-]{2,}', (jd or '').lower()) if w not in _COMMON)
    return {w: min(n, 4) for w, n in c.items()}


def relevance(text, kws, jdw):
    """How directly a line speaks to this posting: its skill terms plus the posting's own words it shares."""
    t = ats.plain(text)
    return _kw_score(t, kws) + 0.35 * sum(jdw.get(w, 0) for w in set(re.findall(r'[a-z][a-z0-9+#./-]{2,}', t.lower())))


def _annotate_fit(full, jd):
    """Mark every entry and bullet 'high'/'medium'/'low' for this posting, so the model starts from what the posting asks for
    (it still decides: a hint, not a rule)."""
    kws, jdw = ats.keywords(jd), _jd_words(jd)
    ents = [(e, relevance(json.dumps(e, ensure_ascii=False), kws, jdw)) for sec in ENTRY_SECS for e in full.get(sec, [])]
    if not ents:
        return
    ranked = sorted(s for _, s in ents)
    lo, hi = ranked[len(ranked) // 3], ranked[(2 * len(ranked)) // 3]
    for e, s in ents:
        e['posting_fit'] = 'high' if s >= hi and s > 0 else 'low' if s <= lo else 'medium'
        bs = [relevance(b['text'], kws, jdw) for b in e.get('bullets', [])]
        top = max(bs, default=0)
        for b, s2 in zip(e.get('bullets', []), bs):
            b['fit'] = (e['posting_fit'] if len(bs) == 1 else
                        'high' if top and s2 >= 0.7 * top else 'low' if s2 <= 0.3 * top else 'medium')


def _vault_for_prompt(v, limit=40000, jd=''):
    """The vault as JSON, short sections (skills, awards, education) first so nothing important is cut off, and alternate
    phrasings dropped before any real content if it's too long."""
    full = _with_bullet_ids(v)
    if jd:
        _annotate_fit(full, jd)
    first = ['basics', 'skills', 'awards', 'education', 'research', 'certifications']
    ordered = {k: full[k] for k in first if k in full}
    ordered.update({k: full[k] for k in full if k not in ordered})
    out = json.dumps(ordered, ensure_ascii=False)
    if len(out) > limit:
        for sec in ENTRY_SECS:
            for e in ordered.get(sec, []):
                e.pop('alts', None)
        out = json.dumps(ordered, ensure_ascii=False)
    return out[:limit]


def _words(s):
    return set(re.findall(r'[a-z0-9]+', (s or '').lower()))


def _closest(bullets, text):
    """Index of the vault bullet a rewrite came from, by shared words (ids can be off by one; the words can't)."""
    w = _words(text)
    best, score = None, 0.0
    for i, b in enumerate(bullets):
        bw = _words(b)
        s = len(w & bw) / (len(w | bw) or 1)
        if s > score:
            best, score = i, s
    return best, score


def apply(v, plan, jd=''):
    """Vault + plan -> concrete resume dict, plus a report of accepted/rejected rewrites."""
    v = ensure_ids(copy.deepcopy(v))
    if isinstance(plan, dict) and len(plan) == 1 and isinstance(next(iter(plan.values())), dict):
        plan = next(iter(plan.values()))   # {"plan": {...}} from a chatty model
    plan = plan if isinstance(plan, dict) else {}
    vt = vault_text(v)
    out = {"basics": copy.deepcopy(v.get('basics', {})), "titles": v.get('titles', {})}
    rep = {"rewrites": [], "rejected": [], "notes": plan.get('notes', ''), "positioning": plan.get('positioning', ''),
           "requirements": plan.get('requirements', [])}
    avoid = set(learn_avoid(v))
    kws = ats.keywords(jd) if jd else []
    head = v.get('basics', {}).get('headline', [])
    if plan.get('headline'):
        vw = _words(vt)
        ok = [h for h in plan['headline'] if isinstance(h, str) and (h in head or (
            len(h) <= 40 and _words(h) and all(w in vw or w in ('and', 'engineering', 'engineer') for w in _words(h))))]
        out['basics']['headline'] = ok[:4] or head
    out['education'] = v.get('education', [])
    # a plan that numbers bullets from 1 never uses .0 and points one past the end somewhere: shift it back
    refs = [r for sec in ENTRY_SECS for c in (plan.get(sec) or []) if isinstance(c, dict) for r in (c.get('bullets') or [])]
    nums = [(m.group(1), int(m.group(2))) for r in refs
            for m in [re.match(r'(.+)\.(\d+)$', str(r.get('from') if isinstance(r, dict) else r))] if m]
    allb = {e['id']: len(e.get('bullets', [])) for sec in ENTRY_SECS for e in v.get(sec, [])}
    one_based = bool(nums) and all(n >= 1 for _, n in nums) and any(n == allb.get(i, -1) for i, n in nums)
    for sec in ENTRY_SECS:
        byid = {e['id']: e for e in v.get(sec, [])}
        chosen = plan.get(sec)
        if chosen is None:
            out[sec] = v.get(sec, [])
            continue
        lst = []
        for c in chosen:
            cid = c['id'] if isinstance(c, dict) else c
            e = byid.get(cid)
            if not e:
                continue
            e2 = {k: e[k] for k in e if k != 'bullets'}
            bl, used = [], set()
            for ref in (c.get('bullets') if isinstance(c, dict) and c.get('bullets') is not None else
                        [f'{cid}.{i}' for i in range(len(e.get('bullets', [])))]):
                src_id, text = (ref.get('from'), ref.get('text')) if isinstance(ref, dict) else (ref, None)
                m = re.match(r'(.+)\.(\d+)$', str(src_id or ''))
                owner = e   # a bullet only ever appears under its own role/project, whatever id the plan wrote
                obl = owner.get('bullets', [])
                if not obl:
                    continue
                k = (int(m.group(2)) - (1 if one_based else 0)) if m else -1
                if text:   # a rewrite: find the bullet it came from by its words
                    near, score = _closest(obl, text)
                    if near is not None and (not 0 <= k < len(obl) or score > len(_words(text) & _words(obl[k])) / (len(_words(text) | _words(obl[k])) or 1)):
                        k = near
                if m and m.group(1) != e['id'] and not text:
                    continue   # a bare reference to another entry's bullet: skip it rather than mislabel
                if not 0 <= k < len(obl):
                    continue
                orig = obl[k]
                if f"{e['id']}.{k}" in avoid:
                    continue   # the user said never to use this one
                src_id = f"{owner['id']}.{k}"
                if text and text.strip() != orig:
                    src = owner
                    etxt = ' '.join([src.get('title', ''), src.get('org', ''), src.get('name', ''), src.get('tagline', ''),
                                     ' '.join(src.get('tech', []))] + src.get('bullets', []) + src.get('alts', []))
                    why = check_rewrite(orig, text, vt, jd, etxt)
                    if why:
                        rep['rejected'].append({"bullet": src_id, "reason": why, "text": text})
                        text = None
                    else:
                        rep['rewrites'].append({"bullet": src_id, "from": orig, "to": text})
                if (text or orig) not in bl and k not in used:
                    bl.append(text or orig)
                    used.add(k)
            # never ship a thin entry: roles keep at least 2 bullets and projects/leadership at least 1 when the vault has
            # them (the renderer trims to one page afterwards, so this never overflows)
            # a section of one entry with one line reads as an afterthought: that entry gets a second line too
            least = 2 if sec == 'experience' or len(chosen) == 1 else 1
            for bi, b in enumerate(e.get('bullets', [])):
                if len(bl) >= least:
                    break
                if f"{e['id']}.{bi}" in avoid or bi in used or weak(b):
                    continue
                if b not in bl and not any(_closest([b], x)[1] > 0.5 for x in bl):
                    bl.append(b)
            e2['bullets'] = _one_per_fact(_upgrade(bl, e, avoid, kws, least))
            e2['_used'] = sorted(used | {i for i, b in enumerate(e.get('bullets', [])) if b in e2['bullets']})
            lst.append(e2)
        out[sec] = lst
    rid = {p.get('id'): p for p in v.get('research', [])}
    out['research'] = [rid[i] for i in plan.get('research', []) if i in rid] if 'research' in plan else v.get('research', [])
    aw = v.get('awards', [])
    out['awards'] = _pick_awards(aw, plan['awards']) if 'awards' in plan else aw
    out['awards'] = _not_repeated(out['awards'], out)
    if len(out['awards']) == 1 and out['education'] and isinstance(out['awards'][0], str):
        # one award doesn't need a section of its own: it reads better beside the school's honors
        out['education'] = copy.deepcopy(out['education'])
        out['education'][0]['honors'] = list(out['education'][0].get('honors') or []) + out['awards']
        out['awards'] = []
    out['certifications'] = v.get('certifications', [])
    out['skills'] = _pick_skills(v.get('skills', []), plan.get('skills'))
    # every section the plan selected is shown, education leads, and experience is newest first
    order = [s for s in (plan.get('order') or v.get('order') or []) if out.get(s)]
    order += [s for s in (v.get('order') or []) if s not in order and out.get(s) and s not in ('research', 'awards')]
    order += [s for s in ('research', 'awards') if s not in order and out.get(s) and s in plan]
    if 'education' in order and order[0] != 'education':
        order.remove('education')
        order.insert(0, 'education')
    tail = [s for s in ('skills', 'certifications', 'awards') if s in order]
    order = [s for s in order if s not in tail] + tail   # what you did leads; lists of skills and honors close the page
    out['order'] = order
    for sec in ('experience', 'leadership', 'volunteering'):
        if out.get(sec):
            out[sec] = sorted(out[sec], key=_recency, reverse=True)
    return out, rep


AUDIT = """You check resume rewrites for honesty. Each item has the candidate's ORIGINAL bullet (the truth) and a NEW version.
Flag a NEW version if it claims anything the ORIGINAL does not support, even slightly:
- more ownership ("ran" or "led" an A/B test the original only "analyzed"; "managed" what was "maintained"; "built" what was "helped build")
- a purpose, audience, scope, outcome or causal link that is not stated ("to support due diligence", "driving a 1.8% lift" for "showed a 1.8% lift")
- a dropped qualifier that changes the claim ("top 3 of 17" without "in the New England region"; "estimated" savings stated as real)
- a number attached to a different thing, or a different kind of test/equipment ("shaker rig" for "rig")
Rewording, reordering, mirroring the posting's vocabulary for the SAME fact, and cutting words are fine.
Reply with ONLY JSON: {"overclaims": [{"id": "<item id>", "why": "<short reason>"}]}

ITEMS:
"""


def audit(res, rep):
    """A second, quick read of every rewrite against its original: any that claims more than the vault says goes back to
    the user's own words (the fact checker catches new numbers and names, not a quietly upgraded verb or a dropped qualifier)."""
    items = [{"id": str(i), "original": r['from'], "new": r['to']} for i, r in enumerate(rep['rewrites'])]
    try:
        out = call_llm(AUDIT + json.dumps(items, ensure_ascii=False), timeout=90, fast=True)
    except Exception:
        out = None
    flagged = {str(x.get('id')): x.get('why', '') for x in (out or {}).get('overclaims', []) if isinstance(x, dict)}
    if not flagged:
        return 0
    keep = []
    for i, r in enumerate(rep['rewrites']):
        if str(i) not in flagged:
            keep.append(r)
            continue
        for sec in ENTRY_SECS:
            for e in res.get(sec, []):
                e['bullets'] = [r['from'] if b == r['to'] else b for b in e.get('bullets', [])]
        rep['rejected'].append({"bullet": r['bullet'], "reason": 'overclaims: ' + flagged[str(i)], "text": r['to']})
    rep['rewrites'] = keep
    return len(flagged)


def trim_worth(res, kws, jd):
    """What to keep when the page runs long: measured results, the posting's own words, and the order the plan chose within
    each entry (keyword overlap alone threw out 'Merged 5 PRs into kubectl' and kept 'Reviewed PRs and triaged issues')."""
    jdw = _jd_words(jd)
    rank = {}
    for sec in ENTRY_SECS:
        for e in res.get(sec, []):
            for i, b in enumerate(e.get('bullets', [])):
                rank.setdefault(b, i)
    return lambda b: strength(b, kws) + 0.35 * sum(jdw.get(w, 0) for w in set(re.findall(r'[a-z][a-z0-9+#./-]{2,}', ats.plain(b).lower()))) - 1.0 * rank.get(b, 0)


def _same_fact(a, b):
    """Two lines stating one fact: most words shared, or the same distinctive figure ('6x', '1e-12', '4B+') with real overlap."""
    wa, wb = _words(ats.plain(a)), _words(ats.plain(b))
    j = len(wa & wb) / (len(wa | wb) or 1)
    figs = lambda t: {m for m in re.findall(r'\d[\d.,]*\s*(?:x|%|[kmb]\+?|e-?\d+)\b', ats.plain(t).lower())}
    return j > 0.55 or (j > 0.25 and bool(figs(a) & figs(b)))


def _one_per_fact(bl):
    out = []
    for b in bl:
        if not any(_same_fact(b, x) for x in out):
            out.append(b)
    return out


def _fill_page(v, res, jd, style, probe, k=1.0):
    """A two-thirds-empty page reads as thin. While there's clear room, add the user's next strongest true bullets for
    this posting (from the same roles first, then roles/projects the plan left out), never past one page."""
    from . import render
    v = ensure_ids(copy.deepcopy(v))
    kws = ats.keywords(jd)
    avoid = set(learn_avoid(v))
    shown = {e.get('id') for sec in ENTRY_SECS for e in res.get(sec, [])}
    pick = trim_worth({}, kws, jd)   # the same measure trimming uses: results and the posting's words, not keywords alone
    cands = []
    for sec in ('experience', 'projects', 'leadership'):
        byid = {e['id']: e for e in v.get(sec, [])}
        for e in res.get(sec, []):
            src = byid.get(e.get('id'))
            for i, b in enumerate((src or {}).get('bullets', [])):
                if (f"{src['id']}.{i}" in avoid or i in e.get('_used', []) or weak(b)
                        or any(_closest([b], x)[1] > 0.45 or _same_fact(b, x) for x in e.get('bullets', []))):
                    continue
                cands.append((pick(b), 'bullet', sec, e.get('id'), b))
        for e in v.get(sec, []):
            if e['id'] not in shown and e.get('bullets') and not OLD.search(json.dumps(e)):
                cands.append((max(pick(b) for b in e['bullets']) - 1, 'entry', sec, e['id'], e))
    shown_skills = {s.get('label') for s in res.get('skills', [])}
    for s in v.get('skills', []):   # a skills line trimmed to fit is one short line: often exactly what a gap needs
        if s.get('label') not in shown_skills and s.get('items'):
            cands.append((_kw_score(ats.plain(' '.join(s['items'])), kws) + 1, 'skills', 'skills', s.get('label'), s))
    cands.sort(key=lambda c: -c[0])
    best, rest = cands[:8], sorted(cands[8:], key=lambda c: len(json.dumps(c[4])))   # strongest first, then the shortest
    added, misses = [], 0
    for score, kind, sec, eid, x in best + rest[:10]:
        if misses >= 6:   # six in a row didn't fit: the page is full
            break
        if kind == 'skills':
            res.setdefault('skills', []).append(x)
            undo = lambda: res['skills'].pop()
        elif kind == 'bullet':
            tgt = next(e for e in res[sec] if e.get('id') == eid)
            tgt['bullets'].append(x)
            undo = lambda: tgt['bullets'].pop()
            src_b = next((e for e in v[sec] if e['id'] == eid), {}).get('bullets', [])
            tgt.setdefault('_used', []).extend(j for j, b in enumerate(src_b) if b == x)
        else:
            e2 = {k: x[k] for k in x if k != 'bullets'}
            e2['bullets'] = [b for b in x['bullets'] if not weak(b)][:2] or x['bullets'][:1]
            res.setdefault(sec, []).append(e2)
            if sec not in res.get('order', []):
                res.setdefault('order', []).append(sec)
            undo = lambda: res[sec].pop()
        if not render.fits(res, style, k, probe):
            undo()
            misses += 1
            continue   # too big for the space left: try the next, smaller candidate
        misses = 0
        added.append(f"{sec}: {ats.plain(x if isinstance(x, str) else x.get('org') or x.get('name') or x.get('label', ''))[:60]}")
    return added


MONTHS = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}


def _when(s):
    """'November 2025' -> 2025.83; 'Present' -> far future; unknown -> None."""
    s = (s or '').strip().lower()
    if not s:
        return None
    if re.search(r'present|current|now|ongoing', s):
        return 9999.0
    y = re.search(r'(19|20)\d\d', s)
    if not y:
        return None
    mo = next((v for k, v in MONTHS.items() if k in s), 6)
    return int(y.group(0)) + mo / 12


def _recency(e):
    """Sort key: current roles first, then by end date (resumes read newest first)."""
    dates = e.get('dates') or ' '.join(str(e.get(k, '')) for k in ('start', 'end'))
    parts = re.split(r'\s*[–—-]\s*|\s+to\s+', str(dates)) if dates else []
    end = _when(e.get('end')) or (_when(parts[-1]) if parts else None)
    start = _when(e.get('start')) or (_when(parts[0]) if parts else None)
    when = end or start or 0
    # anything current or finished in the last year is "recent": among those the plan's relevance order stands (sorted() is
    # stable), so this summer's internship isn't pushed under an older part-time role that happens to still be ongoing
    import time
    now = time.localtime()
    return 9999.0 if when >= now.tm_year + now.tm_mon / 12 - 1 else when


def _not_repeated(awards, res):
    """An award already stated under education or in a bullet only takes a line twice."""
    seen = json.dumps([res.get('education', [])] + [[e.get(k) for k in ('org', 'name', 'title', 'tagline')] + e.get('bullets', [])
                                                     for sec in ENTRY_SECS for e in res.get(sec, [])], ensure_ascii=False)
    sw = _words(seen)
    keep = []
    for a in awards:
        w = _words(a if isinstance(a, str) else ' '.join(str(x) for x in a.values() if isinstance(x, str)))
        if len(w) >= 3 and len(w & sw) / len(w) >= 0.75:
            continue
        keep.append(a)
    return keep


def _pick_awards(aw, picks):
    texts = [a if isinstance(a, str) else json.dumps(a) for a in aw]
    ints = [p for p in picks if isinstance(p, int)]
    shift = 1 if ints and min(ints) >= 1 and max(ints) == len(aw) else 0   # counted from 1
    out = []
    for p in picks:
        if isinstance(p, int) and 0 <= p - shift < len(aw):
            a = aw[p - shift]
        elif isinstance(p, str):
            i, score = _closest(texts, p)
            a = aw[i] if i is not None and score > 0.4 else None
        else:
            a = None
        if a is not None and a not in out:
            out.append(a)
    return out or aw


def _pick_skills(vault_skills, picks):
    """Keep the plan's order and emphasis, but only real items, matched to the user's labels loosely ('Programming
    Languages' is 'Languages'), and never drop most of what the user knows."""
    if not picks:
        return vault_skills
    norm = lambda x: re.sub(r'[^a-z0-9+#]', '', (x or '').lower())
    allitems = {norm(i): i for s in vault_skills for i in s.get('items', [])}
    out, used = [], set()
    for s in picks:
        if not isinstance(s, dict):
            continue
        items = [allitems[norm(i)] for i in s.get('items', []) if norm(i) in allitems and norm(i) not in used]
        lab = next((vs['label'] for vs in vault_skills if norm(vs.get('label')) == norm(s.get('label'))), None) or \
            next((vs['label'] for vs in vault_skills if items and items[0] in vs.get('items', [])), s.get('label'))
        if items:
            used.update(norm(i) for i in items)
            out.append({"label": lab, "items": items})
    if sum(len(s['items']) for s in out) < 0.35 * len(allitems):   # a lost line, not a choice: add back the rest
        for vs in vault_skills:
            rest = [i for i in vs.get('items', []) if norm(i) not in used]
            if not rest:
                continue
            tgt = next((o for o in out if o['label'] == vs.get('label')), None)
            if tgt:
                tgt['items'] += rest
            else:
                out.append({"label": vs.get('label'), "items": rest})
            used.update(norm(i) for i in rest)
    return out or vault_skills


def learn_avoid(v):
    try:
        from . import learn
        return learn.context_for({}).get('avoid', [])
    except Exception:
        return []


def tailor(v, job, jd, mode='auto', plan=None, style=None, out_dir=None):
    """Full pipeline -> {pdf, pages, ats before/after, rewrites}."""
    from . import learn, render, store
    ctx = learn.context_for(job)
    style = style or ctx['template']
    if plan is None:
        if mode in ('auto', 'api'):
            import time
            t0 = time.time()
            for _ in range(2):   # a busy or rate-limited agent often answers on the second try; the built-in writer is a big step down
                left = 330 - (time.time() - t0)   # never leave someone waiting: past this, the built-in writer takes over
                if left < 90:
                    break
                try:
                    plan = call_llm(prompt(v, job, jd, ctx), timeout=min(200, left))   # a full plan takes Sonnet ~2 min
                except Exception:
                    plan = None
                if plan:
                    break
        if plan is None:
            plan = heuristic_plan(v, jd, title=job.get('title', ''), ctx=ctx)
            mode = 'heuristic'
        else:
            mode = 'api'
    else:
        mode = 'agent'
    res, rep = apply(v, plan, jd)
    if mode == 'api' and rep['rejected']:   # one revision: show the model exactly what the fact checker refused, and why
        fix = (prompt(v, job, jd, ctx) + '\n\nYOUR PREVIOUS PLAN:\n' + json.dumps(plan, ensure_ascii=False)[:12000] +
               '\n\nTHE FACT CHECKER REJECTED THESE REWRITES (bullet, reason, your text):\n' +
               '\n'.join(f"- {r['bullet']}: {r['reason']}: {r['text']}" for r in rep['rejected']) +
               '\n\nReturn the same JSON plan with each rejected rewrite fixed: keep its facts exactly as the vault states them '
               '(no new numbers, tools or claims), or use the bullet id as-is. Change nothing else.')
        try:
            plan2 = call_llm(fix, timeout=120)
            if plan2:
                res2, rep2 = apply(v, plan2, jd)
                if len(rep2['rejected']) < len(rep['rejected']):
                    plan, res, rep = plan2, res2, rep2
        except Exception:
            pass
    if mode == 'api' and rep['rewrites']:
        audit(res, rep)
    out_dir = out_dir or store.path('resumes', job.get('id', 'general'))
    name = (re.sub(r'[^\w]+', '_', res['basics'].get('name', 'Resume') or '', flags=re.UNICODE).strip('_') or 'Resume') + '_Resume.pdf'
    pdf = os.path.join(out_dir, name)
    kws = ats.keywords(jd)
    worth = trim_worth(res, kws, jd)
    r = render.render(res, style, pdf, worth=worth)
    if r['pages'] == 1 and style != 'latex':   # room left on the page (also after trimming a big item): fill it with real material
        base = r['resume'] if r['dropped'] else res
        added = _fill_page(v, base, jd, style, pdf + '.probe.pdf', k=r['scale'])
        if added:
            rep['added'] = added
            res = base
            r = render.render(res, style, pdf, worth=worth)
        if r['pages'] == 1 and r['scale'] < 1 and not r['dropped']:
            # the content is final: set the type as large as one page allows, so the page ends full instead of short
            k2 = next((k for k in (1.0, .99, .98, .97, .96) if k > r['scale'] and render.fits(res, style, k, pdf + '.probe.pdf')), None)
            if k2:
                render.fits(res, style, k2, pdf)
                r['scale'] = k2
        for f in (pdf + '.probe.pdf',):
            if os.path.exists(f):
                os.remove(f)
    from . import latex
    with open(pdf[:-4] + '.tex', 'w', encoding='utf-8') as f:  # every tailored resume also ships as editable LaTeX
        f.write(latex.build_tex(res))
    txt = render.pdf_text(pdf)
    before = ats.report(v, jd)
    after = ats.report(res, jd, r['pages'], txt)
    r.pop('resume', None)
    json.dump({"plan": plan, "resume": res, "report": rep, "render": r, "mode": mode, "style": style, "field": ctx['field']},
              open(os.path.join(out_dir, 'tailor.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    return {"pdf": pdf, "tex": pdf[:-4] + '.tex', "pages": r['pages'], "dropped": r['dropped'], "mode": mode, "style": style,
            "coverage_vault": before.get('coverage'), "coverage": after.get('coverage'), "score": after['score'],
            "missing": [m['term'] for m in after.get('missing', []) if m['hard']][:12],
            "rewrites": len(rep["rewrites"]), "rejected": rep["rejected"], "notes": rep["notes"], "field": ctx["field"], "added": rep.get("added", []),
            "positioning": rep.get("positioning", ''), "requirements": rep.get("requirements", [])}
