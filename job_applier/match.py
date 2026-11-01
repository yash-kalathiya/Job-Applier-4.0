"""Fit score 0-100: how well a posting matches the user's profile and search preferences.

Fast and explainable on purpose (it runs on tens of thousands of postings per scan). The resume-vs-JD
keyword match lives in ats.py and runs only on jobs you actually look at.
"""
import re
import time

INTERN = re.compile(r'\b(intern|interns|internship|extern|externship|practicum|trainee|traineeship|co-?op|summer (?:analyst|associate|scholar|fellow)|'
                    r'student|apprentice|apprenticeship|'
                    r'fellow(?:ship)?|insight (?:day|days|week|program|series)|discovery (?:day|days|program|week)|sophomore|freshman|first[- ]year|'
                    r'early (?:career|talent) program)\b', re.I)
NEWGRAD = re.compile(r'\b(new grad|graduate|entry[- ]level|university grad|early career|junior|associate|analyst)\b', re.I)
SENIOR = re.compile(r'\b(senior|sr\.?|staff|principal|lead|manager|director|head of|vp|architect|distinguished|fellow engineer)\b', re.I)
US = re.compile(r'\b(united states|usa|u\.s\.|remote|[A-Z][a-z]+,? (?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|'
                r'LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b|'
                r'new york|san francisco|seattle|boston|chicago|austin|los angeles|atlanta|denver|'
                r'mountain view|palo alto|sunnyvale|menlo park|cambridge|pittsburgh|philadelphia|miami)', re.I)
NO_SPONSOR = re.compile(r'(will not|won\'t|unable to|does not|not able to) (?:provide |offer )?sponsor|'
                        r'must be (?:a )?u\.?s\.? citizen|security clearance (?:is )?required|requires? (?:an? )?(?:active )?clearance|'
                        r'citizenship is required|does not offer sponsorship', re.I)
CITIZEN = re.compile(r'u\.?s\.? citizen(?:ship)? (?:is )?required|must be (?:a )?u\.?s\.? citizen|citizenship is required|'
                     r'(?:active|secret|ts/sci) (?:security )?clearance', re.I)
CANADA = re.compile(r'\b(canada|toronto|vancouver|montreal|ottawa|calgary|waterloo|ontario|quebec|british columbia|alberta)\b|,\s*(ON|BC|QC|AB|MB|NS)\b(?!\w)', re.I)
MONTHS = 'jan feb mar apr may jun jul aug sep oct nov dec'.split()

STATES = ('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC '
          'SD TN TX UT VT VA WA WV WI WY DC PR').split()
US_STATE = re.compile(r"[A-Za-z][A-Za-z .'-]*,\s*(" + '|'.join(STATES) + r")\b(?!\s*,\s*(?!US\b|USA\b)[A-Z]{2}\b)")   # case-sensitive
US_WORDS = re.compile(r'\b(united states|usa|u\.s\.a?\.?|us only|us-based|us remote|remote,? us\b|remote - us\b)', re.I)
FOREIGN = re.compile(r'\b(india|bengaluru|bangalore|hyderabad|pune|mumbai|delhi|gurgaon|gurugram|noida|chennai|israel|tel aviv|haifa|'
                     r'united kingdom|\buk\b|england|london|manchester|edinburgh|ireland|dublin|germany|berlin|munich|frankfurt|'
                     r'france|paris|netherlands|amsterdam|spain|madrid|barcelona|italy|milan|switzerland|zurich|geneva|poland|'
                     r'warsaw|krakow|romania|bucharest|portugal|lisbon|sweden|stockholm|denmark|copenhagen|singapore|japan|tokyo|'
                     r'china|beijing|shanghai|shenzhen|hong kong|taiwan|taipei|korea|seoul|australia|sydney|melbourne|'
                     r'brazil|s[aã]o paulo|mexico|mexico city|argentina|buenos aires|colombia|bogot[aá]|philippines|manila|'
                     r'vietnam|indonesia|jakarta|uae|dubai|emea|apac|latam)\b', re.I)


