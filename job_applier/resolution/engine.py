"""Deterministic matching and validation shared by all resolution tiers."""
import hashlib
import re
import time
import unicodedata


CHOICES = {'combobox', 'listbox', 'select', 'single_choice', 'multiple_choice', 'radio'}
BLOCKED_WARNINGS = {
    'label_conflict',
    'question_label_missing',
    'group_label_missing',
    'option_inspection_changed_value',
}
EMPLOYER_STOPWORDS = {
    'in', 'on', 'at', 'or', 'to', 'co', 'be', 'it', 'us', 'go',
    'up', 'an', 'as', 'by', 'do', 'if', 'me', 'my', 'no', 'so', 'we',
    'the', 'you', 'one', 'all', 'our', 'any', 'new', 'for', 'and', 'not', 'are',
}
CORP_SUFFIXES = {
    'corp', 'corporation', 'inc', 'incorporated', 'llc',
    'ltd', 'limited', 'co', 'company',
}


def normalize(text):
    if text is None:
        return ''
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', str(text)).casefold()))


def eligible(question, entry):
    q_types = {question.get('input_type'), question.get('native_input_type')} - {None}
    if 'textbox' in q_types:
        q_types.add('text')
    if 'text' in q_types:
        q_types.add('textbox')
    if not q_types.intersection(entry.get('input_types') or []):
        return False
    section = normalize(question.get('section') or '')
    required_section = entry.get('section_contains')
    return not required_section or normalize(required_section) in section


def exact_match(question, bank):
    """Whole aliases plus reviewed positive keyword rules; no fuzzy substring guess."""
    if BLOCKED_WARNINGS.intersection(question.get('warnings') or []):
        return None, 'conflicting_or_missing_label'
    text = normalize(question.get('text'))
    if not text:
        return None, 'no_exact_match'
    questions_bank = bank.get('questions') or []
    hits = {
        e.get('fact')
        for e in questions_bank
        if isinstance(e, dict)
        and e.get('fact')
        and eligible(question, e)
        and text in {normalize(a) for a in (e.get('aliases') or []) if a}
    }
    if len(hits) == 1:
        return next(iter(hits)), 'normalized_exact_alias'
    if hits:
        return None, 'ambiguous_exact_alias'
    # This rule is intentionally narrow: other countries, time scopes and negation
    # must not inherit a US now-or-future sponsorship answer.
    if question.get('input_type') in CHOICES:
        tokens = set(text.split())
        negative_tokens = {'not', 'no', 'without', 'never', 'only', 'except', 'previously', 'past'}
        non_us_locations = ('canada', 'united kingdom', 'europe', 'australia')
        has_now_or_future = ('now' in tokens or 'future' in tokens or 'now or future' in text)
        if ('require sponsorship' in text and 'now' in tokens and 'future' in tokens
                and 'united states' in text and 'visa' in tokens
                and not tokens.intersection(negative_tokens)
                and not any(x in text for x in non_us_locations)):
            return (
                'work.us_sponsorship_now_or_future',
                'reviewed_keyword_rule:us_sponsorship_now_or_future',
            )
        if (('require sponsorship' in text or 'require immigration sponsorship' in text)
                and has_now_or_future
                and 'united states' in text
                and not tokens.intersection(negative_tokens)
                and not any(x in text for x in non_us_locations)):
            return (
                'work.us_sponsorship_now_or_future',
                'reviewed_keyword_rule:us_sponsorship_now_or_future',
            )
        is_prior_employed = (
            (('previously' in tokens or 'ever' in tokens) and ('employed' in tokens or 'worked' in tokens))
            or
            ('former' in tokens and ('employee' in tokens or 'worker' in tokens))
        )
        reject_prior_employee_tokens = (
            'government', 'federal', 'public',
            'with', 'using', 'remotely', 'shifts', 'shift',
            'weekends', 'nights', 'overtime', 'visa', 'sponsorship',
            'scale', 'startup', 'agency',
        )
        is_rejected_prior_employee = (
            bool(tokens.intersection(reject_prior_employee_tokens))
            or 'worked with' in text
            or 'worked on' in text
        )
        has_known_emp = False
        emp_fact = (bank.get('facts') or {}).get('work.prior_employee')
        known_employers = (emp_fact.get('known_employers') or []) if isinstance(emp_fact, dict) else []
        for emp in known_employers:
            norm_emp = normalize(emp)
            if not norm_emp:
                continue
            emp_cands = [norm_emp]
            e_toks = norm_emp.split()
            while len(e_toks) > 1 and e_toks[-1] in CORP_SUFFIXES:
                e_toks.pop()
            core_e = ' '.join(e_toks)
            if core_e != norm_emp:
                emp_cands.append(core_e)
            for cand in emp_cands:
                cand_toks = cand.split()
                if all(t in (EMPLOYER_STOPWORDS | CORP_SUFFIXES) for t in cand_toks):
                    continue
                if len(cand_toks) == 1 and (cand in EMPLOYER_STOPWORDS or len(cand) < 3):
                    continue
                if re.search(r'\b' + re.escape(cand) + r'\b', text):
                    has_known_emp = True
                    break
            if has_known_emp:
                break

        has_deictic_company = any(
            p in text
            for p in (
                'this company',
                'this employer',
                'this organization',
                'this firm',
                'our company',
                'the company',
                'worked here',
                'employed here',
                'been here',
            )
        )
        has_employer_context = has_deictic_company or has_known_emp
        if is_prior_employed and has_employer_context and not is_rejected_prior_employee:
            return (
                'work.prior_employee',
                'reviewed_keyword_rule:prior_employee',
            )
        if ('how did you' in text or 'where did you' in text) and ('hear' in tokens or 'learn' in tokens or 'find' in tokens):
            return (
                'meta.hear_about',
                'reviewed_keyword_rule:meta_hear_about',
            )
        if 'state' in tokens and ('province' in tokens or 'reside' in tokens):
            return (
                'contact.state',
                'reviewed_keyword_rule:contact_state',
            )
    return None, 'no_exact_match'


