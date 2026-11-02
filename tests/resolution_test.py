"""Unit tests for deterministic resolution engine, matching, rendering, and cascade."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from job_applier.resolution.engine import (
    CHOICES,
    BLOCKED_WARNINGS,
    normalize,
    eligible,
    exact_match,
    abstain,
    render,
    resolve_exact,
    resolve_semantic,
    resolve_cascade,
    pending_questions,
)


def make_bank():
    return {
        'questions': [
            {
                'fact': 'contact.email',
                'input_types': ['text', 'email'],
                'aliases': ['Email', 'Email Address'],
            },
            {
                'fact': 'contact.phone',
                'input_types': ['text', 'tel'],
                'aliases': ['Phone Number', 'Mobile Phone'],
            },
            {
                'fact': 'education.degree',
                'input_types': ['combobox', 'single_choice', 'select'],
                'aliases': ['Degree', 'Highest Degree Completed'],
            },
            {
                'fact': 'work.us_sponsorship_now_or_future',
                'input_types': ['single_choice', 'combobox', 'select', 'radio'],
                'aliases': ['Will you now or in the future require sponsorship for employment visa status?'],
            },
            {
                'fact': 'work.authorized_us',
                'input_types': ['single_choice', 'combobox', 'select', 'radio'],
                'aliases': ['Legally authorized to work in United States'],
            },
            {
                'fact': 'personal.relocate',
                'input_types': ['single_choice', 'radio'],
                'aliases': ['Willing to relocate'],
                'section_contains': 'preferences',
            },
            {
                'fact': 'application.resume',
                'input_types': ['file'],
                'aliases': ['Resume/CV', 'Upload Resume'],
            },
        ],
        'facts': {
            'contact.email': {
                'value': 'ada@example.com',
                'confirmed': True,
                'source': 'vault',
            },
            'contact.phone': {
                'value': '+15551234567',
                'confirmed': True,
                'source': 'vault',
            },
            'education.degree': {
                'value': "Bachelor's Degree",
                'option_labels': ['BS', 'Bachelor of Science', "Bachelor's"],
                'confirmed': True,
                'source': 'vault',
            },
            'work.us_sponsorship_now_or_future': {
                'value': False,
                'confirmed': True,
                'source': 'vault',
            },
            'work.authorized_us': {
                'value': True,
                'confirmed': True,
                'source': 'vault',
            },
            'personal.relocate': {
                'value': True,
                'confirmed': True,
                'source': 'vault',
            },
            'application.resume': {
                'value': '/tmp/resume.pdf',
                'confirmed': True,
                'source': 'vault',
            },
        },
    }


_UNSET = object()


def make_question(
    question_id='q1',
    text='Email Address',
    input_type='text',
    section='',
    options=_UNSET,
    warnings=_UNSET,
    required=True,
    **extra_kwargs,
):
    qid = extra_kwargs.pop('id', question_id)
    resolved_options = {'items': [], 'complete': False} if options is _UNSET else options
    resolved_warnings = [] if warnings is _UNSET else warnings
    return {
        'id': qid,
        'text': text,
        'input_type': input_type,
        'section': section,
        'options': resolved_options,
        'warnings': resolved_warnings,
        'required': required,
        'frame_id': 'frame-0',
        'control_ids': [f'ctrl-{qid}'],
    }


class DummySemantic:
    def __init__(self, candidates_map=None, threshold=0.82, margin=0.06):
        self.candidates_map = candidates_map or {}
        self.threshold = threshold
        self.margin = margin
        self.ranked_queries = []

    def rank(self, question, bank):
        self.ranked_queries.append(question['id'])
        return self.candidates_map.get(question['id'], [])


class DummyLLM:
    def __init__(self, predictions=None, calls=None):
        self.predictions = predictions or {}
        self.recorded_calls = calls or [{'model': 'qwen', 'status': 'ok'}]
        self.matched_batches = []

    def match(self, questions, bank):
        self.matched_batches.append([q['id'] for q in questions])
        return self.predictions, self.recorded_calls


class TestNormalize(unittest.TestCase):
    def test_unicode_nfkc_normalization(self):
        # Ligatures and fullwidth characters decompose and normalize under NFKC
        self.assertEqual(normalize('ﬁle'), 'file')
        self.assertEqual(normalize('ﬂow'), 'flow')
        self.assertEqual(normalize('Ｆｕｌｌｗｉｄｔｈ'), 'fullwidth')
        self.assertEqual(normalize('Café'), 'café')

    def test_casing(self):
        self.assertEqual(normalize('First Name'), 'first name')
        self.assertEqual(normalize('UPPERCASE TEXT'), 'uppercase text')
        # German eszett casefolds to ss
        self.assertEqual(normalize('Straße'), 'strasse')

    def test_punctuation_removal(self):
        self.assertEqual(
            normalize('Email (work/personal): required! [100%]'),
            'email work personal required 100',
        )
        self.assertEqual(normalize('hello-world_test.123'), 'hello world_test 123')

    def test_whitespace_collapsing(self):
        self.assertEqual(normalize('  \n\t  hello   world \t\n  '), 'hello world')
        self.assertEqual(normalize(''), '')


class TestEligible(unittest.TestCase):
    def test_input_type_matching(self):
        entry = {'input_types': ['text', 'email']}
        self.assertTrue(eligible(make_question(input_type='text'), entry))
        self.assertTrue(eligible(make_question(input_type='email'), entry))
        self.assertFalse(eligible(make_question(input_type='single_choice'), entry))

    def test_section_contains_filtering(self):
        entry_with_section = {
            'input_types': ['single_choice', 'radio'],
            'section_contains': 'preferences',
        }
        # Matching section substring after normalization
        q_matching = make_question(
            input_type='single_choice',
            section='1. General Preferences / Work Options',
        )
        self.assertTrue(eligible(q_matching, entry_with_section))

        # Non-matching section
        q_mismatch = make_question(
            input_type='single_choice',
            section='Education History',
        )
        self.assertFalse(eligible(q_mismatch, entry_with_section))

        # Missing or empty section fails when section_contains is required
        q_empty = make_question(input_type='single_choice', section='')
        self.assertFalse(eligible(q_empty, entry_with_section))

        # Entry without section_contains allows any section
        entry_open = {'input_types': ['text']}
        self.assertTrue(eligible(make_question(input_type='text', section=''), entry_open))
        self.assertTrue(
            eligible(make_question(input_type='text', section='Any Section'), entry_open)
        )


class TestExactMatch(unittest.TestCase):
    def setUp(self):
        self.bank = make_bank()

    def test_positive_exact_alias_match(self):
        q = make_question(text='Email Address', input_type='text')
        key, status = exact_match(q, self.bank)
        self.assertEqual(key, 'contact.email')
        self.assertEqual(status, 'normalized_exact_alias')

        # Normalized punctuation and casing still match
        q_punct = make_question(text='  EMAIL: address ! ', input_type='text')
        key, status = exact_match(q_punct, self.bank)
        self.assertEqual(key, 'contact.email')
        self.assertEqual(status, 'normalized_exact_alias')

    def test_multiple_conflicting_aliases(self):
        ambiguous_bank = {
            'questions': [
                {'fact': 'fact.one', 'input_types': ['text'], 'aliases': ['Duplicate Label']},
                {'fact': 'fact.two', 'input_types': ['text'], 'aliases': ['Duplicate Label']},
            ],
            'facts': {},
        }
        q = make_question(text='Duplicate Label', input_type='text')
        key, status = exact_match(q, ambiguous_bank)
        self.assertIsNone(key)
        self.assertEqual(status, 'ambiguous_exact_alias')

    def test_blocked_warnings(self):
        for warning in sorted(BLOCKED_WARNINGS):
            q = make_question(text='Email Address', input_type='text', warnings=[warning])
            key, status = exact_match(q, self.bank)
            self.assertIsNone(key, f'Failed for warning {warning}')
            self.assertEqual(
                status,
                'conflicting_or_missing_label',
                f'Failed for warning {warning}',
            )

        # Non-blocked warnings must not block exact match
        q_safe = make_question(
            text='Email Address',
            input_type='text',
            warnings=['accessibility_control_missing'],
        )
        key, status = exact_match(q_safe, self.bank)
        self.assertEqual(key, 'contact.email')
        self.assertEqual(status, 'normalized_exact_alias')

    def test_us_sponsorship_keyword_rule_positive(self):
        positive_text = (
            'Will you now or in the future require sponsorship for employment visa '
            'status in the United States?'
        )
        for choice_type in CHOICES:
            q = make_question(text=positive_text, input_type=choice_type)
            key, status = exact_match(q, self.bank)
            self.assertEqual(
                key,
                'work.us_sponsorship_now_or_future',
                f'Failed for choice type {choice_type}',
            )
            self.assertEqual(
                status,
                'reviewed_keyword_rule:us_sponsorship_now_or_future',
                f'Failed for choice type {choice_type}',
            )

    def test_us_sponsorship_keyword_rule_negative_words_rejected(self):
        base_prompt = (
            'Will you {neg} now or in the future require sponsorship for employment '
            'visa status in the United States?'
        )
        negative_words = ('not', 'no', 'without', 'never', 'only', 'except', 'previously', 'past')
        for neg in negative_words:
            prompt = base_prompt.format(neg=neg)
            q = make_question(text=prompt, input_type='single_choice')
            key, status = exact_match(q, self.bank)
            self.assertIsNone(key, f'Negative word "{neg}" should have rejected match')
            self.assertEqual(status, 'no_exact_match')

    def test_us_sponsorship_keyword_rule_non_us_country_rejected(self):
        non_us_countries = ('canada', 'united kingdom', 'europe', 'australia')
        for country in non_us_countries:
            prompt = (
                f'Will you now or in the future require sponsorship for employment visa '
                f'status in the United States or {country}?'
            )
            q = make_question(text=prompt, input_type='single_choice')
            key, status = exact_match(q, self.bank)
            self.assertIsNone(key, f'Country "{country}" should have rejected match')
            self.assertEqual(status, 'no_exact_match')

    def test_us_sponsorship_keyword_rule_non_choice_type_rejected(self):
        prompt = (
            'Will you now or in the future require sponsorship for employment visa '
            'status in the United States?'
        )
        for non_choice in ('text', 'textarea', 'file'):
            q = make_question(text=prompt, input_type=non_choice)
            key, status = exact_match(q, self.bank)
            self.assertIsNone(
                key,
                f'Non-choice input_type "{non_choice}" should have rejected match',
            )
            self.assertEqual(status, 'no_exact_match')

    def test_fallback_no_exact_match(self):
        q = make_question(text='What is your favorite programming language?', input_type='text')
        key, status = exact_match(q, self.bank)
        self.assertIsNone(key)
        self.assertEqual(status, 'no_exact_match')


class TestAbstain(unittest.TestCase):
    def test_abstain_structure(self):
        q = make_question(question_id='q-42', text='Years of Experience')
        res = abstain(q, 'exact', 'no_exact_match', extra_field='custom_val', score=0.45)
        self.assertEqual(res['question_id'], 'q-42')
        self.assertEqual(res['text'], 'Years of Experience')
        self.assertEqual(res['tier'], 'exact')
        self.assertEqual(res['status'], 'needs_user')
        self.assertIsNone(res['fact_key'])
        self.assertIsNone(res['answer'])
        self.assertEqual(res['reason'], 'no_exact_match')
        self.assertEqual(res['extra_field'], 'custom_val')
        self.assertEqual(res['score'], 0.45)
        self.assertEqual(res['input_type'], 'text')
        self.assertEqual(res['frame_id'], 'frame-0')
        self.assertEqual(res['control_ids'], ['ctrl-q-42'])


class TestRender(unittest.TestCase):
    def setUp(self):
        self.bank = make_bank()

    def test_warning_blocking_check(self):
        q = make_question(
            question_id='q-warn',
            text='Email Address',
            input_type='text',
            warnings=['label_conflict'],
        )
        res = render(q, 'contact.email', self.bank, 'exact', 'normalized_exact_alias')
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'conflicting_or_missing_label')
        self.assertIsNone(res['fact_key'])

    def test_missing_or_unsupported_fact_key(self):
        q = make_question(text='Email Address', input_type='text')
        res_none = render(q, None, self.bank, 'exact', 'no_exact_match')
        self.assertEqual(res_none['status'], 'needs_user')
        self.assertEqual(res_none['reason'], 'no_exact_match')

        res_none_default = render(q, None, self.bank, 'exact', None)
        self.assertEqual(res_none_default['status'], 'needs_user')
        self.assertEqual(res_none_default['reason'], 'no_supported_fact')

        res_unknown = render(q, 'nonexistent.fact', self.bank, 'exact', 'unknown')
        self.assertEqual(res_unknown['status'], 'needs_user')
        self.assertEqual(res_unknown['reason'], 'unknown')

    def test_incompatible_fact_type(self):
        # contact.email only supports text and email, but question is single_choice
        q = make_question(text='Email Address', input_type='single_choice')
        res = render(q, 'contact.email', self.bank, 'exact', 'normalized_exact_alias')
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'incompatible_fact_type_or_scope')

    def test_missing_or_unconfirmed_fact(self):
        bank = make_bank()
        # Case 1: confirmed is False
        bank['facts']['contact.email']['confirmed'] = False
        q = make_question(text='Email Address', input_type='text')
        res_unconfirmed = render(q, 'contact.email', bank, 'exact', 'normalized_exact_alias')
        self.assertEqual(res_unconfirmed['status'], 'needs_user')
        self.assertEqual(res_unconfirmed['reason'], 'fact_missing_or_unconfirmed')

        # Case 2: value is None
        bank['facts']['contact.email']['confirmed'] = True
        bank['facts']['contact.email']['value'] = None
        res_none_val = render(q, 'contact.email', bank, 'exact', 'normalized_exact_alias')
        self.assertEqual(res_none_val['status'], 'needs_user')
        self.assertEqual(res_none_val['reason'], 'fact_missing_or_unconfirmed')

    def test_file_input_type(self):
        q = make_question(text='Resume/CV', input_type='file')
        res = render(q, 'application.resume', self.bank, 'exact', 'normalized_exact_alias')
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'file_selection_requires_verified_local_artifact')

    def test_choice_option_exact_label_match(self):
        q = make_question(
            text='Highest Degree Completed',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-1', 'label': 'High School', 'value': 'hs'},
                    {'id': 'opt-2', 'label': "Bachelor's Degree", 'value': 'bs'},
                    {'id': 'opt-3', 'label': "Master's Degree", 'value': 'ms'},
                ],
                'complete': True,
            },
        )
        res = render(q, 'education.degree', self.bank, 'exact', 'normalized_exact_alias')
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['answer'], "Bachelor's Degree")
        self.assertEqual(
            res['selected_option'],
            {'id': 'opt-2', 'label': "Bachelor's Degree", 'value': 'bs'},
        )

    def test_choice_option_boolean_matching(self):
        q_yes_no = make_question(
            text='Are you legally authorized to work in the United States?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-yes', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-no', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        # authorized_us value is True -> matches 'Yes'
        res_true = render(
            q_yes_no,
            'work.authorized_us',
            self.bank,
            'exact',
            'normalized_exact_alias',
        )
        self.assertEqual(res_true['status'], 'ready')
        self.assertEqual(res_true['answer'], 'Yes')
        self.assertEqual(res_true['selected_option']['id'], 'opt-yes')

        # us_sponsorship_now_or_future value is False -> matches 'No'
        res_false = render(
            q_yes_no,
            'work.us_sponsorship_now_or_future',
            self.bank,
            'exact',
            'reviewed_keyword_rule:us_sponsorship_now_or_future',
        )
        self.assertEqual(res_false['status'], 'ready')
        self.assertEqual(res_false['answer'], 'No')
        self.assertEqual(res_false['selected_option']['id'], 'opt-no')

    def test_choice_non_unique_option_matching(self):
        # Zero matches in options
        q_zero = make_question(
            text='Degree',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-1', 'label': 'Doctorate', 'value': 'phd'},
                    {'id': 'opt-2', 'label': 'Associate', 'value': 'aa'},
                ],
                'complete': True,
            },
        )
        res_zero = render(
            q_zero,
            'education.degree',
            self.bank,
            'exact',
            'normalized_exact_alias',
        )
        self.assertEqual(res_zero['status'], 'needs_user')
        self.assertEqual(res_zero['reason'], 'option_not_uniquely_observed')

        # Multiple matches in options (e.g. duplicate or multiple alias hits)
        q_multi = make_question(
            text='Degree',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-1', 'label': "Bachelor's Degree", 'value': 'bs1'},
                    {'id': 'opt-2', 'label': "BS", 'value': 'bs2'},
                ],
                'complete': True,
            },
        )
        res_multi = render(
            q_multi,
            'education.degree',
            self.bank,
            'exact',
            'normalized_exact_alias',
        )
        self.assertEqual(res_multi['status'], 'needs_user')
        self.assertEqual(res_multi['reason'], 'option_not_uniquely_observed')

    def test_choice_disabled_options_ignored(self):
        # Option 1 matches but is disabled; Option 2 matches and is active
        q = make_question(
            text='Are you legally authorized to work in the United States?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-disabled-yes', 'label': 'Yes', 'value': 'Y1', 'disabled': True},
                    {'id': 'opt-active-yes', 'label': 'Yes', 'value': 'Y2', 'disabled': False},
                    {'id': 'opt-no', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        res = render(q, 'work.authorized_us', self.bank, 'exact', 'normalized_exact_alias')
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['selected_option']['id'], 'opt-active-yes')

        # If the only matching option is disabled, it abstains
        q_all_disabled = make_question(
            text='Are you legally authorized to work in the United States?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-disabled-yes', 'label': 'Yes', 'value': 'Y1', 'disabled': True},
                    {'id': 'opt-no', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        res_all_disabled = render(
            q_all_disabled,
            'work.authorized_us',
            self.bank,
            'exact',
            'normalized_exact_alias',
        )
        self.assertEqual(res_all_disabled['status'], 'needs_user')
        self.assertEqual(res_all_disabled['reason'], 'option_not_uniquely_observed')

    def test_unsupported_value_shape_for_non_choice(self):
        bank = make_bank()
        bank['facts']['contact.email']['value'] = ['ada@example.com', 'ada2@example.com']
        q = make_question(text='Email Address', input_type='text')
        res = render(q, 'contact.email', bank, 'exact', 'normalized_exact_alias')
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'unsupported_value_shape')

    def test_status_by_tier(self):
        q = make_question(text='Email Address', input_type='text')
        res_exact = render(q, 'contact.email', self.bank, 'exact', 'alias')
        self.assertEqual(res_exact['status'], 'ready')

        res_semantic = render(q, 'contact.email', self.bank, 'semantic', 'embedding')
        self.assertEqual(res_semantic['status'], 'review')

        res_qwen = render(q, 'contact.email', self.bank, 'qwen', 'llm')
        self.assertEqual(res_qwen['status'], 'review')


class TestResolveExact(unittest.TestCase):
    def setUp(self):
        self.bank = make_bank()

    def test_resolve_exact_success(self):
        q = make_question(text='Email Address', input_type='text')
        res = resolve_exact(q, self.bank)
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['tier'], 'exact')
        self.assertEqual(res['fact_key'], 'contact.email')
        self.assertEqual(res['answer'], 'ada@example.com')
        self.assertEqual(res['reason'], 'normalized_exact_alias')

    def test_resolve_exact_abstains_on_unknown(self):
        q = make_question(text='What is your favorite book?', input_type='text')
        res = resolve_exact(q, self.bank)
        self.assertEqual(res['status'], 'needs_user')
        self.assertIsNone(res['fact_key'])
        self.assertIsNone(res['answer'])
        self.assertEqual(res['reason'], 'no_exact_match')

    def test_resolve_exact_abstains_on_blocked_warning(self):
        q = make_question(text='Email Address', input_type='text', warnings=['label_conflict'])
        res = resolve_exact(q, self.bank)
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'conflicting_or_missing_label')


class TestResolveSemantic(unittest.TestCase):
    def setUp(self):
        self.bank = make_bank()

    def test_empty_candidates(self):
        q = make_question(text='Mobile Phone', input_type='text')
        semantic = DummySemantic(candidates_map={})
        res = resolve_semantic(q, self.bank, semantic)
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['tier'], 'semantic')
        self.assertEqual(res['reason'], 'no_semantic_candidates')
        self.assertIsNone(res['fact_key'])

    def test_top_score_below_threshold(self):
        q = make_question(text='Mobile Phone', input_type='text')
        semantic = DummySemantic(
            candidates_map={
                'q1': [{'fact_key': 'contact.phone', 'score': 0.70}],
            },
            threshold=0.82,
            margin=0.06,
        )
        res = resolve_semantic(q, self.bank, semantic)
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['tier'], 'semantic')
        self.assertEqual(res['reason'], 'below_similarity_or_margin_threshold')
        self.assertEqual(res['similarity'], 0.70)
        self.assertEqual(res['margin'], 0.70)

    def test_margin_below_threshold(self):
        q = make_question(text='Mobile Phone', input_type='text')
        semantic = DummySemantic(
            candidates_map={
                'q1': [
                    {'fact_key': 'contact.phone', 'score': 0.90},
                    {'fact_key': 'contact.email', 'score': 0.88},
                ],
            },
            threshold=0.82,
            margin=0.06,
        )
        res = resolve_semantic(q, self.bank, semantic)
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['tier'], 'semantic')
        self.assertEqual(res['reason'], 'below_similarity_or_margin_threshold')
        self.assertEqual(res['similarity'], 0.90)
        self.assertEqual(res['margin'], 0.02)

    def test_successful_match(self):
        q = make_question(text='Mobile Phone', input_type='text')
        semantic = DummySemantic(
            candidates_map={
                'q1': [
                    {'fact_key': 'contact.phone', 'score': 0.92},
                    {'fact_key': 'contact.email', 'score': 0.80},
                ],
            },
            threshold=0.82,
            margin=0.06,
        )
        res = resolve_semantic(q, self.bank, semantic)
        self.assertEqual(res['status'], 'review')
        self.assertEqual(res['tier'], 'semantic')
        self.assertEqual(res['fact_key'], 'contact.phone')
        self.assertEqual(res['answer'], '+15551234567')
        self.assertEqual(res['reason'], 'local_embedding_match')
        self.assertEqual(res['similarity'], 0.92)
        self.assertEqual(res['margin'], 0.12)
        self.assertIn('candidates', res)


class TestResolveCascade(unittest.TestCase):
    def setUp(self):
        self.bank = make_bank()

    def test_resolve_cascade_tiers(self):
        # q1: exact match
        q1 = make_question(question_id='q1', text='Email Address', input_type='text')
        # q2: semantic match
        q2 = make_question(question_id='q2', text='Primary Mobile Phone', input_type='text')
        # q3: unknown to exact & semantic, resolved by LLM
        q3 = make_question(
            question_id='q3',
            text='What degree did you finish?',
            input_type='single_choice',
            options={
                'items': [{'id': 'o1', 'label': "Bachelor's Degree", 'value': 'bs'}],
                'complete': True,
            },
        )
        # q4: completely unsupported
        q4 = make_question(question_id='q4', text='Favorite color?', input_type='text')

        semantic = DummySemantic(
            candidates_map={
                'q2': [{'fact_key': 'contact.phone', 'score': 0.94}],
                'q3': [{'fact_key': 'education.degree', 'score': 0.50}],  # below threshold
            },
            threshold=0.82,
            margin=0.06,
        )

        llm = DummyLLM(
            predictions={
                'q3': {'fact_key': 'education.degree', 'reason': 'model_selected_supported_fact'},
                'q4': {'fact_key': None, 'reason': 'model_abstained'},
            },
            calls=[{'model': 'qwen', 'status': 'ok', 'usage': {'prompt_tokens': 100}}],
        )

        cascade = resolve_cascade([q1, q2, q3, q4], self.bank, semantic, llm)
        results = cascade['results']

        self.assertEqual(len(results), 4)
        # q1 exact
        self.assertEqual(results[0]['status'], 'ready')
        self.assertEqual(results[0]['tier'], 'exact')
        self.assertEqual(results[0]['fact_key'], 'contact.email')

        # q2 semantic
        self.assertEqual(results[1]['status'], 'review')
        self.assertEqual(results[1]['tier'], 'semantic')
        self.assertEqual(results[1]['fact_key'], 'contact.phone')

        # q3 LLM
        self.assertEqual(results[2]['status'], 'review')
        self.assertEqual(results[2]['tier'], 'qwen')
        self.assertEqual(results[2]['fact_key'], 'education.degree')

        # q4 abstained
        self.assertEqual(results[3]['status'], 'needs_user')
        self.assertEqual(results[3]['tier'], 'qwen')
        self.assertIsNone(results[3]['fact_key'])

        # Semantic was not asked about q1
        self.assertNotIn('q1', semantic.ranked_queries)
        # LLM was asked only about q3 and q4
        self.assertEqual(llm.matched_batches, [['q3', 'q4']])

        # Structure & elapsed_ms
        self.assertIn('elapsed_ms', cascade)
        self.assertIsInstance(cascade['elapsed_ms'], (int, float))
        self.assertGreaterEqual(cascade['elapsed_ms'], 0.0)
        self.assertEqual(
            cascade['calls'],
            [{'model': 'qwen', 'status': 'ok', 'usage': {'prompt_tokens': 100}}],
        )

    def test_resolve_cascade_without_llm(self):
        q1 = make_question(question_id='q1', text='Email Address', input_type='text')
        q2 = make_question(question_id='q2', text='Unmatched Question', input_type='text')
        semantic = DummySemantic(candidates_map={})

        cascade = resolve_cascade([q1, q2], self.bank, semantic, llm=None)
        self.assertEqual(cascade['calls'], [])
        self.assertEqual(cascade['results'][0]['status'], 'ready')
        self.assertEqual(cascade['results'][1]['status'], 'needs_user')


class TestPendingQuestions(unittest.TestCase):
    def test_omits_ready_and_retains_review_and_needs_user(self):
        q1 = make_question(question_id='q1', text='Email Address', input_type='text')
        q2 = make_question(question_id='q2', text='Mobile Phone', input_type='text')
        q3 = make_question(question_id='q3', text='Favorite color?', input_type='text')

        r1 = {'question_id': 'q1', 'status': 'ready'}
        r2 = {'question_id': 'q2', 'status': 'review'}
        r3 = {'question_id': 'q3', 'status': 'needs_user'}

        pending = pending_questions([q1, q2, q3], [r1, r2, r3], scope='board:greenhouse')
        self.assertEqual(len(pending), 2)
        self.assertEqual([p['question']['id'] for p in pending], ['q2', 'q3'])

    def test_deterministic_24_char_hex_pending_id(self):
        q = make_question(
            question_id='q-rev',
            text='Highest Degree Completed?',
            input_type='single_choice',
            section='1. Education Information',
            options={
                'items': [
                    {'id': 'opt-1', 'label': 'High School', 'value': 'hs'},
                    {'id': 'opt-2', 'label': "Bachelor's Degree", 'value': 'bs'},
                ],
                'complete': True,
            },
        )
        r = {'question_id': 'q-rev', 'status': 'review', 'fact_key': 'education.degree'}
        scope = 'company:acme:job:123'

        pending1 = pending_questions([q], [r], scope=scope)
        pending2 = pending_questions([q], [r], scope=scope)

        item = pending1[0]
        pending_id = item['pending_id']
        self.assertEqual(len(pending_id), 24)
        # Must be valid hexadecimal
        self.assertRegex(pending_id, r'^[0-9a-f]{24}$')
        # Deterministic across calls
        self.assertEqual(pending1[0]['pending_id'], pending2[0]['pending_id'])

        # Explicit SHA-256 verification
        expected_sig = '|'.join([
            scope,
            normalize(q['text']),
            q['input_type'],
            normalize(q.get('section') or ''),
            '|'.join(normalize(o.get('label') or '') for o in q['options']['items']),
        ])
        expected_hex = hashlib.sha256(expected_sig.encode()).hexdigest()[:24]
        self.assertEqual(pending_id, expected_hex)
        self.assertEqual(item['scope'], scope)
        self.assertEqual(item['question'], q)
        self.assertEqual(item['proposal'], r)
        self.assertIn('Confirm the fact', item['instruction'])

        # Different scope produces different pending_id
        pending_diff_scope = pending_questions([q], [r], scope='company:other:job:999')
        self.assertNotEqual(pending_id, pending_diff_scope[0]['pending_id'])


class TestRegressionReviewFixes(unittest.TestCase):
    def setUp(self):
        self.bank = make_bank()

    def test_null_warnings_and_options_do_not_crash(self):
        q = make_question(
            question_id='q-nulls',
            text='Email Address',
            input_type='text',
            options=None,
            warnings=None,
        )
        key, status = exact_match(q, self.bank)
        self.assertEqual(key, 'contact.email')
        self.assertEqual(status, 'normalized_exact_alias')

        res = render(q, 'contact.email', self.bank, 'exact', 'normalized_exact_alias')
        self.assertEqual(res['status'], 'ready')

        res_exact = resolve_exact(q, self.bank)
        self.assertEqual(res_exact['status'], 'ready')

        r_review = {'question_id': 'q-nulls', 'status': 'review'}
        pending = pending_questions([q], [r_review], scope='scope:test')
        self.assertEqual(len(pending), 1)

    def test_cascade_halts_on_blocked_warnings(self):
        q_blocked = make_question(
            question_id='q-blocked',
            text='Email Address',
            input_type='text',
            warnings=['label_conflict'],
        )
        semantic = DummySemantic(
            candidates_map={'q-blocked': [{'fact_key': 'contact.email', 'score': 0.99}]}
        )
        llm = DummyLLM(
            predictions={'q-blocked': {'fact_key': 'contact.email', 'reason': 'llm_matched'}}
        )
        cascade = resolve_cascade([q_blocked], self.bank, semantic, llm)
        results = cascade['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['status'], 'needs_user')
        self.assertEqual(results[0]['reason'], 'conflicting_or_missing_label')
        # Assert semantic and LLM are not called for blocked questions
        self.assertNotIn('q-blocked', semantic.ranked_queries)
        self.assertEqual(llm.matched_batches, [])

    def test_custom_option_labels_on_boolean_facts(self):
        bank = make_bank()
        bank['facts']['work.authorized_us']['option_labels'] = ['Authorized', 'US Citizen / PR']
        q = make_question(
            text='Work authorization',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'o1', 'label': 'Authorized', 'value': 'auth'},
                    {'id': 'o2', 'label': 'Other', 'value': 'oth'},
                ],
                'complete': True,
            },
        )
        res = render(q, 'work.authorized_us', bank, 'exact', 'alias')
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['answer'], 'Authorized')
        self.assertEqual(res['selected_option']['id'], 'o1')

    def test_preserved_caller_abstention_reason(self):
        q = make_question(text='Unknown Question', input_type='text')
        res = render(q, None, self.bank, 'exact', 'ambiguous_exact_alias')
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'ambiguous_exact_alias')

        res_default = render(q, None, self.bank, 'exact', None)
        self.assertEqual(res_default['status'], 'needs_user')
        self.assertEqual(res_default['reason'], 'no_supported_fact')

    def test_missing_or_none_label_on_options(self):
        q = make_question(
            text='Degree',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'o1', 'label': None, 'value': 'val1'},
                    {'id': 'o2', 'value': 'val2'},
                    {'id': 'o3', 'label': "Bachelor's Degree", 'value': 'bs'},
                ],
                'complete': True,
            },
        )
        res = render(q, 'education.degree', self.bank, 'exact', 'alias')
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['answer'], "Bachelor's Degree")
        self.assertEqual(res['selected_option']['id'], 'o3')

        r = {'question_id': 'q1', 'status': 'review'}
        pending = pending_questions([q], [r], scope='test:scope')
        self.assertEqual(len(pending), 1)
        self.assertRegex(pending[0]['pending_id'], r'^[0-9a-f]{24}$')

    def test_null_section_does_not_match_section_contains_none(self):
        entry = {'input_types': ['text'], 'section_contains': 'none'}
        q = make_question(input_type='text', section=None)
        self.assertFalse(eligible(q, entry))

    def test_mixed_batch_cascade_preserves_blocked_warning_tier_and_status(self):
        q_blocked = make_question(
            question_id='q-blocked',
            text='Email Address',
            input_type='text',
            warnings=['label_conflict'],
        )
        q_unresolved = make_question(
            question_id='q-unresolved',
            text='Unknown',
            input_type='text',
        )
        semantic = DummySemantic(candidates_map={})
        llm = DummyLLM(
            predictions={
                'q-unresolved': {'fact_key': None, 'reason': 'model_abstained'},
            }
        )
        cascade = resolve_cascade([q_blocked, q_unresolved], self.bank, semantic, llm)
        results = cascade['results']
        self.assertEqual(len(results), 2)
        blocked_res = results[0]
        self.assertEqual(blocked_res['tier'], 'exact')
        self.assertEqual(blocked_res['reason'], 'conflicting_or_missing_label')
        self.assertEqual(blocked_res['status'], 'needs_user')
        self.assertNotIn('q-blocked', semantic.ranked_queries)
        self.assertEqual(llm.matched_batches, [['q-unresolved']])

    def test_render_with_none_option_labels(self):
        bank = make_bank()
        bank['facts']['work.authorized_us']['option_labels'] = None
        bank['facts']['education.degree']['option_labels'] = None

        q_bool = make_question(
            text='Are you legally authorized to work in the United States?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-yes', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-no', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        res_bool = render(q_bool, 'work.authorized_us', bank, 'exact', 'alias')
        self.assertEqual(res_bool['status'], 'ready')
        self.assertEqual(res_bool['answer'], 'Yes')

        q_str = make_question(
            text='Highest Degree Completed',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-deg', 'label': "Bachelor's Degree", 'value': 'bs'},
                ],
                'complete': True,
            },
        )
        res_str = render(q_str, 'education.degree', bank, 'exact', 'alias')
        self.assertEqual(res_str['status'], 'ready')
        self.assertEqual(res_str['answer'], "Bachelor's Degree")

    def test_pending_questions_with_none_scope(self):
        q = make_question(question_id='q-scope-none', text='Email Address', input_type='text')
        r = {'question_id': 'q-scope-none', 'status': 'needs_user'}
        pending = pending_questions([q], [r], scope=None)
        self.assertEqual(len(pending), 1)
        pending_id = pending[0]['pending_id']
        self.assertEqual(len(pending_id), 24)
        self.assertRegex(pending_id, r'^[0-9a-f]{24}$')
        self.assertIsNone(pending[0]['scope'])

    def test_exact_match_blank_and_none_text(self):
        for blank_val in ('', '   ', None):
            q = make_question(text=blank_val, input_type='text')
            key, status = exact_match(q, self.bank)
            self.assertIsNone(key, f'Failed for blank text {blank_val!r}')
            self.assertEqual(status, 'no_exact_match', f'Failed for blank text {blank_val!r}')

    def test_resolve_semantic_direct_blocked_warning(self):
        q = make_question(text='Email Address', input_type='text', warnings=['label_conflict'])
        semantic = DummySemantic(candidates_map={})
        res = resolve_semantic(q, self.bank, semantic)
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'conflicting_or_missing_label')
        self.assertEqual(res['tier'], 'semantic')
        self.assertEqual(len(semantic.ranked_queries), 0)

    def test_bachelor_profile_master_only_needs_user(self):
        from job_applier.resolution.__main__ import _build_bank_from_profile_and_answers
        profile = {'degree': "Bachelor's Degree"}
        bank = _build_bank_from_profile_and_answers(profile, [])
        q = make_question(
            text='Highest Degree Completed',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-ms', 'label': "Master's Degree", 'value': 'masters'},
                    {'id': 'opt-phd', 'label': "PhD", 'value': 'phd'},
                ],
                'complete': True,
            },
        )
        res = render(q, 'education.degree', bank, 'exact', 'alias')
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'option_not_uniquely_observed')

    def test_normal_multidegree_picks_actual_bachelor_uniquely(self):
        from job_applier.resolution.__main__ import _build_bank_from_profile_and_answers
        profile = {'degree': "Bachelor of Science"}
        bank = _build_bank_from_profile_and_answers(profile, [])
        q = make_question(
            text='Highest Degree Completed',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-hs', 'label': "High School", 'value': 'hs'},
                    {'id': 'opt-bs', 'label': "Bachelor of Science", 'value': 'bs'},
                    {'id': 'opt-ms', 'label': "Master of Science", 'value': 'ms'},
                    {'id': 'opt-phd', 'label': "PhD", 'value': 'phd'},
                ],
                'complete': True,
            },
        )
        res = render(q, 'education.degree', bank, 'exact', 'alias')
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['answer'], "Bachelor of Science")
        self.assertEqual(res['selected_option']['value'], "bs")

    def test_degree_cross_qualification_aliases_removed_exact_semantics(self):
        from job_applier.resolution.__main__ import _build_bank_from_profile_and_answers

        cases_needs_user = [
            # High School Diploma vs Master
            ("High School Diploma", "Master's Degree", "opt-ms", "ms"),
            # MBA vs Bachelor
            ("MBA", "Bachelor of Science", "opt-bs", "bs"),
            # PhD Mathematics vs Master
            ("PhD Mathematics", "Master of Science", "opt-ms", "ms"),
            # BS vs BA
            ("BS", "BA", "opt-ba", "ba"),
            # MS vs MA
            ("MS", "MA", "opt-ma", "ma"),
        ]

        for profile_degree, opt_label, opt_id, opt_val in cases_needs_user:
            with self.subTest(profile_degree=profile_degree, opt_label=opt_label):
                profile = {'degree': profile_degree}
                bank = _build_bank_from_profile_and_answers(profile, [])
                q = make_question(
                    text='Highest Degree Completed',
                    input_type='single_choice',
                    options={
                        'items': [
                            {'id': opt_id, 'label': opt_label, 'value': opt_val},
                        ],
                        'complete': True,
                    },
                )
                res = render(q, 'education.degree', bank, 'exact', 'alias')
                self.assertEqual(res['status'], 'needs_user')
                self.assertEqual(res['reason'], 'option_not_uniquely_observed')

        cases_exact_success = [
            ("BS", "BS", "opt-bs", "bs"),
            ("MS", "MS", "opt-ms", "ms"),
            ("Bachelor of Science", "Bachelor of Science", "opt-bs", "bs"),
            ("Master of Science", "Master of Science", "opt-ms", "ms"),
            ("High School Diploma", "High School Diploma", "opt-hs", "hs"),
        ]

        for profile_degree, opt_label, opt_id, opt_val in cases_exact_success:
            with self.subTest(exact_degree=profile_degree):
                profile = {'degree': profile_degree}
                bank = _build_bank_from_profile_and_answers(profile, [])
                q = make_question(
                    text='Highest Degree Completed',
                    input_type='single_choice',
                    options={
                        'items': [
                            {'id': opt_id, 'label': opt_label, 'value': opt_val},
                        ],
                        'complete': True,
                    },
                )
                res = render(q, 'education.degree', bank, 'exact', 'alias')
                self.assertEqual(res['status'], 'ready')
                self.assertEqual(res['answer'], profile_degree)
                self.assertEqual(res['selected_option']['value'], opt_val)

    def test_safe_io_atomic_no_clobber_competing_creation(self):
        import concurrent.futures
        from job_applier.safe_io import write_bytes_atomic
        with tempfile.TemporaryDirectory() as td:
            target_file = Path(td) / 'test_competing.bin'
            results = []
            errors = []

            def worker(data):
                try:
                    write_bytes_atomic(target_file, data, overwrite=False)
                    return True
                except FileExistsError:
                    return False

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                futs = [ex.submit(worker, f"data-{i}".encode('utf-8')) for i in range(5)]
                for f in concurrent.futures.as_completed(futs):
                    res = f.result()
                    results.append(res)

            # Exactly one creation succeeded, other four got FileExistsError
            self.assertEqual(results.count(True), 1)
            self.assertEqual(results.count(False), 4)

    def test_safe_io_symlink_refusal_destination_and_parent(self):
        from job_applier.safe_io import write_bytes_atomic
        with tempfile.TemporaryDirectory() as td:
            real_file = Path(td) / 'secret_real.txt'
            real_file.write_text('secret-original', encoding='utf-8')
            symlink_dest = Path(td) / 'symlink_dest.txt'
            symlink_dest.symlink_to(real_file)

            # Refuse writing to symlink destination with target unchanged
            with self.assertRaises(ValueError) as ctx:
                write_bytes_atomic(symlink_dest, b'malicious payload', overwrite=False)
            self.assertIn("Refusing to write to symlink", str(ctx.exception))
            self.assertEqual(real_file.read_text(encoding='utf-8'), 'secret-original')

            with self.assertRaises(ValueError) as ctx2:
                write_bytes_atomic(symlink_dest, b'malicious payload', overwrite=True)
            self.assertIn("Refusing to write to symlink", str(ctx2.exception))
            self.assertEqual(real_file.read_text(encoding='utf-8'), 'secret-original')

            # Refuse writing through symlink parent directory
            real_dir = Path(td) / 'real_dir'
            real_dir.mkdir(mode=0o700)
            symlink_dir = Path(td) / 'symlink_dir'
            symlink_dir.symlink_to(real_dir)
            nested_file = symlink_dir / 'child.txt'
            with self.assertRaises(ValueError) as ctx3:
                write_bytes_atomic(nested_file, b'data', overwrite=False)
            self.assertIn("Refusing to access path through symlink", str(ctx3.exception))

    def test_safe_io_overwrite_shorter_output_exact_bytes_and_0600(self):
        import stat
        from job_applier.safe_io import write_bytes_atomic
        with tempfile.TemporaryDirectory() as td:
            target_file = Path(td) / 'shorter_test.bin'
            write_bytes_atomic(target_file, b'A' * 200, overwrite=False)
            self.assertEqual(len(target_file.read_bytes()), 200)

            # Overwrite with shorter content (20 bytes)
            write_bytes_atomic(target_file, b'B' * 20, overwrite=True)
            content = target_file.read_bytes()
            self.assertEqual(content, b'B' * 20)
            self.assertEqual(len(content), 20)
            mode = stat.S_IMODE(target_file.stat().st_mode)
            self.assertEqual(mode, 0o600)
            # Parent directory mode 0700
            parent_mode = stat.S_IMODE(target_file.parent.stat().st_mode)
            self.assertEqual(parent_mode, 0o700)


class TestPriorEmployeeResolution(unittest.TestCase):
    def setUp(self):
        from job_applier.resolution.__main__ import _build_bank_from_profile_and_answers
        self._build_bank = _build_bank_from_profile_and_answers

    def test_absent_employer_complex_greenhouse_options(self):
        # Absent employer: question asks about Affirm, resume has Acme Corp
        resume = {'experience': [{'company': 'Acme Corp'}]}
        bank = self._build_bank({}, [], resume=resume)
        q = make_question(
            question_id='q-prior-absent',
            text='Have you previously been employed at Affirm for any length of time?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-yes', 'label': 'I have previously been employed at Affirm', 'value': 'yes'},
                    {'id': 'opt-no', 'label': 'I have not previously been employed at Affirm', 'value': 'no'},
                ],
                'complete': True,
            },
        )
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['answer'], 'I have not previously been employed at Affirm')
        self.assertEqual(res['selected_option']['id'], 'opt-no')
        self.assertEqual(res['selected_option']['label'], 'I have not previously been employed at Affirm')
        self.assertEqual(res['source'], 'resume_absence')

    def test_generic_yes_no_question(self):
        # Generic Yes/No question -> resolves to ready, selects "No"
        resume = {'experience': [{'company': 'Acme Corp'}]}
        bank = self._build_bank({}, [], resume=resume)
        q = make_question(
            question_id='q-prior-yesno',
            text='Have you previously worked for this company?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['answer'], 'No')
        self.assertEqual(res['selected_option']['id'], 'opt-n')
        self.assertEqual(res['source'], 'resume_absence')

    def test_known_employer_on_resume_abstains(self):
        # Known employer on resume -> abstains with needs_user and reason 'prior_employer_present_in_resume'
        resume = {'experience': [{'company': 'Acme Corp'}]}
        bank = self._build_bank({}, [], resume=resume)
        q = make_question(
            question_id='q-prior-known',
            text='Have you previously worked at Acme Corp?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'prior_employer_present_in_resume')
        self.assertIsNone(res['fact_key'])
        self.assertIsNone(res['answer'])

    def test_former_employee_alias(self):
        # Former employee alias -> resolves to ready, selects "No"
        resume = {'experience': [{'company': 'Acme Corp'}]}
        bank = self._build_bank({}, [], resume=resume)
        q = make_question(
            question_id='q-prior-former',
            text='Are you a former employee of this company?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['answer'], 'No')
        self.assertEqual(res['selected_option']['id'], 'opt-n')
        self.assertEqual(res['source'], 'resume_absence')

    def test_known_employer_from_profile_org_abstains(self):
        # Known employer extracted from profile experience using 'org' field
        profile = {'experience': [{'org': 'Beta Dynamics'}]}
        bank = self._build_bank(profile, [])
        q = make_question(
            question_id='q-prior-profile-org',
            text='Have you ever worked at Beta Dynamics?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'prior_employer_present_in_resume')
        self.assertIsNone(res['fact_key'])
        self.assertIsNone(res['answer'])

    def test_negative_options_variations(self):
        resume = {'experience': [{'company': 'Acme Corp'}]}
        bank = self._build_bank({}, [], resume=resume)

        # "I have never worked at this company"
        q1 = make_question(
            question_id='q-never',
            text='Have you previously been employed at this company for any length of time?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-1', 'label': 'I have worked here before', 'value': 'worked'},
                    {'id': 'opt-2', 'label': 'I have never worked at this company', 'value': 'never'},
                ],
                'complete': True,
            },
        )
        res1 = resolve_exact(q1, bank)
        self.assertEqual(res1['status'], 'ready')
        self.assertEqual(res1['answer'], 'I have never worked at this company')
        self.assertEqual(res1['selected_option']['id'], 'opt-2')

        # "Not a former employee"
        q2 = make_question(
            question_id='q-not-former',
            text='Former Employee',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-1', 'label': 'Former employee', 'value': 'former'},
                    {'id': 'opt-2', 'label': 'Not a former employee', 'value': 'not_former'},
                ],
                'complete': True,
            },
        )
        res2 = resolve_exact(q2, bank)
        self.assertEqual(res2['status'], 'ready')
        self.assertEqual(res2['answer'], 'Not a former employee')
        self.assertEqual(res2['selected_option']['id'], 'opt-2')

    def test_government_federal_public_excluded(self):
        resume = {'experience': [{'company': 'Acme Corp'}]}
        bank = self._build_bank({}, [], resume=resume)
        q = make_question(
            question_id='q-gov',
            text='Were you previously employed by the federal government?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        key, reason = exact_match(q, bank)
        self.assertNotEqual(key, 'work.prior_employee')
        self.assertEqual(key, None)
        self.assertEqual(reason, 'no_exact_match')

    def test_skill_and_remote_questions_do_not_match_prior_employee(self):
        bank = self._build_bank({}, [])
        skill_remote_questions = [
            'Have you previously worked with Python?',
            'Have you ever worked remotely?',
            'Have you worked using Docker?',
            'Have you previously worked on night shifts?',
            'Have you previously worked weekends or overtime?',
            'Have you worked with distributed systems?',
            'Have you previously worked on machine learning projects?',
        ]
        for q_text in skill_remote_questions:
            q = make_question(
                question_id=f"q-skill-{abs(hash(q_text)) % 10000}",
                text=q_text,
                input_type='single_choice',
                options={
                    'items': [
                        {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                        {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                    ],
                    'complete': True,
                },
            )
            key, reason = exact_match(q, bank)
            self.assertNotEqual(key, 'work.prior_employee', f"Question '{q_text}' incorrectly matched prior_employee")
            self.assertEqual(key, None)
            res = resolve_exact(q, bank)
            self.assertEqual(res['status'], 'needs_user')
            self.assertIsNone(res['fact_key'])

    def test_positive_option_with_negation_clause_abstains(self):
        resume = {'experience': [{'company': 'Acme Corp'}]}
        bank = self._build_bank({}, [], resume=resume)
        q = make_question(
            question_id='q-pos-neg-clause',
            text='Have you previously worked for this company?',
            input_type='single_choice',
            options={
                'items': [
                    {
                        'id': 'opt-1',
                        'label': 'I was previously employed, but not at this company',
                        'value': 'was_employed',
                    },
                    {
                        'id': 'opt-2',
                        'label': 'Yes, currently employed',
                        'value': 'currently_employed',
                    },
                ],
                'complete': True,
            },
        )
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'option_not_uniquely_observed')
        self.assertIsNone(res.get('selected_option'))
        self.assertIsNone(res['fact_key'])
        self.assertIsNone(res['answer'])

    def test_employer_substring_intra_token_does_not_abstain(self):
        # Candidate worked at 'Cat' and 'In' and 'Co' (intra-token substrings or stopwords)
        resume = {'experience': [{'company': 'Cat'}, {'company': 'In'}, {'company': 'Co'}]}
        bank = self._build_bank({}, [], resume=resume)
        q = make_question(
            question_id='q-intra-token',
            text='Have you previously been employed at Affirm for any length of time?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-yes', 'label': 'I have previously been employed at Affirm', 'value': 'yes'},
                    {'id': 'opt-no', 'label': 'I have not previously been employed at Affirm', 'value': 'no'},
                ],
                'complete': True,
            },
        )
        res = resolve_exact(q, bank)
        # Word boundary and stopword guards prevent false abstain
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['answer'], 'I have not previously been employed at Affirm')
        self.assertEqual(res['selected_option']['id'], 'opt-no')

    def test_corporate_suffix_matching_abstains(self):
        # Candidate worked at 'Acme Corp'; question asks about core name 'Acme'
        resume = {'experience': [{'company': 'Acme Corp'}]}
        bank = self._build_bank({}, [], resume=resume)
        q = make_question(
            question_id='q-corp-suffix',
            text='Have you previously worked at Acme?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'prior_employer_present_in_resume')
        self.assertIsNone(res['fact_key'])

        # Also test LLC suffix
        resume_llc = {'experience': [{'company': 'Globex LLC'}]}
        bank_llc = self._build_bank({}, [], resume=resume_llc)
        q_llc = make_question(
            question_id='q-llc-suffix',
            text='Have you ever worked at Globex?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        res_llc = resolve_exact(q_llc, bank_llc)
        self.assertEqual(res_llc['status'], 'needs_user')
        self.assertEqual(res_llc['reason'], 'prior_employer_present_in_resume')

    def test_build_bank_handles_none_profile_and_schema_variants(self):
        # 1. profile = None must not raise AttributeError
        bank = self._build_bank(None, [])
        self.assertIn('facts', bank)
        self.assertIn('questions', bank)
        self.assertIn('work.prior_employee', bank['facts'])

        # 2. Schema variants for employer: company, org, name, employer, organization
        profile = {
            'experience': [
                {'name': 'Company Alpha'},
                {'employer': 'Beta Systems'},
            ]
        }
        resume = {
            'experience': [
                {'organization': 'Gamma Labs'},
                {'org': 'Delta Tech'},
                {'company': 'Epsilon Inc'},
            ]
        }
        bank_variants = self._build_bank(profile, [], resume=resume)
        known_employers = bank_variants['facts']['work.prior_employee']['known_employers']
        self.assertIn('company alpha', known_employers)
        self.assertIn('beta systems', known_employers)
        self.assertIn('gamma labs', known_employers)
        self.assertIn('delta tech', known_employers)
        self.assertIn('epsilon inc', known_employers)

    def test_user_answers_override_prior_employee_default(self):
        # Explicit user answer 'Yes' overrides default 'No'
        raw_answers = [
            {'key': 'prior_employee', 'answer': 'Yes', 'source': 'user_vault'},
        ]
        bank = self._build_bank({}, raw_answers)
        fact = bank['facts']['work.prior_employee']
        self.assertEqual(fact['value'], 'Yes')
        self.assertEqual(fact['source'], 'user_vault')
        self.assertTrue(fact['confirmed'])

        # Question resolution selects 'Yes'
        q = make_question(
            question_id='q-override-yes',
            text='Have you previously worked for this company?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['answer'], 'Yes')
        self.assertEqual(res['selected_option']['id'], 'opt-y')
        self.assertEqual(res['source'], 'user_vault')

    def test_general_experience_questions_do_not_match_prior_employee(self):
        bank = self._build_bank({}, [])
        general_experience_questions = [
            'Have you ever worked at scale?',
            'Have you ever worked at a startup?',
            'Have you ever worked for an agency?',
            'Have you previously worked in an enterprise environment?',
            'Do you affirm that you have previously worked in an office?',
        ]
        for q_text in general_experience_questions:
            q = make_question(
                question_id=f"q-gen-{abs(hash(q_text)) % 10000}",
                text=q_text,
                input_type='single_choice',
                options={
                    'items': [
                        {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                        {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                    ],
                    'complete': True,
                },
            )
            key, reason = exact_match(q, bank)
            self.assertNotEqual(key, 'work.prior_employee', f"Question '{q_text}' incorrectly matched prior_employee")
            self.assertIsNone(key)
            res = resolve_exact(q, bank)
            self.assertEqual(res['status'], 'needs_user')
            self.assertIsNone(res['fact_key'])

    def test_negative_option_guard_rejects_affirmative_contractor_option(self):
        resume = {'experience': [{'company': 'Acme Corp'}]}
        bank = self._build_bank({}, [], resume=resume)
        # Option starting with 'No' but affirming contractor work
        q1 = make_question(
            question_id='q-contractor-reject',
            text='Have you previously worked for this company?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-1', 'label': 'Yes, I was a full-time employee', 'value': 'full_time'},
                    {'id': 'opt-2', 'label': 'No, I worked here as a contractor', 'value': 'contractor'},
                ],
                'complete': True,
            },
        )
        res1 = resolve_exact(q1, bank)
        self.assertEqual(res1['status'], 'needs_user')
        self.assertEqual(res1['reason'], 'option_not_uniquely_observed')
        self.assertIsNone(res1.get('selected_option'))

        # When a true negative option is also present, it selects the true negative
        q2 = make_question(
            question_id='q-contractor-with-never',
            text='Have you previously worked for this company?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-1', 'label': 'Yes, I was an employee', 'value': 'emp'},
                    {'id': 'opt-2', 'label': 'No, I worked here as a contractor', 'value': 'contractor'},
                    {'id': 'opt-3', 'label': 'No, I have never worked here', 'value': 'never'},
                ],
                'complete': True,
            },
        )
        res2 = resolve_exact(q2, bank)
        self.assertEqual(res2['status'], 'ready')
        self.assertEqual(res2['answer'], 'No, I have never worked here')
        self.assertEqual(res2['selected_option']['id'], 'opt-3')

    def test_resume_with_the_company_does_not_falsely_abstain_on_the_word(self):
        # Employer named 'The Company' -> 'the' must be in EMPLOYER_STOPWORDS so it doesn't match 'the' in questions
        resume = {'experience': [{'company': 'The Company'}]}
        bank = self._build_bank({}, [], resume=resume)
        q = make_question(
            question_id='q-the-stopword',
            text='Have you previously worked for this company?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['answer'], 'No')
        self.assertEqual(res['selected_option']['id'], 'opt-n')

    def test_standard_json_resume_work_key_extracted(self):
        # Standard JSON Resume schema uses top-level 'work' key with 'name'
        resume = {
            'work': [
                {'name': 'Initech LLC', 'position': 'Software Engineer'}
            ]
        }
        bank = self._build_bank({}, [], resume=resume)
        known_employers = bank['facts']['work.prior_employee']['known_employers']
        self.assertIn('initech llc', known_employers)

        # Question mentioning Initech should abstain because employer is on resume
        q = make_question(
            question_id='q-initech-prior',
            text='Have you previously worked at Initech?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'prior_employer_present_in_resume')

    def test_resolve_cascade_handles_question_id_key_safely(self):
        from job_applier.resolution.__main__ import NullSemanticMatcher
        bank = self._build_bank({}, [])
        q = {
            'question_id': 'qid-cascade-test',
            'text': 'Some unknown question that requires user input?',
            'input_type': 'single_choice',
            'options': {
                'items': [
                    {'id': 'opt-1', 'label': 'Option A', 'value': 'A'},
                    {'id': 'opt-2', 'label': 'Option B', 'value': 'B'},
                ],
                'complete': True,
            },
        }
        out = resolve_cascade([q], bank, NullSemanticMatcher())
        self.assertIn('results', out)
        self.assertEqual(len(out['results']), 1)
        self.assertEqual(out['results'][0]['question_id'], 'qid-cascade-test')
        self.assertEqual(out['results'][0]['status'], 'needs_user')

        pending = pending_questions([q], out['results'], scope='greenhouse')
        self.assertEqual(len(pending), 1)
        self.assertIn('pending_id', pending[0])

    def test_negative_option_guard_rejects_affirmative_contractor_bypass(self):
        resume = {'experience': [{'company': 'Acme Corp'}]}
        bank = self._build_bank({}, [], resume=resume)
        q = make_question(
            question_id='q-contractor-bypass',
            text='Have you previously worked for this company?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-1', 'label': 'Yes, I was an employee', 'value': 'employee'},
                    {'id': 'opt-2', 'label': 'No, not an employee, I worked here as a contractor', 'value': 'contractor'},
                ],
                'complete': True,
            },
        )
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'needs_user')
        self.assertEqual(res['reason'], 'option_not_uniquely_observed')
        self.assertIsNone(res.get('selected_option'))

    def test_resume_with_the_company_does_not_abstain_on_standard_question(self):
        resume = {'experience': [{'company': 'The Company'}]}
        bank = self._build_bank({}, [], resume=resume)
        q = make_question(
            question_id='q-the-company-std',
            text='Have you previously worked for the company?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['answer'], 'No')
        self.assertEqual(res['selected_option']['id'], 'opt-n')

    def test_general_work_at_another_company_does_not_match_prior_employee(self):
        resume = {'experience': [{'company': 'Acme Corp'}]}
        bank = self._build_bank({}, [], resume=resume)
        q = make_question(
            question_id='q-another-company',
            text='Have you previously worked at another company?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        key, reason = exact_match(q, bank)
        self.assertNotEqual(key, 'work.prior_employee')
        self.assertIsNone(key)
        self.assertEqual(reason, 'no_exact_match')
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'needs_user')
        self.assertIsNone(res['fact_key'])

    def test_sponsorship_without_temporality_does_not_match_us_sponsorship(self):
        bank = self._build_bank({}, [])
        q = make_question(
            question_id='q-sponsorship-notemp',
            text='Will you require sponsorship?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        key, reason = exact_match(q, bank)
        self.assertNotEqual(key, 'work.us_sponsorship_now_or_future')
        self.assertIsNone(key)
        self.assertEqual(reason, 'no_exact_match')
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'needs_user')
        self.assertIsNone(res['fact_key'])

    def test_negative_option_guard_rejects_internship_and_apprentice_variants(self):
        resume = {'experience': [{'company': 'Acme Corp'}]}
        bank = self._build_bank({}, [], resume=resume)
        labels_to_reject = [
            'No, completed an internship here',
            'No, interned at this company',
            'No, was an apprentice here',
            'No, completed an apprenticeship',
            'No, worked as a consultant',
            'No, was a temp worker',
            'No, temporary employee',
            'No, seasonal worker',
            'No, worked as a vendor',
            'No, was a coop',
            'No, was a fellow',
            'No, was an extern',
        ]
        for idx, lbl in enumerate(labels_to_reject):
            # When only affirmative and this pseudo-negative role option are present, must abstain
            q1 = make_question(
                question_id=f'q-reject-role-{idx}',
                text='Have you previously worked for this company?',
                input_type='single_choice',
                options={
                    'items': [
                        {'id': 'opt-1', 'label': 'Yes, I was a regular employee', 'value': 'regular'},
                        {'id': 'opt-2', 'label': lbl, 'value': 'role_val'},
                    ],
                    'complete': True,
                },
            )
            res1 = resolve_exact(q1, bank)
            self.assertEqual(res1['status'], 'needs_user', f"Option '{lbl}' was not rejected")
            self.assertEqual(res1['reason'], 'option_not_uniquely_observed')
            self.assertIsNone(res1.get('selected_option'))

            # When a true negative option is also present, it selects the true negative
            q2 = make_question(
                question_id=f'q-true-neg-{idx}',
                text='Have you previously worked for this company?',
                input_type='single_choice',
                options={
                    'items': [
                        {'id': 'opt-1', 'label': 'Yes, I was a regular employee', 'value': 'regular'},
                        {'id': 'opt-2', 'label': lbl, 'value': 'role_val'},
                        {'id': 'opt-3', 'label': 'No, I have never worked here', 'value': 'never'},
                    ],
                    'complete': True,
                },
            )
            res2 = resolve_exact(q2, bank)
            self.assertEqual(res2['status'], 'ready', f"Option '{lbl}' interfered with true negative")
            self.assertEqual(res2['answer'], 'No, I have never worked here')
            self.assertEqual(res2['selected_option']['id'], 'opt-3')

    def test_office_near_here_does_not_match_prior_employee(self):
        bank = self._build_bank({}, [])
        q = make_question(
            question_id='q-office-near-here',
            text='Have you ever worked in an office near here?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        key, reason = exact_match(q, bank)
        self.assertNotEqual(key, 'work.prior_employee')
        self.assertIsNone(key)
        self.assertEqual(reason, 'no_exact_match')
        res = resolve_exact(q, bank)
        self.assertEqual(res['status'], 'needs_user')
        self.assertIsNone(res['fact_key'])

    def test_render_handles_fact_without_source_key(self):
        bank = {
            'facts': {
                'contact.email': {
                    'value': 'test@example.com',
                    'confirmed': True,
                }
            },
            'questions': [
                {
                    'fact': 'contact.email',
                    'input_types': ['text', 'email'],
                    'aliases': ['Email Address'],
                }
            ]
        }
        q = make_question(question_id='q-email-no-source', text='Email Address', input_type='text')
        res = render(q, 'contact.email', bank, 'exact', 'test_exact_reason')
        self.assertEqual(res['status'], 'ready')
        self.assertEqual(res['source'], 'vault')
        self.assertEqual(res['answer'], 'test@example.com')

    def test_exact_match_handles_malformed_bank_safely(self):
        q = make_question(question_id='q-malformed', text='Email Address', input_type='text')

        # 1. Bank completely missing 'questions' key
        key1, reason1 = exact_match(q, {})
        self.assertIsNone(key1)
        self.assertEqual(reason1, 'no_exact_match')

        # 2. Bank with 'questions' set to None
        key2, reason2 = exact_match(q, {'questions': None})
        self.assertIsNone(key2)
        self.assertEqual(reason2, 'no_exact_match')

        # 3. Entries missing 'aliases' or 'fact' or not dictionaries
        malformed_bank = {
            'questions': [
                None,
                'invalid_entry_string',
                {},
                {'fact': None, 'aliases': ['Email Address']},
                {'fact': 'contact.email', 'aliases': None, 'input_types': ['text']},
                {'fact': 'contact.email', 'input_types': ['text']},
            ]
        }
        key3, reason3 = exact_match(q, malformed_bank)
        self.assertIsNone(key3)
        self.assertEqual(reason3, 'no_exact_match')

        # 4. Bank with malformed entries alongside valid entry matches correctly
        valid_bank = {
            'questions': [
                None,
                {},
                {'fact': 'contact.email', 'aliases': None},
                {'fact': 'contact.email', 'aliases': ['Email Address'], 'input_types': ['text']},
            ]
        }
        key4, reason4 = exact_match(q, valid_bank)
        self.assertEqual(key4, 'contact.email')
        self.assertEqual(reason4, 'normalized_exact_alias')

    def test_render_handles_malformed_bank_questions_safely(self):
        q = make_question(question_id='q-render-malformed', text='Email Address', input_type='text')
        bank_facts = {
            'facts': {
                'contact.email': {
                    'value': 'user@example.com',
                    'confirmed': True,
                    'source': 'vault',
                }
            }
        }

        # 1. bank['questions'] is None
        bank_none_q = dict(bank_facts, questions=None)
        res1 = render(q, 'contact.email', bank_none_q, 'exact', 'test_reason')
        self.assertEqual(res1['status'], 'needs_user')
        self.assertEqual(res1['reason'], 'incompatible_fact_type_or_scope')

        # 2. bank['questions'] contains non-dicts and malformed items
        bank_malformed_q = dict(bank_facts, questions=[
            None,
            'not-a-dict',
            123,
            {},
            {'fact': None},
            {'fact': 'contact.email', 'input_types': ['text'], 'aliases': ['Email Address']},
        ])
        res2 = render(q, 'contact.email', bank_malformed_q, 'exact', 'test_reason')
        self.assertEqual(res2['status'], 'ready')
        self.assertEqual(res2['answer'], 'user@example.com')

    def test_exact_match_and_render_handle_none_facts_safely(self):
        q_prior = make_question(
            question_id='q-prior-emp-test',
            text='Have you previously worked for this company?',
            input_type='single_choice',
            options={
                'items': [
                    {'id': 'opt-y', 'label': 'Yes', 'value': 'Y'},
                    {'id': 'opt-n', 'label': 'No', 'value': 'N'},
                ],
                'complete': True,
            },
        )
        q_text = make_question(question_id='q-email-test', text='Email Address', input_type='text')

        # 1. bank with facts=None
        bank_none_facts = {
            'facts': None,
            'questions': [
                {'fact': 'contact.email', 'input_types': ['text'], 'aliases': ['Email Address']},
            ],
        }
        # exact_match on prior employee text should not crash when facts is None
        key1, reason1 = exact_match(q_prior, bank_none_facts)
        self.assertEqual(key1, 'work.prior_employee')

        # exact_match on normal question should not crash
        key2, reason2 = exact_match(q_text, bank_none_facts)
        self.assertEqual(key2, 'contact.email')

        # render should not crash when facts is None, should abstain
        res1 = render(q_text, 'contact.email', bank_none_facts, 'exact', None)
        self.assertEqual(res1['status'], 'needs_user')
        self.assertEqual(res1['reason'], 'no_supported_fact')

        # 2. bank missing 'facts' key entirely
        bank_empty = {'questions': []}
        key3, reason3 = exact_match(q_prior, bank_empty)
        self.assertEqual(key3, 'work.prior_employee')
        res2 = render(q_text, 'contact.email', bank_empty, 'exact', None)
        self.assertEqual(res2['status'], 'needs_user')
        self.assertEqual(res2['reason'], 'no_supported_fact')

    def test_cascade_does_not_clobber_resolved_question_sharing_none_id(self):
        from job_applier.resolution.__main__ import NullSemanticMatcher
        bank = {
            'facts': {
                'contact.email': {
                    'value': 'user@example.com',
                    'confirmed': True,
                    'source': 'vault',
                },
                'other.fact': {
                    'value': 'other_value',
                    'confirmed': True,
                    'source': 'vault',
                },
            },
            'questions': [
                {
                    'fact': 'contact.email',
                    'input_types': ['text'],
                    'aliases': ['Email Address'],
                },
                {
                    'fact': 'other.fact',
                    'input_types': ['text'],
                    'aliases': ['Other Question'],
                },
            ],
        }
        # q1 matches exact alias and resolves to ready. Has no id / question_id (None).
        q1 = {
            'text': 'Email Address',
            'input_type': 'text',
        }
        # q2 has no exact match and needs_user. Also has no id / question_id (None).
        q2 = {
            'text': 'Completely unknown question not in bank',
            'input_type': 'text',
        }

        class MockLLM:
            def match(self, unresolved, bank):
                return {None: {'fact_key': 'other.fact', 'reason': 'llm_matched'}}, [{'tier': 'llm'}]

        cascade_result = resolve_cascade([q1, q2], bank, NullSemanticMatcher(), llm=MockLLM())
        results = cascade_result['results']
        self.assertEqual(len(results), 2)
        # q1 was resolved by exact match to 'ready'. Cascade must NOT clobber it to llm/other.fact.
        self.assertEqual(results[0]['status'], 'ready')
        self.assertEqual(results[0]['fact_key'], 'contact.email')
        self.assertEqual(results[0]['answer'], 'user@example.com')
        self.assertEqual(results[0]['tier'], 'exact')

        # q2 was unresolved, so it gets updated by llm
        self.assertEqual(results[1]['fact_key'], 'other.fact')
        self.assertEqual(results[1]['tier'], 'qwen')
        self.assertEqual(results[1]['reason'], 'llm_matched')

    def test_negative_option_guard_rejects_hyphenated_coop_and_subcontractor(self):
        resume = {'experience': [{'company': 'Acme Corp'}]}
        bank = self._build_bank({}, [], resume=resume)
        labels_to_reject = [
            'No, was a co-op',
            'No, I was a co-op',
            'No, co-op',
            'No, former co-op',
            'No, was a co op',
            'No, was a subcontractor',
            'No, freelance',
            'No, freelancer',
        ]
        for idx, lbl in enumerate(labels_to_reject):
            # 1. When paired only with an affirmative option, resolve_exact() returns
            # status == 'needs_user', reason == 'option_not_uniquely_observed', and selected_option is None
            q1 = make_question(
                question_id=f'q-reject-coop-{idx}',
                text='Have you previously worked for this company?',
                input_type='single_choice',
                options={
                    'items': [
                        {'id': 'opt-1', 'label': 'Yes, regular employee', 'value': 'regular'},
                        {'id': 'opt-2', 'label': lbl, 'value': 'reject_val'},
                    ],
                    'complete': True,
                },
            )
            res1 = resolve_exact(q1, bank)
            self.assertEqual(res1['status'], 'needs_user', f"Option '{lbl}' was not rejected")
            self.assertEqual(res1['reason'], 'option_not_uniquely_observed')
            self.assertIsNone(res1.get('selected_option'))

            # 2. When paired with a true negative option, cleanly selects the true negative option with status == 'ready'
            q2 = make_question(
                question_id=f'q-true-neg-coop-{idx}',
                text='Have you previously worked for this company?',
                input_type='single_choice',
                options={
                    'items': [
                        {'id': 'opt-1', 'label': 'Yes, regular employee', 'value': 'regular'},
                        {'id': 'opt-2', 'label': lbl, 'value': 'reject_val'},
                        {'id': 'opt-3', 'label': 'No, I have never worked here', 'value': 'never'},
                    ],
                    'complete': True,
                },
            )
            res2 = resolve_exact(q2, bank)
            self.assertEqual(res2['status'], 'ready', f"Option '{lbl}' interfered with true negative")
            self.assertEqual(res2['answer'], 'No, I have never worked here')
            self.assertEqual(res2['selected_option']['id'], 'opt-3')


class TestG02Round6Rework(unittest.TestCase):
    def test_qwen_match_handles_none_and_malformed_facts(self):
        import json
        from unittest.mock import patch
        from job_applier.resolution.qwen import QwenMatcher

        with patch.dict(os.environ, {'GROQ_API_KEY': 'fake-key'}):
            matcher = QwenMatcher()

        bank = {
            'facts': {
                'bad': None,
                'other': 'str',
                'valid': {'value': 'val', 'confirmed': True},
            }
        }
        # Calling match with empty questions parses facts without network calls or AttributeError
        predictions, calls = matcher.match([], bank)
        self.assertEqual(predictions, {})
        self.assertEqual(calls, [])

        # Also verify with a question to ensure payload generation uses parsed facts without error
        q = {'id': 'q1', 'text': 'Question 1', 'input_type': 'text'}
        with patch.object(matcher.client, 'post') as mock_post:
            mock_post.return_value.status_code = 400
            mock_post.return_value.headers = {}
            matcher.match([q], bank)
            self.assertTrue(mock_post.called)
            sent_payload = json.loads(mock_post.call_args[1]['json']['messages'][1]['content'])
            self.assertIn('valid', sent_payload['facts'])
            self.assertEqual(sent_payload['facts']['valid']['value'], 'val')
            self.assertNotIn('bad', sent_payload['facts'])
            self.assertNotIn('other', sent_payload['facts'])

    def test_qwen_match_handles_none_options(self):
        import json
        from unittest.mock import patch
        from job_applier.resolution.qwen import QwenMatcher

        with patch.dict(os.environ, {'GROQ_API_KEY': 'fake-key'}):
            matcher = QwenMatcher()

        questions = [
            {'id': 'q1', 'text': 'Question 1', 'input_type': 'text', 'options': None},
            {'id': 'q2', 'text': 'Question 2', 'input_type': 'single_choice', 'options': {}},
        ]
        bank = {'facts': {}}
        with patch.object(matcher.client, 'post') as mock_post:
            mock_post.return_value.status_code = 400
            mock_post.return_value.headers = {}
            # Verify payload generation does not crash with TypeError or KeyError
            matcher.match(questions, bank)
            self.assertTrue(mock_post.called)
            sent_payload = json.loads(mock_post.call_args[1]['json']['messages'][1]['content'])
            self.assertEqual(len(sent_payload['questions']), 2)
            self.assertEqual(sent_payload['questions'][0]['options'], [])
            self.assertEqual(sent_payload['questions'][0]['options_truncated'], False)
            self.assertEqual(sent_payload['questions'][1]['options'], [])
            self.assertEqual(sent_payload['questions'][1]['options_truncated'], False)

    def test_cascade_handles_crashing_llm(self):
        from job_applier.resolution.__main__ import NullSemanticMatcher

        bank = {
            'facts': {},
            'questions': [],
        }
        q = {
            'id': 'q-unresolved',
            'text': 'Unresolved question',
            'input_type': 'text',
        }

        class CrashingLLM:
            model = 'mock-qwen'

            def match(self, unresolved, bank):
                raise RuntimeError("timeout")

        res = resolve_cascade([q], bank, NullSemanticMatcher(), llm=CrashingLLM())
        self.assertEqual(len(res['results']), 1)
        self.assertEqual(res['results'][0]['status'], 'needs_user')
        self.assertEqual(len(res['calls']), 1)
        self.assertEqual(res['calls'][0]['status'], 'provider_exception')
        self.assertEqual(res['calls'][0]['error_type'], 'RuntimeError')
        self.assertEqual(res['calls'][0]['model'], 'mock-qwen')

    def test_country_matching_strips_parenthesized_dial_code(self):
        bank = {
            'facts': {
                'contact.country': {
                    'value': 'United States',
                    'confirmed': True,
                    'source': 'vault',
                    'option_labels': ['United States'],
                }
            },
            'questions': [
                {
                    'fact': 'contact.country',
                    'input_types': ['single_choice', 'combobox', 'select'],
                    'aliases': ['Country'],
                }
            ],
        }
        q = {
            'id': 'q-country',
            'text': 'Country',
            'input_type': 'single_choice',
            'options': {
                'items': [
                    {'id': 'opt-us', 'label': 'United States (+1)', 'value': 'US'},
                    {'id': 'opt-ca', 'label': 'Canada (+1)', 'value': 'CA'},
                ],
                'complete': True,
            },
        }
        res = render(q, 'contact.country', bank, 'exact', 'test_reason')
        self.assertEqual(res['status'], 'ready')
        self.assertIsNotNone(res.get('selected_option'))
        self.assertEqual(res['selected_option']['label'], 'United States (+1)')
        self.assertEqual(res['selected_option']['id'], 'opt-us')


if __name__ == '__main__':
    unittest.main()