def place(loc):
    """'us', 'foreign' or 'unknown' for a location string. Every option counts: 'New York, NY or Toronto, ON' is US."""
    if not loc or re.fullmatch(r'\s*\d+\s+locations?\s*', loc, re.I):
        return 'unknown'
    kinds = set()
    for p in re.split(r';|\||\s/\s|\bor\b|\band\b|\n', loc):
        p = p.strip(' ,-')
        if not p:
            continue
        if re.search(r',\s*(ON|BC|QC|AB|MB|NS|NB|NL|PE|SK)\b(\s*,\s*(CA|CAN|Canada))?\s*$', p) and not US_WORDS.search(p):
            kinds.add('foreign')   # a Canadian province ("Toronto, ON, CA": that CA is Canada, not California)
            continue
        if US_WORDS.search(p) or (US_STATE.search(p) and not FOREIGN.search(p)) or (US.search(p) and not FOREIGN.search(p)
                                                                                   and not CANADA.search(p) and not re.fullmatch(r'remote', p, re.I)):
            kinds.add('us')
        elif FOREIGN.search(p) or (CANADA.search(p) and not US_STATE.search(p)) or re.search(r',\s*[A-Z]{2}\s*$', p) and not US_STATE.search(p):
            kinds.add('foreign')
        else:
            kinds.add('unknown')
    return 'us' if 'us' in kinds else ('unknown' if 'unknown' in kinds or not kinds else 'foreign')

