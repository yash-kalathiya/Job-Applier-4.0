"""Unit tests for the Phase 2 resolution CLI (job-applier resolve)."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from job_applier.resolution.__main__ import main, load_bank
from job_applier.resolution import SCHEMA_VERSION


def make_synthetic_bank():
    return {
        'questions': [
            {
                'fact': 'contact.email',
                'input_types': ['text', 'email'],
                'aliases': ['Email', 'Email Address'],
            },
            {
                'fact': 'work.authorized_us',
                'input_types': ['single_choice', 'combobox', 'select', 'radio'],
                'aliases': ['Legally authorized to work in United States'],
            },
            {
                'fact': 'contact.name',
                'input_types': ['text'],
                'aliases': ['Full Name', 'Nom complet'],
            },
        ],
        'facts': {
            'contact.email': {
                'value': 'ada@example.com',
                'confirmed': True,
                'source': 'vault',
            },
            'work.authorized_us': {
                'value': True,
                'confirmed': True,
                'source': 'vault',
            },
            'contact.name': {
                'value': 'Ada Lovelace — 艾达 · 洛夫莱斯',
                'confirmed': True,
                'source': 'vault',
            },
        },
    }


def make_synthetic_questions():
    return {
        'schema': 'job-applier.extraction.v1',
        'snapshot_id': 'snap-test-xyz-987',
        'questions': [
            {
                'id': 'q1',
                'text': 'Email Address',
                'input_type': 'text',
                'section': 'Contact Information',
                'options': {'items': [], 'complete': False},
                'warnings': [],
                'required': True,
                'frame_id': 'frame-0',
                'control_ids': ['ctrl-q1'],
            },
            {
                'id': 'q2',
                'text': 'Legally authorized to work in United States',
                'input_type': 'single_choice',
                'section': 'Work Eligibility',
                'options': {
                    'items': [
                        {'id': 'opt-yes', 'label': 'Yes', 'value': 'yes'},
                        {'id': 'opt-no', 'label': 'No', 'value': 'no'},
                    ],
                    'complete': True,
                },
                'warnings': [],
                'required': True,
                'frame_id': 'frame-0',
                'control_ids': ['ctrl-q2'],
            },
            {
                'id': 'q3',
                'text': 'What is your favorite constellation?',
                'input_type': 'text',
                'section': 'Additional Questions',
                'options': {'items': [], 'complete': False},
                'warnings': [],
                'required': False,
                'frame_id': 'frame-0',
                'control_ids': ['ctrl-q3'],
            },
            {
                'id': 'q4',
                'text': 'Nom complet (Full Name)',
                'input_type': 'text',
                'section': 'Personal Details / Coordonnées',
                'options': {'items': [], 'complete': False},
                'warnings': [],
                'required': True,
                'frame_id': 'frame-0',
                'control_ids': ['ctrl-q4'],
            },
        ],
    }


class TestResolutionCLIArgParse(unittest.TestCase):
    def setUp(self):
        self._env_backup = {
            'GROQ_API_KEY': os.environ.get('GROQ_API_KEY'),
            'JOB_APPLIER_HOME': os.environ.get('JOB_APPLIER_HOME'),
            'APPLYTWIN_HOME': os.environ.get('APPLYTWIN_HOME'),
        }
        os.environ.pop('GROQ_API_KEY', None)

    def tearDown(self):
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_help_flag_exits_cleanly(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
            main(['--help'])
        self.assertEqual(cm.exception.code, 0)

    def test_missing_all_arguments_exits_with_code_2(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            main([])
        self.assertEqual(cm.exception.code, 2)

    def test_missing_out_argument_exits_with_code_2(self):
        with tempfile.TemporaryDirectory() as td:
            q_file = Path(td) / 'questions.json'
            q_file.write_text('{"questions": []}', encoding='utf-8')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                main([str(q_file)])
            self.assertEqual(cm.exception.code, 2)

    def test_missing_questions_argument_exits_with_code_2(self):
        with tempfile.TemporaryDirectory() as td:
            out_file = Path(td) / 'answers.json'
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                main(['--out', str(out_file)])
            self.assertEqual(cm.exception.code, 2)

    def test_nonexistent_questions_file_exits_with_code_2(self):
        with tempfile.TemporaryDirectory() as td:
            missing_q = Path(td) / 'nonexistent_q.json'
            out_file = Path(td) / 'answers.json'
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                main([str(missing_q), '--out', str(out_file)])
            self.assertEqual(cm.exception.code, 2)

    def test_nonexistent_bank_file_exits_with_code_2(self):
        with tempfile.TemporaryDirectory() as td:
            q_file = Path(td) / 'questions.json'
            q_file.write_text('{"questions": []}', encoding='utf-8')
            missing_bank = Path(td) / 'missing_bank.json'
            out_file = Path(td) / 'answers.json'
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                main([str(q_file), '--bank', str(missing_bank), '--out', str(out_file)])
            self.assertEqual(cm.exception.code, 2)

    def test_invalid_format_exits_with_code_2(self):
        with tempfile.TemporaryDirectory() as td:
            q_file = Path(td) / 'questions.json'
            q_file.write_text('{"questions": []}', encoding='utf-8')
            out_file = Path(td) / 'answers.json'
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                main([str(q_file), '--out', str(out_file), '--format', 'invalid_format'])
            self.assertEqual(cm.exception.code, 2)


class TestResolutionCLIFunctional(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.home_dir = self.dir / 'home'
        self.home_dir.mkdir(parents=True, exist_ok=True)

        self._env_backup = {
            'GROQ_API_KEY': os.environ.get('GROQ_API_KEY'),
            'JOB_APPLIER_HOME': os.environ.get('JOB_APPLIER_HOME'),
            'APPLYTWIN_HOME': os.environ.get('APPLYTWIN_HOME'),
        }
        os.environ.pop('GROQ_API_KEY', None)
        os.environ['JOB_APPLIER_HOME'] = str(self.home_dir)
        os.environ['APPLYTWIN_HOME'] = str(self.home_dir)
        if 'job_applier.store' in sys.modules:
            sys.modules['job_applier.store'].HOME = str(self.home_dir)

        test_profile = {
            'name': 'Ada Lovelace',
            'work_authorized_us': True,
            'email': 'ada@example.com',
        }
        (self.home_dir / 'profile.json').write_text(
            json.dumps(test_profile, ensure_ascii=False),
            encoding='utf-8',
        )

        self.bank_file = self.dir / 'bank.json'
        self.bank_file.write_text(
            json.dumps(make_synthetic_bank(), ensure_ascii=False),
            encoding='utf-8',
        )
        self.questions_file = self.dir / 'questions.json'
        self.questions_file.write_text(
            json.dumps(make_synthetic_questions(), ensure_ascii=False),
            encoding='utf-8',
        )

    def tearDown(self):
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if 'job_applier.store' in sys.modules:
            sys.modules['job_applier.store'].HOME = (
                os.environ.get('JOB_APPLIER_HOME')
                or os.environ.get('APPLYTWIN_HOME')
                or os.path.expanduser(
                    '~/.job-applier'
                    if os.path.exists(os.path.expanduser('~/.job-applier'))
                    or not os.path.exists(os.path.expanduser('~/.applytwin'))
                    else '~/.applytwin'
                )
            )
        self.tmp.cleanup()

    def test_resolve_synthetic_questions_to_file(self):
        out_file = self.dir / 'answers.json'
        argv = [
            str(self.questions_file),
            '--bank', str(self.bank_file),
            '--out', str(out_file),
            '--scope', 'test_application_01',
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = main(argv)
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_file.exists())

        content = json.loads(out_file.read_text(encoding='utf-8'))
        self.assertEqual(content['schema'], SCHEMA_VERSION)
        self.assertEqual(content['snapshot_id'], 'snap-test-xyz-987')
        self.assertEqual(content['scope'], 'test_application_01')

        summary = content['summary']
        self.assertEqual(summary['total'], 4)
        self.assertEqual(summary['ready'], 2)  # q1 (email) and q2 (work authorization)
        self.assertEqual(summary['review'], 0)
        # q3 (constellation) and q4 (nom complet / full name not exact alias)
        self.assertEqual(summary['needs_user'], 2)

        answers = content['answers']
        self.assertEqual(len(answers), 4)

        # q1 ready with exact match
        self.assertEqual(answers[0]['question_id'], 'q1')
        self.assertEqual(answers[0]['status'], 'ready')
        self.assertEqual(answers[0]['fact_key'], 'contact.email')
        self.assertEqual(answers[0]['answer'], 'ada@example.com')

        # q2 ready with option match
        self.assertEqual(answers[1]['question_id'], 'q2')
        self.assertEqual(answers[1]['status'], 'ready')
        self.assertEqual(answers[1]['fact_key'], 'work.authorized_us')
        self.assertEqual(answers[1]['selected_option']['label'], 'Yes')

        # q3 needs_user
        self.assertEqual(answers[2]['question_id'], 'q3')
        self.assertEqual(answers[2]['status'], 'needs_user')
        self.assertIsNone(answers[2]['fact_key'])

        # Pending questions
        pending = content['pending']
        self.assertEqual(len(pending), 2)
        pending_ids = [p['question']['id'] for p in pending]
        self.assertIn('q3', pending_ids)
        self.assertIn('q4', pending_ids)
        for p in pending:
            self.assertEqual(p['scope'], 'test_application_01')
            self.assertIn('pending_id', p)

        # Calls and timing
        self.assertIsInstance(content['calls'], list)
        self.assertIsInstance(content['elapsed_ms'], (int, float))
        self.assertGreaterEqual(content['elapsed_ms'], 0.0)

    def test_resolve_with_output_directory(self):
        out_dir = self.dir / 'sub_artifacts'
        argv = [
            str(self.questions_file),
            '--bank', str(self.bank_file),
            '--out', str(out_dir),
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = main(argv)
        self.assertEqual(exit_code, 0)
        expected_file = out_dir / 'answers.json'
        self.assertTrue(expected_file.exists())
        data = json.loads(expected_file.read_text(encoding='utf-8'))
        self.assertEqual(data['schema'], SCHEMA_VERSION)
        self.assertEqual(data['scope'], 'job_application')  # default scope

    def test_resolve_raw_questions_list(self):
        raw_list_file = self.dir / 'raw_list.json'
        questions_array = make_synthetic_questions()['questions']
        raw_list_file.write_text(
            json.dumps(questions_array, ensure_ascii=False),
            encoding='utf-8',
        )
        out_file = self.dir / 'raw_answers.json'

        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = main([
                str(raw_list_file),
                '--bank', str(self.bank_file),
                '--out', str(out_file),
            ])
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_file.exists())
        data = json.loads(out_file.read_text(encoding='utf-8'))
        self.assertIsNone(data['snapshot_id'])
        self.assertEqual(data['summary']['total'], 4)

    def test_utf8_encoding_preservation(self):
        # Verify Unicode non-ASCII characters in questions and answers survive serialization
        unicode_q_file = self.dir / 'unicode_questions.json'
        unicode_questions = {
            'snapshot_id': 'snap-unicode-üöä',
            'questions': [
                {
                    'id': 'qu1',
                    'text': 'Nom complet',
                    'input_type': 'text',
                    'section': 'Identité',
                    'options': {'items': [], 'complete': False},
                    'warnings': [],
                    'required': True,
                }
            ],
        }
        unicode_q_file.write_text(
            json.dumps(unicode_questions, ensure_ascii=False),
            encoding='utf-8',
        )
        out_file = self.dir / 'unicode_answers.json'

        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = main([
                str(unicode_q_file),
                '--bank', str(self.bank_file),
                '--out', str(out_file),
            ])
        self.assertEqual(exit_code, 0)
        raw_bytes = out_file.read_bytes()
        # Ensure it decodes cleanly as utf-8
        text = raw_bytes.decode('utf-8')
        self.assertIn('Ada Lovelace — 艾达 · 洛夫莱斯', text)
        data = json.loads(text)
        self.assertEqual(data['answers'][0]['answer'], 'Ada Lovelace — 艾达 · 洛夫莱斯')

    def test_summary_format_stdout(self):
        out_file = self.dir / 'summary_answers.json'
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            exit_code = main([
                str(self.questions_file),
                '--bank', str(self.bank_file),
                '--out', str(out_file),
                '--format', 'summary',
                '--scope', 'test_summary_scope',
            ])

        self.assertEqual(exit_code, 0)
        output = captured.getvalue()
        self.assertIn('Scope: test_summary_scope', output)
        self.assertIn('Total: 4', output)
        self.assertIn('Ready: 2', output)
        self.assertIn('Needs User: 2', output)

    def test_default_bank_resolution_without_bank_argument(self):
        out_file = self.dir / 'default_bank_answers.json'
        # Calling without --bank loads from store or answers.default_bank
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = main([
                str(self.questions_file),
                '--out', str(out_file),
            ])
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_file.exists())
        data = json.loads(out_file.read_text(encoding='utf-8'))
        self.assertEqual(data['schema'], SCHEMA_VERSION)
        self.assertEqual(data['summary']['total'], 4)
        q2_answer = next(a for a in data['answers'] if a['question_id'] == 'q2')
        self.assertEqual(q2_answer['status'], 'ready')
        self.assertIsNotNone(q2_answer['selected_option'])
        self.assertEqual(q2_answer['selected_option']['label'], 'Yes')

    def test_questions_null_value(self):
        null_q_file = self.dir / 'null_questions.json'
        null_q_file.write_text(
            '{"questions": null, "snapshot_id": "snap-null"}',
            encoding='utf-8',
        )
        out_file = self.dir / 'null_answers.json'
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = main([
                str(null_q_file),
                '--bank', str(self.bank_file),
                '--out', str(out_file),
            ])
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_file.exists())
        data = json.loads(out_file.read_text(encoding='utf-8'))
        self.assertEqual(data['summary']['total'], 0)
        self.assertEqual(data['answers'], [])
        self.assertEqual(data['pending'], [])
        self.assertEqual(data['snapshot_id'], 'snap-null')

    def test_whitespace_name_profile(self):
        from job_applier.resolution.__main__ import _build_bank_from_profile_and_answers
        bank = _build_bank_from_profile_and_answers({'name': '   '}, [])
        self.assertIsNone(bank['facts']['contact.first_name']['value'])
        self.assertFalse(bank['facts']['contact.first_name']['confirmed'])
        self.assertIsNone(bank['facts']['contact.last_name']['value'])
        self.assertFalse(bank['facts']['contact.last_name']['confirmed'])
        self.assertIsNone(bank['facts']['contact.name']['value'])
        self.assertFalse(bank['facts']['contact.name']['confirmed'])

    def test_default_bank_choice_resolution(self):
        from job_applier.resolution.engine import resolve_cascade
        bank = load_bank()
        choice_q = [{
            'id': 'qc1',
            'text': 'Are you willing to relocate?',
            'input_type': 'single_choice',
            'section': 'Preferences',
            'options': {
                'items': [
                    {'id': 'opt-1', 'label': 'Yes', 'value': 'yes'},
                    {'id': 'opt-2', 'label': 'No', 'value': 'no'},
                ],
                'complete': True,
            },
            'warnings': [],
            'required': True,
        }]
        bank['facts']['personal.relocate']['value'] = True
        bank['facts']['personal.relocate']['confirmed'] = True
        res = resolve_cascade(choice_q, bank, None)
        ans = res['results'][0]
        self.assertEqual(ans['status'], 'ready')
        self.assertEqual(ans['fact_key'], 'personal.relocate')
        self.assertIsNotNone(ans['selected_option'])
        self.assertEqual(ans['selected_option']['label'], 'Yes')

    def test_file_input_abstains_with_correct_artifact_reason(self):
        from job_applier.resolution.engine import resolve_exact
        bank = load_bank()
        file_q = {
            'id': 'q_file',
            'text': 'Upload Resume',
            'input_type': 'file',
            'section': 'Resume',
            'options': {'items': [], 'complete': False},
            'warnings': [],
            'required': True,
        }
        ans = resolve_exact(file_q, bank)
        self.assertEqual(ans['status'], 'needs_user')
        self.assertEqual(
            ans['reason'],
            'file_selection_requires_verified_local_artifact',
        )

    def test_falsy_answers_preserved(self):
        from job_applier.resolution.__main__ import _build_bank_from_profile_and_answers
        profile = {'work_authorized_us': None, 'willing_to_relocate': None}
        raw_answers = [
            {'key': 'relocate', 'answer': False},
            {'key': 'years_experience', 'answer': 0},
            {'key': 'work_auth', 'answer': 'No'},
        ]
        bank = _build_bank_from_profile_and_answers(profile, raw_answers)
        facts = bank['facts']
        self.assertIs(facts['personal.relocate']['value'], False)
        self.assertTrue(facts['personal.relocate']['confirmed'])
        self.assertIs(facts['work.authorized_us']['value'], False)
        self.assertTrue(facts['work.authorized_us']['confirmed'])
        self.assertEqual(facts['years_experience']['value'], 0)
        self.assertTrue(facts['years_experience']['confirmed'])

    def test_unwritable_out_path_exits_code_2(self):
        blocking_file = self.dir / 'blocking_file.txt'
        blocking_file.write_text('occupied', encoding='utf-8')
        unwritable_out = blocking_file / 'sub' / 'answers.json'
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            main([
                str(self.questions_file),
                '--bank', str(self.bank_file),
                '--out', str(unwritable_out),
            ])
        self.assertEqual(cm.exception.code, 2)

    def test_resolution_cli_refuses_symlink_final_intermediate_and_dangling(self):
        real_target = self.dir / 'real_target.json'
        real_target.write_text('{}', encoding='utf-8')

        # 1. Final path is a symlink
        sym_file = self.dir / 'sym_answers.json'
        sym_file.symlink_to(real_target)
        with contextlib.redirect_stderr(io.StringIO()) as stderr_buf, self.assertRaises(SystemExit) as cm:
            main([
                str(self.questions_file),
                '--bank', str(self.bank_file),
                '--out', str(sym_file),
            ])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("symlink", stderr_buf.getvalue().lower())

        # 2. Intermediate directory component is a symlink
        real_dir = self.dir / 'real_dir'
        real_dir.mkdir(parents=True, exist_ok=True)
        sym_dir = self.dir / 'sym_dir'
        sym_dir.symlink_to(real_dir)
        sym_dir_out = sym_dir / 'answers.json'
        with contextlib.redirect_stderr(io.StringIO()) as stderr_buf, self.assertRaises(SystemExit) as cm:
            main([
                str(self.questions_file),
                '--bank', str(self.bank_file),
                '--out', str(sym_dir_out),
            ])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("symlink", stderr_buf.getvalue().lower())

        # 3. Dangling symlink
        dangling_sym = self.dir / 'dangling_answers.json'
        dangling_sym.symlink_to(self.dir / 'nonexistent_target_xyz.json')
        with contextlib.redirect_stderr(io.StringIO()) as stderr_buf, self.assertRaises(SystemExit) as cm:
            main([
                str(self.questions_file),
                '--bank', str(self.bank_file),
                '--out', str(dangling_sym),
            ])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("symlink", stderr_buf.getvalue().lower())


class TestResolutionSubprocessExecution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.home_dir = self.dir / 'home'
        self.home_dir.mkdir(parents=True, exist_ok=True)

        self._env_backup = {
            'GROQ_API_KEY': os.environ.get('GROQ_API_KEY'),
            'JOB_APPLIER_HOME': os.environ.get('JOB_APPLIER_HOME'),
            'APPLYTWIN_HOME': os.environ.get('APPLYTWIN_HOME'),
        }
        os.environ.pop('GROQ_API_KEY', None)
        os.environ['JOB_APPLIER_HOME'] = str(self.home_dir)
        os.environ['APPLYTWIN_HOME'] = str(self.home_dir)

        test_profile = {
            'name': 'Ada Lovelace',
            'work_authorized_us': True,
            'email': 'ada@example.com',
        }
        (self.home_dir / 'profile.json').write_text(
            json.dumps(test_profile, ensure_ascii=False),
            encoding='utf-8',
        )

        self.bank_file = self.dir / 'bank.json'
        self.bank_file.write_text(
            json.dumps(make_synthetic_bank(), ensure_ascii=False),
            encoding='utf-8',
        )
        self.questions_file = self.dir / 'questions.json'
        self.questions_file.write_text(
            json.dumps(make_synthetic_questions(), ensure_ascii=False),
            encoding='utf-8',
        )
        self.bin_job_applier = ROOT / 'bin' / 'job-applier'

        self.subproc_env = dict(os.environ)
        self.subproc_env.pop('GROQ_API_KEY', None)
        self.subproc_env['JOB_APPLIER_HOME'] = str(self.home_dir)
        self.subproc_env['APPLYTWIN_HOME'] = str(self.home_dir)

    def tearDown(self):
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_subprocess_bin_job_applier_resolve(self):
        out_file = self.dir / 'subproc_answers.json'
        cmd = [
            sys.executable,
            str(self.bin_job_applier),
            'resolve',
            str(self.questions_file),
            '--bank', str(self.bank_file),
            '--out', str(out_file),
            '--scope', 'subproc_scope',
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            env=self.subproc_env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        self.assertTrue(out_file.exists())
        data = json.loads(out_file.read_text(encoding='utf-8'))
        self.assertEqual(data['schema'], SCHEMA_VERSION)
        self.assertEqual(data['scope'], 'subproc_scope')
        self.assertEqual(data['summary']['total'], 4)
        self.assertEqual(data['summary']['ready'], 2)

    def test_subprocess_bin_job_applier_resolve_help(self):
        cmd = [
            sys.executable,
            str(self.bin_job_applier),
            'resolve',
            '--help',
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            env=self.subproc_env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn('Phase 2', proc.stdout)
        self.assertIn('questions', proc.stdout)
        self.assertIn('--out', proc.stdout)

    def test_subprocess_bin_job_applier_main_help_contains_resolve(self):
        cmd = [
            sys.executable,
            str(self.bin_job_applier),
            '--help',
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            env=self.subproc_env,
            timeout=30,
        )
        self.assertIn('job-applier resolve QUESTIONS.json --out ANSWERS.json', proc.stdout)


if __name__ == '__main__':
    unittest.main()
