"""Application-question answer bank.

Every application asks the same ~40 questions in different words. The bank stores one truthful answer per
question type; match() maps any wording to the right answer with a confidence. Below the threshold the agent
must ask the user (and save the answer so it never asks twice).
"""
import re

STOP = set('a an the of to for in on and or is are you your do does did be been have has with at by as this that '
           'will would can could please any if from our we us it its which what when where who how'.split())


def _yn(b):
    """True/False -> Yes/No; None (never answered) -> '' so the twin asks instead of guessing."""
    return '' if b is None else ('Yes' if b else 'No')


YEARS = ['Freshman', 'Sophomore', 'Junior', 'Senior']


def standing(p):
    # (now, during a summer internship): a sophomore today is a rising junior next summer
    now = (p.get('class_standing') or '').strip().title()
    if now in YEARS:
        i = YEARS.index(now)
        return now, ('Rising ' + YEARS[i + 1]) if i < 3 else 'Senior'
    return now, ''


def default_bank(p):
    s = p.get('eeo', {})
    grad = f"{p.get('grad_month', '')} {p.get('grad_year', '')}".strip()
    rows = [
        ('work_auth', 'Are you legally authorized to work in the United States?',
         r'(legally )?(authori[sz]ed|eligible|permitted) to work|work authori[sz]ation|right to work', _yn(p.get('work_authorized_us'))),
        ('sponsorship', 'Will you now or in the future require visa sponsorship?',
         r'sponsor|h-?1b|visa status|immigration (support|assistance)', _yn(p.get('needs_sponsorship'))),
        ('citizenship', 'What is your citizenship status?', r'citizen(ship)?\b(?! of)|u\.?s\.? person|green card|permanent resident',
         p.get('citizenship') or ''),
        ('relocate', 'Are you willing to relocate?', r'relocat', _yn(p.get('willing_to_relocate'))),
        ('onsite', 'Are you able to work on-site / hybrid at this location?', r'on-?site|in[- ]office|in person|hybrid|commut',
         _yn(p.get('onsite_ok'))),
        ('start', 'When can you start?', r'start date|available to start|earliest (start|date)|when can you (start|begin)',
         p.get('earliest_start', '')),
        ('grad_year', 'Graduation year', r'graduation year|class of|year of graduation|(what|which) year (will|do) you graduate', p.get('grad_year', '')),
        ('grad', 'What is your expected graduation date?', r'graduat(ion|e) (date|month)|expected graduation|when (do|will) you graduate',
         grad),
        ('standing', 'What is your current class standing / year in school?',
         r'class (standing|level|year)|(current|academic) (year|standing)|year in (school|college|university)|what year are you',
         standing(p)[0]),
        ('standing_summer', 'What will your class standing be during the internship?',
         r'rising|standing (during|at the time)|year (during|at the time of) the internship|(entering|going into) your',
         standing(p)[1]),
        ('school', 'School / university', r'(school|university|college|institution)( name)?$|which (school|university)',
         p.get('school', '')),
        ('degree', 'Degree', r'^degree|degree (type|level|pursuing)|highest (level of )?education|degree are you', p.get('degree', '')),
        ('major', 'Major / field of study', r'major|field of study|discipline|area of study|concentration', p.get('major', '')),
        ('gpa', 'GPA', r'\bgpa\b|grade point', p.get('gpa', '')),
        ('enrolled', 'Are you currently enrolled in a degree program?', r'currently (enrolled|pursuing|a student)|enrolled in',
         _yn(p.get('enrolled'))),
        ('age', 'Are you at least 18 years old?', r'18 (years|or older)|at least 18|over the age', _yn(p.get('over_18'))),
        ('background', 'Will you consent to a background check?', r'background (check|screen)|drug (test|screen)', _yn(p.get('background_check_ok'))),
        ('hear', 'How did you hear about us?', r'how did you (hear|find|learn)|source of (application|referral)|where did you (hear|find)',
         'Company careers website'),
        ('government', 'Are you a current or former government employee?',
         r'government (official|employee|entity|agency)|employee of (the |a |any )?(u\.?s\.? |federal |state )?government|public official|federal employee',
         _yn(p.get('government_employee'))),
        ('prior_employee', 'Have you previously worked for this company?',
         r'^(?!.*government)(?=.*(previously|ever|currently|before|former))(.*(employed|worked) (by|for|at)|.*former employee)', 'No'),
        ('referral', 'Were you referred by an employee?', r'\breferr(ed|al)\b|who referred', 'No'),
        ('noncompete', 'Are you subject to a non-compete or non-solicit agreement?', r'non-?compete|non-?solicit|restrictive covenant',
         _yn(p.get('has_noncompete'))),

        ('salary', 'What are your salary expectations?', r'salary|compensation (expectation|requirement)|pay (expectation|range)|desired (pay|rate)',
         p.get('salary_expectation', '')),
        ('first_name', 'First name', r'^(legal |preferred )?(first|given) name|^preferred name', (p.get('name') or '').split(' ')[0]),
        ('last_name', 'Last name', r'^(legal )?(last|family) name|^surname', (p.get('name') or '').split(' ')[-1] if ' ' in (p.get('name') or '') else ''),
        ('full_name', 'Full name', r'^(full |legal )?name$|^(your )?full (legal )?name', p.get('name', '')),
        ('linkedin', 'LinkedIn profile', r'linkedin', p.get('linkedin', '')),
        ('github', 'GitHub', r'github', p.get('github', '')),
        ('website', 'Website / portfolio', r'website|portfolio|personal (site|url)', p.get('website', '')),
        ('phone', 'Phone', r'^(phone|mobile|cell)', p.get('phone', '')),
        ('email', 'Email', r'^e-?mail', p.get('email', '')),
        # forms that split the address into fields (checked before the combined 'location' question)
        ('address2', 'Address line 2', r'address line ?2|address ?2\b|apartment|suite|\bunit\b|\bapt\b', p.get('address2', '')),
        ('address', 'Street address', r'^(home |mailing |current |street |permanent |residential )?address( line ?1| ?1)?\b(?!.*e-?mail)|^street', p.get('address', '')),
        ('city', 'City', r'^(current )?city\b(?!,? ?(and|&|/) ?state)|^town\b', (p.get('location', '') or '').split(',')[0].strip()),
        ('state', 'State / province', r'^(state|province|region)( or province| / province)?( of residence)?$', (p.get('location', '').split(',')[1].strip() if ',' in (p.get('location') or '') else '')),
        ('postal_code', 'ZIP / postal code', r'\bzip\b|postal|post code|postcode', p.get('postal_code', '')),
        ('country', 'Country', r'^(current )?country( of residence)?$|^country\b(?!.*(citizen|authori))', p.get('country', '')),
        ('location', 'Current location', r'(?<![a-z])(current )?(location|city)( of residence)?$|city,? ?(and|&|/) ?state|where are you (located|based)', p.get('location', '')),
        ('gender', 'Gender', r'\bgender\b|\bsex\b', s.get('gender', '')),
        ('race', 'Race / ethnicity', r'\brace\b|ethnic', s.get('race', '')),
        ('hispanic', 'Are you Hispanic or Latino?', r'hispanic|latin[oax]', s.get('hispanic', '')),
        ('veteran', 'Veteran status', r'veteran|military (service|status)', s.get('veteran', '')),
        ('disability', 'Disability status', r'disab', s.get('disability', '')),
        ('pronouns', 'Pronouns', r'pronoun', s.get('pronouns', '')),
        ('sms', 'Do you consent to SMS / text messages?', r'\bsms\b|text messag', _yn(p.get('sms_ok'))),
        ('ai_review', 'May AI tools help review your application?', r'automated tools|\bai\b.*(review|process)', _yn(p.get('ai_review_ok'))),
        ('arbitration', 'Do you agree to the arbitration agreement?', r'arbitrat|class[- ]action waiver|jury trial|waive', ''),
        ('privacy', 'Do you acknowledge the privacy policy / certify your answers?', r'privacy (policy|notice)|certify|acknowledge|attest|i agree',
         'Yes'),
    ]
    return [{"key": k, "question": q, "pattern": pat, "answer": a, "source": "profile"} for k, q, pat, a in rows]


