"""Integration tests and comprehensive mock tests for validate_pipeline.

Covers:
- Step-by-step truthful required-completion validation
- Detection and rejection of required skips, stale artifacts, forged counts
- Integrity checks (duplicate/foreign/malformed IDs, schema & lineage validation)
- Semantic control verification (checkbox, file, choice No/false, combobox)
- Regression coverage for phase exits and safe I/O handling
"""
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from job_applier.extraction import SCHEMA_VERSION as EXTRACTION_SCHEMA  # noqa: E402
from job_applier.filling import SCHEMA_VERSION as FILL_SCHEMA  # noqa: E402
from job_applier.resolution import SCHEMA_VERSION as RESOLUTION_SCHEMA  # noqa: E402
from job_applier.safe_io import write_json_atomic  # noqa: E402
from job_applier.validate_pipeline import main, validate_pipeline  # noqa: E402


try:
    from playwright.sync_api import sync_playwright  # noqa: F401
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


class ValidatePipelineMockTests(unittest.TestCase):
    """Browser-free mock tests for validate_pipeline logic and contract invariants."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='validate-mock-test-')
        self.url = 'https://example.com/mock-job'

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_extract_mock(self, questions, snapshot_id='snap-001', summary=None, exit_code=0, raise_exc=None):
        def _extract(args):
            if raise_exc:
                raise raise_exc
            if exit_code != 0:
                return exit_code
            out_dir = Path(args[args.index('--out') + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                'schema_version': EXTRACTION_SCHEMA,
                'snapshot_id': snapshot_id,
                'questions': questions,
                'summary': summary if summary is not None else {'questions': len(questions)},
            }
            write_json_atomic(out_dir / 'questions.json', payload, overwrite=True)
            return 0
        return _extract

    def _make_resolve_mock(self, answers, snapshot_id='snap-001', summary=None, exit_code=0, raise_exc=None):
        def _resolve(args):
            if raise_exc:
                raise raise_exc
            if exit_code != 0:
                return exit_code
            out_file = Path(args[args.index('--out') + 1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            if summary is None:
                r_cnt = sum(1 for a in answers if a.get('status') == 'ready')
                rv_cnt = sum(1 for a in answers if a.get('status') == 'review')
                nu_cnt = sum(1 for a in answers if a.get('status') == 'needs_user')
                sum_payload = {'ready': r_cnt, 'review': rv_cnt, 'needs_user': nu_cnt, 'total': len(answers)}
            else:
                sum_payload = summary
            payload = {
                'schema': RESOLUTION_SCHEMA,
                'snapshot_id': snapshot_id,
                'scope': 'test',
                'answers': answers,
                'summary': sum_payload,
            }
            write_json_atomic(out_file, payload, overwrite=True)
            return 0
        return _resolve

    def _make_fill_mock(
        self,
        fields,
        snapshot_id='snap-001',
        summary=None,
        exit_code=0,
        raise_exc=None,
        write_screenshot=True,
        screenshot_bytes=b'MOCK_PNG_DATA_STUB_BYTES',
        screenshot_path=None,
        guard_active=True,
        blocked_submits=0,
        total_answers=None,
    ):
        def _fill(args):
            if raise_exc:
                raise raise_exc
            out_dir = Path(args[args.index('--out') + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            rep_file = out_dir / 'fill_report.json'
            ss_file = out_dir / 'screenshot.png'
            if write_screenshot:
                ss_file.write_bytes(screenshot_bytes)
            if summary is None:
                f_cnt = sum(1 for f in fields if f.get('status') == 'filled')
                s_cnt = sum(1 for f in fields if f.get('status') == 'skipped')
                fl_cnt = sum(1 for f in fields if f.get('status') == 'failed')
                tot_ans = total_answers if total_answers is not None else len(fields)
                sum_payload = {'filled': f_cnt, 'skipped': s_cnt, 'failed': fl_cnt, 'total_answers': tot_ans}
            else:
                sum_payload = summary
            payload = {
                'schema': FILL_SCHEMA,
                'snapshot_id': snapshot_id,
                'fields': fields,
                'summary': sum_payload,
                'screenshot_path': str(screenshot_path) if screenshot_path else str(ss_file),
                'telemetry': {
                    'guard_active': guard_active,
                    'blocked_form_submits': blocked_submits,
                },
            }
            write_json_atomic(rep_file, payload, overwrite=True)
            return exit_code
        return _fill

    def test_23questions_15verified_8requiredskips_yields_partial_and_optional_yields_success(self):
        """Regression: 15 verified + 8 required skips must return PARTIAL, not SUCCESS.
        When the same 8 skips are all optional, SUCCESS is allowed.
        """
        # Case A: 23 questions all required=True
        q_req = [{'id': f'q_{i}', 'text': f'Q{i}', 'input_type': 'text', 'required': True} for i in range(23)]
        ans_all = [{'question_id': f'q_{i}', 'id': f'q_{i}', 'text': f'Q{i}', 'status': 'ready', 'answer': f'v_{i}'} for i in range(15)]
        ans_all += [{'question_id': f'q_{i}', 'id': f'q_{i}', 'text': f'Q{i}', 'status': 'needs_user', 'answer': None} for i in range(15, 23)]
        fields_all = [{'question_id': f'q_{i}', 'id': f'q_{i}', 'text': f'Q{i}', 'input_type': 'text', 'status': 'filled', 'verified_value': f'v_{i}'} for i in range(15)]
        fields_all += [{'question_id': f'q_{i}', 'id': f'q_{i}', 'text': f'Q{i}', 'input_type': 'text', 'status': 'skipped', 'verified_value': None, 'skip_reason': 'needs_user'} for i in range(15, 23)]

        run_dir_a = Path(self.temp_dir) / 'run_a'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_req)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_all)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(fields_all)):
            res_a = validate_pipeline(self.url, run_dir_a, overwrite=True)

        self.assertEqual(res_a['status'], 'PARTIAL')
        self.assertTrue(res_a['filled'])
        self.assertEqual(res_a['required_count'], 23)
        self.assertEqual(res_a['required_verified'], 15)
        self.assertEqual(len(res_a['missing_required']), 8)
        self.assertEqual(res_a['required_verified'] + len(res_a['missing_required']), res_a['required_count'])
        self.assertEqual(res_a['validation_scope'], 'reported_fill_evidence')
        self.assertEqual(res_a['final_dom_validity'], 'not_reported')

        # Case B: First 15 required=True, remaining 8 required=False (optional)
        q_opt = [{'id': f'q_{i}', 'text': f'Q{i}', 'input_type': 'text', 'required': True} for i in range(15)]
        q_opt += [{'id': f'q_{i}', 'text': f'Q{i}', 'input_type': 'text', 'required': False} for i in range(15, 23)]

        run_dir_b = Path(self.temp_dir) / 'run_b'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_opt)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_all)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(fields_all)):
            res_b = validate_pipeline(self.url, run_dir_b, overwrite=True)

        self.assertEqual(res_b['status'], 'SUCCESS')
        self.assertTrue(res_b['filled'])
        self.assertEqual(res_b['required_count'], 15)
        self.assertEqual(res_b['required_verified'], 15)
        self.assertEqual(len(res_b['missing_required']), 0)
        self.assertEqual(res_b['required_verified'] + len(res_b['missing_required']), res_b['required_count'])

    def test_greenhouse_like_13req_9opt_1unk_10filled_yields_partial_with_proper_ids(self):
        """Actual Greenhouse-like form: 13 required, 9 optional, 1 unknown; 10 filled, 6 missing => PARTIAL."""
        questions = []
        for i in range(13):
            questions.append({'id': f'req_q_{i}', 'text': f'Req Q{i}', 'input_type': 'text', 'required': True})
        for i in range(9):
            questions.append({'id': f'opt_q_{i}', 'text': f'Opt Q{i}', 'input_type': 'text', 'required': False})
        questions.append({'id': 'unk_q_0', 'text': 'Unk Q0', 'input_type': 'text', 'required': None})

        # 10 filled: 7 required + 3 optional
        answers = []
        fields = []
        for i in range(7):
            qid = f'req_q_{i}'
            answers.append({'question_id': qid, 'id': qid, 'text': f'Req Q{i}', 'status': 'ready', 'answer': f'val_{i}'})
            fields.append({'question_id': qid, 'id': qid, 'text': f'Req Q{i}', 'input_type': 'text', 'status': 'filled', 'verified_value': f'val_{i}'})
        for i in range(3):
            qid = f'opt_q_{i}'
            answers.append({'question_id': qid, 'id': qid, 'text': f'Opt Q{i}', 'status': 'ready', 'answer': f'optval_{i}'})
            fields.append({'question_id': qid, 'id': qid, 'text': f'Opt Q{i}', 'input_type': 'text', 'status': 'filled', 'verified_value': f'optval_{i}'})

        # 6 required unanswered
        for i in range(7, 13):
            qid = f'req_q_{i}'
            answers.append({'question_id': qid, 'id': qid, 'text': f'Req Q{i}', 'status': 'needs_user', 'answer': None})
            fields.append({'question_id': qid, 'id': qid, 'text': f'Req Q{i}', 'input_type': 'text', 'status': 'skipped', 'verified_value': None, 'skip_reason': 'needs_user'})

        run_dir = Path(self.temp_dir) / 'run_greenhouse_like'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(questions)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(answers)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(fields)):
            res = validate_pipeline(self.url, run_dir, overwrite=True)

        self.assertEqual(res['status'], 'PARTIAL')
        self.assertEqual(res['required_count'], 13)
        self.assertEqual(res['required_verified'], 7)
        self.assertEqual(len(res['missing_required']), 6)
        self.assertEqual(res['required_verified'] + len(res['missing_required']), res['required_count'])
        self.assertEqual(len(res['unknown_required_unresolved']), 1)
        self.assertIn('unk_q_0', res['unknown_required_unresolved'])

        expected_missing = [f'req_q_{i}' for i in range(7, 13)]
        self.assertEqual(sorted(res['missing_required']), sorted(expected_missing))

        # Check no PII in errors
        for err in res['errors']:
            self.assertNotIn('val_', err)
            self.assertNotIn('optval_', err)

    def test_unanswered_and_missing_rows_deficits(self):
        """Unknown unanswered / missing required answer / missing fill row produce proper deficits."""
        questions = [
            {'id': 'q_req_no_ans', 'text': 'Req No Ans', 'input_type': 'text', 'required': True},
            {'id': 'q_req_no_fill', 'text': 'Req No Fill', 'input_type': 'text', 'required': True},
            {'id': 'q_req_ok', 'text': 'Req OK', 'input_type': 'text', 'required': True},
            {'id': 'q_opt_empty', 'text': 'Opt Empty', 'input_type': 'text', 'required': False},
            {'id': 'q_unk_unresolved', 'text': 'Unk Unresolved', 'input_type': 'text', 'required': None},
        ]

        # Only q_req_no_fill and q_req_ok have answers; q_req_no_ans and q_unk_unresolved have no answer row
        answers = [
            {'question_id': 'q_req_no_fill', 'id': 'q_req_no_fill', 'text': 'Req No Fill', 'status': 'ready', 'answer': 'ans_fill'},
            {'question_id': 'q_req_ok', 'id': 'q_req_ok', 'text': 'Req OK', 'status': 'ready', 'answer': 'ans_ok'},
        ]

        # Only q_req_ok has a fill row; q_req_no_fill has no fill row
        fields = [
            {'question_id': 'q_req_ok', 'id': 'q_req_ok', 'text': 'Req OK', 'input_type': 'text', 'status': 'filled', 'verified_value': 'ans_ok'},
        ]

        run_dir = Path(self.temp_dir) / 'run_missing_rows'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(questions)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(answers)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(fields, total_answers=len(answers))):
            res = validate_pipeline(self.url, run_dir, overwrite=True)

        self.assertEqual(res['status'], 'PARTIAL')
        self.assertEqual(res['required_count'], 3)
        self.assertEqual(res['required_verified'], 1)
        self.assertEqual(sorted(res['missing_required']), sorted(['q_req_no_ans', 'q_req_no_fill']))
        self.assertEqual(res['unknown_required_unresolved'], ['q_unk_unresolved'])
        # Optional empty question is permitted and not in missing_required
        self.assertNotIn('q_opt_empty', res['missing_required'])

    def test_review_approval_readback_and_control_types(self):
        """Review approval gating, blank/null readbacks, checkboxes, No/false choices, file handling."""
        questions = [
            {'id': 'q_rev', 'text': 'Needs Review', 'input_type': 'text', 'required': True},
            {'id': 'q_blank', 'text': 'Blank Readback', 'input_type': 'text', 'required': True},
            {'id': 'q_null', 'text': 'Null Readback', 'input_type': 'text', 'required': True},
            {'id': 'q_chk_req', 'text': 'Required Checkbox', 'input_type': 'checkbox', 'required': True},
            {'id': 'q_chk_opt', 'text': 'Optional Checkbox', 'input_type': 'checkbox', 'required': False},
            {'id': 'q_choice_no', 'text': 'Prior Employment', 'input_type': 'radio', 'required': True},
            {'id': 'q_file_nofile', 'text': 'Resume Missing', 'input_type': 'file', 'required': True},
            {'id': 'q_file_ok', 'text': 'Resume Attached', 'input_type': 'file', 'required': True},
        ]

        answers = [
            {'question_id': 'q_rev', 'id': 'q_rev', 'text': 'Needs Review', 'status': 'review', 'answer': 'review_val'},
            {'question_id': 'q_blank', 'id': 'q_blank', 'text': 'Blank Readback', 'status': 'ready', 'answer': 'val'},
            {'question_id': 'q_null', 'id': 'q_null', 'text': 'Null Readback', 'status': 'ready', 'answer': 'val'},
            {'question_id': 'q_chk_req', 'id': 'q_chk_req', 'text': 'Required Checkbox', 'status': 'ready', 'answer': True},
            {'question_id': 'q_chk_opt', 'id': 'q_chk_opt', 'text': 'Optional Checkbox', 'status': 'ready', 'answer': False},
            {'question_id': 'q_choice_no', 'id': 'q_choice_no', 'text': 'Prior Employment', 'status': 'ready', 'answer': 'No', 'selected_option': {'label': 'No', 'value': 'false'}},
            {'question_id': 'q_file_nofile', 'id': 'q_file_nofile', 'text': 'Resume Missing', 'status': 'ready', 'answer': '/path/to/resume.pdf'},
            {'question_id': 'q_file_ok', 'id': 'q_file_ok', 'text': 'Resume Attached', 'status': 'ready', 'answer': '/path/to/resume.pdf'},
        ]

        fields = [
            {'question_id': 'q_rev', 'id': 'q_rev', 'text': 'Needs Review', 'input_type': 'text', 'status': 'filled', 'verified_value': 'review_val'},
            {'question_id': 'q_blank', 'id': 'q_blank', 'text': 'Blank Readback', 'input_type': 'text', 'status': 'filled', 'verified_value': '   '},
            {'question_id': 'q_null', 'id': 'q_null', 'text': 'Null Readback', 'input_type': 'text', 'status': 'filled', 'verified_value': None},
            {'question_id': 'q_chk_req', 'id': 'q_chk_req', 'text': 'Required Checkbox', 'input_type': 'checkbox', 'status': 'filled', 'verified_value': False},
            {'question_id': 'q_chk_opt', 'id': 'q_chk_opt', 'text': 'Optional Checkbox', 'input_type': 'checkbox', 'status': 'filled', 'verified_value': False},
            {'question_id': 'q_choice_no', 'id': 'q_choice_no', 'text': 'Prior Employment', 'input_type': 'radio', 'status': 'filled', 'verified_value': 'No'},
            {'question_id': 'q_file_nofile', 'id': 'q_file_nofile', 'text': 'Resume Missing', 'input_type': 'file', 'status': 'filled', 'verified_value': 'no observed file'},
            {'question_id': 'q_file_ok', 'id': 'q_file_ok', 'text': 'Resume Attached', 'input_type': 'file', 'status': 'filled', 'verified_value': 'resume.pdf'},
        ]

        # Test without allow_review: q_rev must NOT satisfy coverage
        run_dir_1 = Path(self.temp_dir) / 'run_types_no_review'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(questions)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(answers)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(fields)):
            res_1 = validate_pipeline(self.url, run_dir_1, allow_review=False, overwrite=True)

        self.assertIn('q_rev', res_1['missing_required'])
        self.assertIn('q_blank', res_1['missing_required'])
        self.assertIn('q_null', res_1['missing_required'])
        self.assertIn('q_chk_req', res_1['missing_required'])
        self.assertIn('q_file_nofile', res_1['missing_required'])

        # q_choice_no ("No" selection) and q_file_ok ("resume.pdf") must be verified!
        self.assertNotIn('q_choice_no', res_1['missing_required'])
        self.assertNotIn('q_file_ok', res_1['missing_required'])
        # Optional checkbox with False must NOT fail
        self.assertNotIn('q_chk_opt', res_1['missing_required'])

        # Test with allow_review=True: q_rev is now eligible
        run_dir_2 = Path(self.temp_dir) / 'run_types_allow_review'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(questions)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(answers)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(fields)):
            res_2 = validate_pipeline(self.url, run_dir_2, allow_review=True, overwrite=True)

        self.assertNotIn('q_rev', res_2['missing_required'])

    def test_integrity_checks_reject_success(self):
        """Duplicate/foreign/malformed IDs, forged counts, schema/lineage mismatch, invalid required flags."""
        base_q = [{'id': 'q_1', 'text': 'Q1', 'input_type': 'text', 'required': True}]
        base_ans = [{'question_id': 'q_1', 'id': 'q_1', 'text': 'Q1', 'status': 'ready', 'answer': 'v1'}]
        base_f = [{'question_id': 'q_1', 'id': 'q_1', 'text': 'Q1', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'}]

        # 1. Duplicate question ID in snapshot
        dup_q = [
            {'id': 'q_1', 'text': 'Q1', 'input_type': 'text', 'required': True},
            {'id': 'q_1', 'text': 'Q1 duplicate', 'input_type': 'text', 'required': True},
        ]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(dup_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f)):
            res = validate_pipeline(self.url, Path(self.temp_dir) / 'run_dup_q', overwrite=True)
            self.assertNotEqual(res['status'], 'SUCCESS')

        # 2. Foreign question_id in answers
        foreign_ans = [
            {'question_id': 'q_1', 'id': 'q_1', 'text': 'Q1', 'status': 'ready', 'answer': 'v1'},
            {'question_id': 'foreign_q', 'id': 'foreign_q', 'text': 'Foreign', 'status': 'ready', 'answer': 'vf'},
        ]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(foreign_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f)):
            res = validate_pipeline(self.url, Path(self.temp_dir) / 'run_foreign_ans', overwrite=True)
            self.assertNotEqual(res['status'], 'SUCCESS')

        # 3. Foreign question_id in fill fields
        foreign_f = [
            {'question_id': 'q_1', 'id': 'q_1', 'text': 'Q1', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'},
            {'question_id': 'foreign_q', 'id': 'foreign_q', 'text': 'Foreign', 'input_type': 'text', 'status': 'filled', 'verified_value': 'vf'},
        ]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(foreign_f)):
            res = validate_pipeline(self.url, Path(self.temp_dir) / 'run_foreign_f', overwrite=True)
            self.assertNotEqual(res['status'], 'SUCCESS')

        # 4. Forged summary counts in answers
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans, summary={'ready': 99, 'review': 0, 'needs_user': 0, 'total': 1})), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f)):
            res = validate_pipeline(self.url, Path(self.temp_dir) / 'run_forged_cnt', overwrite=True)
            self.assertNotEqual(res['status'], 'SUCCESS')

        # 5. Lineage mismatch between snapshot and answers
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q, snapshot_id='snap-A')), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans, snapshot_id='snap-B')), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f, snapshot_id='snap-A')):
            res = validate_pipeline(self.url, Path(self.temp_dir) / 'run_lineage_mismatch', overwrite=True)
            self.assertNotEqual(res['status'], 'SUCCESS')

        # 6. Invalid required flag shape (e.g. string "true" instead of literal True)
        invalid_req_q = [{'id': 'q_1', 'text': 'Q1', 'input_type': 'text', 'required': 'true'}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(invalid_req_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f)):
            res = validate_pipeline(self.url, Path(self.temp_dir) / 'run_invalid_req', overwrite=True)
            self.assertNotEqual(res['status'], 'SUCCESS')

    def test_phase_failures_and_stale_artifacts(self):
        """Phase failure prevents old artifact consumption; stale artifacts and nonzero fill handled."""
        run_dir = Path(self.temp_dir) / 'run_unmodified'
        run_dir.mkdir(parents=True, exist_ok=True)

        # Prepopulate old artifacts
        old_q = run_dir / 'questions.json'
        old_a = run_dir / 'answers.json'
        old_r = run_dir / 'fill_report.json'
        old_s = run_dir / 'screenshot.png'
        write_json_atomic(old_q, {'schema_version': EXTRACTION_SCHEMA, 'snapshot_id': 'old', 'questions': []}, overwrite=True)
        write_json_atomic(old_a, {'schema': RESOLUTION_SCHEMA, 'snapshot_id': 'old', 'answers': []}, overwrite=True)
        write_json_atomic(old_r, {'schema': FILL_SCHEMA, 'snapshot_id': 'old', 'fields': []}, overwrite=True)
        old_s.write_bytes(b'OLD_SCREENSHOT')

        # 1. Step 1 fails with nonzero exit code -> downstream NOT called, old questions NOT consumed
        resolve_called = []
        fill_called = []
        with patch('job_applier.validate_pipeline.extract_main', return_value=1), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=lambda a: resolve_called.append(True)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=lambda a: fill_called.append(True)):
            res = validate_pipeline(self.url, run_dir, overwrite=True)

        self.assertEqual(res['status'], 'FAILED')
        self.assertFalse(res['fetched'])
        self.assertEqual(len(resolve_called), 0)
        self.assertEqual(len(fill_called), 0)
        self.assertIsNone(res['artifacts']['questions'])

        # 2. Step 1 exits 0 but does not rewrite questions.json -> stale artifact detected
        with patch('job_applier.validate_pipeline.extract_main', return_value=0):
            res = validate_pipeline(self.url, run_dir, overwrite=True)
        self.assertEqual(res['status'], 'FAILED')
        self.assertFalse(res['fetched'])
        self.assertTrue(any('not freshly created' in err for err in res['errors']))

        # 3. Legitimate partial fill (exit code 1) consumes fresh report for diagnostics, status PARTIAL not SUCCESS
        base_q = [{'id': 'q_1', 'text': 'Q1', 'input_type': 'text', 'required': False}]
        base_ans = [{'question_id': 'q_1', 'id': 'q_1', 'text': 'Q1', 'status': 'ready', 'answer': 'v1'}]
        partial_f = [
            {'question_id': 'q_1', 'id': 'q_1', 'text': 'Q1', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'},
        ]
        run_dir_partial = Path(self.temp_dir) / 'run_partial_code1'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(partial_f, exit_code=1)):
            res = validate_pipeline(self.url, run_dir_partial, overwrite=True)

        self.assertEqual(res['status'], 'PARTIAL')
        self.assertEqual(res['filled_count'], 1)
        self.assertIsNotNone(res['artifacts']['fill_report'])

    def test_summary_write_failure_and_cli_exit_codes(self):
        """Summary write failure prevents returned SUCCESS; CLI returns 0 on SUCCESS and 1 on PARTIAL/FAILED."""
        base_q = [{'id': 'q_1', 'text': 'Q1', 'input_type': 'text', 'required': False}]
        base_ans = [{'question_id': 'q_1', 'id': 'q_1', 'text': 'Q1', 'status': 'ready', 'answer': 'v1'}]
        base_f = [{'question_id': 'q_1', 'id': 'q_1', 'text': 'Q1', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'}]

        run_dir = Path(self.temp_dir) / 'run_cli_test'

        # Test CLI success return code 0
        cli_args = [self.url, '--out', str(run_dir), '--overwrite']
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f)):
            captured_stdout = io.StringIO()
            with patch('sys.stdout', captured_stdout):
                code = main(cli_args)
            self.assertEqual(code, 0)
            parsed = json.loads(captured_stdout.getvalue())
            self.assertEqual(parsed['status'], 'SUCCESS')

        # Test summary write failure degrades SUCCESS
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f)), \
             patch('job_applier.validate_pipeline.write_json_atomic', side_effect=OSError('Disk full simulated')):
            res = validate_pipeline(self.url, Path(self.temp_dir) / 'run_write_fail', overwrite=True)
            self.assertNotEqual(res['status'], 'SUCCESS')
            self.assertEqual(res['status'], 'PARTIAL')

    def test_checkbox_verified_value_matrix(self):
        """Isolated checks for checkbox verified_value: non-bools/0/1/strings rejected, optional False allowed."""
        q_req = [{'id': 'q_chk', 'text': 'Agree', 'input_type': 'checkbox', 'required': True}]
        ans_req = [{'question_id': 'q_chk', 'id': 'q_chk', 'text': 'Agree', 'status': 'ready', 'answer': True}]

        bad_values = [0, 1, 'unchecked', 'no', 'true', {}, [], False]
        for idx, bad_val in enumerate(bad_values):
            with self.subTest(bad_val=bad_val):
                f_bad = [{'question_id': 'q_chk', 'id': 'q_chk', 'text': 'Agree', 'input_type': 'checkbox', 'status': 'filled', 'verified_value': bad_val}]
                run_dir = Path(self.temp_dir) / f'run_chk_bad_{idx}'
                with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_req)), \
                     patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_req)), \
                     patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_bad)):
                    res = validate_pipeline(self.url, run_dir, overwrite=True)
                self.assertNotEqual(res['status'], 'SUCCESS')
                self.assertEqual(res['required_verified'], 0)
                self.assertIn('q_chk', res['missing_required'])

        # Unknown requiredness checkbox with False -> conservatively unresolved
        q_unk = [{'id': 'q_unk_chk', 'text': 'Agree', 'input_type': 'checkbox', 'required': None}]
        ans_unk = [{'question_id': 'q_unk_chk', 'id': 'q_unk_chk', 'text': 'Agree', 'status': 'ready', 'answer': False}]
        f_unk = [{'question_id': 'q_unk_chk', 'id': 'q_unk_chk', 'text': 'Agree', 'input_type': 'checkbox', 'status': 'filled', 'verified_value': False}]
        run_dir_unk = Path(self.temp_dir) / 'run_chk_unk_false'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_unk)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_unk)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_unk)):
            res_unk = validate_pipeline(self.url, run_dir_unk, overwrite=True)
        self.assertNotEqual(res_unk['status'], 'SUCCESS')
        self.assertIn('q_unk_chk', res_unk['unknown_required_unresolved'])

        # Optional checkbox with False -> valid
        q_opt = [{'id': 'q_opt_chk', 'text': 'Newsletter', 'input_type': 'checkbox', 'required': False}]
        ans_opt = [{'question_id': 'q_opt_chk', 'id': 'q_opt_chk', 'text': 'Newsletter', 'status': 'ready', 'answer': False}]
        f_opt = [{'question_id': 'q_opt_chk', 'id': 'q_opt_chk', 'text': 'Newsletter', 'input_type': 'checkbox', 'status': 'filled', 'verified_value': False}]
        run_dir_opt = Path(self.temp_dir) / 'run_chk_opt_false'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_opt)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_opt)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_opt)):
            res_opt = validate_pipeline(self.url, run_dir_opt, overwrite=True)
        self.assertEqual(res_opt['status'], 'SUCCESS')
        self.assertEqual(res_opt['verified_count'], 1)

    def test_text_verified_value_matrix(self):
        """Isolated checks for text verified_value: non-string/bool/numbers/containers/mismatches rejected."""
        q_txt = [{'id': 'q_txt', 'text': 'Name', 'input_type': 'text', 'required': True}]
        ans_txt = [{'question_id': 'q_txt', 'id': 'q_txt', 'text': 'Name', 'status': 'ready', 'answer': 'Alice'}]

        bad_values = [False, 123, ['Alice'], {'name': 'Alice'}]
        for idx, bad_val in enumerate(bad_values):
            with self.subTest(bad_val=bad_val):
                f_bad = [{'question_id': 'q_txt', 'id': 'q_txt', 'text': 'Name', 'input_type': 'text', 'status': 'filled', 'verified_value': bad_val}]
                run_dir = Path(self.temp_dir) / f'run_txt_bad_{idx}'
                with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_txt)), \
                     patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_txt)), \
                     patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_bad)):
                    res = validate_pipeline(self.url, run_dir, overwrite=True)
                self.assertNotEqual(res['status'], 'SUCCESS')
                self.assertIn('q_txt', res['missing_required'])

        # Planned 'Alice' observed 'Bob' -> mismatch
        f_mismatch = [{'question_id': 'q_txt', 'id': 'q_txt', 'text': 'Name', 'input_type': 'text', 'status': 'filled', 'verified_value': 'Bob'}]
        run_dir_mis = Path(self.temp_dir) / 'run_txt_mismatch'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_txt)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_txt)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_mismatch)):
            res_mis = validate_pipeline(self.url, run_dir_mis, overwrite=True)
        self.assertNotEqual(res_mis['status'], 'SUCCESS')
        self.assertIn('q_txt', res_mis['missing_required'])

        # Planned '  Alice   Smith  ' observed 'Alice Smith' -> whitespace safe collapse matches
        ans_ws = [{'question_id': 'q_txt', 'id': 'q_txt', 'text': 'Name', 'status': 'ready', 'answer': '  Alice   Smith  '}]
        f_ws = [{'question_id': 'q_txt', 'id': 'q_txt', 'text': 'Name', 'input_type': 'text', 'status': 'filled', 'verified_value': 'Alice Smith'}]
        run_dir_ws = Path(self.temp_dir) / 'run_txt_whitespace'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_txt)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_ws)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_ws)):
            res_ws = validate_pipeline(self.url, run_dir_ws, overwrite=True)
        self.assertEqual(res_ws['status'], 'SUCCESS')

    def test_choice_verified_value_matrix(self):
        """Isolated checks for choices: Canada vs France mismatch, contradictory selected_option, No/false valid."""
        q_c = [{'id': 'q_c', 'text': 'Country', 'input_type': 'select', 'required': True}]

        # Planned Canada, observed France -> mismatch
        ans_ca = [{'question_id': 'q_c', 'id': 'q_c', 'text': 'Country', 'status': 'ready', 'answer': 'Canada'}]
        f_fr = [{'question_id': 'q_c', 'id': 'q_c', 'text': 'Country', 'input_type': 'select', 'status': 'filled', 'verified_value': 'France'}]
        run_dir_mis = Path(self.temp_dir) / 'run_choice_mismatch'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_c)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_ca)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_fr)):
            res_mis = validate_pipeline(self.url, run_dir_mis, overwrite=True)
        self.assertNotEqual(res_mis['status'], 'SUCCESS')
        self.assertIn('q_c', res_mis['missing_required'])

        # Contradictory selected_option (Canada vs France) -> rejected
        ans_contra = [{'question_id': 'q_c', 'id': 'q_c', 'text': 'Country', 'status': 'ready', 'answer': 'Canada', 'selected_option': {'label': 'France', 'value': 'FR'}}]
        run_dir_contra = Path(self.temp_dir) / 'run_choice_contra'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_c)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_contra)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_fr)):
            res_contra = validate_pipeline(self.url, run_dir_contra, overwrite=True)
        self.assertNotEqual(res_contra['status'], 'SUCCESS')
        self.assertIn('q_c', res_contra['missing_required'])

        # Valid choice No with selected_option false mapping
        q_no = [{'id': 'q_no', 'text': 'Relocate', 'input_type': 'radio', 'required': True}]
        ans_no = [{'question_id': 'q_no', 'id': 'q_no', 'text': 'Relocate', 'status': 'ready', 'answer': 'No', 'selected_option': {'label': 'No', 'value': 'false'}}]
        f_no_val = [{'question_id': 'q_no', 'id': 'q_no', 'text': 'Relocate', 'input_type': 'radio', 'status': 'filled', 'verified_value': 'false'}]
        run_dir_no = Path(self.temp_dir) / 'run_choice_no_false'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_no)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_no)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_no_val)):
            res_no = validate_pipeline(self.url, run_dir_no, overwrite=True)
        self.assertEqual(res_no['status'], 'SUCCESS')

    def test_file_verified_value_matrix(self):
        """Isolated checks for file verified_value: paths/URIs/wrong filenames rejected, basename accepted, no masking by text."""
        q_f = [{'id': 'q_f', 'text': 'Resume', 'input_type': 'file', 'required': True}]
        ans_f = [{'question_id': 'q_f', 'id': 'q_f', 'text': 'Resume', 'status': 'ready', 'answer': '/path/to/resume.pdf'}]

        bad_file_values = [
            '/home/user/resume.pdf',
            'C:\\Users\\user\\resume.pdf',
            'uploads/resume.pdf',
            'file:///path/to/resume.pdf',
            'wrong_resume.pdf',
        ]
        for idx, bad_val in enumerate(bad_file_values):
            with self.subTest(bad_val=bad_val):
                f_bad = [{'question_id': 'q_f', 'id': 'q_f', 'text': 'Resume', 'input_type': 'file', 'status': 'filled', 'verified_value': bad_val}]
                run_dir = Path(self.temp_dir) / f'run_file_bad_{idx}'
                with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_f)), \
                     patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_f)), \
                     patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_bad)):
                    res = validate_pipeline(self.url, run_dir, overwrite=True)
                self.assertNotEqual(res['status'], 'SUCCESS')
                self.assertIn('q_f', res['missing_required'])

        # Correct basename string -> SUCCESS
        f_ok = [{'question_id': 'q_f', 'id': 'q_f', 'text': 'Resume', 'input_type': 'file', 'status': 'filled', 'verified_value': 'resume.pdf'}]
        run_dir_ok = Path(self.temp_dir) / 'run_file_ok'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_f)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_f)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_ok)):
            res_ok = validate_pipeline(self.url, run_dir_ok, overwrite=True)
        self.assertEqual(res_ok['status'], 'SUCCESS')

        # Semantic file question masked by fill input_type 'text' -> rejected
        f_masked = [{'question_id': 'q_f', 'id': 'q_f', 'text': 'Resume', 'input_type': 'text', 'status': 'filled', 'verified_value': 'resume.pdf'}]
        run_dir_mask = Path(self.temp_dir) / 'run_file_masked'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_f)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_f)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_masked)):
            res_mask = validate_pipeline(self.url, run_dir_mask, overwrite=True)
        self.assertNotEqual(res_mask['status'], 'SUCCESS')
        self.assertIn('q_f', res_mask['missing_required'])

    def test_optional_field_verification_matrix(self):
        """Isolated checks for optional fields: omission/skip allowed, invalid fill / review-off prevents SUCCESS."""
        q = [
            {'id': 'q_req', 'text': 'Required Field', 'input_type': 'text', 'required': True},
            {'id': 'q_opt', 'text': 'Optional Field', 'input_type': 'text', 'required': False},
        ]
        ans_base = [{'question_id': 'q_req', 'id': 'q_req', 'text': 'Required Field', 'status': 'ready', 'answer': 'ReqVal'}]
        f_base = [{'question_id': 'q_req', 'id': 'q_req', 'text': 'Required Field', 'input_type': 'text', 'status': 'filled', 'verified_value': 'ReqVal'}]

        # 1. Optional omitted -> SUCCESS
        run_dir_omit = Path(self.temp_dir) / 'run_opt_omit'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_base)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_base)):
            res_omit = validate_pipeline(self.url, run_dir_omit, overwrite=True)
        self.assertEqual(res_omit['status'], 'SUCCESS')

        # 2. Optional skipped in fill report -> SUCCESS
        ans_skip = ans_base + [{'question_id': 'q_opt', 'id': 'q_opt', 'text': 'Optional Field', 'status': 'ready', 'answer': 'OptVal'}]
        f_skip = f_base + [{'question_id': 'q_opt', 'id': 'q_opt', 'text': 'Optional Field', 'input_type': 'text', 'status': 'skipped', 'verified_value': None, 'skip_reason': 'not_needed'}]
        run_dir_skip = Path(self.temp_dir) / 'run_opt_skip'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_skip)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_skip)):
            res_skip = validate_pipeline(self.url, run_dir_skip, overwrite=True)
        self.assertEqual(res_skip['status'], 'SUCCESS')

        # 3. Optional reported filled with invalid readback (None) -> prevents SUCCESS (PARTIAL)
        ans_fill = ans_base + [{'question_id': 'q_opt', 'id': 'q_opt', 'text': 'Optional Field', 'status': 'ready', 'answer': 'OptVal'}]
        f_invalid_opt = f_base + [{'question_id': 'q_opt', 'id': 'q_opt', 'text': 'Optional Field', 'input_type': 'text', 'status': 'filled', 'verified_value': None}]
        run_dir_inv = Path(self.temp_dir) / 'run_opt_invalid_fill'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_fill)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_invalid_opt)):
            res_inv = validate_pipeline(self.url, run_dir_inv, overwrite=True)
        self.assertNotEqual(res_inv['status'], 'SUCCESS')
        self.assertEqual(res_inv['status'], 'PARTIAL')
        self.assertIn('q_opt', res_inv.get('optional_invalid_fills', []))
        self.assertEqual(len(res_inv['missing_required']), 0)

        # 4. Optional reported filled with status 'review' and allow_review=False -> prevents SUCCESS
        ans_rev = ans_base + [{'question_id': 'q_opt', 'id': 'q_opt', 'text': 'Optional Field', 'status': 'review', 'answer': 'OptVal'}]
        f_valid_opt = f_base + [{'question_id': 'q_opt', 'id': 'q_opt', 'text': 'Optional Field', 'input_type': 'text', 'status': 'filled', 'verified_value': 'OptVal'}]
        run_dir_rev_off = Path(self.temp_dir) / 'run_opt_rev_off'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_rev)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_valid_opt)):
            res_rev_off = validate_pipeline(self.url, run_dir_rev_off, allow_review=False, overwrite=True)
        self.assertNotEqual(res_rev_off['status'], 'SUCCESS')
        self.assertEqual(res_rev_off['status'], 'PARTIAL')
        self.assertIn('q_opt', res_rev_off.get('optional_invalid_fills', []))

        # 5. Optional reported filled with status 'review' and allow_review=True -> SUCCESS
        run_dir_rev_on = Path(self.temp_dir) / 'run_opt_rev_on'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_rev)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_valid_opt)):
            res_rev_on = validate_pipeline(self.url, run_dir_rev_on, allow_review=True, overwrite=True)
        self.assertEqual(res_rev_on['status'], 'SUCCESS')

    def test_guard_telemetry_shapes(self):
        """Isolated checks for guard telemetry: guard_active strict True, blocked_form_submits non-neg int excl bool."""
        base_q = [{'id': 'q1', 'text': 'Field', 'input_type': 'text', 'required': True}]
        base_ans = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'status': 'ready', 'answer': 'v1'}]
        base_f = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'}]

        bad_guard_configs = [
            (False, 0),        # guard_active is False
            ('true', 0),       # guard_active is string
            (None, 0),         # guard_active is None
            (True, None),      # blocked_submits is None
            (True, -1),        # blocked_submits is negative
            (True, '0'),       # blocked_submits is string
            (True, True),      # blocked_submits is boolean
        ]
        for idx, (g_act, b_sub) in enumerate(bad_guard_configs):
            with self.subTest(guard_active=g_act, blocked_submits=b_sub):
                run_dir = Path(self.temp_dir) / f'run_guard_bad_{idx}'
                with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
                     patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
                     patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f, guard_active=g_act, blocked_submits=b_sub)):
                    res = validate_pipeline(self.url, run_dir, overwrite=True)
                self.assertNotEqual(res['status'], 'SUCCESS')

        # Valid telemetry: guard_active=True, blocked_submits=0
        run_dir_ok0 = Path(self.temp_dir) / 'run_guard_ok_0'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f, guard_active=True, blocked_submits=0)):
            res_ok0 = validate_pipeline(self.url, run_dir_ok0, overwrite=True)
        self.assertEqual(res_ok0['status'], 'SUCCESS')

        # Valid telemetry: guard_active=True, blocked_submits=2
        run_dir_ok2 = Path(self.temp_dir) / 'run_guard_ok_2'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f, guard_active=True, blocked_submits=2)):
            res_ok2 = validate_pipeline(self.url, run_dir_ok2, overwrite=True)
        self.assertEqual(res_ok2['status'], 'SUCCESS')

    def test_integrity_and_summary_shapes(self):
        """Isolated checks for summary shapes, non-negative ints excl bool, and forged totals."""
        base_q = [{'id': 'q1', 'text': 'Field', 'input_type': 'text', 'required': True}]
        base_ans = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'status': 'ready', 'answer': 'v1'}]
        base_f = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'}]

        # 1. Malformed summary as list in questions
        run_dir_q_list = Path(self.temp_dir) / 'run_q_sum_list'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q, summary=[1, 2, 3])), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f)):
            res = validate_pipeline(self.url, run_dir_q_list, overwrite=True)
        self.assertNotEqual(res['status'], 'SUCCESS')

        # 2. Malformed summary as list in answers
        run_dir_a_list = Path(self.temp_dir) / 'run_a_sum_list'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans, summary=['ready'])), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f)):
            res = validate_pipeline(self.url, run_dir_a_list, overwrite=True)
        self.assertNotEqual(res['status'], 'SUCCESS')

        # 3. Malformed summary as list in fill report
        run_dir_f_list = Path(self.temp_dir) / 'run_f_sum_list'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f, summary=[10])):
            res = validate_pipeline(self.url, run_dir_f_list, overwrite=True)
        self.assertNotEqual(res['status'], 'SUCCESS')

        # 4. Forged total_answers in fill report (999)
        run_dir_forged_f = Path(self.temp_dir) / 'run_f_sum_forged'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f, summary={'filled': 1, 'skipped': 0, 'failed': 0, 'total_answers': 999})):
            res = validate_pipeline(self.url, run_dir_forged_f, overwrite=True)
        self.assertNotEqual(res['status'], 'SUCCESS')

        # 5. Non-integer or boolean count in summary
        run_dir_bool_cnt = Path(self.temp_dir) / 'run_f_sum_bool_cnt'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f, summary={'filled': True, 'skipped': 0, 'failed': 0, 'total_answers': 1})):
            res = validate_pipeline(self.url, run_dir_bool_cnt, overwrite=True)
        self.assertNotEqual(res['status'], 'SUCCESS')

    def test_required_flag_shapes(self):
        """Isolated checks for question required flag: literal True, False, None valid; 0, 'false' invalid."""
        base_ans = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'status': 'ready', 'answer': 'v1'}]
        base_f = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'}]

        valid_flags = [True, False, None]
        for idx, flag in enumerate(valid_flags):
            with self.subTest(flag=flag):
                q = [{'id': 'q1', 'text': 'Field', 'input_type': 'text', 'required': flag}]
                run_dir = Path(self.temp_dir) / f'run_req_valid_{idx}'
                with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q)), \
                     patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
                     patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f)):
                    res = validate_pipeline(self.url, run_dir, overwrite=True)
                self.assertEqual(res['status'], 'SUCCESS')

        invalid_flags = [0, 1, 'true', 'false', [], {}]
        for idx, flag in enumerate(invalid_flags):
            with self.subTest(flag=flag):
                q = [{'id': 'q1', 'text': 'Field', 'input_type': 'text', 'required': flag}]
                run_dir = Path(self.temp_dir) / f'run_req_invalid_{idx}'
                with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q)), \
                     patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
                     patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f)):
                    res = validate_pipeline(self.url, run_dir, overwrite=True)
                self.assertNotEqual(res['status'], 'SUCCESS')

    def test_phase_exceptions_and_downstream_calls(self):
        """Exceptions in extract/resolve prevent downstream phase execution."""
        run_dir_ext_raise = Path(self.temp_dir) / 'run_ext_raise'
        res_called = []
        fill_called = []
        with patch('job_applier.validate_pipeline.extract_main', side_effect=RuntimeError('extract crashed')), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=lambda a: res_called.append(True)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=lambda a: fill_called.append(True)):
            res = validate_pipeline(self.url, run_dir_ext_raise, overwrite=True)
        self.assertEqual(res['status'], 'FAILED')
        self.assertEqual(len(res_called), 0)
        self.assertEqual(len(fill_called), 0)

        run_dir_res_raise = Path(self.temp_dir) / 'run_res_raise'
        base_q = [{'id': 'q1', 'text': 'Field', 'input_type': 'text', 'required': True}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=RuntimeError('resolve crashed')), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=lambda a: fill_called.append(True)):
            res = validate_pipeline(self.url, run_dir_res_raise, overwrite=True)
        self.assertEqual(res['status'], 'FAILED')
        self.assertEqual(len(fill_called), 0)

    def test_screenshot_issues_reject_success(self):
        """Missing screenshot, empty screenshot (0 bytes), or path mismatch rejects SUCCESS."""
        base_q = [{'id': 'q1', 'text': 'Field', 'input_type': 'text', 'required': True}]
        base_ans = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'status': 'ready', 'answer': 'v1'}]
        base_f = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'}]

        # 1. Screenshot not written
        run_dir_no_ss = Path(self.temp_dir) / 'run_no_screenshot'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f, write_screenshot=False)):
            res = validate_pipeline(self.url, run_dir_no_ss, overwrite=True)
        self.assertNotEqual(res['status'], 'SUCCESS')

        # 2. Screenshot empty (0 bytes)
        run_dir_empty_ss = Path(self.temp_dir) / 'run_empty_screenshot'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f, screenshot_bytes=b'')):
            res = validate_pipeline(self.url, run_dir_empty_ss, overwrite=True)
        self.assertNotEqual(res['status'], 'SUCCESS')

        # 3. Screenshot path mismatch
        run_dir_mis_ss = Path(self.temp_dir) / 'run_mis_screenshot'
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f, screenshot_path='/tmp/other_path.png')):
            res = validate_pipeline(self.url, run_dir_mis_ss, overwrite=True)
        self.assertNotEqual(res['status'], 'SUCCESS')

    def test_f03_planned_intent_rejections_otherwise_success(self):
        """F03 residual 1: reject null/blank/unusable planned intent kind-specific instead of skipping comparison."""
        # 1. Null text planned answer with observed non-blank text -> otherwise SUCCESS must fail
        q_txt = [{'id': 'q_t', 'text': 'Name', 'input_type': 'text', 'required': True}]
        ans_txt_null = [{'question_id': 'q_t', 'id': 'q_t', 'text': 'Name', 'status': 'ready', 'answer': None}]
        f_txt = [{'question_id': 'q_t', 'id': 'q_t', 'text': 'Name', 'input_type': 'text', 'status': 'filled', 'verified_value': 'Alice'}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_txt)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_txt_null)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_txt)):
            res_txt_null = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f03_txt_null', overwrite=True)
        self.assertNotEqual(res_txt_null['status'], 'SUCCESS')
        self.assertIn('q_t', res_txt_null['missing_required'])

        # 2. Null choice planned answer without selected_option with observed non-blank -> must fail
        q_sel = [{'id': 'q_s', 'text': 'Choice', 'input_type': 'select', 'required': True}]
        ans_sel_null = [{'question_id': 'q_s', 'id': 'q_s', 'text': 'Choice', 'status': 'ready', 'answer': None}]
        f_sel = [{'question_id': 'q_s', 'id': 'q_s', 'text': 'Choice', 'input_type': 'select', 'status': 'filled', 'verified_value': 'OptionA'}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_sel)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_sel_null)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_sel)):
            res_sel_null = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f03_sel_null', overwrite=True)
        self.assertNotEqual(res_sel_null['status'], 'SUCCESS')
        self.assertIn('q_s', res_sel_null['missing_required'])

        # 3. Null file planned answer with observed basename -> must fail
        q_file = [{'id': 'q_f', 'text': 'Resume', 'input_type': 'file', 'required': True}]
        ans_file_null = [{'question_id': 'q_f', 'id': 'q_f', 'text': 'Resume', 'status': 'ready', 'answer': None}]
        f_file = [{'question_id': 'q_f', 'id': 'q_f', 'text': 'Resume', 'input_type': 'file', 'status': 'filled', 'verified_value': 'resume.pdf'}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_file)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_file_null)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_file)):
            res_file_null = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f03_file_null', overwrite=True)
        self.assertNotEqual(res_file_null['status'], 'SUCCESS')
        self.assertIn('q_f', res_file_null['missing_required'])

        # 4. Numeric file planned answer (123) with observed basename -> must fail
        ans_file_num = [{'question_id': 'q_f', 'id': 'q_f', 'text': 'Resume', 'status': 'ready', 'answer': 123}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_file)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_file_num)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_file)):
            res_file_num = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f03_file_num', overwrite=True)
        self.assertNotEqual(res_file_num['status'], 'SUCCESS')
        self.assertIn('q_f', res_file_num['missing_required'])

        # 5. Checkbox planned 0 (numeric) observed True required -> must fail
        q_chk_req = [{'id': 'q_c0', 'text': 'Agree', 'input_type': 'checkbox', 'required': True}]
        ans_chk_0 = [{'question_id': 'q_c0', 'id': 'q_c0', 'text': 'Agree', 'status': 'ready', 'answer': 0}]
        f_chk_true = [{'question_id': 'q_c0', 'id': 'q_c0', 'text': 'Agree', 'input_type': 'checkbox', 'status': 'filled', 'verified_value': True}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_chk_req)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_chk_0)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_chk_true)):
            res_chk_0 = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f03_chk_0', overwrite=True)
        self.assertNotEqual(res_chk_0['status'], 'SUCCESS')
        self.assertIn('q_c0', res_chk_0['missing_required'])

        # 6. Checkbox numeric 1 optional observed False -> must fail
        q_chk_opt = [{'id': 'q_c1', 'text': 'Newsletter', 'input_type': 'checkbox', 'required': False}]
        ans_chk_1 = [{'question_id': 'q_c1', 'id': 'q_c1', 'text': 'Newsletter', 'status': 'ready', 'answer': 1}]
        f_chk_false = [{'question_id': 'q_c1', 'id': 'q_c1', 'text': 'Newsletter', 'input_type': 'checkbox', 'status': 'filled', 'verified_value': False}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_chk_opt)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_chk_1)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_chk_false)):
            res_chk_1 = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f03_chk_1', overwrite=True)
        self.assertNotEqual(res_chk_1['status'], 'SUCCESS')
        self.assertIn('q_c1', res_chk_1.get('optional_invalid_fills', []))

    def test_f03_choice_captured_options_same_option_and_aliases(self):
        """F03 residual 2: choices selected label/value must identify SAME captured option."""
        # Snapshot has Canada/CA and France/FR
        q_choice = [{
            'id': 'q_country',
            'text': 'Country',
            'input_type': 'select',
            'required': True,
            'options': {
                'items': [
                    {'id': 'opt_1', 'label': 'Canada', 'value': 'CA'},
                    {'id': 'opt_2', 'label': 'France', 'value': 'FR'},
                ]
            }
        }]

        # Contradictory: answer Canada, selected {label: Canada, value: FR}, observed FR -> MUST FAIL
        ans_contra = [{
            'question_id': 'q_country',
            'id': 'q_country',
            'text': 'Country',
            'status': 'ready',
            'answer': 'Canada',
            'selected_option': {'label': 'Canada', 'value': 'FR'},
        }]
        f_fr = [{
            'question_id': 'q_country',
            'id': 'q_country',
            'text': 'Country',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': 'FR',
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_choice)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_contra)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_fr)):
            res_contra = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f03_choice_contra', overwrite=True)
        self.assertNotEqual(res_contra['status'], 'SUCCESS')
        self.assertIn('q_country', res_contra['missing_required'])

        # Consistent: answer Canada, selected {label: Canada, value: CA}, observed CA -> MUST SUCCEED
        ans_ok = [{
            'question_id': 'q_country',
            'id': 'q_country',
            'text': 'Country',
            'status': 'ready',
            'answer': 'Canada',
            'selected_option': {'label': 'Canada', 'value': 'CA'},
        }]
        f_ca = [{
            'question_id': 'q_country',
            'id': 'q_country',
            'text': 'Country',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': 'CA',
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_choice)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_ok)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_ca)):
            res_ok = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f03_choice_ok', overwrite=True)
        self.assertEqual(res_ok['status'], 'SUCCESS')

        # Selected-option-only plan actually supported by producer -> MUST SUCCEED
        ans_sel_only = [{
            'question_id': 'q_country',
            'id': 'q_country',
            'text': 'Country',
            'status': 'ready',
            'answer': None,
            'selected_option': {'label': 'Canada', 'value': 'CA'},
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_choice)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_sel_only)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_ca)):
            res_sel_only = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f03_choice_sel_only', overwrite=True)
        self.assertEqual(res_sel_only['status'], 'SUCCESS')

        # Without captured option metadata, unattested contradictory label/value alias -> MUST FAIL
        q_no_opts = [{'id': 'q_c_no_opts', 'text': 'Country', 'input_type': 'select', 'required': True}]
        ans_unattested = [{
            'question_id': 'q_c_no_opts',
            'id': 'q_c_no_opts',
            'text': 'Country',
            'status': 'ready',
            'answer': 'Canada',
            'selected_option': {'label': 'Canada', 'value': 'FR'},
        }]
        f_unattested = [{
            'question_id': 'q_c_no_opts',
            'id': 'q_c_no_opts',
            'text': 'Country',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': 'FR',
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_no_opts)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_unattested)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_unattested)):
            res_unattested = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f03_unattested', overwrite=True)
        self.assertNotEqual(res_unattested['status'], 'SUCCESS')
        self.assertIn('q_c_no_opts', res_unattested['missing_required'])

    def test_f03_fill_total_answers_exclusively_equals_answer_plan_count(self):
        """F03 residual 3: fill.total_answers exclusively equals len(answers), NOT len(fields)."""
        questions = [
            {'id': 'q_req', 'text': 'Required Field', 'input_type': 'text', 'required': True},
            {'id': 'q_opt', 'text': 'Optional Field', 'input_type': 'text', 'required': False},
        ]
        answers = [
            {'question_id': 'q_req', 'id': 'q_req', 'text': 'Required Field', 'status': 'ready', 'answer': 'ReqVal'},
            {'question_id': 'q_opt', 'id': 'q_opt', 'text': 'Optional Field', 'status': 'ready', 'answer': 'OptVal'},
        ]
        # Only required field is filled; optional is omitted (valid omission contract)
        fields = [
            {'question_id': 'q_req', 'id': 'q_req', 'text': 'Required Field', 'input_type': 'text', 'status': 'filled', 'verified_value': 'ReqVal'},
        ]

        # Case A: total_answers declared as 1 (equals len(fields), not len(answers)) -> integrity failure
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(questions)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(answers)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(fields, total_answers=1)):
            res_1 = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f03_total_1', overwrite=True)
        self.assertNotEqual(res_1['status'], 'SUCCESS')
        self.assertEqual(res_1['status'], 'PARTIAL')
        self.assertTrue(any('Step 3 (Fill) summary mismatch: claimed total_answers=1, expected 2' in err for err in res_1['errors']))

        # Case B: total_answers declared as 2 (consistent with len(answers_by_id)) -> SUCCESS
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(questions)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(answers)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(fields, total_answers=2)):
            res_2 = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f03_total_2', overwrite=True)
        self.assertEqual(res_2['status'], 'SUCCESS')

    def test_f03_stale_artifacts_and_downstream_nonexecution(self):
        """F03 residual 4: stale answer/fill_report/screenshot artifacts with downstream non-execution."""
        base_q = [{'id': 'q1', 'text': 'Field', 'input_type': 'text', 'required': True}]
        base_ans = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'status': 'ready', 'answer': 'v1'}]
        base_f = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'}]

        # 1. Stale answers.json after fresh extraction
        run_dir_stale_ans = Path(self.temp_dir) / 'run_stale_ans'
        run_dir_stale_ans.mkdir(parents=True, exist_ok=True)
        old_ans_file = run_dir_stale_ans / 'answers.json'
        write_json_atomic(old_ans_file, {'schema': RESOLUTION_SCHEMA, 'snapshot_id': 'snap-001', 'answers': []}, overwrite=True)

        fill_called = []
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', return_value=0), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=lambda a: fill_called.append(True)):
            res_stale_ans = validate_pipeline(self.url, run_dir_stale_ans, overwrite=True)
        self.assertEqual(res_stale_ans['status'], 'FAILED')
        self.assertFalse(res_stale_ans['answered'])
        self.assertEqual(len(fill_called), 0)
        self.assertTrue(any('answers.json not freshly created' in err for err in res_stale_ans['errors']))

        # 2. Stale fill_report.json after fresh answer
        run_dir_stale_rep = Path(self.temp_dir) / 'run_stale_rep'
        run_dir_stale_rep.mkdir(parents=True, exist_ok=True)
        old_rep_file = run_dir_stale_rep / 'fill_report.json'
        write_json_atomic(old_rep_file, {'schema': FILL_SCHEMA, 'snapshot_id': 'snap-001', 'fields': []}, overwrite=True)

        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', return_value=0):
            res_stale_rep = validate_pipeline(self.url, run_dir_stale_rep, overwrite=True)
        self.assertEqual(res_stale_rep['status'], 'FAILED')
        self.assertFalse(res_stale_rep['filled'])
        self.assertTrue(any('fill_report.json not freshly created' in err for err in res_stale_rep['errors']))

        # 3. Unchanged screenshot after fresh fill_report.json
        run_dir_stale_ss = Path(self.temp_dir) / 'run_stale_ss'
        run_dir_stale_ss.mkdir(parents=True, exist_ok=True)
        old_ss = run_dir_stale_ss / 'screenshot.png'
        old_ss.write_bytes(b'PREEXISTING_SCREENSHOT_BYTES')

        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f, write_screenshot=False)):
            res_stale_ss = validate_pipeline(self.url, run_dir_stale_ss, overwrite=True)
        self.assertNotEqual(res_stale_ss['status'], 'SUCCESS')
        self.assertTrue(any('screenshot not freshly created' in err for err in res_stale_ss['errors']))

    def test_f03_fill_report_schema_and_lineage_mismatches(self):
        """F03 residual 4: fill report schema/version and lineage mismatches."""
        base_q = [{'id': 'q1', 'text': 'Field', 'input_type': 'text', 'required': True}]
        base_ans = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'status': 'ready', 'answer': 'v1'}]
        base_f = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'}]

        # 1. Fill report schema mismatch
        def _fill_bad_schema(args):
            out_dir = Path(args[args.index('--out') + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            rep_file = out_dir / 'fill_report.json'
            (out_dir / 'screenshot.png').write_bytes(b'PNG_BYTES')
            payload = {
                'schema': 'https://job-applier.invalid/schema/fill/v999.json',
                'snapshot_id': 'snap-001',
                'fields': base_f,
                'summary': {'filled': 1, 'skipped': 0, 'failed': 0, 'total_answers': 1},
                'screenshot_path': str(out_dir / 'screenshot.png'),
                'telemetry': {'guard_active': True, 'blocked_form_submits': 0},
            }
            write_json_atomic(rep_file, payload, overwrite=True)
            return 0

        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=_fill_bad_schema):
            res_schema = validate_pipeline(self.url, Path(self.temp_dir) / 'run_bad_schema', overwrite=True)
        self.assertNotEqual(res_schema['status'], 'SUCCESS')
        self.assertTrue(any('invalid schema' in err for err in res_schema['errors']))

        # 2. Fill report lineage mismatch
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q, snapshot_id='snap-AAA')), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans, snapshot_id='snap-AAA')), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f, snapshot_id='snap-ZZZ')):
            res_lineage = validate_pipeline(self.url, Path(self.temp_dir) / 'run_bad_lineage', overwrite=True)
        self.assertNotEqual(res_lineage['status'], 'SUCCESS')
        self.assertTrue(any('lineage mismatch' in err for err in res_lineage['errors']))

    def test_f03_answer_summary_total_forged_999(self):
        """F03 residual 4: answer summary total forged count 999 rejected."""
        base_q = [{'id': 'q1', 'text': 'Field', 'input_type': 'text', 'required': True}]
        base_ans = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'status': 'ready', 'answer': 'v1'}]
        base_f = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'}]

        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans, summary={'ready': 1, 'review': 0, 'needs_user': 0, 'total': 999})), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f)):
            res = validate_pipeline(self.url, Path(self.temp_dir) / 'run_ans_tot_999', overwrite=True)
        self.assertNotEqual(res['status'], 'SUCCESS')
        self.assertTrue(any('claimed total=999' in err for err in res['errors']))

    def test_f03_cli_exit_codes_success_partial_failed(self):
        """F03 residual 4: mock CLI invocation returns 0 for SUCCESS, 1 for PARTIAL, 1 for FAILED."""
        base_q = [{'id': 'q1', 'text': 'Field', 'input_type': 'text', 'required': True}]
        base_ans = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'status': 'ready', 'answer': 'v1'}]
        base_f = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'}]

        # 1. SUCCESS -> code 0
        run_dir_succ = Path(self.temp_dir) / 'run_cli_succ'
        cli_args_succ = [self.url, '--out', str(run_dir_succ), '--overwrite']
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(base_f)):
            cap_out = io.StringIO()
            with patch('sys.stdout', cap_out):
                code_succ = main(cli_args_succ)
            self.assertEqual(code_succ, 0)
            self.assertEqual(json.loads(cap_out.getvalue())['status'], 'SUCCESS')

        # 2. PARTIAL (e.g. required skip) -> code 1
        q_partial = [
            {'id': 'q1', 'text': 'Field 1', 'input_type': 'text', 'required': True},
            {'id': 'q2', 'text': 'Field 2', 'input_type': 'text', 'required': True},
        ]
        ans_partial = [
            {'question_id': 'q1', 'id': 'q1', 'text': 'Field 1', 'status': 'ready', 'answer': 'v1'},
            {'question_id': 'q2', 'id': 'q2', 'text': 'Field 2', 'status': 'needs_user', 'answer': None},
        ]
        f_partial = [
            {'question_id': 'q1', 'id': 'q1', 'text': 'Field 1', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'},
            {'question_id': 'q2', 'id': 'q2', 'text': 'Field 2', 'input_type': 'text', 'status': 'skipped', 'verified_value': None, 'skip_reason': 'needs_user'},
        ]
        run_dir_part = Path(self.temp_dir) / 'run_cli_part'
        cli_args_part = [self.url, '--out', str(run_dir_part), '--overwrite']
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_partial)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_partial)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_partial, total_answers=2)):
            cap_out = io.StringIO()
            with patch('sys.stdout', cap_out):
                code_part = main(cli_args_part)
            self.assertEqual(code_part, 1)
            self.assertEqual(json.loads(cap_out.getvalue())['status'], 'PARTIAL')

        # 3. FAILED (e.g. extract crash) -> code 1
        run_dir_fail = Path(self.temp_dir) / 'run_cli_fail'
        cli_args_fail = [self.url, '--out', str(run_dir_fail), '--overwrite']
        with patch('job_applier.validate_pipeline.extract_main', return_value=1):
            cap_out = io.StringIO()
            with patch('sys.stdout', cap_out):
                code_fail = main(cli_args_fail)
            self.assertEqual(code_fail, 1)
            self.assertEqual(json.loads(cap_out.getvalue())['status'], 'FAILED')

    def test_f04_choice_selected_option_blank_or_unknown_key_rejected(self):
        """F04 Finding 1: selected_option with blank label or unknown keys must not wildcard match."""
        q_ca = [{
            'id': 'q_country',
            'text': 'Country',
            'input_type': 'select',
            'required': True,
            'options': {'items': [{'label': 'Canada', 'value': 'CA'}]},
        }]
        f_ca = [{
            'question_id': 'q_country',
            'id': 'q_country',
            'text': 'Country',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': 'CA',
        }]

        # 1A: selected_option={'label': ''} with answer=None must NOT wildcard match Canada/CA
        ans_blank_lbl = [{
            'question_id': 'q_country',
            'id': 'q_country',
            'text': 'Country',
            'status': 'ready',
            'answer': None,
            'selected_option': {'label': ''},
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_ca)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_blank_lbl)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_ca)):
            res_blank = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_blank_lbl', overwrite=True)
        self.assertNotEqual(res_blank['status'], 'SUCCESS')
        self.assertIn('q_country', res_blank['missing_required'])

        # 1B: selected_option={'unknown_key': 'foo'} with answer=None must NOT wildcard match Canada/CA
        ans_unknown_key = [{
            'question_id': 'q_country',
            'id': 'q_country',
            'text': 'Country',
            'status': 'ready',
            'answer': None,
            'selected_option': {'unknown_key': 'foo'},
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_ca)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_unknown_key)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_ca)):
            res_unk = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_unk_key', overwrite=True)
        self.assertNotEqual(res_unk['status'], 'SUCCESS')
        self.assertIn('q_country', res_unk['missing_required'])

        # 1C: Legitimate selected-option-only intent with unambiguous captured option -> MUST SUCCEED
        ans_legit = [{
            'question_id': 'q_country',
            'id': 'q_country',
            'text': 'Country',
            'status': 'ready',
            'answer': None,
            'selected_option': {'label': 'Canada'},
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_ca)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_legit)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_ca)):
            res_legit = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_legit_ca', overwrite=True)
        self.assertEqual(res_legit['status'], 'SUCCESS')

    def test_f04_choice_falsy_primitive_values_captured_and_uncaptured(self):
        """F04 Finding 2: 0 and False must not be discarded; contradictory values fail; valid falsy primitives pass."""
        # 2A: Contradictory Canada/CA with selected value 0 or False must fail
        q_ca = [{
            'id': 'q_country',
            'text': 'Country',
            'input_type': 'select',
            'required': True,
            'options': {'items': [{'label': 'Canada', 'value': 'CA'}]},
        }]
        f_ca = [{
            'question_id': 'q_country',
            'id': 'q_country',
            'text': 'Country',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': 'CA',
        }]

        for bad_val in (0, False):
            with self.subTest(bad_val=bad_val):
                ans_contra = [{
                    'question_id': 'q_country',
                    'id': 'q_country',
                    'text': 'Country',
                    'status': 'ready',
                    'answer': None,
                    'selected_option': {'label': 'Canada', 'value': bad_val},
                }]
                with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_ca)), \
                     patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_contra)), \
                     patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_ca)):
                    res_c = validate_pipeline(self.url, Path(self.temp_dir) / f'run_f04_contra_ca_{bad_val}', overwrite=True)
                self.assertNotEqual(res_c['status'], 'SUCCESS')
                self.assertIn('q_country', res_c['missing_required'])

        # 2B: Valid falsy primitive with captured metadata -> MUST SUCCEED
        q_dis = [{
            'id': 'q_dis',
            'text': 'Disability',
            'input_type': 'select',
            'required': True,
            'options': {'items': [{'label': 'None', 'value': 0}]},
        }]
        ans_dis = [{
            'question_id': 'q_dis',
            'id': 'q_dis',
            'text': 'Disability',
            'status': 'ready',
            'answer': None,
            'selected_option': {'label': 'None', 'value': 0},
        }]
        f_dis = [{
            'question_id': 'q_dis',
            'id': 'q_dis',
            'text': 'Disability',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': '0',
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_dis)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_dis)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_dis)):
            res_dis = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_dis_0', overwrite=True)
        self.assertEqual(res_dis['status'], 'SUCCESS')

        # 2C: Valid falsy primitive without captured metadata -> MUST SUCCEED
        q_no_meta = [{'id': 'q_opt_nm', 'text': 'Option', 'input_type': 'select', 'required': True}]
        ans_no_meta = [{
            'question_id': 'q_opt_nm',
            'id': 'q_opt_nm',
            'text': 'Option',
            'status': 'ready',
            'answer': None,
            'selected_option': {'label': 'No', 'value': False},
        }]
        f_no_meta = [{
            'question_id': 'q_opt_nm',
            'id': 'q_opt_nm',
            'text': 'Option',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': 'false',
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_no_meta)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_no_meta)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_no_meta)):
            res_nm = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_nm_false', overwrite=True)
        self.assertEqual(res_nm['status'], 'SUCCESS')

        # 2D: Valid falsy primitive value-only without captured metadata -> MUST SUCCEED
        ans_val_0 = [{
            'question_id': 'q_opt_nm',
            'id': 'q_opt_nm',
            'text': 'Option',
            'status': 'ready',
            'answer': None,
            'selected_option': {'value': 0},
        }]
        f_val_0 = [{
            'question_id': 'q_opt_nm',
            'id': 'q_opt_nm',
            'text': 'Option',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': '0',
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_no_meta)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_val_0)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_val_0)):
            res_v0 = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_nm_val0', overwrite=True)
        self.assertEqual(res_v0['status'], 'SUCCESS')

        # 2E: Contradictory without captured metadata -> MUST FAIL
        ans_contra_nm = [{
            'question_id': 'q_opt_nm',
            'id': 'q_opt_nm',
            'text': 'Option',
            'status': 'ready',
            'answer': None,
            'selected_option': {'label': 'Canada', 'value': 0},
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_no_meta)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_contra_nm)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_val_0)):
            res_cnm = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_nm_contra', overwrite=True)
        self.assertNotEqual(res_cnm['status'], 'SUCCESS')

    def test_f04_choice_boolean_alias_expansion_no1_yes0(self):
        """F04 Finding 3: captured No/1 Yes/0 plan No selected No/1 observed Yes must fail; No or 1 passes."""
        q_choice = [{
            'id': 'q_reloc',
            'text': 'Willing to relocate?',
            'input_type': 'select',
            'required': True,
            'options': {
                'items': [
                    {'id': 'opt_no', 'label': 'No', 'value': '1'},
                    {'id': 'opt_yes', 'label': 'Yes', 'value': '0'},
                ]
            },
        }]
        ans_plan_no = [{
            'question_id': 'q_reloc',
            'id': 'q_reloc',
            'text': 'Willing to relocate?',
            'status': 'ready',
            'answer': 'No',
            'selected_option': {'label': 'No', 'value': '1'},
        }]

        # 3A: Observed Yes -> MUST FAIL
        f_obs_yes = [{
            'question_id': 'q_reloc',
            'id': 'q_reloc',
            'text': 'Willing to relocate?',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': 'Yes',
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_choice)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_plan_no)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_obs_yes)):
            res_yes = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_obs_yes', overwrite=True)
        self.assertNotEqual(res_yes['status'], 'SUCCESS')
        self.assertIn('q_reloc', res_yes['missing_required'])

        # 3B: Observed No -> MUST SUCCEED
        f_obs_no = [{
            'question_id': 'q_reloc',
            'id': 'q_reloc',
            'text': 'Willing to relocate?',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': 'No',
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_choice)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_plan_no)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_obs_no)):
            res_no = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_obs_no', overwrite=True)
        self.assertEqual(res_no['status'], 'SUCCESS')

        # 3C: Observed canonical value '1' -> MUST SUCCEED
        f_obs_1 = [{
            'question_id': 'q_reloc',
            'id': 'q_reloc',
            'text': 'Willing to relocate?',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': '1',
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_choice)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_plan_no)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_obs_1)):
            res_1 = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_obs_1', overwrite=True)
        self.assertEqual(res_1['status'], 'SUCCESS')

    def test_f04_numeric_text_plan_and_negatives(self):
        """F04 Finding 4: number control planned int 3 observed '3' must pass; negatives fail."""
        q_num = [{'id': 'q_exp', 'text': 'Years of experience', 'input_type': 'number', 'required': True}]

        # 4A: planned int 3, observed str '3' -> MUST SUCCEED
        ans_int3 = [{'question_id': 'q_exp', 'id': 'q_exp', 'text': 'Years of experience', 'status': 'ready', 'answer': 3}]
        f_str3 = [{'question_id': 'q_exp', 'id': 'q_exp', 'text': 'Years of experience', 'input_type': 'number', 'status': 'filled', 'verified_value': '3'}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_num)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_int3)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_str3)):
            res_3 = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_num_3', overwrite=True)
        self.assertEqual(res_3['status'], 'SUCCESS')

        # 4B: planned int 3, observed str '4' -> MUST FAIL (mismatch)
        f_str4 = [{'question_id': 'q_exp', 'id': 'q_exp', 'text': 'Years of experience', 'input_type': 'number', 'status': 'filled', 'verified_value': '4'}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_num)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_int3)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_str4)):
            res_mis = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_num_mismatch', overwrite=True)
        self.assertNotEqual(res_mis['status'], 'SUCCESS')
        self.assertIn('q_exp', res_mis['missing_required'])

        # 4C: planned None, observed str '3' -> MUST FAIL (null)
        ans_null = [{'question_id': 'q_exp', 'id': 'q_exp', 'text': 'Years of experience', 'status': 'ready', 'answer': None}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_num)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_null)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_str3)):
            res_null = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_num_null', overwrite=True)
        self.assertNotEqual(res_null['status'], 'SUCCESS')

        # 4D: planned blank, observed str '3' -> MUST FAIL (blank)
        ans_blank = [{'question_id': 'q_exp', 'id': 'q_exp', 'text': 'Years of experience', 'status': 'ready', 'answer': '   '}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_num)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_blank)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_str3)):
            res_blank = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_num_blank', overwrite=True)
        self.assertNotEqual(res_blank['status'], 'SUCCESS')

        # 4E: planned container [3], observed str '3' -> MUST FAIL (container)
        ans_cont = [{'question_id': 'q_exp', 'id': 'q_exp', 'text': 'Years of experience', 'status': 'ready', 'answer': [3]}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_num)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_cont)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_str3)):
            res_cont = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_num_cont', overwrite=True)
        self.assertNotEqual(res_cont['status'], 'SUCCESS')

        # 4F: planned bool True, observed str 'True' -> MUST FAIL (excludebool)
        ans_bool = [{'question_id': 'q_exp', 'id': 'q_exp', 'text': 'Years of experience', 'status': 'ready', 'answer': True}]
        f_bool = [{'question_id': 'q_exp', 'id': 'q_exp', 'text': 'Years of experience', 'input_type': 'number', 'status': 'filled', 'verified_value': 'True'}]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q_num)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans_bool)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f_bool)):
            res_bool = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_num_bool', overwrite=True)
        self.assertNotEqual(res_bool['status'], 'SUCCESS')

    def test_f04_field_integrity_reset_retention(self):
        """F04 Finding 5: field_integrity_ok must not be reset after schema/lineage mismatch."""
        base_q = [{'id': 'q1', 'text': 'Field', 'input_type': 'text', 'required': True}]
        base_ans = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'status': 'ready', 'answer': 'v1'}]
        base_f = [{'question_id': 'q1', 'id': 'q1', 'text': 'Field', 'input_type': 'text', 'status': 'filled', 'verified_value': 'v1'}]

        # Custom fill mock that provides schema mismatch
        def _fill_schema_mismatch(args):
            out_dir = Path(args[args.index('--out') + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            rep_file = out_dir / 'fill_report.json'
            (out_dir / 'screenshot.png').write_bytes(b'PNG_BYTES')
            payload = {
                'schema': 'wrong-schema-v0',
                'snapshot_id': 'snap-001',
                'fields': base_f,
                'summary': {'filled': 1, 'skipped': 0, 'failed': 0, 'total_answers': 1},
                'screenshot_path': str(out_dir / 'screenshot.png'),
                'telemetry': {'guard_active': True, 'blocked_form_submits': 0},
            }
            write_json_atomic(rep_file, payload, overwrite=True)
            return 0

        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(base_q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(base_ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=_fill_schema_mismatch):
            res = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_field_integrity', overwrite=True)
        self.assertNotEqual(res['status'], 'SUCCESS')
        self.assertFalse(res['filled'])
        self.assertTrue(any('invalid schema' in err for err in res['errors']))

    def test_f04_rework_uncaptured_contradictory_id_fails(self):
        """Rework 1: Question without captured options, answer="Canada", selected_option={"id": "opt_us"}, observed="opt_us".
        Must fail and report missing required deficit (NOT SUCCESS).
        """
        q = [{'id': 'q_country', 'text': 'Country', 'input_type': 'select', 'required': True}]
        ans = [{
            'question_id': 'q_country',
            'id': 'q_country',
            'text': 'Country',
            'status': 'ready',
            'answer': 'Canada',
            'selected_option': {'id': 'opt_us'},
        }]
        f = [{
            'question_id': 'q_country',
            'id': 'q_country',
            'text': 'Country',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': 'opt_us',
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f)):
            res = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_uncaptured_contra_id', overwrite=True)
        self.assertNotEqual(res['status'], 'SUCCESS')
        self.assertIn('q_country', res['missing_required'])

    def test_f04_rework_option_id_primitive_zero_succeeds(self):
        """Rework 2: Captured option with id: 0, label: "Zero", value: "zero".
        Answer with selected_option={"id": 0, "label": "Zero"}. Observed DOM value "0". Must succeed.
        """
        q = [{
            'id': 'q_num_choice',
            'text': 'Number Option',
            'input_type': 'select',
            'required': True,
            'options': {'items': [{'id': 0, 'label': 'Zero', 'value': 'zero'}]},
        }]
        ans = [{
            'question_id': 'q_num_choice',
            'id': 'q_num_choice',
            'text': 'Number Option',
            'status': 'ready',
            'answer': None,
            'selected_option': {'id': 0, 'label': 'Zero'},
        }]
        f = [{
            'question_id': 'q_num_choice',
            'id': 'q_num_choice',
            'text': 'Number Option',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': '0',
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f)):
            res = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_opt_id_zero', overwrite=True)
        self.assertEqual(res['status'], 'SUCCESS')
        self.assertEqual(res['missing_required'], [])

    def test_f04_rework_choice_numeric_planned_answer(self):
        """Rework 3: Choice select question with options 1, 2, 3.
        Answer plan has answer: 3 (int). Observed "3". Must succeed.
        """
        q = [{
            'id': 'q_rating',
            'text': 'Rating',
            'input_type': 'select',
            'required': True,
            'options': {
                'items': [
                    {'label': '1', 'value': '1'},
                    {'label': '2', 'value': '2'},
                    {'label': '3', 'value': '3'},
                ]
            },
        }]
        ans = [{
            'question_id': 'q_rating',
            'id': 'q_rating',
            'text': 'Rating',
            'status': 'ready',
            'answer': 3,
        }]
        f = [{
            'question_id': 'q_rating',
            'id': 'q_rating',
            'text': 'Rating',
            'input_type': 'select',
            'status': 'filled',
            'verified_value': '3',
        }]
        with patch('job_applier.validate_pipeline.extract_main', side_effect=self._make_extract_mock(q)), \
             patch('job_applier.validate_pipeline.resolve_main', side_effect=self._make_resolve_mock(ans)), \
             patch('job_applier.validate_pipeline.fill_main', side_effect=self._make_fill_mock(f)):
            res = validate_pipeline(self.url, Path(self.temp_dir) / 'run_f04_choice_numeric', overwrite=True)
        self.assertEqual(res['status'], 'SUCCESS')
        self.assertEqual(res['missing_required'], [])


class ValidatePipelineTests(unittest.TestCase):
    """Integration checks with honest expectations (mandatory resume unfilled)."""

    def setUp(self):
        self.fixture_path = ROOT / 'tests/fixtures/greenhouse.html'
        self.fixture_url = self.fixture_path.as_uri()
        self.temp_dir = tempfile.mkdtemp(prefix='validate-pipeline-test-')

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @unittest.skipUnless(HAS_PLAYWRIGHT, "Playwright / requirements-phase1 not installed in current environment")
    def test_validate_pipeline_greenhouse_e2e(self):
        """Test full pipeline validation against greenhouse.html synthetic fixture.
        Honest expectation: PARTIAL due to mandatory resume unfilled without complete bank.
        """
        run_dir = Path(self.temp_dir) / 'run_e2e'
        result = validate_pipeline(self.fixture_url, run_dir, overwrite=True)

        self.assertEqual(result['status'], 'PARTIAL')
        self.assertTrue(result['fetched'])
        self.assertGreater(result['question_count'], 0)
        self.assertTrue(result['answered'])
        self.assertTrue(result['filled'])
        self.assertGreater(result['required_count'], 0)
        self.assertGreater(len(result['missing_required']), 0)

    @unittest.skipUnless(HAS_PLAYWRIGHT, "Playwright / requirements-phase1 not installed in current environment")
    def test_validate_pipeline_with_custom_bank(self):
        """Test pipeline validation with custom bank.
        Honest expectation: PARTIAL because resume remains unfilled.
        """
        run_dir = Path(self.temp_dir) / 'run_bank'

        bank_data = {
            'facts': {
                'contact.first_name': {'value': 'Marie', 'confirmed': True, 'source': 'vault'},
                'contact.last_name': {'value': 'Curie', 'confirmed': True, 'source': 'vault'},
                'contact.email': {'value': 'marie.curie@example.com', 'confirmed': True, 'source': 'vault'},
                'contact.phone': {'value': '+15551234567', 'confirmed': True, 'source': 'vault'},
                'contact.linkedin': {'value': 'https://linkedin.com/in/mariecurie', 'confirmed': True, 'source': 'vault'},
                'education.degree': {'value': 'Doctorate / PhD', 'confirmed': True, 'source': 'vault'},
                'personal.relocate': {'value': True, 'confirmed': True, 'source': 'vault'},
            }
        }
        bank_file = Path(self.temp_dir) / 'bank.json'
        bank_file.write_text(json.dumps(bank_data), encoding='utf-8')

        result = validate_pipeline(self.fixture_url, run_dir, bank=bank_file, overwrite=True)

        self.assertEqual(result['status'], 'PARTIAL')
        self.assertTrue(result['fetched'])
        self.assertTrue(result['answered'])
        self.assertTrue(result['filled'])

    @unittest.skipUnless(HAS_PLAYWRIGHT, "Playwright / requirements-phase1 not installed in current environment")
    def test_validate_pipeline_cli_invocation(self):
        """Test CLI main() execution returning 1 on PARTIAL for greenhouse fixture."""
        run_dir = Path(self.temp_dir) / 'run_cli'
        cli_args = [self.fixture_url, '--out', str(run_dir), '--overwrite']

        captured_stdout = io.StringIO()
        original_stdout = sys.stdout
        try:
            sys.stdout = captured_stdout
            exit_code = main(cli_args)
        finally:
            sys.stdout = original_stdout

        output_str = captured_stdout.getvalue().strip()
        parsed = json.loads(output_str)

        self.assertEqual(exit_code, 1)
        self.assertEqual(parsed['status'], 'PARTIAL')

    def test_validate_pipeline_invalid_scheme(self):
        """Test pipeline validation gracefully rejects unsupported URL schemes."""
        run_dir = Path(self.temp_dir) / 'run_invalid'
        result = validate_pipeline('ftp://example.com/form', run_dir, overwrite=True)

        self.assertEqual(result['status'], 'FAILED')
        self.assertFalse(result['fetched'])
        self.assertFalse(result['answered'])
        self.assertFalse(result['filled'])
        self.assertIsNone(result['screenshot'])
        self.assertIn('errors', result)
        self.assertTrue(any('URL must use' in err for err in result['errors']))


if __name__ == '__main__':
    unittest.main()