def _copy_question_metadata(question):
    keys = (
        'input_type',
        'native_input_type',
        'ax_role',
        'frame_id',
        'frame_descriptor',
        'locator_candidates',
        'locator_scope',
        'control_ids',
        'control_metadata',
        'options',
        'section',
        'warnings',
        'required',
        'help',
    )
    return {k: question[k] for k in keys if k in question}


def abstain(question, tier, reason, **extra):
    meta = _copy_question_metadata(question)
    return {'question_id': question.get('id') or question.get('question_id'),
            'text': question.get('text', ''), 'tier': tier,
            'status': 'needs_user', 'fact_key': None, 'answer': None,
            'reason': reason, **meta, **extra}


def render(question, fact_key, bank, tier, reason, **extra):
    """Only copy confirmed facts and observed option identifiers. Never generate facts."""
    if BLOCKED_WARNINGS.intersection(question.get('warnings') or []):
        return abstain(question, tier, 'conflicting_or_missing_label', **extra)
    facts = bank.get('facts') or {}
    if not fact_key or fact_key not in facts:
        return abstain(question, tier, reason or 'no_supported_fact', **extra)
    fact = facts[fact_key]
    templates = [
        e for e in (bank.get('questions') or [])
        if isinstance(e, dict) and e.get('fact') == fact_key and eligible(question, e)
    ]
    if not templates:
        return abstain(question, tier, 'incompatible_fact_type_or_scope', **extra)
    if not isinstance(fact, dict) or fact.get('confirmed') is not True or fact.get('value') is None:
        return abstain(question, tier, 'fact_missing_or_unconfirmed', **extra)
    if question.get('input_type') == 'file':
        return abstain(question, tier, 'file_selection_requires_verified_local_artifact', **extra)
    if fact_key == 'work.prior_employee':
        known_employers = fact.get('known_employers') or []
        norm_q = normalize(question.get('text'))
        for emp in known_employers:
            norm_emp = normalize(emp)
            if not norm_emp:
                continue
            emp_candidates = [norm_emp]
            emp_tokens = norm_emp.split()
            while len(emp_tokens) > 1 and emp_tokens[-1] in CORP_SUFFIXES:
                emp_tokens.pop()
            core_emp = ' '.join(emp_tokens)
            if core_emp != norm_emp:
                emp_candidates.append(core_emp)
            for cand in emp_candidates:
                cand_tokens = cand.split()
                if all(t in (EMPLOYER_STOPWORDS | CORP_SUFFIXES) for t in cand_tokens):
                    continue
                if len(cand_tokens) == 1 and (cand in EMPLOYER_STOPWORDS or len(cand) < 3):
                    continue
                if re.search(r'\b' + re.escape(cand) + r'\b', norm_q):
                    return abstain(question, tier, 'prior_employer_present_in_resume', **extra)
    value = fact['value']
    selected = None
    if question.get('input_type') in CHOICES:
        # Reviewed aliases are attached to a specific fact, never inferred from a
        # generic word such as "country" or from the first option.
        opt_labels = fact.get('option_labels') or []
        if isinstance(value, bool):
            aliases = ['Yes' if value else 'No', *opt_labels]
        else:
            aliases = [value, *opt_labels]
        items = (question.get('options') or {}).get('items') or []
        matches = [o for o in items if not o.get('disabled')
                   and normalize(o.get('label') or '') in {normalize(v) for v in aliases}]
        if fact_key == 'contact.country' and not matches:
            country_norm_aliases = {normalize(v) for v in aliases}
            matches = [
                o for o in items if not o.get('disabled')
                and normalize(re.sub(r'\s*\(?\+\d+\)?$', '', o.get('label') or '')) in country_norm_aliases
            ]
        if fact_key == 'work.prior_employee' and value in ('No', False):
            def _is_valid_negative_option(opt):
                if opt.get('disabled'):
                    return False
                lbl = normalize(opt.get('label') or '')
                toks = set(lbl.split())
                # 1. Must NOT contain affirmative indicators or role claims
                if 'yes' in toks:
                    return False
                # 2. Must NOT contain contrasting clauses
                contrasting_tokens = {'but', 'except', 'however'}
                if toks.intersection(contrasting_tokens):
                    return False
                # 3. Unnegated affirmative phrases or contractor/intern roles must NEVER be accepted
                if any(role in toks for role in (
                    'contractor', 'subcontractor', 'intern', 'internship', 'interned',
                    'apprentice', 'apprenticeship', 'consultant', 'temp', 'temporary',
                    'seasonal', 'vendor', 'coop', 'fellow', 'extern', 'freelance', 'freelancer'
                )):
                    return False
                if 'co op' in lbl or 'coop' in toks:
                    return False
                affirmative_patterns = (
                    r'(?<!\bnot\s)(?<!\bnever\s)\bworked\s+here\b',
                    r'(?<!\bnot\s)(?<!\bnever\s)\bworked\s+at\b',
                    r'(?<!\bnot\s)(?<!\bnever\s)\bworked\s+for\b',
                    r'(?<!\bnot\s)(?<!\bnever\s)\bworked\s+as\b',
                    r'(?<!\bnot\s)(?<!\bnever\s)\bpreviously\s+worked\b',
                    r'(?<!\bnot\s)(?<!\bnever\s)\bhave\s+worked\b',
                    r'(?<!\bnot\s)(?<!\bnever\s)\bcurrently\s+employed\b',
                    r'(?<!\bnot\s)(?<!\bnever\s)\bwas\s+employed\b',
                    r'(?<!\bnot\s)(?<!\bnever\s)\bam\s+employed\b',
                    r'(?<!\bnot\s)(?<!\bnever\s)\bhave\s+been\s+employed\b',
                    r'(?<!\bnot\s)(?<!\bnever\s)\bpreviously\s+employed\b',
                    r'(?<!\bnot\s)(?<!\bnever\s)\bwas\s+an\s+employee\b',
                    r'(?<!\bnot\s)(?<!\bnever\s)\bbeen\s+an\s+employee\b',
                    r'\bas\s+a\s+contractor\b',
                    r'\bas\s+an\s+intern\b',
                    r'\b(completed|did|had)\s+(an?\s+)?internship\b',
                    r'\binterned\b',
                    r'\bapprentice(ship)?\b',
                    r'\bas\s+an?\s+(intern|apprentice)\b',
                )
                has_affirmative_phrase = any(bool(re.search(pat, lbl)) for pat in affirmative_patterns)
                if has_affirmative_phrase:
                    return False
                # 4. Matches negative phrasing:
                # starts with 'no' or contains ('not', 'never') followed by employment words
                has_neg_emp = bool(re.search(
                    r'\b(not|never)\b.*\b(employed|worked|employee|employment|worker)\b',
                    lbl,
                ))
                affirmative_work_terms = {
                    'employed', 'worked', 'employee', 'contractor', 'subcontractor', 'intern', 'worker', 'employment',
                    'internship', 'interned', 'apprentice', 'apprenticeship',
                    'consultant', 'temp', 'temporary', 'seasonal', 'vendor', 'coop', 'fellow', 'extern',
                    'freelance', 'freelancer',
                }
                if lbl.startswith('no '):
                    if (toks.intersection(affirmative_work_terms) or 'co op' in lbl) and not has_neg_emp:
                        return False
                is_no_start = (
                    lbl == 'no'
                    or lbl.startswith('no ')
                    or lbl == 'never'
                    or lbl.startswith('never ')
                )
                return is_no_start or has_neg_emp

            # Filter matches through negative guards
            matches = [o for o in matches if _is_valid_negative_option(o)]
            if len(matches) != 1:
                neg_opts = [o for o in items if _is_valid_negative_option(o)]
                if len(neg_opts) == 1:
                    matches = neg_opts
                else:
                    matches = []
        if fact_key == 'meta.hear_about' and len(matches) > 1:
            pref_order = ['Job Board', 'LinkedIn', 'Indeed', 'Online Job Board', 'Company careers website', *aliases]
            for cand in pref_order:
                cand_norm = normalize(cand)
                c_matches = [o for o in matches if normalize(o.get('label') or '') == cand_norm]
                if len(c_matches) == 1:
                    matches = c_matches
                    break
        if len(matches) != 1:
            return abstain(question, tier, 'option_not_uniquely_observed', **extra)
        selected = {k: matches[0].get(k) for k in ('id', 'label', 'value')}
        value = selected['label']
    elif isinstance(value, (dict, list, bool)):
        return abstain(question, tier, 'unsupported_value_shape', **extra)
    # New semantic/model aliases are proposals. Promote only after user review.
    status = 'ready' if tier == 'exact' else 'review'
    meta = _copy_question_metadata(question)
    return {'question_id': question.get('id') or question.get('question_id'),
            'text': question.get('text', ''), 'tier': tier,
            'status': status, 'fact_key': fact_key, 'answer': value,
            'selected_option': selected, 'source': fact.get('source', 'vault'), 'reason': reason,
            **meta, **extra}