def _tokens(s):
    return {w for w in re.findall(r'[a-z0-9]+', (s or '').lower()) if w not in STOP and len(w) > 1}


# Questions with no single right answer ("What interested you in CFS?", "Anything else?"): the agent writes these per job.
OPEN_ENDED = re.compile(r'\bwhy\b|interest(ed|s)? (you|in)|what (draws|drew|attracts|excites|motivates)|tell us (about|why|what)|'
                        r'\bdescribe\b|\bexplain\b|cover letter|anything else|additional (information|comments)|what makes you|'
                        r'how (would|will|do) you|share (a|an|your|any)|in your own words|\bmotivat|what do you hope|'
                        r'what are you (looking|hoping)|walk us through|\bessay\b', re.I)

WRITE_RULES = (
    "Write this one yourself, for this job only. Read the posting (job_applier_get_job) and the user's vault. "
    "2-4 sentences and under 90 words unless the form asks for more; stay under any character limit. First person, plain words, "
    "the way a sharp student writes in five minutes. Name one specific thing about this company or role from the posting and tie "
    "it to one real thing the user did, with its real numbers. Do not restate the question, do not open with 'I am excited', "
    "'passionate' or 'thrilled', no 'not only X but Y' or 'it's not X, it's Y', no em dashes, no list of three, no closing line "
    "that sums up, no buzzwords (leverage, cutting-edge, innovative, synergy, dynamic, journey, impactful). Never invent "
    "experience, interests or facts. Do not save it with job_applier_save_answer: it is specific to this company.")


