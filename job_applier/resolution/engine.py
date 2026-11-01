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


def normalize(text):
    if text is None:
        return ''
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', str(text)).casefold()))


def eligible(question, entry):
    if question['input_type'] not in entry['input_types']:
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
    hits = {e['fact'] for e in bank['questions'] if eligible(question, e)
            and text in {normalize(a) for a in e['aliases']}}
    if len(hits) == 1:
        return next(iter(hits)), 'normalized_exact_alias'
    if hits:
        return None, 'ambiguous_exact_alias'
    # This rule is intentionally narrow: other countries, time scopes and negation
    # must not inherit a US now-or-future sponsorship answer.
    if question['input_type'] in CHOICES:
        tokens = set(text.split())
        negative_tokens = {'not', 'no', 'without', 'never', 'only', 'except', 'previously', 'past'}
        non_us_locations = ('canada', 'united kingdom', 'europe', 'australia')
        if ('require sponsorship' in text and 'now' in tokens and 'future' in tokens
                and 'united states' in text and 'visa' in tokens
                and not tokens.intersection(negative_tokens)
                and not any(x in text for x in non_us_locations)):
            return (
                'work.us_sponsorship_now_or_future',
                'reviewed_keyword_rule:us_sponsorship_now_or_future',
            )
    return None, 'no_exact_match'


def abstain(question, tier, reason, **extra):
    return {'question_id': question['id'], 'text': question['text'], 'tier': tier,
            'status': 'needs_user', 'fact_key': None, 'answer': None,
            'reason': reason, **extra}


def render(question, fact_key, bank, tier, reason, **extra):
    """Only copy confirmed facts and observed option identifiers. Never generate facts."""
    if BLOCKED_WARNINGS.intersection(question.get('warnings') or []):
        return abstain(question, tier, 'conflicting_or_missing_label', **extra)
    if not fact_key or fact_key not in bank['facts']:
        return abstain(question, tier, reason or 'no_supported_fact', **extra)
    fact = bank['facts'][fact_key]
    templates = [e for e in bank['questions'] if e['fact'] == fact_key and eligible(question, e)]
    if not templates:
        return abstain(question, tier, 'incompatible_fact_type_or_scope', **extra)
    if fact.get('confirmed') is not True or fact.get('value') is None:
        return abstain(question, tier, 'fact_missing_or_unconfirmed', **extra)
    if question['input_type'] == 'file':
        return abstain(question, tier, 'file_selection_requires_verified_local_artifact', **extra)
    value = fact['value']
    selected = None
    if question['input_type'] in CHOICES:
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
        if len(matches) != 1:
            return abstain(question, tier, 'option_not_uniquely_observed', **extra)
        selected = {k: matches[0].get(k) for k in ('id', 'label', 'value')}
        value = selected['label']
    elif isinstance(value, (dict, list, bool)):
        return abstain(question, tier, 'unsupported_value_shape', **extra)
    # New semantic/model aliases are proposals. Promote only after user review.
    status = 'ready' if tier == 'exact' else 'review'
    return {'question_id': question['id'], 'text': question['text'], 'tier': tier,
            'status': status, 'fact_key': fact_key, 'answer': value,
            'selected_option': selected, 'source': fact['source'], 'reason': reason, **extra}


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
    if unresolved and llm:
        predictions, calls = llm.match(unresolved, bank)
        unresolved_ids = {q['id'] for q in unresolved}
        for i, (q, result) in enumerate(zip(questions, results)):
            if q['id'] in unresolved_ids:
                prediction = predictions.get(q['id'], {})
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
        if r['status'] == 'ready':
            continue
        items = (q.get('options') or {}).get('items') or []
        options_sig = '|'.join(normalize(o.get('label') or '') for o in items)
        signature = '|'.join([
            scope or '',
            normalize(q['text']),
            q['input_type'],
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