ROLE_SYNONYMS = {
    'software engineer': ['software', 'swe', 'sde', 'developer', 'backend', 'back-end', 'frontend', 'front-end', 'full stack',
                          'full-stack', 'mobile', 'ios', 'android', 'platform engineer', 'infrastructure', 'devops', 'site reliability',
                          'web', 'cloud', 'programmer'],
    'machine learning': ['machine learning', 'ml', 'ai', 'deep learning', 'llm', 'applied scientist', 'research engineer',
                         'computer vision', 'nlp', 'perception'],
    'data science': ['data scien', 'data analy', 'analytics', 'data engineer', 'business intelligence'],
    'quant': ['quant', 'trader', 'quantitative', 'strats', 'algorithmic', 'trading intern', 'trading analyst', 'trading engineer', 'trading developer'],
    'hardware': ['hardware', 'electrical', 'embedded', 'firmware', 'fpga', 'asic', 'silicon', 'circuit', 'rf'],
    'robotics': ['robot', 'autonom', 'controls', 'mechatronic', 'perception', 'guidance', 'gnc'],
    'product': ['product manag', 'product design', 'technical program', 'tpm'],
    'finance': ['investment bank', 'finance', 'financial', 'private equity', 'asset management', 'wealth', 'equity research', 'summer analyst',
                'global markets', 'capital markets', 'sales & trading', 'sales and trading', 'm&a', 'mergers', 'leveraged finance', 'restructuring',
                'treasury', 'fp&a', 'credit', 'fixed income', 'investment', 'portfolio', 'banking', 'private credit', 'venture', 'underwriting'],
    'investment banking': ['investment bank', 'm&a', 'mergers', 'capital markets', 'leveraged finance', 'restructuring', 'coverage', 'ibd',
                           'summer analyst', 'corporate finance', 'advisory'],
    'accounting': ['accounting', 'accountant', 'audit', 'assurance', 'tax', 'cpa', 'controller', 'financial reporting', 'sox'],
    'sales and trading': ['sales & trading', 'sales and trading', 'global markets', 'trading', 'trader', 'markets', 'fixed income', 'equities'],
    'actuarial': ['actuar', 'underwriting', 'insurance', 'risk analyst', 'claims'],
    'real estate': ['real estate', 'property', 'reit', 'development', 'acquisitions'],
    'security': ['security', 'cyber', 'offensive', 'appsec'],
    'design': ['design', 'ux', 'ui', 'graphic', 'visual', 'creative', 'illustrat', 'motion'],
    'marketing': ['marketing', 'brand', 'social media', 'content', 'growth', 'communications', 'pr ', 'public relations', 'seo'],
    'sales': ['sales', 'business development', 'account', 'partnerships'],
    'consulting': ['consult', 'strategy', 'advisory'],
    'operations': ['operations', 'supply chain', 'logistics', 'procurement', 'project manag', 'program'],
    'healthcare': ['health', 'clinical', 'nurs', 'medical', 'patient', 'pharm', 'public health', 'hospital'],
    'research': ['research', 'lab', 'scientist', 'analyst'],
    'policy': ['policy', 'government', 'public affairs', 'legislat', 'advocacy', 'nonprofit', 'non-profit'],
    'education': ['teach', 'tutor', 'education', 'curriculum', 'instruct'],
    'writing': ['writ', 'editor', 'journalis', 'copy', 'reporter'],
    'legal': ['legal', 'law', 'paralegal', 'compliance'],
    'hr': ['human resources', 'people ops', 'recruit', 'talent'],
    'mechanical': ['mechanical', 'manufactur', 'aerospace', 'civil', 'structural', 'chemical', 'industrial'],
    'civil': ['civil', 'structural', 'transportation', 'geotech', 'construction', 'water resources', 'infrastructure'],
    'architecture': ['architect', 'interior design', 'urban design', 'landscape', 'urban planning', 'planner'],
    'environmental': ['environment', 'sustainab', 'climate', 'energy', 'ecolog', 'conservation', 'renewable', 'esg'],
    'biology': ['biolog', 'biotech', 'life science', 'molecular', 'genetic', 'microbio', 'immunolog', 'neuroscien', 'cell', 'lab'],
    'chemistry': ['chemist', 'chemical', 'formulation', 'analytical', 'materials scien'],
    'pharma': ['pharm', 'clinical research', 'regulatory', 'drug', 'medical affairs', 'clinical trial'],
    'public health': ['public health', 'epidemiolog', 'health policy', 'global health', 'community health'],
    'psychology': ['psycholog', 'behavioral', 'mental health', 'counsel', 'social work', 'therap'],
    'economics': ['econom', 'policy analy', 'research analyst', 'pricing'],
    'statistics': ['statistic', 'biostatistic', 'actuar', 'data analy', 'quantitative analy'],
    'journalism': ['journalis', 'reporter', 'editorial', 'newsroom', 'editor', 'producer', 'broadcast'],
    'media': ['media', 'film', 'video', 'production', 'entertainment', 'studio', 'podcast', 'broadcast', 'animation', 'music'],
    'communications': ['communications', 'public relations', 'pr ', 'corporate affairs', 'internal comms', 'media relations'],
    'supply chain': ['supply chain', 'logistics', 'procurement', 'sourcing', 'planning', 'inventory', 'distribution'],
    'hospitality': ['hospitality', 'hotel', 'event', 'guest', 'culinary', 'tourism', 'restaurant'],
    'retail': ['retail', 'merchandis', 'buyer', 'store', 'e-commerce', 'ecommerce', 'category'],
    'fashion': ['fashion', 'apparel', 'merchandis', 'textile', 'styling'],
    'sports': ['sport', 'athletic', 'fitness', 'coaching'],
    'government': ['government', 'public sector', 'federal', 'municipal', 'legislat', 'congress', 'civic', 'public service'],
    'nonprofit': ['nonprofit', 'non-profit', 'foundation', 'philanthrop', 'fundrais', 'development', 'ngo', 'community'],
    'cybersecurity': ['security', 'cyber', 'soc ', 'threat', 'grc', 'penetration', 'infosec'],
    'aerospace': ['aerospace', 'aircraft', 'propulsion', 'flight', 'avionics', 'space', 'satellite'],
    'agriculture': ['agricultur', 'agronom', 'food science', 'crop', 'animal science', 'farm'],
}


# ------------------------------------------------------------------ company names
# Boards spell one company many ways: "🔥 Tesla", "Tesla, Inc.", "JPMorganChase", "JPMorgan Chase & Co.", "jpmc".
# Every comparison (skip list, dream companies, per-company cap) goes through company_key, so they all agree.
LEGAL = {'inc', 'incorporated', 'llc', 'ltd', 'limited', 'corp', 'corporation', 'co', 'company', 'plc', 'lp', 'llp', 'gmbh', 'ag', 'sa', 'the'}
ALIASES = {
    'jpmorganchase': 'jpmorgan', 'jpmorganchaseco': 'jpmorgan', 'jpmc': 'jpmorgan', 'jpmorganchasebank': 'jpmorgan', 'chase': 'jpmorgan',
    'jpmorgan': 'jpmorgan', 'bofa': 'bankofamerica', 'bofasecurities': 'bankofamerica', 'bankofamericamerrill': 'bankofamerica',
    'gs': 'goldmansachs', 'goldman': 'goldmansachs', 'ms': 'morganstanley', 'facebook': 'meta', 'metaplatforms': 'meta',
    'alphabet': 'google', 'googlellc': 'google', 'aws': 'amazon', 'amazonwebservices': 'amazon', 'teslamotors': 'tesla',
    'microntechnology': 'micron', 'citigroup': 'citi', 'citibank': 'citi', 'wellsfargobank': 'wellsfargo', 'pwcus': 'pwc',
    'pricewaterhousecoopers': 'pwc', 'ernstyoung': 'ey', 'deloittetoucheusa': 'deloitte', 'bcg': 'bostonconsultinggroup',
}