def open_ended(question):
    return bool(OPEN_ENDED.search(question or ''))


def match(question, bank, options=None):
    """Best answer for one question. options = the dropdown/radio choices, if any (we pick the closest)."""
    q = (question or '').strip()
    # "Why ...?", "Describe ...", "Tell us ...": always written for the job, even when a word inside ("major", "relocate")
    # would match a saved fact
    if re.match(r'\s*(why|please (describe|explain|tell)|describe|explain|tell us|what (interest|excite|draw|motivat))', q, re.I) and open_ended(q) \
            and not re.search(r'linkedin|github|portfolio|website|url|link|race|ethnic|gender|veteran|disab|authori[sz]|sponsor|visa|citizen', q, re.I):
        return {"question": q, "answer": None, "confidence": 0, "key": None, "action": "write", "how": WRITE_RULES}
    k = {r.get('key'): r.get('answer') for r in bank}
    if re.search(r'authori[sz]ed|eligible|permitted', q, re.I) and re.search(r'sponsor', q, re.I) and k.get('work_auth') and k.get('sponsorship'):
        # "authorized to work WITHOUT sponsorship": yes only if both are true
        both = k['work_auth'] == 'Yes' and k['sponsorship'] == 'No'
        ans = 'Yes' if both else 'No'
        return {"question": q, "answer": pick_option(ans, options) if options else ans, "confidence": 0.9, "key": 'work_auth'}
    best, conf = None, 0.0
    for row in bank:
        pat = row.get('pattern')
        if pat:
            try:
                if re.search(pat, q, re.I):
                    best, conf = row, 0.92
                    break
            except re.error:
                pass
    if best is not None and best.get('answer') in (None, '') and best.get('key') != 'arbitration':
        # the profile field is blank, but the user may have saved this same question in their own words
        qt = _tokens(q)
        for row in bank:
            if row.get('source') == 'user' and row.get('answer') not in (None, ''):
                rt = _tokens(row.get('question'))
                if qt and rt and len(qt & rt) / len(qt | rt) >= 0.5:
                    best = row
                    break
    if not best:
        qt = _tokens(q)
        for row in bank:
            rt = _tokens(row.get('question'))
            if not qt or not rt:
                continue
            j = len(qt & rt) / len(qt | rt)
            if j > conf:
                best, conf = row, j
        conf = min(0.85, conf * 1.3)
    if (not best or conf < 0.92) and open_ended(q):   # nothing saved fits exactly: write it for this job
        return {"question": q, "answer": None, "confidence": 0, "key": None, "action": "write", "how": WRITE_RULES}
    if not best or conf < 0.45 or best.get('answer') in (None, ''):
        return {"question": q, "answer": None, "confidence": round(conf, 2), "key": best.get('key') if best else None,
                "action": "ask the user, then job_applier_save_answer"}
    ans = best['answer']
    if options:
        ans = pick_option(ans, options)
    return {"question": q, "answer": ans, "confidence": round(conf, 2), "key": best.get('key')}