def resolve_exact(question, bank):
    key, reason = exact_match(question, bank)
    return render(question, key, bank, 'exact', reason)


def resolve_semantic(question, bank, semantic):
    if BLOCKED_WARNINGS.intersection(question.get('warnings') or []):
        return abstain(question, 'semantic', 'conflicting_or_missing_label')
    candidates = semantic.rank(question, bank)
    if not candidates:
        return abstain(question, 'semantic', 'no_semantic_candidates')
    top = candidates[0]
    margin = top['score'] - (candidates[1]['score'] if len(candidates) > 1 else 0)
    extra = {'similarity': top['score'], 'margin': round(margin, 6), 'candidates': candidates[:3]}
    if top['score'] < semantic.threshold or margin < semantic.margin:
        return abstain(question, 'semantic', 'below_similarity_or_margin_threshold', **extra)
    return render(question, top['fact_key'], bank, 'semantic', 'local_embedding_match', **extra)


def resolve_cascade(questions, bank, semantic, llm=None):
    results, unresolved = [], []
    started = time.perf_counter()
    for q in questions:
        result = resolve_exact(q, bank)
        is_blocked = (
            result.get('reason') == 'conflicting_or_missing_label'
            or bool(BLOCKED_WARNINGS.intersection(q.get('warnings') or []))
        )
        if result['status'] == 'needs_user' and not is_blocked:
            result = resolve_semantic(q, bank, semantic)
        results.append(result)
        if result['status'] == 'needs_user' and not is_blocked:
            unresolved.append(q)
    calls = []
    unresolved_indices = {
        i for i, (q, r) in enumerate(zip(questions, results))
        if r.get('status') == 'needs_user' and not (
            r.get('reason') == 'conflicting_or_missing_label'
            or bool(BLOCKED_WARNINGS.intersection(q.get('warnings') or []))
        )
    }
    if unresolved and llm:
        try:
            predictions, calls = llm.match(unresolved, bank)
        except Exception as exc:
            predictions = {}
            calls = [{
                'model': getattr(llm, 'model', 'unknown'),
                'status': 'provider_exception',
                'error_type': type(exc).__name__,
                'elapsed_ms': 0.0,
            }]
        for i, q in enumerate(questions):
            if i in unresolved_indices:
                qid = q.get('id') or q.get('question_id')
                prediction = predictions.get(qid) or {}
                results[i] = render(q, prediction.get('fact_key'), bank, 'qwen',
                                    prediction.get('reason', 'llm_unavailable_or_abstained'))
    return {
        'results': results,
        'calls': calls,
        'elapsed_ms': round((time.perf_counter() - started) * 1000, 2),
    }


def pending_questions(questions, results, scope):
    """Stable scoped IDs for user review; no unreviewed answer is learned."""
    pending = []
    for q, r in zip(questions, results):
        if r.get('status') == 'ready':
            continue
        items = (q.get('options') or {}).get('items') or []
        options_sig = '|'.join(normalize(o.get('label') or '') for o in items)
        signature = '|'.join([
            scope or '',
            normalize(q.get('text') or ''),
            q.get('input_type') or '',
            normalize(q.get('section') or ''),
            options_sig,
        ])
        pending.append({
            'pending_id': hashlib.sha256(signature.encode()).hexdigest()[:24],
            'scope': scope,
            'question': q,
            'proposal': r,
            'instruction': (
                'Confirm the fact or mapping before adding an approved scoped alias.'
            ),
        })
    return pending