def company_words(name):
    words = re.findall(r'[a-z0-9]+', (name or '').lower().replace('&', ' '))
    while words and words[-1] in LEGAL:
        words.pop()
    while words and words[0] == 'the':
        words.pop(0)
    return words


def company_key(name):
    collapsed = ''.join(company_words(name))
    return ALIASES.get(collapsed, collapsed)


def same_company(a, b):
    """True when two spellings name the same company, or one is the other plus more words ('Tesla' / 'Tesla Energy')."""
    ka, kb = company_key(a), company_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    wa, wb = ' '.join(company_words(a)), ' '.join(company_words(b))
    return wb.startswith(wa + ' ') or wa.startswith(wb + ' ')


def role_terms(role):
    """Search terms for any role a user types, known or not. Unknown roles match on word stems, so 'marine biology'
    finds 'Marine Biologist' and 'environmental science' finds 'Environmental Sciences Intern'."""
    r = role.lower().strip()
    if r in ROLE_SYNONYMS:
        return ROLE_SYNONYMS[r], []
    # the same role in other words: "software engineering", "software engineers", "Software Developer" -> software engineer
    def base(x):
        while True:
            y = re.sub(r'(ing|ers|er|s)$', '', x)
            if y == x:
                return x
            x = y
    for k in ROLE_SYNONYMS:
        if base(k) == base(r) or (r in ROLE_SYNONYMS[k] and len(r) > 4) or \
                re.fullmatch(re.escape(k) + r' (engineer|engineering|intern|internship|role|scientist|developer)s?', r):
            return ROLE_SYNONYMS[k] + [r], []
    words = [w for w in re.findall(r'[a-z0-9+#&]+', r) if w not in ('and', 'of', 'the', 'for', 'in')]
    stems = [w if len(w) <= 4 else w[:max(4, len(w) - 3)] for w in words]
    return [r], stems


def role_hit(role, title, desc=''):
    syns, stems = role_terms(role)
    # short synonyms need a whole word ("ai" is not "Aircraft", "ml" is not "html")
    if any(re.search(r'\b' + re.escape(x) + (r'\b' if len(x) <= 3 else ''), title) for x in syns):
        return True
    if stems and all(re.search(r'\b' + re.escape(x), title) for x in stems):
        return True
    # part of it in the title and the whole phrase in the posting (a 'Marine Intern' that's about marine biology)
    return bool(stems) and any(re.search(r'\b' + re.escape(x), title) for x in stems) and role.lower() in desc[:2000].lower()


def _grad_ok(text, year, month):
    """Look for 'graduating between X and Y' style windows; return (ok, note) or (None, '')."""
    if not year:
        return None, ''
    try:
        y = int(year)
    except ValueError:
        return None, ''
    m_idx = MONTHS.index(month[:3].lower()) if month and month[:3].lower() in MONTHS else 4
    me = y * 12 + m_idx
    pat = re.compile(r'(?:graduat\w*|degree|completion)[^.\n]{0,60}?(?:(%s)[a-z]*\.?,? )?(20\d\d)[^.\n]{0,25}?'
                     r'(?:and|to|through|-|–|or)\s*(?:(%s)[a-z]*\.?,? )?(20\d\d)' % ('|'.join(MONTHS), '|'.join(MONTHS)), re.I)
    m = pat.search(text)
    if m:
        a = int(m.group(2)) * 12 + (MONTHS.index(m.group(1)[:3].lower()) if m.group(1) else 0)
        b = int(m.group(4)) * 12 + (MONTHS.index(m.group(3)[:3].lower()) if m.group(3) else 11)
        return a <= me <= b, f'grad window {m.group(2)}-{m.group(4)}'
    m = re.search(r'graduat\w*[^.\n]{0,40}?(?:by|before|no later than|prior to)\s+(?:(%s)[a-z]*\.?,? )?(20\d\d)'
                  % '|'.join(MONTHS), text, re.I)
    if m:
        b = int(m.group(2)) * 12 + (MONTHS.index(m.group(1)[:3].lower()) if m.group(1) else 11)
        return me <= b + 3, f'grad by {m.group(2)}'
    return None, ''