def pick_option(answer, options):
    """Map a free answer onto the closest of the form's options (Yes -> 'Yes, I am authorized...')."""
    a = (answer or '').lower().strip()
    opts = [o for o in options if o and o.lower() not in ('select', 'select one', '--', 'please select')]
    for o in opts:
        if o.lower() == a:
            return o
    if a in ('yes', 'no'):
        for o in opts:
            if re.match(r'^%s\b' % a, o.lower()):
                return o
    at = _tokens(a)
    scored = sorted(opts, key=lambda o: -len(at & _tokens(o)) / (len(_tokens(o)) or 1))
    return scored[0] if scored and at & _tokens(scored[0]) else answer


def upsert(bank, question, answer, key=None):
    key = key or re.sub(r'[^a-z0-9]+', '_', question.lower())[:40]
    for row in bank:
        if row.get('key') == key or row.get('question', '').lower() == question.lower():
            row['answer'] = answer
            row['source'] = 'user'
            return bank
    bank.append({"key": key, "question": question, "pattern": None, "answer": answer, "source": "user"})
    return bank


# ------------------------------------------------------------------ the questions every application asks

YES_NO = ['Yes', 'No']
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
QUESTIONS = [   # (key, label, group, kind, options, optional, hint)  ... kind: text | yesno | select. 'eeo.x' keys are nested.
    ('name', 'Full name', 'You', 'text', None, False, ''),
    ('email', 'Email', 'You', 'text', None, False, ''),
    ('phone', 'Phone', 'You', 'text', None, False, ''),
    ('location', 'Where you live', 'You', 'text', None, False, 'City, State'),
    ('address', 'Street address', 'You', 'text', None, False, '123 Main St'),
    ('address2', 'Apartment, suite or unit', 'You', 'text', None, True, 'Apt 4B'),
    ('postal_code', 'ZIP or postal code', 'You', 'text', None, False, ''),
    ('country', 'Country', 'You', 'text', None, False, 'United States'),
    ('linkedin', 'LinkedIn', 'You', 'text', None, True, 'linkedin.com/in/...'),
    ('github', 'GitHub', 'You', 'text', None, True, ''),
    ('website', 'Website or portfolio', 'You', 'text', None, True, ''),
    ('school', 'School', 'School', 'text', None, False, ''),
    ('degree', 'Degree', 'School', 'select', ['Bachelor of Science', 'Bachelor of Arts', 'Bachelor of Engineering', 'Bachelor of Fine Arts',
                                              'Bachelor of Business Administration', 'Associate', 'Master', 'MBA', 'PhD', 'JD', 'MD', 'Other'], False, ''),
    ('major', 'Major', 'School', 'text', None, False, ''),
    ('minor', 'Minor', 'School', 'text', None, True, ''),
    ('gpa', 'GPA', 'School', 'text', None, True, 'Leave blank to never share it'),
    ('grad_month', 'Graduation month', 'School', 'select', MONTHS, False, ''),
    ('grad_year', 'Graduation year', 'School', 'text', None, False, ''),
    ('class_standing', 'Year in school right now', 'School', 'select', ['Freshman', 'Sophomore', 'Junior', 'Senior', 'Graduate'], False, ''),
    ('enrolled', 'Currently enrolled in a degree program', 'School', 'yesno', YES_NO, False, ''),
    ('earliest_start', 'Earliest start date', 'School', 'text', None, False, 'May 2027'),
    ('work_authorized_us', 'Legally authorized to work in the US', 'Work authorization', 'yesno', YES_NO, False, ''),
    ('needs_sponsorship', 'Will need visa sponsorship, now or later', 'Work authorization', 'yesno', YES_NO, False, ''),
    ('citizenship', 'Citizenship status', 'Work authorization', 'select',
     ['U.S. citizen', 'U.S. permanent resident (green card)', 'Authorized to work, not a citizen or permanent resident',
      'Need sponsorship (F-1, H-1B, etc.)', 'Prefer not to say'], False, 'Only used when a form asks'),
    ('willing_to_relocate', 'Willing to relocate', 'Work authorization', 'yesno', YES_NO, False, ''),
    ('onsite_ok', 'Able to work on-site or hybrid', 'Work authorization', 'yesno', YES_NO, False, ''),
    ('over_18', 'At least 18 years old', 'Standard questions', 'yesno', YES_NO, False, ''),
    ('background_check_ok', 'Consent to a background check', 'Standard questions', 'yesno', YES_NO, False, ''),
    ('has_noncompete', 'Bound by a non-compete or non-solicit', 'Standard questions', 'yesno', YES_NO, False, ''),
    ('government_employee', 'Current or former government employee', 'Standard questions', 'yesno', YES_NO, False, ''),
    ('sms_ok', 'OK with recruiters texting you', 'Standard questions', 'yesno', YES_NO, False, ''),
    ('ai_review_ok', 'OK with companies using AI to review your application', 'Standard questions', 'yesno', YES_NO, False, ''),
    ('salary_expectation', 'Salary expectations', 'Standard questions', 'text', None, False, 'e.g. Flexible, in line with the posted range'),
    ('eeo.gender', 'Gender', 'Voluntary self-identification', 'select', ['Male', 'Female', 'Non-binary', 'Decline to self-identify'], False, ''),
    ('eeo.race', 'Race', 'Voluntary self-identification', 'select',
     ['American Indian or Alaska Native', 'Asian', 'Black or African American', 'Native Hawaiian or Other Pacific Islander', 'White',
      'Two or more races', 'Decline to self-identify'], False, ''),
    ('eeo.hispanic', 'Hispanic or Latino', 'Voluntary self-identification', 'select', ['Yes', 'No', 'Decline to self-identify'], False, ''),
    ('eeo.veteran', 'Veteran status', 'Voluntary self-identification', 'select',
     ['I am not a protected veteran', 'I identify as one or more of the classifications of protected veteran', 'Decline to self-identify'], False, ''),
    ('eeo.disability', 'Disability', 'Voluntary self-identification', 'select',
     ['No, I do not have a disability', 'Yes, I have a disability (or previously had one)', 'I do not want to answer'], False, ''),
    ('eeo.pronouns', 'Pronouns', 'Voluntary self-identification', 'text', None, True, 'Optional'),
]


def get(p, key):
    if key.startswith('eeo.'):
        return (p.get('eeo') or {}).get(key[4:], '')
    return p.get(key)


def gaps(p):
    """Required questions with no answer yet: [{key, label, group}]. Blank never gets guessed; the user is asked."""
    return [{"key": k, "label": l, "group": g} for k, l, g, kind, opts, optional, hint in QUESTIONS
            if not optional and get(p, k) in (None, '')]


def questions():
    return [{"key": k, "label": l, "group": g, "kind": kind, "options": opts, "optional": optional, "hint": hint}
            for k, l, g, kind, opts, optional, hint in QUESTIONS]