ONLY = re.compile(r'((?:\b[A-Z][\w&.\-]*\s+){1,4}?)(?:students?|candidates?)\s+only')
GENERIC_ONLY = re.compile(r'^(current|undergraduate|undergrad|graduate|college|university|enrolled|us|u\.s\.|international|'
                          r'domestic|eligible|qualified|female|women|black|hispanic|latinx?|first[- ]generation|\s)+$', re.I)


def fit(job, prof, vault_terms=None):
    """vault_terms: set of LEXICON terms the user's vault contains (makes the score personal)."""
    s = prof.get('search', {})
    title = job.get('title', '')
    t = title.lower()
    text = f"{title}\n{job.get('description', '')}"
    why, score = [], 32.0
    only = ONLY.search(title)
    who = only.group(1).strip(' -,(') if only else ''
    if only and not GENERIC_ONLY.match(who) and (prof.get('school') or '').lower()[:6] not in who.lower():
        return 0, f'restricted to {who} students'
    company = job.get('company') or ''
    if any(same_company(c, company) for c in s.get('companies_skip', [])):
        return 0, 'company on skip list'
    # graduate-only programs ("Intern, MS, Software Engineering", "PhD Intern") for an undergrad
    undergrad = not re.search(r'master|mba|ph\.?d|doctor|graduate', f"{prof.get('degree', '')} {prof.get('class_standing', '')}", re.I)
    if undergrad and re.search(r"\b(M\.?S\.?|Masters?|Master's|Ph\.?D\.?|MBA)\b(?!\s*(Excel|Office|Word|Teams))", title) and \
            not re.search(r"\b(B\.?S\.?|B\.?A\.?|Bachelor'?s?|undergrad\w*)\b", title, re.I):
        return 0, 'graduate students only'
    intern_title = bool(re.search(r'\b(intern|internship|co-?op)\b', t))
    for x in s.get('exclude', []):
        x = (x or '').lower().strip()
        if not x:
            continue
        if x in ('master', 'masters') and not re.search(r"\bmaster'?s?\b(?! ?card)", t):
            continue   # "Mastercard" is not a master's program
        if x in ('manager', 'senior', 'staff', 'principal') and intern_title:
            continue   # "Product Manager Intern", "Staff Accountant Intern" are internships
        if re.search(r'\b%s' % re.escape(x), t):
            return 0, 'excluded keyword in title'
    kind = s.get('kind') or 'internship'
    if kind == 'co-op':   # co-ops are internships for matching; the term picks which ones
        kind = 'internship'
    if kind == 'internship':
        if not INTERN.search(title):
            return 0, 'not an internship'
        if SENIOR.search(title) and not re.search(r'\bintern', title, re.I):
            return 0, 'senior role'
        score += 10
    elif kind == 'new-grad':
        program = re.search(r'early career|new grad|graduate (program|trainee|scheme)|rotational|fellowship program', t)
        if re.search(r'\b(intern|internship|co-?op)\b', t) or (SENIOR.search(title) and not program):
            return 0, 'not new-grad level'
        score += 10 if NEWGRAD.search(title) else 0
    elif SENIOR.search(title) and not s.get('allow_senior'):
        score -= 25
    roles = s.get('roles') or []
    hit = []
    for r in roles:
        if role_hit(r, t, job.get('description') or ''):
            hit.append(r)
    if roles and not hit:
        return 0, 'role does not match'
    if hit:
        score += 18
        why.append('role: ' + ', '.join(hit))
    if vault_terms and job.get('description'):
        from . import ats
        want = [t for t, w, n in ats.keywords(job['description']) if t not in ats.SOFT]
        if want:
            have = sum(1 for t in want if t in vault_terms)
            frac = have / len(want)
            score += round(22 * frac)
            if frac >= .5:
                why.append(f'{have}/{len(want)} of its skills')
        else:
            score += 11
    elif vault_terms:
        score += 11  # no description yet: neutral
    if any(x and x.lower() in t for x in s.get('include', [])):
        score += 10
        why.append('include keyword')
    season = (s.get('season') or '').lower()   # one or more terms, e.g. "Summer 2027, Fall 2027"
    if not season and (s.get('kind') or 'internship') == 'internship':   # no cycle chosen: this recruiting cycle (co-ops run all year)
        from .store import next_summer
        season = f'summer {next_summer()}'
    want_years = set(re.findall(r'20\d\d', season))
    from .store import next_summer
    cycle = next_summer()
    if want_years and max(int(y) for y in want_years) < cycle:   # a cycle saved last year: roll it forward instead of rejecting everything
        shift = cycle - max(int(y) for y in want_years)
        want_years = {str(int(y) + shift) for y in want_years}
    if want_years:
        years = set(re.findall(r'20\d\d', title))
        if not years and job.get('source') == 'community':
            years = set(re.findall(r'20\d\d', job.get('description', '')[:80]))
        if years and not years & want_years:
            return 0, f'wrong cycle ({", ".join(sorted(years))})'
        if years & want_years:
            score += 8
            why.append(', '.join(sorted(years & want_years)))
    # a title that names a different term (a Spring or January co-op when you're after Summer) isn't your cycle
    norm = lambda x: 'fall' if x == 'autumn' else x
    want_terms = {norm(x) for x in re.findall(r'summer|spring|fall|autumn|winter', season)}
    if want_terms and kind == 'internship' and not s.get('any_term'):
        terms = {norm(x) for x in re.findall(r'\b(summer|spring|fall|autumn|winter)\b', t)} | (
            {'winter'} if re.search(r'\b(jan(uary)?|feb(ruary)?)\b\.? ?20\d\d|\(jan', t) else set())
        if terms and not terms & want_terms:
            return 0, f"{'/'.join(sorted(terms))} term, you want {'/'.join(sorted(want_terms))}"
    arr = set(s.get('arrangement') or [])   # on-site / hybrid / remote
    if arr == {'remote'} and not re.search(r'remote|anywhere|distributed', f"{job.get('location', '')} {title}", re.I):
        return 0, 'not remote'
    if re.search(r'\bhigh[- ]school\b', title, re.I) and prof.get('school'):
        return 0, 'high school program'
    es = re.search(r'20\d\d', prof.get('earliest_start') or '')
    if es and int(es.group()) > time.gmtime().tm_year and re.search(r'\b(immediate(ly)? start|start(ing)? immediately|asap)\b', title, re.I):
        return 0, 'immediate start, before your earliest start'
    locs = [l.lower() for l in s.get('locations', [])]
    loc = job.get('location') or ''
    if locs and loc:
        if any(l in ('united states', 'us', 'usa') for l in locs):
            if place(loc) == 'foreign' and not any(l in loc.lower() for l in locs if l not in ('united states', 'us', 'usa')):
                return 0, 'outside target locations'
        elif not any(l in loc.lower() for l in locs):
            score -= 20
    ok, note = _grad_ok(text, prof.get('grad_year'), prof.get('grad_month'))
    if ok is False:
        return 5, note + ' (you are outside it)'
    if ok:
        score += 10
        why.append(note)
    if prof.get('needs_sponsorship') and NO_SPONSOR.search(text):
        return 3, 'no sponsorship / citizenship required'
    cit = (prof.get('citizenship') or '').lower()
    us_citizen = re.match(r'\s*(u\.?s\.?|us|united states|american)\b.*citizen|^\s*citizen', cit) and not re.search(r'\bnot\b|non-?citizen', cit)
    if cit and not us_citizen and CITIZEN.search(text):
        return 3, 'US citizenship or clearance required'
    m = re.match(r'(20\d\d)-(\d\d)-(\d\d)', job.get('posted') or '')
    if m:
        import datetime
        age = (datetime.date.today() - datetime.date(*map(int, m.groups()))).days
        if age > 120:
            score -= 25
            why.append('old posting')
        elif age > 60:
            score -= 10
        elif age <= 3:
            score += 6
            why.append('posted in the last 3 days')
    if any(same_company(c, company) for c in s.get('companies_priority', [])):
        score += 15
        why.append('priority company')
    return max(1, min(100, round(score))), '; '.join(why)
