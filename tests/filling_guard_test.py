"""Integration tests for Phase 3 form filling engine and observation/submit-blocker guard."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright
from job_applier.extraction.engine import collect
from job_applier.filling.engine import fill_form, install_observation_guard, SCHEMA_VERSION


class FillingGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(chromium_sandbox=True)
        cls.fixture_path = ROOT / 'tests/fixtures/greenhouse.html'

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='filling-test-')
        self.context = self.browser.new_context(
            viewport={'width': 1360, 'height': 1000},
            service_workers='block',
        )
        self.blocked = install_observation_guard(self.context)
        self.page = self.context.new_page()
        self.page.goto(self.fixture_path.as_uri())

    def tearDown(self):
        self.context.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_fill_greenhouse_form_and_verify_values(self):
        resume_file = Path(self.temp_dir) / 'test_resume.pdf'
        resume_file.write_bytes(b'%PDF-1.4 synthetic dummy resume content')
        nonexistent_file = Path(self.temp_dir) / 'nonexistent_portfolio.pdf'
        screenshot_file = Path(self.temp_dir) / 'screenshot.png'

        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-greenhouse-test',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_first_name',
                    'text': 'First Name *',
                    'input_type': 'text',
                    'answer': 'Ada',
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'first_name'}],
                },
                {
                    'question_id': 'q_last_name',
                    'text': 'Last Name *',
                    'input_type': 'text',
                    'answer': 'Lovelace',
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'last_name'}],
                },
                {
                    'question_id': 'q_email',
                    'text': 'Email *',
                    'input_type': 'email',
                    'answer': 'ada@example.com',
                    'status': 'ready',
                },
                {
                    'question_id': 'q_phone',
                    'text': 'Phone',
                    'input_type': 'tel',
                    'answer': '+15551234567',
                    'status': 'ready',
                },
                {
                    'question_id': 'q_linkedin',
                    'text': 'LinkedIn URL',
                    'input_type': 'url',
                    'answer': 'https://linkedin.com/in/ada-lovelace',
                    'status': 'ready',
                },
                {
                    'question_id': 'q_resume',
                    'text': 'Resume/CV *',
                    'input_type': 'file',
                    'answer': str(resume_file),
                    'status': 'ready',
                },
                {
                    'question_id': 'q_degree',
                    'text': 'Highest Degree Completed',
                    'input_type': 'combobox',
                    'answer': "Bachelor's Degree",
                    'selected_option': {
                        'label': "Bachelor's Degree",
                        'value': 'bachelors',
                    },
                    'status': 'ready',
                },
                {
                    'question_id': 'q_work_auth',
                    'text': 'Are you legally authorized to work in the United States?',
                    'input_type': 'single_choice',
                    'answer': True,
                    'selected_option': {'label': 'Yes', 'value': 'true'},
                    'status': 'ready',
                },
                {
                    'question_id': 'q_sponsorship',
                    'text': 'Will you now or in the future require sponsorship?',
                    'input_type': 'single_choice',
                    'answer': False,
                    'selected_option': {'label': 'No', 'value': 'false'},
                    'status': 'ready',
                },
                {
                    'question_id': 'q_cover_letter',
                    'text': 'Cover Letter',
                    'input_type': 'textarea',
                    'answer': 'Excited about the role.',
                    'status': 'ready',
                },
                {
                    'question_id': 'q_terms',
                    'text': 'I acknowledge and agree to the privacy policy',
                    'input_type': 'checkbox',
                    'answer': True,
                    'status': 'ready',
                },
                {
                    'question_id': 'q_missing_file',
                    'text': 'Portfolio Attachment',
                    'input_type': 'file',
                    'answer': str(nonexistent_file),
                    'status': 'ready',
                },
                {
                    'question_id': 'q_needs_user',
                    'text': 'Custom unknown question',
                    'input_type': 'text',
                    'answer': None,
                    'status': 'needs_user',
                },
            ],
        }

        report = fill_form(self.page, answers_plan, options={
            'screenshot': True,
            'screenshot_path': str(screenshot_file),
        })

        # Schema and summary verification
        self.assertEqual(report['schema'], SCHEMA_VERSION)
        self.assertEqual(report['snapshot_id'], 'snap-greenhouse-test')
        self.assertEqual(report['summary']['total_answers'], 13)
        self.assertEqual(report['summary']['filled'], 10)
        self.assertEqual(report['summary']['skipped'], 3)  # missing file + needs_user + privacy policy agreement
        self.assertEqual(report['summary']['failed'], 0)

        # Field verified values on report
        fields_by_id = {f['question_id']: f for f in report['fields']}
        self.assertEqual(fields_by_id['q_first_name']['verified_value'], 'Ada')
        self.assertEqual(fields_by_id['q_last_name']['verified_value'], 'Lovelace')
        self.assertEqual(fields_by_id['q_email']['verified_value'], 'ada@example.com')
        self.assertEqual(fields_by_id['q_phone']['verified_value'], '+15551234567')
        self.assertEqual(
            fields_by_id['q_linkedin']['verified_value'],
            'https://linkedin.com/in/ada-lovelace',
        )
        self.assertEqual(fields_by_id['q_degree']['verified_value'], "Bachelor's Degree")
        self.assertEqual(fields_by_id['q_work_auth']['verified_value'], 'Yes')
        self.assertIn('No', str(fields_by_id['q_sponsorship']['verified_value']))
        self.assertEqual(
            fields_by_id['q_cover_letter']['verified_value'],
            'Excited about the role.',
        )
        self.assertEqual(fields_by_id['q_terms']['status'], 'skipped')
        self.assertIsNone(fields_by_id['q_terms']['verified_value'])
        self.assertEqual(fields_by_id['q_resume']['verified_value'], 'test_resume.pdf')
        self.assertEqual(fields_by_id['q_missing_file']['status'], 'skipped')
        self.assertEqual(fields_by_id['q_needs_user']['status'], 'skipped')

        # Observable DOM values check
        self.assertEqual(self.page.locator('#first_name').input_value(), 'Ada')
        self.assertEqual(self.page.locator('#last_name').input_value(), 'Lovelace')
        self.assertEqual(self.page.locator('#email').input_value(), 'ada@example.com')
        self.assertEqual(self.page.locator('#phone').input_value(), '+15551234567')
        self.assertEqual(
            self.page.locator('#job_application_answers_attributes_0_text_value').input_value(),
            'https://linkedin.com/in/ada-lovelace',
        )
        self.assertEqual(
            self.page.locator('#cover_letter').input_value(),
            'Excited about the role.',
        )
        self.assertFalse(self.page.locator('#terms_agree').is_checked())
        self.assertEqual(
            self.page.locator('.select__single-value').inner_text().strip(),
            "Bachelor's Degree",
        )
        self.assertTrue(
            self.page.locator("#work-auth-field input[value='true']").is_checked()
        )
        self.assertFalse(
            self.page.locator("#work-auth-field input[value='false']").is_checked()
        )
        self.assertEqual(self.page.locator('#sponsorship_select').input_value(), 'false')
        self.assertEqual(self.page.locator('#resume').evaluate("el => el.files.length"), 1)

        # Screenshot verification
        self.assertTrue(screenshot_file.is_file())
        self.assertGreater(screenshot_file.stat().st_size, 0)
        self.assertEqual(report['screenshot_path'], str(screenshot_file.resolve()))
        self.assertEqual(screenshot_file.stat().st_mode & 0o777, 0o600)

    def test_combobox_mismatch_fails_cleanly_without_selecting_first_option(self):
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-combobox-mismatch',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_degree_mismatch',
                    'text': 'Highest Degree Completed',
                    'input_type': 'combobox',
                    'answer': 'Nonexistent Degree XYZ',
                    'selected_option': {
                        'label': 'Nonexistent Degree XYZ',
                        'value': 'nonexistent_degree_xyz',
                    },
                    'status': 'ready',
                },
            ],
        }

        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)

        field = report['fields'][0]
        self.assertEqual(field['status'], 'failed')
        self.assertIn("No matching option found for combobox", field.get('error', ''))

        # Verify in live DOM that the first option ("High School") was NEVER selected
        single_val = self.page.locator('.select__single-value')
        if single_val.count() > 0 and single_val.is_visible():
            self.assertNotEqual(single_val.inner_text().strip(), 'High School')

    def test_sibling_label_for_radio_resolution(self):
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-sibling-radio',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_relocation',
                    'text': 'Are you willing to relocate? *',
                    'input_type': 'radio',
                    'answer': True,
                    'selected_option': {'label': 'Yes', 'value': 'true'},
                    'status': 'ready',
                },
            ],
        }

        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 0)
        self.assertEqual(report['summary']['filled'], 1)

        field = report['fields'][0]
        self.assertEqual(field['status'], 'filled')
        self.assertEqual(field['verified_value'], 'Yes')

        # Verify live DOM state
        yes_radio = self.page.locator('#relocate_yes')
        no_radio = self.page.locator('#relocate_no')
        self.assertTrue(yes_radio.is_checked())
        self.assertFalse(no_radio.is_checked())

    def test_fill_contenteditable_control(self):
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-contenteditable',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_rich_notes',
                    'text': 'Additional Notes',
                    'input_type': 'textarea',
                    'answer': 'I am proficient in Python and distributed systems.',
                    'status': 'ready',
                },
            ],
        }

        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 0)
        self.assertEqual(report['summary']['filled'], 1)

        field = report['fields'][0]
        self.assertEqual(field['status'], 'filled')
        self.assertEqual(
            field['verified_value'],
            'I am proficient in Python and distributed systems.',
        )
        self.assertEqual(
            self.page.locator('#rich_notes').inner_text().strip(),
            'I am proficient in Python and distributed systems.',
        )

    def test_submit_button_strictly_blocked_by_guard(self):
        # Click the submit button
        submit_btn = self.page.locator('#submit_app')
        submit_btn.click()

        # Check guard recorded blocked submit
        self.assertTrue(self.page.evaluate('window.__job_applier_submit_blocked'))
        self.assertGreaterEqual(self.page.evaluate('window.__job_applier_blocked_submits'), 1)

        # Check form.submit() and form.requestSubmit() throws
        throws_on_submit = self.page.evaluate("""() => {
            try {
                document.getElementById('application-form').submit();
                return false;
            } catch (e) {
                return true;
            }
        }""")
        self.assertTrue(throws_on_submit)

        throws_on_request_submit = self.page.evaluate("""() => {
            try {
                document.getElementById('application-form').requestSubmit();
                return false;
            } catch (e) {
                return true;
            }
        }""")
        self.assertTrue(throws_on_request_submit)

        # Check network request guard blocks POST / PUT / DELETE
        self.page.evaluate(
            "fetch('https://example.invalid/submit', { method: 'POST', body: 'guard-test' })"
            ".catch(() => {})"
        )
        self.page.wait_for_timeout(150)
        self.assertTrue(any(r['method'] == 'POST' for r in self.blocked))

    def test_cli_fill_integration(self):
        answers_file = Path(self.temp_dir) / 'answers.json'
        cli_out_dir = Path(self.temp_dir) / 'cli_out'

        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-cli-test',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_first_name',
                    'text': 'First Name *',
                    'input_type': 'text',
                    'answer': 'Grace',
                    'status': 'ready',
                },
                {
                    'question_id': 'q_email',
                    'text': 'Email *',
                    'input_type': 'email',
                    'answer': 'grace@example.com',
                    'status': 'ready',
                },
            ],
        }
        with open(answers_file, 'w', encoding='utf-8') as f:
            json.dump(answers_plan, f, indent=2)

        proc = subprocess.run([
            sys.executable,
            '-m', 'job_applier.filling',
            self.fixture_path.as_uri(),
            '--answers', str(answers_file),
            '--out', str(cli_out_dir),
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=30)
        self.assertEqual(proc.returncode, 0, f"CLI stderr: {proc.stderr}")

        report_json_path = cli_out_dir / 'fill_report.json'
        screenshot_png_path = cli_out_dir / 'screenshot.png'

        self.assertTrue(report_json_path.is_file())
        self.assertTrue(screenshot_png_path.is_file())

        with open(report_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['schema'], SCHEMA_VERSION)
        self.assertEqual(data['summary']['filled'], 2)
        self.assertEqual(data['summary']['failed'], 0)

    def test_cli_fill_error_handling(self):
        answers_file = Path(self.temp_dir) / 'answers_err.json'
        cli_out_dir = Path(self.temp_dir) / 'cli_err_out'

        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-cli-err-test',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_first_name',
                    'text': 'First Name *',
                    'input_type': 'text',
                    'answer': 'Grace',
                    'status': 'ready',
                },
            ],
        }
        with open(answers_file, 'w', encoding='utf-8') as f:
            json.dump(answers_plan, f, indent=2)

        invalid_url = 'file:///nonexistent/directory/fake_page.html'
        proc = subprocess.run([
            sys.executable,
            '-m', 'job_applier.filling',
            invalid_url,
            '--answers', str(answers_file),
            '--out', str(cli_out_dir),
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=30)
        self.assertEqual(proc.returncode, 1)

        report_json_path = cli_out_dir / 'fill_report.json'
        self.assertTrue(report_json_path.is_file())

        with open(report_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['schema'], SCHEMA_VERSION)
        self.assertEqual(data['summary']['failed'], 1)
        self.assertEqual(data['summary']['filled'], 0)
        self.assertIn('error', data)

        stdout_data = json.loads(proc.stdout)
        self.assertEqual(stdout_data['status'], 'error')
        self.assertEqual(stdout_data['failed'], 1)

    def test_combobox_shared_prefix_fails_without_mutating(self):
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-combobox-shared-prefix',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_degree_prefix',
                    'text': 'Highest Degree Completed',
                    'input_type': 'combobox',
                    'answer': 'Bachelor',
                    'selected_option': {
                        'label': 'Bachelor',
                        'value': 'bachelor',
                    },
                    'status': 'ready',
                },
            ],
        }
        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        field = report['fields'][0]
        self.assertEqual(field['status'], 'failed')
        self.assertIn("No matching option found for combobox", field.get('error', ''))

        # Live DOM remains unmutated
        single_val = self.page.locator('.select__single-value')
        if single_val.count() > 0 and single_val.is_visible():
            self.assertNotEqual(single_val.inner_text().strip(), "Bachelor's Degree")

    def test_duplicate_labels_abstain_without_first_match_mutation(self):
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-dup-label',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_dup',
                    'text': 'Duplicate Question Label *',
                    'input_type': 'text',
                    'answer': 'Ambiguous Val',
                    'status': 'ready',
                },
            ],
        }
        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        err = report['fields'][0].get('error', '')
        self.assertTrue('Ambiguous' in err or 'Duplicate' in err)

        # Neither duplicate input was mutated
        self.assertEqual(self.page.locator('#dup_field_1').input_value(), '')
        self.assertEqual(self.page.locator('#dup_field_2').input_value(), '')

    def test_rejected_reverted_write_reported_failed(self):
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-reverting',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_reverting',
                    'text': 'Reverting Field',
                    'input_type': 'text',
                    'answer': 'Typed Text',
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'reverting_field'}],
                },
            ],
        }
        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("reverted write", report['fields'][0].get('error', '').lower())

    def test_mixed_ready_and_review_plan(self):
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-mixed-plan',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_ready_name',
                    'text': 'First Name *',
                    'input_type': 'text',
                    'answer': 'Katherine',
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'first_name'}],
                },
                {
                    'question_id': 'q_review_name',
                    'text': 'Last Name *',
                    'input_type': 'text',
                    'answer': 'Johnson',
                    'status': 'review',
                    'locator_candidates': [{'by': 'id', 'value': 'last_name'}],
                },
            ],
        }
        # Run without allow_review -> review question skipped
        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['filled'], 1)
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['failed'], 0)
        fields_by_id = {f['question_id']: f for f in report['fields']}
        self.assertEqual(fields_by_id['q_ready_name']['status'], 'filled')
        self.assertEqual(fields_by_id['q_review_name']['status'], 'skipped')
        self.assertEqual(
            fields_by_id['q_review_name']['skip_reason'],
            'review_requires_explicit_approval',
        )
        self.assertEqual(self.page.locator('#first_name').input_value(), 'Katherine')
        self.assertEqual(self.page.locator('#last_name').input_value(), '')

    def test_prohibited_controls_skipped_without_mutation(self):
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-prohibited',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_pwd',
                    'text': 'Create Account Password',
                    'input_type': 'password',
                    'answer': 'supersecret',
                    'status': 'ready',
                },
                {
                    'question_id': 'q_arb',
                    'text': 'Do you agree to the binding arbitration agreement? *',
                    'input_type': 'single_choice',
                    'answer': True,
                    'status': 'ready',
                },
            ],
        }
        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['filled'], 0)
        self.assertEqual(report['summary']['skipped'], 2)
        self.assertEqual(report['summary']['failed'], 0)
        self.assertEqual(self.page.locator('#user_password').input_value(), '')
        self.assertFalse(self.page.locator('#arb_yes').is_checked())

    def test_unsupported_frame_abstains_without_filling_other_frame(self):
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-frame',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_frame_missing',
                    'frame_id': 'frame-42',
                    'text': 'First Name *',
                    'input_type': 'text',
                    'answer': 'Should Not Fill',
                    'status': 'ready',
                },
            ],
        }
        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertIn("frame-42", report['fields'][0].get('error', ''))
        self.assertEqual(self.page.locator('#first_name').input_value(), '')

    def test_guard_telemetry_in_report_without_fixture_globals(self):
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-telem',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_first_name',
                    'text': 'First Name *',
                    'input_type': 'text',
                    'answer': 'Dorothy',
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'first_name'}],
                },
            ],
        }
        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertIn('telemetry', report)
        telem = report['telemetry']
        self.assertTrue(telem['guard_active'])
        self.assertIsInstance(telem['blocked_network_requests'], list)
        self.assertIsInstance(telem['blocked_form_submits'], int)
        self.assertIn('limitation', telem.get('remote_side_effect_limitation', '').lower())

    def test_screenshot_restrictive_permissions_and_no_silent_overwrite(self):
        sc_file = Path(self.temp_dir) / 'private_sc.png'
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-sc',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_first_name',
                    'text': 'First Name *',
                    'input_type': 'text',
                    'answer': 'Mary',
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'first_name'}],
                },
            ],
        }
        fill_form(self.page, answers_plan, options={
            'screenshot': True,
            'screenshot_path': str(sc_file),
            'overwrite': False,
        })
        self.assertTrue(sc_file.is_file())
        mode = sc_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

        # Refuse silent overwrite when overwrite=False
        with self.assertRaises(FileExistsError):
            fill_form(self.page, answers_plan, options={
                'screenshot': True,
                'screenshot_path': str(sc_file),
                'overwrite': False,
            })

    def test_duplicate_native_select_options_and_conflicting_label_val_rejected(self):
        # Inject select with duplicate options into page
        self.page.evaluate("""() => {
            const sel = document.createElement('select');
            sel.id = 'dup_select';
            sel.innerHTML = '<option value="v1">Duplicate</option><option value="v2">Duplicate</option>';
            document.body.appendChild(sel);
        }""")
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-dup-select',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_dup_sel',
                    'text': 'Duplicate Select Question',
                    'input_type': 'select',
                    'answer': 'Duplicate',
                    'selected_option': {'label': 'Duplicate'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'dup_select'}],
                },
                {
                    'question_id': 'q_conflict_sel',
                    'text': 'Conflicting Select Question',
                    'input_type': 'select',
                    'answer': 'Yes',
                    'selected_option': {'label': 'Yes', 'value': 'false'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'sponsorship_select'}],
                },
            ],
        }
        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 2)
        self.assertEqual(report['summary']['filled'], 0)

        err_dup = report['fields'][0].get('error', '')
        self.assertIn('Duplicate enabled option label', err_dup)
        err_conflict = report['fields'][1].get('error', '')
        self.assertIn('Conflicting label', err_conflict)

        # Ensure DOM was not mutated
        self.assertEqual(self.page.locator('#sponsorship_select').input_value(), '')

    def test_radio_missing_prefer_not_to_answer_never_clicks_no(self):
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-prefer-not-answer',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_relocation_decline',
                    'text': 'Are you willing to relocate? *',
                    'input_type': 'radio',
                    'answer': 'Prefer not to answer',
                    'selected_option': {'label': 'Prefer not to answer', 'value': 'decline'},
                    'status': 'ready',
                },
            ],
        }
        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)

        # Crucial check: neither Yes nor No was clicked
        self.assertFalse(self.page.locator('#relocate_yes').is_checked())
        self.assertFalse(self.page.locator('#relocate_no').is_checked())

    def test_combobox_unrelated_menu_and_no_op_click_not_filled(self):
        # Inject an unrelated menu outside the degree container
        self.page.evaluate("""() => {
            const menu = document.createElement('div');
            menu.id = 'unrelated-menu';
            menu.className = 'select__menu';
            menu.style.display = 'block';
            menu.innerHTML = '<div class="select__option" role="option">Unrelated Degree</div>';
            document.body.appendChild(menu);
        }""")
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-combobox-unrelated',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_deg_unrelated',
                    'text': 'Highest Degree Completed',
                    'input_type': 'combobox',
                    'answer': 'Unrelated Degree',
                    'selected_option': {'label': 'Unrelated Degree'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'degree-select-input'}],
                },
            ],
        }
        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)

        # Unrelated menu is unchanged and degree single-value is empty
        single_val = self.page.locator('#degree-container .select__single-value')
        if single_val.count() > 0 and single_val.is_visible():
            self.assertNotEqual(single_val.inner_text().strip(), 'Unrelated Degree')

    def test_disguised_password_and_ordinary_agreement_unchanged(self):
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-disguised',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_disguised_pwd',
                    'text': 'Account Passcode Verification',
                    'input_type': 'text',
                    'answer': 'SecretPass123!',
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'user_password'}],
                },
                {
                    'question_id': 'q_ordinary_agreement',
                    'text': 'I acknowledge and agree to the privacy policy',
                    'input_type': 'checkbox',
                    'answer': True,
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'terms_agree'}],
                },
            ],
        }
        report = fill_form(self.page, answers_plan, options={'screenshot': False, 'allow_review': False})
        self.assertEqual(report['summary']['filled'], 0)
        self.assertEqual(report['summary']['skipped'], 2)
        self.assertEqual(report['summary']['failed'], 0)

        # Live DOM remains untouched
        self.assertEqual(self.page.locator('#user_password').input_value(), '')
        self.assertFalse(self.page.locator('#terms_agree').is_checked())

    def test_shorter_overwrite_exact_bytes_and_symlink_refusal(self):
        from job_applier.filling.engine import write_bytes_atomic, write_json_atomic

        test_file = Path(self.temp_dir) / 'test_overwrite.json'
        # Create initial file with 0644 permissions and long content
        initial_data = b'{"long_initial_content_key": "' + (b'x' * 300) + b'"}'
        test_file.write_bytes(initial_data)
        os.chmod(test_file, 0o644)
        self.assertEqual(test_file.stat().st_size, len(initial_data))
        self.assertEqual(test_file.stat().st_mode & 0o777, 0o644)

        # Overwrite with short content
        short_data = {'short': 1}
        write_json_atomic(test_file, short_data, overwrite=True)

        # Read back bytes: must be exactly the JSON bytes, NO stale suffix bytes!
        with open(test_file, 'r', encoding='utf-8') as f:
            read_back = json.load(f)
        self.assertEqual(read_back, short_data)
        self.assertLess(test_file.stat().st_size, 30)
        # Permissions must now be 0600
        self.assertEqual(test_file.stat().st_mode & 0o777, 0o600)

        # Symlink refusal test
        real_target = Path(self.temp_dir) / 'real_target.txt'
        real_target.write_text('original-secret', encoding='utf-8')
        symlink_file = Path(self.temp_dir) / 'symlink_target.txt'
        os.symlink(str(real_target), str(symlink_file))

        with self.assertRaises(ValueError) as cm:
            write_bytes_atomic(symlink_file, b'overwritten', overwrite=True)
        self.assertIn('symlink', str(cm.exception).lower())
        self.assertEqual(real_target.read_text(encoding='utf-8'), 'original-secret')

    def test_fill_cli_refuses_symlink_final_intermediate_and_dangling(self):
        answers_file = Path(self.temp_dir) / 'answers_sym_test.json'
        answers_file.write_text(json.dumps({
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-sym',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_fn',
                    'text': 'First Name *',
                    'input_type': 'text',
                    'answer': 'Grace',
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'first_name'}],
                }
            ],
        }), encoding='utf-8')

        real_dest = Path(self.temp_dir) / 'real_dest'
        real_dest.mkdir(parents=True, exist_ok=True)
        real_report = real_dest / 'fill_report.json'
        real_report.write_text('{}', encoding='utf-8')

        # 1. Output directory is a symlink pointing to real_dest
        sym_dir = Path(self.temp_dir) / 'sym_out_dir'
        sym_dir.symlink_to(real_dest)
        proc_sym_dir = subprocess.run([
            sys.executable,
            '-m', 'job_applier.filling',
            self.fixture_path.as_uri(),
            '--answers', str(answers_file),
            '--out', str(sym_dir),
            '--overwrite',
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=30)
        self.assertEqual(proc_sym_dir.returncode, 1)
        parsed_dir = json.loads(proc_sym_dir.stdout)
        self.assertEqual(parsed_dir['status'], 'error')
        self.assertIn('symlink', parsed_dir.get('error', '').lower())

        # 2. Intermediate directory component is a symlink
        sym_child_dir = sym_dir / 'child'
        proc_child = subprocess.run([
            sys.executable,
            '-m', 'job_applier.filling',
            self.fixture_path.as_uri(),
            '--answers', str(answers_file),
            '--out', str(sym_child_dir),
            '--overwrite',
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=30)
        self.assertEqual(proc_child.returncode, 1)
        parsed_child = json.loads(proc_child.stdout)
        self.assertEqual(parsed_child['status'], 'error')
        self.assertIn('symlink', parsed_child.get('error', '').lower())

    def test_malformed_cli_plan_and_write_failure_structured(self):
        malformed_file = Path(self.temp_dir) / 'malformed.json'
        malformed_file.write_text('[]', encoding='utf-8')  # list instead of dict
        cli_out = Path(self.temp_dir) / 'cli_malformed_out'

        proc = subprocess.run([
            sys.executable,
            '-m', 'job_applier.filling',
            self.fixture_path.as_uri(),
            '--answers', str(malformed_file),
            '--out', str(cli_out),
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=30)

        self.assertEqual(proc.returncode, 1)
        # Stdout must be parseable JSON
        parsed = json.loads(proc.stdout)
        self.assertEqual(parsed['status'], 'error')
        self.assertIn('Malformed answers plan', parsed.get('error', ''))

    def test_existing_unguarded_iframe_get_submit_on_change(self):
        # Explicit public fill_form test on PREEXISTING UNGUARDED iframe GET submit-on-change, not preinstalling context guard
        unguarded_context = self.browser.new_context(
            viewport={'width': 1360, 'height': 1000},
            service_workers='block',
        )
        try:
            unguarded_page = unguarded_context.new_page()
            unguarded_page.set_content("""
                <!DOCTYPE html>
                <html>
                <head><title>Parent</title></head>
                <body>
                    <h1>Main Form</h1>
                    <iframe id="sub-frame" name="sub_frame" srcdoc='
                        <!DOCTYPE html>
                        <html>
                        <body>
                            <form id="get-change-form" method="GET" action="/search">
                                <label for="choice_select">Category</label>
                                <select id="choice_select" name="cat" onchange="this.form.submit()">
                                    <option value="books">Books</option>
                                    <option value="music">Music</option>
                                </select>
                            </form>
                        </body>
                        </html>
                    '></iframe>
                </body>
                </html>
            """)
            unguarded_page.wait_for_selector('#sub-frame')
            ifr = next(f for f in unguarded_page.frames if f != unguarded_page.main_frame)
            ifr.wait_for_selector('#choice_select')

            plan = {
                'schema': 'job-applier.answer-plan.v1',
                'snapshot_id': 'snap-unguarded-iframe',
                'scope': 'job_application',
                'answers': [
                    {
                        'question_id': 'q_sub',
                        'text': 'Category',
                        'input_type': 'select',
                        'answer': 'Music',
                        'selected_option': {'label': 'Music', 'value': 'music'},
                        'status': 'ready',
                        'frame_id': 'sub_frame',
                        'frame_descriptor': {'name': 'sub_frame'},
                        'locator_candidates': [{'by': 'id', 'value': 'choice_select'}],
                    }
                ],
            }

            report = fill_form(unguarded_page, plan, options={'screenshot': False})
            self.assertEqual(report['summary']['filled'], 1)
            self.assertEqual(report['summary']['failed'], 0)
            self.assertEqual(report['fields'][0]['verified_value'], 'Music')

            # Telemetry proves form submit attempt from iframe was intercepted and blocked
            blocked_in_ifr = ifr.evaluate("() => window.__job_applier_guard && window.__job_applier_guard.blocked_submits")
            self.assertGreaterEqual(blocked_in_ifr, 1)
            self.assertGreaterEqual(report['telemetry']['blocked_form_submits'], 1)
        finally:
            unguarded_context.close()

    def test_navigation_time_blocked_ledger_retained(self):
        # Perform a blocked request on context before fill_form
        self.page.evaluate("fetch('https://example.invalid/nav-block', { method: 'POST', body: 'nav-test' }).catch(() => {})")
        self.page.wait_for_timeout(100)

        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-nav-ledger',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_fn',
                    'text': 'First Name *',
                    'input_type': 'text',
                    'answer': 'Ada',
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'first_name'}],
                },
            ],
        }
        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        blocked_reqs = report['telemetry']['blocked_network_requests']
        self.assertTrue(any(r['url'] == 'https://example.invalid/nav-block' for r in blocked_reqs))

    def test_stale_or_reordered_frame_identity_no_mutation(self):
        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-stale-frame',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_stale_frame',
                    'text': 'First Name *',
                    'input_type': 'text',
                    'answer': 'Should Not Fill Stale',
                    'status': 'ready',
                    'frame_id': 'frame-nonexistent',
                    'frame_descriptor': {
                        'id': 'frame-nonexistent',
                        'url': 'https://example.invalid/stale-page.html',
                        'name': 'stale_frame',
                    },
                    'locator_candidates': [{'by': 'id', 'value': 'first_name'}],
                },
            ],
        }
        report = fill_form(self.page, answers_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertIn('Unsupported/stale frame identity', report['fields'][0].get('error', ''))
        # Live DOM remains untouched
        self.assertEqual(self.page.locator('#first_name').input_value(), '')

    def test_radio_stale_form_removed_fails_without_mutating_form_b(self):
        # Set up two forms with identical radio legends in DOM
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'dual-forms-container';
            container.innerHTML = `
                <form id="form-a" class="app-form">
                    <fieldset class="field">
                        <legend>Will you require sponsorship?</legend>
                        <label><input type="radio" name="sponsor" value="true"> Yes</label>
                        <label><input type="radio" name="sponsor" value="false"> No</label>
                    </fieldset>
                </form>
                <form id="form-b" class="app-form">
                    <fieldset class="field">
                        <legend>Will you require sponsorship?</legend>
                        <label><input type="radio" name="sponsor" value="true"> Yes</label>
                        <label><input type="radio" name="sponsor" value="false"> No</label>
                    </fieldset>
                </form>
            `;
            document.body.appendChild(container);
        }""")

        # Plan targets Form A
        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-radio-stale',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_sponsor_a',
                    'text': 'Will you require sponsorship?',
                    'input_type': 'radio',
                    'answer': True,
                    'selected_option': {'label': 'Yes', 'value': 'true'},
                    'status': 'ready',
                    'form_id': 'form-a',
                    'locator_scope': {'form_id': 'form-a', 'form': '#form-a'},
                }
            ],
        }

        # Remove Form A from the DOM, leaving Form B with same legend
        self.page.evaluate("() => document.getElementById('form-a').remove()")

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("Stale form scope", report['fields'][0].get('error', ''))

        # Form B radio buttons must remain completely unchecked!
        b_radios = self.page.locator('#form-b input[type="radio"]:checked')
        self.assertEqual(b_radios.count(), 0)

    def test_two_forms_with_same_legend_isolated_by_form_scope(self):
        self.page.evaluate("""() => {
            const el = document.getElementById('dual-forms-container');
            if (el) el.remove();
            const container = document.createElement('div');
            container.id = 'dual-forms-container';
            container.innerHTML = `
                <form id="form-alpha">
                    <fieldset class="field">
                        <legend>Will you require sponsorship?</legend>
                        <label><input type="radio" name="sponsor_a" value="true"> Yes</label>
                        <label><input type="radio" name="sponsor_a" value="false"> No</label>
                    </fieldset>
                </form>
                <form id="form-beta">
                    <fieldset class="field">
                        <legend>Will you require sponsorship?</legend>
                        <label><input type="radio" name="sponsor_b" value="true"> Yes</label>
                        <label><input type="radio" name="sponsor_b" value="false"> No</label>
                    </fieldset>
                </form>
            `;
            document.body.appendChild(container);
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-radio-dual',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_alpha',
                    'text': 'Will you require sponsorship?',
                    'input_type': 'radio',
                    'answer': True,
                    'selected_option': {'label': 'Yes', 'value': 'true'},
                    'status': 'ready',
                    'form_id': 'form-alpha',
                    'locator_scope': {'form_id': 'form-alpha', 'form': '#form-alpha'},
                },
                {
                    'question_id': 'q_beta',
                    'text': 'Will you require sponsorship?',
                    'input_type': 'radio',
                    'answer': False,
                    'selected_option': {'label': 'No', 'value': 'false'},
                    'status': 'ready',
                    'form_id': 'form-beta',
                    'locator_scope': {'form_id': 'form-beta', 'form': '#form-beta'},
                },
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['filled'], 2)
        self.assertEqual(report['summary']['failed'], 0)

        # Assert Form Alpha has Yes checked, Form Beta has No checked
        alpha_checked = self.page.locator('#form-alpha input[type="radio"]:checked')
        beta_checked = self.page.locator('#form-beta input[type="radio"]:checked')
        self.assertEqual(alpha_checked.get_attribute('value'), 'true')
        self.assertEqual(beta_checked.get_attribute('value'), 'false')

    def test_frame_resolver_child_never_main_and_identical_children_abstain(self):
        # Set up page with 2 identical child frames
        self.page.evaluate("""() => {
            const ifr1 = document.createElement('iframe');
            ifr1.name = 'child_frame';
            ifr1.src = 'about:blank';
            const ifr2 = document.createElement('iframe');
            ifr2.name = 'child_frame';
            ifr2.src = 'about:blank';
            document.body.appendChild(ifr1);
            document.body.appendChild(ifr2);
        }""")

        # 1. Explicit child targeting matching multiple identical frames must abstain
        plan_ambiguous = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-ambig-child',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_identical_child',
                    'text': 'First Name *',
                    'input_type': 'text',
                    'answer': 'Ada',
                    'status': 'ready',
                    'frame_id': 'child_frame',
                    'frame_descriptor': {'name': 'child_frame', 'url': 'about:blank'},
                    'locator_candidates': [{'by': 'id', 'value': 'first_name'}],
                }
            ],
        }
        report = fill_form(self.page, plan_ambiguous, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertIn("Ambiguous child frame", report['fields'][0].get('error', ''))
        self.assertEqual(report['fields'][0]['status'], 'failed')

        # 2. Explicit child frame targeting must NEVER resolve to main frame even if same URL
        main_url = self.page.url
        plan_child_same_url = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-child-same-url',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_child_main_url',
                    'text': 'First Name *',
                    'input_type': 'text',
                    'answer': 'Ada',
                    'status': 'ready',
                    'frame_id': 'frame-subframe-99',
                    'frame_descriptor': {'id': 'frame-subframe-99', 'url': main_url, 'name': 'no_such_child'},
                    'locator_candidates': [{'by': 'id', 'value': 'first_name'}],
                }
            ],
        }
        report2 = fill_form(self.page, plan_child_same_url, options={'screenshot': False})
        self.assertEqual(report2['summary']['failed'], 1)
        self.assertIn("Unsupported/stale frame identity", report2['fields'][0].get('error', ''))
        self.assertEqual(report2['fields'][0]['status'], 'failed')

    def test_conflicting_radio_and_combobox_label_value_fail_without_selection(self):
        # 1. Conflicting radio Yes/false
        plan_radio = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-radio-conflict',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_radio_conflict',
                    'text': 'Are you legally authorized to work in the United States?',
                    'input_type': 'radio',
                    'answer': 'Yes',
                    'selected_option': {'label': 'Yes', 'value': 'false'},
                    'status': 'ready',
                }
            ],
        }
        report_radio = fill_form(self.page, plan_radio, options={'screenshot': False})
        self.assertEqual(report_radio['summary']['failed'], 1)
        self.assertEqual(report_radio['summary']['filled'], 0)
        self.assertIn("Conflicting radio label 'Yes'", report_radio['fields'][0].get('error', ''))

        # Live DOM remains unselected
        auth_radios = self.page.locator('#work-auth-field input[type="radio"]:checked')
        self.assertEqual(auth_radios.count(), 0)

        # 2. Conflicting combobox Bachelor's Degree / masters
        plan_combo = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-combo-conflict',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_combo_conflict',
                    'text': 'Highest Degree Completed',
                    'input_type': 'combobox',
                    'answer': "Bachelor's Degree",
                    'selected_option': {'label': "Bachelor's Degree", 'value': 'masters'},
                    'status': 'ready',
                }
            ],
        }
        report_combo = fill_form(self.page, plan_combo, options={'screenshot': False})
        self.assertEqual(report_combo['summary']['failed'], 1)
        self.assertEqual(report_combo['summary']['filled'], 0)
        self.assertIn("Conflicting combobox label", report_combo['fields'][0].get('error', ''))

        # Live DOM combobox value remains empty
        sv = self.page.locator('#degree-container .select__single-value')
        if sv.count() > 0 and sv.is_visible():
            self.assertNotEqual(sv.inner_text().strip(), "Bachelor's Degree")
            self.assertNotEqual(sv.inner_text().strip(), "Master's Degree")

    def test_legal_agreements_always_skipped_independent_of_allow_review(self):
        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-legal-review',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_arbitration',
                    'text': 'I agree to mandatory arbitration and class-action waiver',
                    'fact_key': 'arbitration',
                    'input_type': 'checkbox',
                    'answer': True,
                    'status': 'ready',
                },
                {
                    'question_id': 'q_unrelated_review',
                    'text': 'Cover Letter',
                    'input_type': 'textarea',
                    'answer': 'Proposal text for review.',
                    'status': 'review',
                },
            ],
        }

        # With allow_review=True: legal agreement must STILL be skipped, but unrelated review question is filled
        report = fill_form(self.page, plan, options={'screenshot': False}, allow_review=True)
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 1)
        self.assertEqual(report['summary']['failed'], 0)

        f_arb = next(f for f in report['fields'] if f['question_id'] == 'q_arbitration')
        f_cov = next(f for f in report['fields'] if f['question_id'] == 'q_unrelated_review')

        self.assertEqual(f_arb['status'], 'skipped')
        self.assertIn('Legal agreement or privacy policy', f_arb['skip_reason'])
        self.assertEqual(f_cov['status'], 'filled')
        self.assertEqual(f_cov['verified_value'], 'Proposal text for review.')

    def test_live_dom_label_rerendered_to_arbitration_skips_unchanged(self):
        # Set up a benign checkbox in DOM whose label is changed to arbitration
        self.page.evaluate("""() => {
            const div = document.createElement('div');
            div.id = 'benign-arbitration-container';
            div.innerHTML = `
                <div class="field">
                    <label for="benign_cb">I agree to mandatory binding arbitration and class-action waiver</label>
                    <input type="checkbox" id="benign_cb" name="benign_cb">
                </div>
            `;
            document.body.appendChild(div);
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-rerendered-legal',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_benign',
                    'text': 'Preferences',
                    'input_type': 'checkbox',
                    'answer': True,
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'benign_cb'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False}, allow_review=True)
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("Legal agreement or privacy policy detected in live DOM", report['fields'][0]['skip_reason'])

        # Live checkbox remains unchecked
        self.assertFalse(self.page.locator('#benign_cb').is_checked())

    def test_live_dom_password_misclassified_or_accurate_skipped_unchanged(self):
        self.page.evaluate("""() => {
            const div = document.createElement('div');
            div.id = 'pw-test-container';
            div.innerHTML = `
                <div class="field">
                    <label for="misclassified_pw">Security PIN</label>
                    <input type="password" id="misclassified_pw" name="pin">
                </div>
            `;
            document.body.appendChild(div);
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-misclassified-pw',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_pw',
                    'text': 'Secret token',
                    'input_type': 'text',  # Misclassified as text in plan
                    'answer': '1234',
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'misclassified_pw'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("Unexpected password control in DOM", report['fields'][0]['skip_reason'])
        self.assertEqual(self.page.locator('#misclassified_pw').input_value(), '')

    def test_native_select_change_handler_rewriting_value_fails_readback(self):
        self.page.evaluate("""() => {
            const div = document.createElement('div');
            div.id = 'select-rewriter-container';
            div.innerHTML = `
                <div class="field">
                    <label for="rewriting_select">Confirmation</label>
                    <select id="rewriting_select">
                        <option value="true">Yes</option>
                        <option value="false">No</option>
                    </select>
                </div>
            `;
            document.body.appendChild(div);
            const sel = document.getElementById('rewriting_select');
            sel.addEventListener('change', () => {
                // Change handler rewrites Yes to No at the same index
                sel.options[sel.selectedIndex].text = 'No';
                sel.options[sel.selectedIndex].value = 'false';
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-select-rewriter',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_rewrite_sel',
                    'text': 'Confirmation',
                    'input_type': 'select',
                    'answer': 'Yes',
                    'selected_option': {'label': 'Yes', 'value': 'true'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'rewriting_select'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("Select readback label mismatch", report['fields'][0].get('error', ''))

    def test_combobox_two_widgets_share_ancestor_and_no_op_click(self):
        self.page.evaluate("""() => {
            const div = document.createElement('div');
            div.id = 'dual-combobox-container';
            div.innerHTML = `
                <div class="field" id="shared-ancestor-field">
                    <div class="select__container" id="combo-widget-1">
                        <div class="select__control">
                            <div class="select__value-container">
                                <div class="select__single-value">High School</div>
                                <input id="combo-input-1" role="combobox" aria-controls="combo-menu-1">
                            </div>
                        </div>
                        <div class="select__menu" id="combo-menu-1" style="display:none;" role="listbox">
                            <div class="select__option" role="option" data-value="hs">High School</div>
                        </div>
                    </div>
                    <div class="select__container" id="combo-widget-2">
                        <input type="hidden" name="combo_hidden_2" id="combo-hidden-2" value="">
                        <div class="select__control">
                            <div class="select__value-container">
                                <div class="select__single-value" style="display:none;"></div>
                                <input id="combo-input-2" role="combobox" aria-controls="combo-menu-2">
                            </div>
                        </div>
                        <div class="select__menu" id="combo-menu-2" style="display:none;" role="listbox">
                            <div class="select__option" role="option" data-value="phd">PhD</div>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(div);

            const inp2 = document.getElementById('combo-input-2');
            const m2 = document.getElementById('combo-menu-2');
            inp2.addEventListener('click', () => { m2.style.display = 'block'; });
            inp2.addEventListener('focus', () => { m2.style.display = 'block'; });

            // Menu 2 option click is a NO-OP (does not update single-value)
            m2.querySelector('.select__option').addEventListener('click', (e) => {
                e.stopPropagation();
                // No-op: deliberately does not update singleValue
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-combo-noop',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_w2',
                    'text': 'Target Combobox 2',
                    'input_type': 'combobox',
                    'answer': 'PhD',
                    'selected_option': {'label': 'PhD', 'value': 'phd'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'combo-input-2'}],
                }
            ],
        }

        # Target-specific readback must NOT be fooled by combo-widget-1's "High School" value in shared ancestor,
        # and must fail because the click was a no-op!
        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        err = report['fields'][0].get('error', '')
        self.assertTrue("Combobox readback verification failed" in err or "Existing hidden input empty" in err)

    def test_cli_fill_malformed_plan_shapes_structured_json(self):
        answers_dir = Path(self.temp_dir) / 'malformed_cases'
        answers_dir.mkdir(parents=True, exist_ok=True)
        out_dir = Path(self.temp_dir) / 'cli_malformed_shape_out'

        malformed_cases = [
            ({'answers': 123}, "Malformed answers plan: 'answers' must be a list"),
            ({'answers': [None]}, "Malformed answer at index 0: expected JSON object"),
            ({'answers': [{'text': None}]}, "Malformed answer at index 0: 'text' must be a non-null string"),
            ({'answers': [{'text': 'Test', 'locator_scope': 42}]}, "Malformed answer at index 0: 'locator_scope' must be a dict"),
            ({'answers': [{'text': 'Test', 'selected_option': 'not-a-dict'}]}, "Malformed answer at index 0: 'selected_option' must be a dict"),
            ({'answers': [{'text': 'Test', 'options': 'not-a-dict'}]}, "Malformed answer at index 0: 'options' must be a dict"),
            ({'answers': [{'text': 'Test', 'options': {'items': 'not-a-list'}}]}, "options['items'] must be a list"),
            ({'answers': [{'text': 'Test', 'options': {'items': ['not-a-dict']}}]}, "options['items'][0] must be a dict"),
            ({'answers': [{'text': 'Test', 'options': {'items': [{'label': 123}]}}]}, "options['items'][0]['label'] must be a string"),
            ({'answers': [{'text': 'Test', 'frame_descriptor': 'not-a-dict'}]}, "'frame_descriptor' must be a dict"),
            ({'answers': [{'text': 'Test', 'frame_descriptor': {'url': 123}}]}, "frame_descriptor['url'] must be a string"),
            ({'answers': [{'text': 'Test', 'locator_candidates': 'not-a-list'}]}, "'locator_candidates' must be a list"),
            ({'answers': [{'text': 'Test', 'locator_candidates': ['not-a-dict']}]}, "locator_candidates[0] must be a dict"),
            ({'answers': [{'text': 'Test', 'locator_candidates': [{'by': 123}]}]}, "locator_candidates[0] kind/by must be a string"),
            ({'answers': [{'text': 'Test', 'control_metadata': 'not-a-list'}]}, "'control_metadata' must be a list"),
            ({'answers': [{'text': 'Test', 'control_metadata': [{'dom': 'not-a-dict'}]}]}, "control_metadata[0]['dom'] must be a dict"),
        ]

        for idx, (bad_plan, expected_msg) in enumerate(malformed_cases):
            plan_file = answers_dir / f'bad_{idx}.json'
            plan_file.write_text(json.dumps(bad_plan), encoding='utf-8')

            proc = subprocess.run([
                sys.executable,
                '-m', 'job_applier.filling',
                self.fixture_path.as_uri(),
                '--answers', str(plan_file),
                '--out', str(out_dir),
            ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=30)

            self.assertEqual(proc.returncode, 1)
            parsed = json.loads(proc.stdout)
            self.assertEqual(parsed['status'], 'error')
            self.assertIn(expected_msg, parsed.get('error', ''))

            # Verify public fill_form raises ValueError directly for the same shape
            with self.assertRaises(ValueError) as ctx:
                fill_form(self.page, bad_plan, options={'screenshot': False})
            self.assertIn(expected_msg, str(ctx.exception))

    def test_preflight_schema_browser_sentinel_never_reached_on_malformed_plan(self):
        import io
        import secrets
        from unittest.mock import MagicMock, patch
        import job_applier.filling.__main__ as fill_main

        # Point 4: Enumerate EVERY engine-consumed metadata nested field incl
        # dom.group.path, name, label, form; locator_scope.form/group paths; candidate kind/value; descriptor IDs/names/url; text/null.
        # Malformed any later answer rejects whole plan before browser.
        # Test retained mock assert_not_called (not throwing sentinel swallowed by except);
        # assert specific validation message and no output artifacts.

        test_cases = [
            (
                {'answers': [{'text': 'Valid First Answer', 'status': 'ready'}, {'text': None}]},
                "must be a non-null string",
            ),
            (
                {
                    'answers': [
                        {'text': 'Valid Answer 1', 'status': 'ready'},
                        {
                            'text': 'Answer 2',
                            'control_metadata': [
                                {
                                    'id': 'cm_bad',
                                    'dom': {
                                        'group': {'path': 12345},  # numeric nestedpath!
                                    },
                                }
                            ],
                        },
                    ]
                },
                "control_metadata[0]['dom']['group']['path'] must be a string",
            ),
            (
                {
                    'answers': [
                        {'text': 'Valid Answer 1', 'status': 'ready'},
                        {
                            'text': 'Answer 2',
                            'locator_candidates': [{'by': 999, 'value': 'val'}],  # numeric kind/by!
                        },
                    ]
                },
                "kind/by must be a string",
            ),
            (
                {
                    'answers': [
                        {'text': 'Valid Answer 1', 'status': 'ready'},
                        {
                            'text': 'Answer 2',
                            'locator_scope': {'group': {'form': 123}},  # numeric group form!
                        },
                    ]
                },
                "locator_scope['group']['form'] must be a string",
            ),
            (
                {
                    'answers': [
                        {'text': 'Valid Answer 1', 'status': 'ready'},
                        {
                            'text': 'Answer 2',
                            'frame_descriptor': {'url': 888},  # numeric descriptor URL!
                        },
                    ]
                },
                "frame_descriptor['url'] must be a string",
            ),
        ]

        for plan_dict, expected_err in test_cases:
            bad_plan_file = Path(self.temp_dir) / f'preflight_{secrets.token_hex(6)}.json'
            bad_plan_file.write_text(json.dumps(plan_dict), encoding='utf-8')
            out_dir = Path(self.temp_dir) / f'preflight_out_{secrets.token_hex(6)}'

            mock_pw = MagicMock()
            with patch('playwright.sync_api.sync_playwright', mock_pw), \
                 patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:

                ret = fill_main.main([
                    self.fixture_path.as_uri(),
                    '--answers', str(bad_plan_file),
                    '--out', str(out_dir),
                ])
                # Returncode must be 1 (failure)
                self.assertEqual(ret, 1)

                # RETAINED MOCK: Browser startup MUST NEVER be called when preflight schema check fails!
                mock_pw.assert_not_called()

                # Specific validation message asserted
                output_str = mock_stdout.getvalue()
                parsed = json.loads(output_str)
                self.assertEqual(parsed['status'], 'error')
                self.assertIn(expected_err, parsed.get('error', ''))

                # NO output artifacts created!
                self.assertFalse(out_dir.exists())

    def test_radio_anonymous_form_a_removed_shifts_path_must_not_fill_b(self):
        # Two anonymous forms in DOM (no IDs)
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'anon-dual-forms';
            container.innerHTML = `
                <form class="anon-form">
                    <fieldset>
                        <legend>Will you require sponsorship?</legend>
                        <label><input type="radio" id="sp_a_yes" name="sponsor_a" value="true"> Yes</label>
                        <label><input type="radio" id="sp_a_no" name="sponsor_a" value="false"> No</label>
                    </fieldset>
                </form>
                <form class="anon-form">
                    <fieldset>
                        <legend>Will you require sponsorship?</legend>
                        <label><input type="radio" id="sp_b_yes" name="sponsor_b" value="true"> Yes</label>
                        <label><input type="radio" id="sp_b_no" name="sponsor_b" value="false"> No</label>
                    </fieldset>
                </form>
            `;
            document.body.appendChild(container);

            window.__radio_b_events = [];
            ['click', 'change', 'input'].forEach(evt => {
                document.getElementById('sp_b_yes').addEventListener(evt, () => window.__radio_b_events.push({id: 'sp_b_yes', type: evt}));
                document.getElementById('sp_b_no').addEventListener(evt, () => window.__radio_b_events.push({id: 'sp_b_no', type: evt}));
            });
        }""")

        # Captured metadata targeting Form A at nth-of-type(1)
        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-anon-shift',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_anon_a',
                    'text': 'Will you require sponsorship?',
                    'input_type': 'radio',
                    'answer': True,
                    'selected_option': {'id': 'opt_a_yes', 'label': 'Yes', 'value': 'true'},
                    'status': 'ready',
                    'locator_scope': {'form': 'div#anon-dual-forms > form:nth-of-type(1)'},
                    'control_metadata': [
                        {
                            'id': 'opt_a_yes',
                            'dom': {
                                'id': 'sp_a_yes',
                                'name': 'sponsor_a',
                                'form_path': 'div#anon-dual-forms > form:nth-of-type(1)',
                            },
                        }
                    ],
                }
            ],
        }

        # Remove Form A from the DOM; Form B shifts to nth-of-type(1)
        self.page.evaluate("() => document.querySelector('#anon-dual-forms > form:nth-of-type(1)').remove()")

        # Point 1: Anonymous form path identity is NOT stable -> skips unsupported BEFORE mutation
        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("unsupported", report['fields'][0]['skip_reason'].lower())

        # Form B radio MUST have exactly ZERO real events and remain completely unchecked!
        events = self.page.evaluate("() => window.__radio_b_events")
        self.assertEqual(events, [])
        self.assertFalse(self.page.locator('#sp_b_yes').is_checked())
        self.assertFalse(self.page.locator('#sp_b_no').is_checked())

    def test_radio_same_form_group_a_removed_leaves_group_b_same_legend_must_not_fill(self):
        # Same form containing two radio groups with identical legends
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'same-form-dual-groups-container';
            container.innerHTML = `
                <form id="same-form-groups">
                    <fieldset id="grp-alpha">
                        <legend>Will you require sponsorship?</legend>
                        <label><input type="radio" id="grp_alpha_yes" name="sponsor_alpha" value="true"> Yes</label>
                        <label><input type="radio" id="grp_alpha_no" name="sponsor_alpha" value="false"> No</label>
                    </fieldset>
                    <fieldset id="grp-beta">
                        <legend>Will you require sponsorship?</legend>
                        <label><input type="radio" id="grp_beta_yes" name="sponsor_beta" value="true"> Yes</label>
                        <label><input type="radio" id="grp_beta_no" name="sponsor_beta" value="false"> No</label>
                    </fieldset>
                </form>
            `;
            document.body.appendChild(container);

            window.__grp_beta_events = [];
            ['click', 'change', 'input'].forEach(evt => {
                document.getElementById('grp_beta_yes').addEventListener(evt, () => window.__grp_beta_events.push({id: 'grp_beta_yes', type: evt}));
                document.getElementById('grp_beta_no').addEventListener(evt, () => window.__grp_beta_events.push({id: 'grp_beta_no', type: evt}));
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-same-form-group-shift',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_grp_alpha',
                    'text': 'Will you require sponsorship?',
                    'input_type': 'radio',
                    'answer': True,
                    'selected_option': {'id': 'opt_alpha_yes', 'label': 'Yes', 'value': 'true'},
                    'status': 'ready',
                    'locator_scope': {
                        'form_id': 'same-form-groups',
                        'form': '#same-form-groups',
                        'group': {'path': '#same-form-groups > fieldset:nth-of-type(1)'},
                    },
                    'control_metadata': [
                        {
                            'id': 'opt_alpha_yes',
                            'dom': {
                                'id': 'grp_alpha_yes',
                                'name': 'sponsor_alpha',
                                'group': {'path': '#same-form-groups > fieldset:nth-of-type(1)'},
                            },
                        }
                    ],
                }
            ],
        }

        # Remove Group Alpha from DOM; Group Beta now becomes nth-of-type(1)
        self.page.evaluate("() => document.getElementById('grp-alpha').remove()")

        # Filling Group Alpha must fail and MUST NOT mutate Group Beta
        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)

        # Group Beta radios must have ZERO events and remain untouched!
        events = self.page.evaluate("() => window.__grp_beta_events")
        self.assertEqual(events, [])
        self.assertFalse(self.page.locator('#grp_beta_yes').is_checked())
        self.assertFalse(self.page.locator('#grp_beta_no').is_checked())

    def test_radio_no_stable_identity_in_captured_metadata_unsupported_skip(self):
        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-no-stable-id',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_no_id',
                    'text': 'Will you require sponsorship?',
                    'input_type': 'radio',
                    'answer': True,
                    'selected_option': {'id': 'opt_x', 'label': 'Yes', 'value': 'true'},
                    'status': 'ready',
                    'control_metadata': [
                        {
                            'id': 'opt_x',
                            'dom': {'id': None, 'name': None, 'tag': 'input'},
                        }
                    ],
                }
            ],
        }
        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertIn('unsupported', report['fields'][0]['skip_reason'].lower())

    def test_radio_captured_yes_contradictory_false(self):
        # Point 1: captured Yes with contradictory false value rejects before click; count events
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'radio-contra-val-container';
            container.innerHTML = `
                <form id="contra-radio-form">
                    <fieldset id="contra-radio-fs">
                        <legend>Are you 18 or older?</legend>
                        <label for="rad_yes_id">Yes</label>
                        <input type="radio" id="rad_yes_id" name="age_18" value="true">
                    </fieldset>
                </form>
            `;
            document.body.appendChild(container);
            window.__contra_events = [];
            ['click', 'change', 'input'].forEach(evt => {
                document.getElementById('rad_yes_id').addEventListener(evt, () => window.__contra_events.push(evt));
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-contra-radio-val',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_contra_radio',
                    'text': 'Are you 18 or older?',
                    'input_type': 'radio',
                    'answer': True,
                    'selected_option': {'id': 'opt_yes', 'label': 'Yes', 'value': 'false'},
                    'status': 'ready',
                    'locator_scope': {'form_id': 'contra-radio-form'},
                    'control_metadata': [
                        {
                            'id': 'opt_yes',
                            'dom': {
                                'id': 'rad_yes_id',
                                'name': 'age_18',
                                'form_id': 'contra-radio-form',
                                'form_path': '#contra-radio-form',
                            },
                        }
                    ],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("value mismatch before click", report['fields'][0].get('error', '').lower())

        # Zero click, change, or input events and unchecked!
        events = self.page.evaluate("() => window.__contra_events")
        self.assertEqual(events, [])
        self.assertFalse(self.page.locator('#rad_yes_id').is_checked())

    def test_radio_changed_bachelor_to_master_before_fill(self):
        # Point 1: captured Bachelor ID, later Master requested; must zero click/change/checked mutation
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'radio-changed-bachelor-container';
            container.innerHTML = `
                <form id="deg-radio-form">
                    <fieldset id="deg-radio-fs">
                        <legend>Degree Completed</legend>
                        <label for="rad_bach_id">Bachelor of Science</label>
                        <input type="radio" id="rad_bach_id" name="deg" value="bachelor">
                    </fieldset>
                </form>
            `;
            document.body.appendChild(container);
            window.__bach_events = [];
            ['click', 'change', 'input'].forEach(evt => {
                document.getElementById('rad_bach_id').addEventListener(evt, () => window.__bach_events.push(evt));
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-changed-bach-master',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_deg_change',
                    'text': 'Degree Completed',
                    'input_type': 'radio',
                    'answer': 'Master of Science',
                    'selected_option': {'id': 'opt_deg_bach', 'label': 'Master of Science', 'value': 'master'},
                    'status': 'ready',
                    'locator_scope': {'form_id': 'deg-radio-form'},
                    'control_metadata': [
                        {
                            'id': 'opt_deg_bach',
                            'dom': {
                                'id': 'rad_bach_id',
                                'name': 'deg',
                                'form_id': 'deg-radio-form',
                                'form_path': '#deg-radio-form',
                            },
                        }
                    ],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        err = report['fields'][0].get('error', '').lower()
        self.assertTrue('value mismatch before click' in err or 'label mismatch before click' in err)

        # Exactly zero click/change/input events and unchecked!
        events = self.page.evaluate("() => window.__bach_events")
        self.assertEqual(events, [])
        self.assertFalse(self.page.locator('#rad_bach_id').is_checked())

    def test_benign_checkbox_becomes_arbitration_via_aria_labelled_or_described_or_group(self):
        # Checkbox with benign text in plan, but live DOM links to mandatory arbitration via ARIA references
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'aria-legal-container';
            container.innerHTML = `
                <div id="arb_notice">I agree to mandatory binding arbitration, class-action waiver, and jury trial waiver.</div>
                <div role="group" id="pref_group">
                    <label id="cb_label">Communication Preferences</label>
                    <input type="checkbox" id="benign_aria_cb" aria-labelledby="cb_label" aria-describedby="arb_notice">
                </div>
            `;
            document.body.appendChild(container);
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-benign-aria-legal',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_benign_pref',
                    'text': 'Communication Preferences',
                    'input_type': 'checkbox',
                    'answer': True,
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'benign_aria_cb'}],
                }
            ],
        }

        # Test with allow_review=False: must be skipped unchanged
        report_no_review = fill_form(self.page, plan, options={'screenshot': False}, allow_review=False)
        self.assertEqual(report_no_review['summary']['skipped'], 1)
        self.assertEqual(report_no_review['summary']['filled'], 0)
        self.assertIn("Legal agreement or privacy policy detected in live DOM", report_no_review['fields'][0]['skip_reason'])
        self.assertFalse(self.page.locator('#benign_aria_cb').is_checked())

        # Test with allow_review=True: MUST ALSO be skipped unchanged (no consent override!)
        report_with_review = fill_form(self.page, plan, options={'screenshot': False}, allow_review=True)
        self.assertEqual(report_with_review['summary']['skipped'], 1)
        self.assertEqual(report_with_review['summary']['filled'], 0)
        self.assertIn("Legal agreement or privacy policy detected in live DOM", report_with_review['fields'][0]['skip_reason'])
        self.assertFalse(self.page.locator('#benign_aria_cb').is_checked())

    def test_legal_outer_legal_group_and_inner_benign(self):
        # Point 3: outer fieldset has arbitration legend, inner group is benign; must inspect all ancestors, not closest
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'outer-legal-container';
            container.innerHTML = `
                <fieldset id="outer_legal_fs">
                    <legend>Mandatory Arbitration and Class Action Waiver</legend>
                    <div role="group" id="inner_benign_group">
                        <label for="inner_benign_cb">Subscribe to newsletter</label>
                        <input type="checkbox" id="inner_benign_cb">
                    </div>
                </fieldset>
            `;
            document.body.appendChild(container);
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-outer-legal',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_outer_legal',
                    'text': 'Subscribe to newsletter',
                    'input_type': 'checkbox',
                    'answer': True,
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'inner_benign_cb'}],
                }
            ],
        }

        for review_flag in (False, True):
            report = fill_form(self.page, plan, options={'screenshot': False}, allow_review=review_flag)
            self.assertEqual(report['summary']['skipped'], 1)
            self.assertEqual(report['summary']['filled'], 0)
            self.assertIn("Legal agreement or privacy policy detected in live DOM", report['fields'][0]['skip_reason'])
            self.assertFalse(self.page.locator('#inner_benign_cb').is_checked())

    def test_legal_second_associated_legal_label(self):
        # Point 3: input has two associated labels via label[for=id]; second label is legal agreement
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'second-label-legal-container';
            container.innerHTML = `
                <div>
                    <label for="dual_label_cb">Marketing Communications</label>
                    <input type="checkbox" id="dual_label_cb">
                    <label for="dual_label_cb">I agree to mandatory binding arbitration, dispute release of claims, and terms of service</label>
                </div>
            `;
            document.body.appendChild(container);
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-second-label-legal',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_second_label',
                    'text': 'Marketing Communications',
                    'input_type': 'checkbox',
                    'answer': True,
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'dual_label_cb'}],
                }
            ],
        }

        for review_flag in (False, True):
            report = fill_form(self.page, plan, options={'screenshot': False}, allow_review=review_flag)
            self.assertEqual(report['summary']['skipped'], 1)
            self.assertEqual(report['summary']['filled'], 0)
            self.assertIn("Legal agreement or privacy policy detected in live DOM", report['fields'][0]['skip_reason'])
            self.assertFalse(self.page.locator('#dual_label_cb').is_checked())

    def test_aria_missing_reference_fails_closed(self):
        # Element references an ARIA id that does not exist in the DOM
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'missing-aria-ref-container';
            container.innerHTML = `
                <input type="checkbox" id="missing_ref_cb" aria-labelledby="nonexistent_id_123">
            `;
            document.body.appendChild(container);
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-missing-ref',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_missing_ref',
                    'text': 'Some Checkbox',
                    'input_type': 'checkbox',
                    'answer': True,
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'missing_ref_cb'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("Missing ARIA label/description reference in DOM", report['fields'][0]['skip_reason'])
        self.assertFalse(self.page.locator('#missing_ref_cb').is_checked())

    def test_radio_click_changes_bachelor_to_master_readback_fails(self):
        # Inject dynamic radio where clicking "Bachelor" rewrites label to "Master" while value is unchanged
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'mutating-radio-container';
            container.innerHTML = `
                <fieldset id="mutating-radio-grp">
                    <legend>Degree Completed</legend>
                    <label id="lbl_mut" for="rad_mut">Bachelor</label>
                    <input type="radio" id="rad_mut" name="deg_mut" value="bachelor">
                </fieldset>
            `;
            document.body.appendChild(container);

            const rad = document.getElementById('rad_mut');
            rad.addEventListener('click', () => {
                document.getElementById('lbl_mut').innerText = 'Master';
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-mutating-radio',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_deg_mut',
                    'text': 'Degree Completed',
                    'input_type': 'radio',
                    'answer': 'Bachelor',
                    'selected_option': {'label': 'Bachelor', 'value': 'bachelor'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'rad_mut'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("DOM readback label mismatch for radio", report['fields'][0].get('error', ''))

    def test_combobox_correct_display_wrong_hidden_masters_fails(self):
        # Combobox whose visible single-value shows "Bachelor", but hidden submitted input has "masters"
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'contradictory-combo-container';
            container.innerHTML = `
                <div class="select__container" id="contra-combo">
                    <input id="contra-input" role="combobox" aria-controls="contra-menu">
                    <input type="hidden" name="highest_degree" id="contra-hidden" value="masters">
                    <div class="select__single-value" id="contra-sv">Bachelor of Science</div>
                    <div id="contra-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="bs">Bachelor of Science</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);

            const inp = document.getElementById('contra-input');
            const menu = document.getElementById('contra-menu');
            inp.addEventListener('click', () => { menu.style.display = 'block'; });
            menu.querySelector('.select__option').addEventListener('click', () => {
                // Deliberately keep hidden input as "masters" while display is "Bachelor of Science"
                document.getElementById('contra-sv').innerText = 'Bachelor of Science';
                document.getElementById('contra-hidden').value = 'masters';
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-contra-combo',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_contra_combo',
                    'text': 'Highest Degree',
                    'input_type': 'combobox',
                    'answer': 'Bachelor of Science',
                    'selected_option': {'label': 'Bachelor of Science', 'value': 'bs'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'contra-input'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        error_msg = report['fields'][0].get('error', '')
        self.assertTrue('hidden value mismatch' in error_msg.lower() or 'contradictory' in error_msg.lower())

    def test_combobox_menu_aria_selected_only_without_commit_fails(self):
        # Option click sets aria-selected="true" on menu item but does NOT update target container single-value or hidden input
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'menu-selected-only-combo-container';
            container.innerHTML = `
                <div class="select__container" id="menu-sel-combo">
                    <input id="menu-sel-input" role="combobox" aria-controls="menu-sel-menu">
                    <input type="hidden" name="menu_sel_hidden" id="menu-sel-hidden" value="">
                    <div id="menu-sel-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="bs" id="opt-sel-bs">Bachelor of Science</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);

            const inp = document.getElementById('menu-sel-input');
            const menu = document.getElementById('menu-sel-menu');
            inp.addEventListener('click', () => { menu.style.display = 'block'; });
            const opt = document.getElementById('opt-sel-bs');
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                opt.setAttribute('aria-selected', 'true');
                // No update to target-owned single-value or hidden input
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-menu-sel-only',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_menu_sel',
                    'text': 'Highest Degree',
                    'input_type': 'combobox',
                    'answer': 'Bachelor of Science',
                    'selected_option': {'label': 'Bachelor of Science', 'value': 'bs'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'menu-sel-input'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("cannot establish uniquely target-owned committed value", report['fields'][0].get('error', '').lower())

    def test_combobox_null_valued_label_option_bachelor_with_hidden_phd(self):
        # Point 2: null-valued label option Bachelor with hidden phd input; cannot infer label equivalence => SKIP unsupported before action
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'null-val-combo-container';
            container.innerHTML = `
                <div class="select__container" id="null-val-combo">
                    <input id="null-val-input" role="combobox" aria-controls="null-val-menu">
                    <input type="hidden" name="degree_hidden" id="null-val-hidden" value="phd">
                    <div class="select__single-value" id="null-val-sv"></div>
                    <div id="null-val-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" id="opt-null-val">Bachelor of Science</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);
            const inp = document.getElementById('null-val-input');
            const menu = document.getElementById('null-val-menu');
            inp.addEventListener('click', () => { menu.style.display = 'block'; });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-null-val-combo',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_null_val',
                    'text': 'Degree',
                    'input_type': 'combobox',
                    'answer': 'Bachelor of Science',
                    'selected_option': {'label': 'Bachelor of Science'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'null-val-input'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("cannot infer label equivalence", report['fields'][0]['skip_reason'])
        self.assertEqual(self.page.locator('#null-val-hidden').get_attribute('value'), 'phd')

    def test_combobox_empty_hidden_despite_display(self):
        # Point 2: visible display shows Bachelor, but hidden input exists and is empty "" -> failure
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'empty-hidden-combo-container';
            container.innerHTML = `
                <div class="select__container" id="empty-h-combo">
                    <input id="empty-h-input" role="combobox" aria-controls="empty-h-menu">
                    <input type="hidden" name="deg_empty_h" id="empty-h-hidden" value="">
                    <div class="select__single-value" id="empty-h-sv"></div>
                    <div id="empty-h-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="bs" id="opt-empty-h">Bachelor of Science</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);
            const inp = document.getElementById('empty-h-input');
            const menu = document.getElementById('empty-h-menu');
            inp.addEventListener('click', () => { menu.style.display = 'block'; });
            document.getElementById('opt-empty-h').addEventListener('click', () => {
                document.getElementById('empty-h-sv').innerText = 'Bachelor of Science';
                document.getElementById('empty-h-hidden').value = '';
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-empty-h',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_empty_h',
                    'text': 'Degree',
                    'input_type': 'combobox',
                    'answer': 'Bachelor of Science',
                    'selected_option': {'label': 'Bachelor of Science', 'value': 'bs'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'empty-h-input'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("hidden input empty despite selection", report['fields'][0].get('error', '').lower())

    def test_combobox_aria_master_no_op_requested_bachelor(self):
        # Point 2: target has aria-valuetext="Master"; requested Bachelor; action is no-op -> raises RuntimeError
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'aria-master-noop-container';
            container.innerHTML = `
                <div class="select__container" id="aria-noop-combo">
                    <input id="aria-noop-input" role="combobox" aria-controls="aria-noop-menu" aria-valuetext="Master">
                    <div id="aria-noop-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="bachelor" id="opt-noop-b">Bachelor</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);
            const inp = document.getElementById('aria-noop-input');
            const menu = document.getElementById('aria-noop-menu');
            inp.addEventListener('click', () => { menu.style.display = 'block'; });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-aria-noop',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_aria_noop',
                    'text': 'Degree',
                    'input_type': 'combobox',
                    'answer': 'Bachelor',
                    'selected_option': {'label': 'Bachelor', 'value': 'bachelor'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'aria-noop-input'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertEqual(report['summary']['failed'], 0)
        self.assertIn("unsupported", report['fields'][0].get('skip_reason', '').lower())

    def test_combobox_value_only_mismatch(self):
        # Point 2: option clicked has value "bachelor", but hidden input sets "associate" -> mismatch
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'val-mismatch-combo-container';
            container.innerHTML = `
                <div class="select__container" id="vm-combo">
                    <input id="vm-input" role="combobox" aria-controls="vm-menu">
                    <input type="hidden" name="deg_vm" id="vm-hidden" value="initial">
                    <div class="select__single-value" id="vm-sv"></div>
                    <div id="vm-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="bachelor" id="opt-vm-b">Bachelor</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);
            const inp = document.getElementById('vm-input');
            const menu = document.getElementById('vm-menu');
            inp.addEventListener('click', () => { menu.style.display = 'block'; });
            document.getElementById('opt-vm-b').addEventListener('click', () => {
                document.getElementById('vm-sv').innerText = 'Bachelor';
                document.getElementById('vm-hidden').value = 'associate';
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-val-mismatch',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_val_mismatch',
                    'text': 'Degree',
                    'input_type': 'combobox',
                    'answer': 'Bachelor',
                    'selected_option': {'label': 'Bachelor', 'value': 'bachelor'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'vm-input'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("hidden value mismatch", report['fields'][0].get('error', '').lower())

    def test_combobox_display_only_with_unknown_mapping(self):
        # Point 2: custom div combobox with only visual display and NO hidden input or ARIA valuetext
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'display-only-combo-container';
            container.innerHTML = `
                <div class="select__container" id="disp-only-combo">
                    <div id="disp-only-input" role="combobox" aria-controls="disp-only-menu">Select degree...</div>
                    <div id="disp-only-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="bachelor" id="opt-do-b">Bachelor</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);
            const inp = document.getElementById('disp-only-input');
            const menu = document.getElementById('disp-only-menu');
            inp.addEventListener('click', () => { menu.style.display = 'block'; });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-disp-only',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_disp_only',
                    'text': 'Degree',
                    'input_type': 'combobox',
                    'answer': 'Bachelor',
                    'selected_option': {'label': 'Bachelor', 'value': 'bachelor'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'disp-only-input'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("unsupported needs_user", report['fields'][0]['skip_reason'])

    def test_frame_resolution_same_url_unique_vs_ambiguous(self):
        from job_applier.filling.engine import _resolve_scope_root

        # Inject an iframe with about:blank into the page
        self.page.evaluate("""() => {
            const ifr = document.createElement('iframe');
            ifr.id = 'test-child-frame-id';
            ifr.name = 'test-child-name';
            ifr.src = 'about:blank';
            document.body.appendChild(ifr);
        }""")

        child_frames = [f for f in self.page.frames if f != self.page.main_frame]
        self.assertGreaterEqual(len(child_frames), 1)
        child = child_frames[0]

        # 1. Child frame descriptor with unique name resolves uniquely
        q_unique = {
            'frame_id': 'frame-sub',
            'frame_descriptor': {'id': 'frame-sub', 'name': 'test-child-name', 'url': child.url},
        }
        resolved = _resolve_scope_root(self.page, q_unique)
        self.assertEqual(resolved, child)

        # 2. Ambiguous child frames: mock page with two child frames having identical URL and no unique name
        class DummyFrame:
            def __init__(self, name='', url='http://example.com/same'):
                self.name = name
                self.url = url
            def frame_element(self):
                raise Exception("no element")

        class DummyPage:
            def __init__(self):
                self.main_frame = DummyFrame(name='', url='http://example.com/main')
                self.frames = [self.main_frame, DummyFrame(name='', url='http://example.com/same'), DummyFrame(name='', url='http://example.com/same')]

        dummy_p = DummyPage()
        q_ambiguous = {
            'frame_id': 'frame-ambiguous',
            'frame_descriptor': {'id': 'frame-ambiguous', 'url': 'http://example.com/same'},
        }
        with self.assertRaises(ValueError) as ctx:
            _resolve_scope_root(dummy_p, q_ambiguous)
        self.assertIn("Ambiguous child frame", str(ctx.exception))

    def test_existing_unguarded_iframe_observation_guard_installed(self):
        # Create a new context and page that already contains an iframe before guard install
        ctx = self.browser.new_context()
        p = ctx.new_page()
        p.goto(self.fixture_path.as_uri(), wait_until='domcontentloaded')
        # Inject an iframe before observation guard is installed
        p.evaluate("""() => {
            const ifr = document.createElement('iframe');
            ifr.id = 'pre-existing-iframe';
            ifr.src = 'about:blank';
            document.body.appendChild(ifr);
        }""")

        child_fr = next(f for f in p.frames if f != p.main_frame)
        was_installed = child_fr.evaluate("Boolean(window.__job_applier_guard && window.__job_applier_guard.installed)")
        self.assertFalse(was_installed)

        # Install observation guard on the existing page
        install_observation_guard(p)

        # Iframe MUST now have guard installed immediately!
        is_installed = child_fr.evaluate("Boolean(window.__job_applier_guard && window.__job_applier_guard.installed)")
        self.assertTrue(is_installed)
        ctx.close()

    def test_safe_io_deterministic_ancestor_rename_open_fd_pinned(self):
        import job_applier.safe_io as safe_io
        # Test both overwrite=False and overwrite=True
        for overwrite_flag in (False, True):
            with tempfile.TemporaryDirectory() as td:
                base_real = Path(td) / 'base_real'
                base_real.mkdir(mode=0o700)
                leaf_dir = base_real / 'leaf'
                leaf_dir.mkdir(mode=0o700)

                # Dummy redirect directory that an attacker might point a symlink to
                dummy_redirect = Path(td) / 'dummy_redirect'
                dummy_redirect.mkdir(mode=0o700)
                (dummy_redirect / 'target.txt').write_bytes(b"canary_untouched")
                orig_dummy_stat = os.stat(dummy_redirect)

                target_path = leaf_dir / 'target.txt'
                if overwrite_flag:
                    # Pre-create the destination file in the real leaf dir
                    target_path.write_bytes(b"initial_content")

                # Define hook to rename base_real and replace with symlink to dummy_redirect after parent_fd acquired
                def hook_rename(parent_fd, raw_path):
                    base_renamed = Path(td) / 'base_renamed'
                    if not base_renamed.exists():
                        os.rename(base_real, base_renamed)
                        os.symlink(dummy_redirect, base_real)

                try:
                    safe_io._TEST_POST_WALK_HOOK = hook_rename

                    res = safe_io.write_bytes_atomic(target_path, b"pinned_content", overwrite=overwrite_flag)
                    # Verify commit stayed in original pinned directory (now at base_renamed / leaf / target.txt)
                    pinned_file = Path(td) / 'base_renamed' / 'leaf' / 'target.txt'
                    self.assertTrue(pinned_file.is_file())
                    self.assertEqual(pinned_file.read_bytes(), b"pinned_content")
                    # Dummy redirect contents and permissions MUST be completely unchanged!
                    self.assertEqual((dummy_redirect / 'target.txt').read_bytes(), b"canary_untouched")
                    new_dummy_stat = os.stat(dummy_redirect)
                    self.assertEqual(orig_dummy_stat.st_mode, new_dummy_stat.st_mode)
                finally:
                    safe_io._TEST_POST_WALK_HOOK = None

    def test_safe_io_staged_name_replacement_detected_and_fails_safely(self):
        import job_applier.safe_io as safe_io
        with tempfile.TemporaryDirectory() as td:
            leaf_dir = Path(td) / 'leaf_swap'
            leaf_dir.mkdir(mode=0o700)
            target_path = leaf_dir / 'target.txt'

            def hook_swap(parent_fd, temp_name):
                # Unlink staged temp file and replace with a different inode
                os.unlink(temp_name, dir_fd=parent_fd)
                rep_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd)
                with os.fdopen(rep_fd, 'wb') as f:
                    f.write(b"injected")

            try:
                safe_io._TEST_PRE_COMMIT_HOOK = hook_swap
                with self.assertRaises(ValueError) as ctx:
                    safe_io.write_bytes_atomic(target_path, b"legitimate", overwrite=False)
                self.assertIn("descriptor identity mismatch", str(ctx.exception))
                self.assertFalse(target_path.exists())
            finally:
                safe_io._TEST_PRE_COMMIT_HOOK = None

    def test_safe_io_rejects_group_or_other_writable_leaf_directory(self):
        import job_applier.safe_io as safe_io
        with tempfile.TemporaryDirectory() as td:
            shared_dir = Path(td) / 'shared_insecure'
            shared_dir.mkdir(mode=0o777)
            os.chmod(shared_dir, 0o777)
            target_file = shared_dir / 'test.txt'
            with self.assertRaises(PermissionError) as ctx:
                safe_io.write_bytes_atomic(target_file, b"data", overwrite=False)
            self.assertIn("writable by group/others", str(ctx.exception))

    def test_safe_io_injected_write_fail_leaves_no_dest_retry_succeeds(self):
        from unittest.mock import patch
        from job_applier.safe_io import write_bytes_atomic
        with tempfile.TemporaryDirectory() as td:
            target_file = Path(td) / 'fail_test' / 'target.txt'

            # Inject failure during os.fsync
            with patch('os.fsync', side_effect=OSError("Disk write failed")):
                with self.assertRaises(OSError):
                    write_bytes_atomic(target_file, b"data to fail", overwrite=False)

            # Target destination MUST NOT exist
            self.assertFalse(target_file.exists())

            # Retry succeeds cleanly
            written = write_bytes_atomic(target_file, b"data succeeded", overwrite=False)
            self.assertTrue(target_file.is_file())
            self.assertEqual(written.read_bytes(), b"data succeeded")

    def test_frame_duplicate_identical_survivor_skips_unsupported(self):
        # Point 8: page initially has 2 identical child frames.
        # One is removed after capture. Filling engine sees survivor but identity cannot distinguish captured child
        # from survivor -> skips unsupported without wrong mutation!
        self.page.evaluate("""() => {
            const ifr1 = document.createElement('iframe');
            ifr1.id = 'peer-iframe-1';
            ifr1.srcdoc = '<!doctype html><html><body><input id="peer_input" value="orig1"></body></html>';
            document.body.appendChild(ifr1);

            const ifr2 = document.createElement('iframe');
            ifr2.id = 'peer-iframe-2';
            ifr2.srcdoc = '<!doctype html><html><body><input id="peer_input" value="orig2"></body></html>';
            document.body.appendChild(ifr2);
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-survivor-identical',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_survivor',
                    'text': 'Widget Question',
                    'input_type': 'text',
                    'answer': 'new_mutated_value',
                    'status': 'ready',
                    'frame_id': 'frame-1',
                    'frame_descriptor': {
                        'id': 'frame-1',
                        'url': 'about:srcdoc',
                        'name': '',
                        'ambiguous_peer': True,
                    },
                    'locator_candidates': [{'by': 'id', 'value': 'peer_input'}],
                }
            ],
        }

        # Remove one of the 2 identical child frames after capture; survivor remains
        self.page.evaluate("() => document.getElementById('peer-iframe-1').remove()")

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("unsupported_ambiguous_frame", report['fields'][0]['skip_reason'])

        # Verify survivor frame was NOT mutated!
        survivor_child = next(
            f for f in self.page.frames
            if f != self.page.main_frame and f.evaluate("Boolean(window.frameElement && window.frameElement.id === 'peer-iframe-2')")
        )
        self.assertEqual(survivor_child.locator('#peer_input').input_value(), 'orig2')

    def test_extraction_cli_safe_io_symlink_rejection_and_private_creation(self):
        # Point 6: Extraction CLI preserves lexical path, routes all 4 artifacts through safe_io writer,
        # creates 0700 private leaf dir, enforces 0600 file perms, refuses symlink output, default no-overwrite.
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td) / 'private_ext_out'
            proc = subprocess.run([
                sys.executable,
                '-m', 'job_applier.extraction',
                self.fixture_path.as_uri(),
                '--out', str(base_dir),
                '--no-probe-options',
            ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=45)
            self.assertEqual(proc.returncode, 0, f"Extraction CLI failed: {proc.stderr}")

            # Verify directory is private 0700
            dir_st = os.stat(base_dir)
            self.assertEqual(dir_st.st_mode & 0o777, 0o700)

            # Verify all 4 artifacts exist and have 0600 mode
            artifacts = ['questions.json', 'index.html', 'accessibility.txt', 'source-page.png']
            for art in artifacts:
                art_path = base_dir / art
                self.assertTrue(art_path.is_file(), f"Missing artifact: {art}")
                st = os.stat(art_path)
                self.assertEqual(st.st_mode & 0o777, 0o600, f"Artifact {art} does not have 0600 permissions")

            # Refuses overwrite without --overwrite
            proc_no_ow = subprocess.run([
                sys.executable,
                '-m', 'job_applier.extraction',
                self.fixture_path.as_uri(),
                '--out', str(base_dir),
                '--no-probe-options',
            ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=45)
            self.assertNotEqual(proc_no_ow.returncode, 0)
            self.assertIn("not empty", proc_no_ow.stderr)

            # With --overwrite, succeeds
            proc_ow = subprocess.run([
                sys.executable,
                '-m', 'job_applier.extraction',
                self.fixture_path.as_uri(),
                '--out', str(base_dir),
                '--no-probe-options',
                '--overwrite',
            ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=45)
            self.assertEqual(proc_ow.returncode, 0, f"Overwrite failed: {proc_ow.stderr}")

            # Symlink refusal: create a symlink destination
            symlink_dir = Path(td) / 'symlink_ext_dir'
            dummy_target = Path(td) / 'dummy_target'
            dummy_target.mkdir(mode=0o700)
            os.symlink(dummy_target, symlink_dir)

            proc_sym = subprocess.run([
                sys.executable,
                '-m', 'job_applier.extraction',
                self.fixture_path.as_uri(),
                '--out', str(symlink_dir),
                '--no-probe-options',
            ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=45)
            self.assertNotEqual(proc_sym.returncode, 0)
            self.assertTrue("symlink" in proc_sym.stderr.lower() or "failed to write" in proc_sym.stderr.lower())

    def test_frame_real_collect_survivor_different_id_no_mutation(self):
        # Point 1: Real collect -> resolve -> removeA -> fill test with zero mutation on B.
        # Two identical child frames with distinct element IDs: peerA and peerB.
        # In real extraction, ambiguous_peer is False because element_id distinguishes them.
        from job_applier.extraction.engine import collect
        from job_applier.resolution.engine import resolve_cascade
        from tests.pipeline_test import make_pipeline_bank, NullSemanticMatcher

        self.page.evaluate("""() => {
            const ifrA = document.createElement('iframe');
            ifrA.id = 'peerA';
            ifrA.srcdoc = '<!doctype html><html><body><form id="fA"><label for="fnA">First Name</label><input id="fnA" name="first_name" value="origA"></form></body></html>';
            document.body.appendChild(ifrA);

            const ifrB = document.createElement('iframe');
            ifrB.id = 'peerB';
            ifrB.srcdoc = '<!doctype html><html><body><form id="fB"><label for="fnB">First Name</label><input id="fnB" name="first_name" value="origB"></form></body></html>';
            document.body.appendChild(ifrB);
        }""")

        extraction = collect(self.page, probe_options=False)
        qA = next(q for q in extraction['questions'] if (q.get('frame_descriptor') or {}).get('element_id') == 'peerA')
        self.assertFalse(qA['frame_descriptor'].get('ambiguous_peer', False))
        self.assertEqual(qA['frame_descriptor']['element_id'], 'peerA')

        bank = make_pipeline_bank()
        cascade = resolve_cascade([qA], bank, NullSemanticMatcher())
        resolved_qA = cascade['results'][0]
        self.assertEqual(resolved_qA['frame_descriptor']['element_id'], 'peerA')

        # Remove iframe A from DOM; survivor iframe B remains
        self.page.evaluate("() => document.getElementById('peerA').remove()")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': extraction['snapshot_id'],
            'scope': 'job_application',
            'answers': [resolved_qA],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("Unsupported/stale frame identity", report['fields'][0].get('error', ''))

        # Survivor B must have ZERO mutation!
        survivor_b = next(
            f for f in self.page.frames
            if f != self.page.main_frame and f.evaluate("Boolean(window.frameElement && window.frameElement.id === 'peerB')")
        )
        self.assertEqual(survivor_b.locator('#fnB').input_value(), 'origB')

    def test_nonradio_two_stable_forms_remove_form_a_form_b_unchanged(self):
        # Point 1: Two stable forms with same label; remove Form A, Form B unchanged.
        # Prefer form_id over positional form path.
        from job_applier.extraction.engine import collect
        from job_applier.resolution.engine import resolve_cascade
        from tests.pipeline_test import make_pipeline_bank, NullSemanticMatcher

        self.page.evaluate("""() => {
            const formA = document.createElement('form');
            formA.id = 'stable-form-a';
            formA.innerHTML = '<label for="inp_a">First Name</label><input id="inp_a" name="first_name" value="">';
            document.body.appendChild(formA);

            const formB = document.createElement('form');
            formB.id = 'stable-form-b';
            formB.innerHTML = '<label for="inp_b">First Name</label><input id="inp_b" name="first_name" value="">';
            document.body.appendChild(formB);
        }""")

        extraction = collect(self.page, probe_options=False)
        q_a = next(q for q in extraction['questions'] if (q.get('locator_scope') or {}).get('form_id') == 'stable-form-a')
        self.assertEqual((q_a['locator_scope'])['form_id'], 'stable-form-a')

        bank = make_pipeline_bank()
        cascade = resolve_cascade([q_a], bank, NullSemanticMatcher())
        resolved_a = cascade['results'][0]

        # Remove Form A from DOM; Form B remains and might shift positionally into Form A's place
        self.page.evaluate("() => document.getElementById('stable-form-a').remove()")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': extraction['snapshot_id'],
            'scope': 'job_application',
            'answers': [resolved_a],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertTrue(
            "Stale form scope" in report['fields'][0].get('error', '')
            or "Stale control targeting" in report['fields'][0].get('error', '')
        )

        # Form B input MUST be untouched!
        self.assertEqual(self.page.locator('#inp_b').input_value(), '')

    def test_reused_ids_across_frames_resolved_correctly(self):
        # Point 1: Reused IDs across frames resolved correctly
        self.page.evaluate("""() => {
            const ifr = document.createElement('iframe');
            ifr.id = 'child-reused-frame';
            ifr.srcdoc = '<!doctype html><html><body><form id="child-form"><label for="reused_input">First Name</label><input id="reused_input" name="reused_input" value="child_orig"></form></body></html>';
            document.body.appendChild(ifr);

            const mainInput = document.createElement('input');
            mainInput.id = 'reused_input';
            mainInput.value = 'main_orig';
            document.body.appendChild(mainInput);
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-reused-across-frames',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_child_reused',
                    'text': 'First Name',
                    'input_type': 'text',
                    'answer': 'child_new_value',
                    'status': 'ready',
                    'frame_id': 'child-reused-frame',
                    'frame_descriptor': {
                        'id': 'child-reused-frame',
                        'element_id': 'child-reused-frame',
                        'url': 'about:srcdoc',
                        'name': '',
                    },
                    'locator_candidates': [{'by': 'id', 'value': 'reused_input'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 0)
        self.assertEqual(report['summary']['filled'], 1)

        # Child iframe input is mutated to new value
        child_frame = next(f for f in self.page.frames if f.evaluate("Boolean(window.frameElement && window.frameElement.id === 'child-reused-frame')"))
        self.assertEqual(child_frame.locator('#reused_input').input_value(), 'child_new_value')

        # Main frame input with the same ID MUST BE UNTOUCHED!
        self.assertEqual(self.page.locator('> #reused_input, body > #reused_input').input_value(), 'main_orig')

    def test_combobox_display_only_existing_selected_value_skips_unsupported(self):
        # Point 2: Display-only .single-value does NOT qualify -> skip before any interaction
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'disp-only-existing-val-container';
            container.innerHTML = `
                <div class="select__container" id="disp-only-widget">
                    <div class="select__control">
                        <div class="select__value-container">
                            <div class="select__single-value">Bachelor's Degree</div>
                            <input id="disp-only-search" role="combobox" aria-controls="disp-only-menu">
                        </div>
                    </div>
                    <div class="select__menu" id="disp-only-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="bachelors">Bachelor's Degree</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);

            window.__dispOnlyEvents = [];
            const search = document.getElementById('disp-only-search');
            ['click', 'input', 'change', 'keydown'].forEach(evt => {
                search.addEventListener(evt, () => window.__dispOnlyEvents.push(evt));
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-disp-existing',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_disp_only',
                    'text': 'Degree',
                    'input_type': 'combobox',
                    'answer': "Bachelor's Degree",
                    'selected_option': {'label': "Bachelor's Degree", 'value': 'bachelors'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'disp-only-search'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("display-only .single-value does not qualify", report['fields'][0]['skip_reason'])

        # Search input received ZERO events!
        events = self.page.evaluate("() => window.__dispOnlyEvents")
        self.assertEqual(events, [])

    def test_combobox_two_hidden_inputs_skips_before_interaction(self):
        # Point 2: Multiple hidden submitted inputs (bs/phd) ambiguous => skip BEFORE ANY interaction, do not .first
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'two-hidden-combo-container';
            container.innerHTML = `
                <div class="select__container" id="two-hidden-widget">
                    <input type="hidden" name="degree_bs" value="bachelors">
                    <input type="hidden" name="degree_phd" value="phd">
                    <div class="select__control">
                        <div class="select__value-container">
                            <input id="two-hidden-search" role="combobox" aria-controls="two-hidden-menu">
                        </div>
                    </div>
                    <div class="select__menu" id="two-hidden-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="bachelors">Bachelor's Degree</div>
                        <div class="select__option" role="option" data-value="phd">Doctorate / PhD</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);

            window.__twoHiddenEvents = [];
            const search = document.getElementById('two-hidden-search');
            ['click', 'input', 'change', 'keydown'].forEach(evt => {
                search.addEventListener(evt, () => window.__twoHiddenEvents.push(evt));
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-two-hidden',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_two_hidden',
                    'text': 'Degree',
                    'input_type': 'combobox',
                    'answer': "Bachelor's Degree",
                    'selected_option': {'label': "Bachelor's Degree", 'value': 'bachelors'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'two-hidden-search'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("ambiguous hidden submitted inputs", report['fields'][0]['skip_reason'])

        # Search input received ZERO events
        events = self.page.evaluate("() => window.__twoHiddenEvents")
        self.assertEqual(events, [])

    def test_combobox_aria_bachelor_and_masters_contradiction_rejected(self):
        # Point 2: Both aria-valuetext AND aria-valuenow if present checked independently;
        # reject contradiction ariaBachelor+masters
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'aria-contra-container';
            container.innerHTML = `
                <div class="select__container" id="aria-contra-widget">
                    <input id="aria-contra-input" role="combobox" aria-controls="aria-contra-menu" aria-valuetext="Bachelor's Degree" aria-valuenow="masters">
                    <div class="select__menu" id="aria-contra-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="bachelors">Bachelor's Degree</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);

            const inp = document.getElementById('aria-contra-input');
            const menu = document.getElementById('aria-contra-menu');
            inp.addEventListener('click', () => { menu.style.display = 'block'; });
            menu.querySelector('.select__option').addEventListener('click', (e) => {
                e.stopPropagation();
                inp.setAttribute('aria-valuetext', "Bachelor's Degree");
                inp.setAttribute('aria-valuenow', 'masters');
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-aria-contra',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_aria_contra',
                    'text': 'Degree',
                    'input_type': 'combobox',
                    'answer': "Bachelor's Degree",
                    'selected_option': {'label': "Bachelor's Degree", 'value': 'bachelors'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'aria-contra-input'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertEqual(report['summary']['failed'], 0)
        skip_r = report['fields'][0].get('skip_reason', '')
        self.assertTrue("contradictory" in skip_r.lower() or "unsupported" in skip_r.lower())

    def test_validate_answers_plan_top_fields_and_candidate_types(self):
        # Point 3: validate_answers_plan includes all consumed TOP fields and candidate by-specific types
        from job_applier.filling.engine import validate_answers_plan
        from unittest.mock import patch

        # Invalid top fields
        self.assertIn("field 'frame_id' must be a string", validate_answers_plan({'answers': [{'text': 'T', 'frame_id': 123}]}))
        self.assertIn("field 'form_id' must be a string", validate_answers_plan({'answers': [{'text': 'T', 'form_id': ['bad']}]}))
        self.assertIn("field 'form_path' must be a string", validate_answers_plan({'answers': [{'text': 'T', 'form_path': {'bad': 1}}]}))

        # Invalid candidate by-specific types
        self.assertIn("'role' must be a string", validate_answers_plan({'answers': [{'text': 'T', 'locator_candidates': [{'by': 'role', 'role': []}]}]}))
        self.assertIn("'name' must be a string", validate_answers_plan({'answers': [{'text': 'T', 'locator_candidates': [{'by': 'name', 'name': []}]}]}))
        self.assertIn("'selector' must be a string", validate_answers_plan({'answers': [{'text': 'T', 'locator_candidates': [{'by': 'css', 'selector': {}}]}]}))

        # Valid first + malformed second: entire plan rejects before Playwright/import/navigation/artifacts
        valid_first_malformed_second = {
            'answers': [
                {'text': 'First Valid', 'question_id': 'q1', 'status': 'ready', 'input_type': 'text'},
                {'text': 'Second Malformed', 'locator_candidates': [{'by': 'role', 'role': []}]},
            ]
        }
        val_res = validate_answers_plan(valid_first_malformed_second)
        self.assertIsNotNone(val_res)
        self.assertIn("locator_candidates[0] 'role' must be a string", val_res)

        # CLI test with mock: sync_playwright assert_not_called
        with tempfile.TemporaryDirectory() as td:
            plan_file = Path(td) / 'plan_malformed.json'
            plan_file.write_text(json.dumps(valid_first_malformed_second), encoding='utf-8')
            out_dir = Path(td) / 'cli_out'

            import job_applier.filling.__main__ as fill_cli
            with patch('job_applier.filling.__main__.sync_playwright', create=True) as mock_pw:
                ret = fill_cli.main(['http://127.0.0.1:9999/dummy.html', '--answers', str(plan_file), '--out', str(out_dir)])
                self.assertEqual(ret, 1)
                mock_pw.assert_not_called()
                self.assertFalse((out_dir / 'fill_report.json').exists())

    def test_safe_io_mkdir_substitution_competitor_mode_unchanged(self):
        # Point 5: Deterministic substitution between successful mkdir and open verify competitor mode unchanged.
        # Remove fchmod entirely: never change permissions of preexisting/replacement dirs.
        import job_applier.safe_io as safe_io
        with tempfile.TemporaryDirectory() as td:
            target_path = Path(td) / 'comp_leaf' / 'test.txt'

            def hook_mkdir_sub(curr_fd, comp):
                # Remove newly created leaf component and replace with competitor directory of mode 0777
                os.rmdir(comp, dir_fd=curr_fd)
                os.mkdir(comp, mode=0o777, dir_fd=curr_fd)
                os.chmod(os.path.join(td, comp), 0o777)

            try:
                safe_io._TEST_POST_MKDIR_HOOK = hook_mkdir_sub
                with self.assertRaises(PermissionError) as ctx:
                    safe_io.write_bytes_atomic(target_path, b"data", overwrite=False)
                self.assertIn("writable by group/others", str(ctx.exception))

                # Verify competitor directory mode was NEVER changed by safe_io (remains 0777)!
                st = os.stat(os.path.join(td, 'comp_leaf'))
                self.assertEqual(st.st_mode & 0o777, 0o777)
            finally:
                safe_io._TEST_POST_MKDIR_HOOK = None

    def test_safe_io_staged_fd_held_open_rejects_inode_replacement_repeatedly(self):
        # Point 5: Test repeated replacing stage name with distinct inode as original fd live ensures no reuse and rejected
        import job_applier.safe_io as safe_io
        with tempfile.TemporaryDirectory() as td:
            leaf_dir = Path(td) / 'leaf_swap_multi'
            leaf_dir.mkdir(mode=0o700)

            for attempt in range(3):
                target_path = leaf_dir / f'target_{attempt}.txt'

                def hook_swap(parent_fd, temp_name):
                    os.unlink(temp_name, dir_fd=parent_fd)
                    rep_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd)
                    with os.fdopen(rep_fd, 'wb') as f:
                        f.write(b"injected_bytes")

                try:
                    safe_io._TEST_PRE_COMMIT_HOOK = hook_swap
                    with self.assertRaises(ValueError) as ctx:
                        safe_io.write_bytes_atomic(target_path, b"legit_data", overwrite=False)
                    self.assertIn("descriptor identity mismatch", str(ctx.exception))
                    self.assertFalse(target_path.exists())
                finally:
                    safe_io._TEST_PRE_COMMIT_HOOK = None


    def test_combobox_input_value_masters_aria_bachelor_noop_option_unchanged_skipped(self):
        # GAP-7: actual named input name=degree value masters ARIABachelor noop option,
        # unsupported BEFORE action assert 0 input/click/change and unchanged exact value.
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'contra-combo-container';
            container.innerHTML = `
                <div class="select__container" id="contra-combo-widget">
                    <input id="contra-search-input" name="degree" role="combobox" aria-controls="contra-combo-menu" aria-valuetext="Bachelor" value="masters">
                    <input type="hidden" name="degree_contra" id="contra-hidden" value="initial_hidden">
                    <div class="select__menu" id="contra-combo-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="bachelor" id="opt-contra-b">Bachelor</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);
            window.__contraEvents = [];
            const inp = document.getElementById('contra-search-input');
            ['input', 'change', 'click'].forEach(evt => {
                inp.addEventListener(evt, () => window.__contraEvents.push(evt));
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-contra-combo',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_contra_combo',
                    'text': 'Degree',
                    'input_type': 'combobox',
                    'answer': 'Bachelor',
                    'selected_option': {'label': 'Bachelor', 'value': 'bachelor'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'contra-search-input'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertEqual(report['summary']['failed'], 0)
        self.assertIn("unsupported", report['fields'][0].get('skip_reason', '').lower())

        # Assert unchanged DOM: value remains 'masters', aria-valuetext remains 'Bachelor', zero events
        inp_val = self.page.locator('#contra-search-input').input_value()
        self.assertEqual(inp_val, 'masters')
        hidden_val = self.page.locator('#contra-hidden').input_value()
        self.assertEqual(hidden_val, 'initial_hidden')
        events = self.page.evaluate("() => window.__contraEvents")
        self.assertEqual(events, [])

    def test_combobox_real_supported_unnamed_search_plus_one_named_hidden(self):
        # Item 1: Fixture real supported combo explicit unnamed search +1namedhidden
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'supp-combo-container';
            container.innerHTML = `
                <div class="select__container" id="supp-combo-widget">
                    <input id="supp-search-input" role="combobox" aria-controls="supp-menu">
                    <input type="hidden" name="education_level" id="supp-hidden" value="initial">
                    <div class="select__single-value" id="supp-sv"></div>
                    <div class="select__menu" id="supp-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="bachelors" id="opt-supp-b">Bachelor's Degree</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);
            const inp = document.getElementById('supp-search-input');
            const menu = document.getElementById('supp-menu');
            inp.addEventListener('click', () => { menu.style.display = 'block'; });
            document.getElementById('opt-supp-b').addEventListener('click', () => {
                document.getElementById('supp-hidden').value = 'bachelors';
                document.getElementById('supp-sv').innerText = "Bachelor's Degree";
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-supp-combo',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_supp_combo',
                    'text': 'Degree',
                    'input_type': 'combobox',
                    'answer': "Bachelor's Degree",
                    'selected_option': {'label': "Bachelor's Degree", 'value': 'bachelors'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'supp-search-input'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['filled'], 1)
        self.assertEqual(report['summary']['failed'], 0)
        self.assertEqual(self.page.locator('#supp-hidden').input_value(), 'bachelors')
        self.assertEqual(self.page.locator('#supp-sv').inner_text(), "Bachelor's Degree")

    def test_captured_targets_move_same_id_from_anonymous_a_to_b_zero_events(self):
        # Item 2: actual collect->resolve->move sameID from anonymous A to B (A remains) zero events
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'anon-move-container';
            container.innerHTML = `
                <form id="anon-form-a-wrapper">
                    <input id="moved_field" name="test_field" value="orig_a">
                </form>
                <form id="anon-form-b-wrapper">
                    <span id="b_target"></span>
                </form>
            `;
            container.querySelectorAll('form').forEach(f => f.removeAttribute('id'));
            document.body.appendChild(container);
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-anon-move',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_anon_move',
                    'text': 'Test Field',
                    'input_type': 'text',
                    'answer': 'new_val',
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'moved_field'}],
                    'control_metadata': [
                        {
                            'id': 'moved_field',
                            'dom': {
                                'id': 'moved_field',
                                'name': 'test_field',
                                'form_path': 'html > body > div#anon-move-container > form:nth-of-type(1)',
                            }
                        }
                    ],
                    'locator_scope': {
                        'form': 'html > body > div#anon-move-container > form:nth-of-type(1)',
                    }
                }
            ],
        }

        # Move input into form B
        self.page.evaluate("""() => {
            const inp = document.getElementById('moved_field');
            window.__anonEvents = [];
            ['input', 'change'].forEach(evt => inp.addEventListener(evt, () => window.__anonEvents.push(evt)));
            const b = document.querySelectorAll('#anon-move-container form')[1];
            b.appendChild(inp);
        }""")

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertEqual(report['summary']['failed'], 0)
        self.assertIn("anonymous form", report['fields'][0].get('skip_reason', '').lower())

        events = self.page.evaluate("() => window.__anonEvents")
        self.assertEqual(events, [])
        self.assertEqual(self.page.locator('#moved_field').input_value(), 'orig_a')

    def test_captured_targets_idless_named_a_removed_leaves_nameless_same_form_survivor_unchanged(self):
        # Item 2: IDless named A removed leaves same-label nameless sameform survivor unchanged
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'idless-survivor-container';
            container.innerHTML = `
                <form id="stable_test_form">
                    <label for="named_a_input">Shared Label</label>
                    <input name="named_a_field" value="val_a" id="named_a_input">
                    <label for="nameless_survivor">Shared Label</label>
                    <input value="survivor_init" id="nameless_survivor">
                </form>
            `;
            document.body.appendChild(container);
            document.getElementById('named_a_input').removeAttribute('id');
            const survivor = document.getElementById('nameless_survivor');
            survivor.removeAttribute('id');
            survivor.removeAttribute('name');

            window.__survivorEvents = [];
            ['input', 'change'].forEach(evt => survivor.addEventListener(evt, () => window.__survivorEvents.push(evt)));
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-idless-a',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_named_a',
                    'text': 'Shared Label',
                    'input_type': 'text',
                    'answer': 'new_val_a',
                    'status': 'ready',
                    'control_metadata': [
                        {
                            'dom': {
                                'name': 'named_a_field',
                                'form_id': 'stable_test_form',
                                'form_path': 'form#stable_test_form',
                            }
                        }
                    ],
                    'locator_scope': {
                        'form_id': 'stable_test_form',
                    }
                }
            ],
        }

        self.page.evaluate("""() => {
            const f = document.querySelector('input[name="named_a_field"]');
            if (f) f.remove();
        }""")

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['skipped'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertEqual(report['summary']['failed'], 0)

        survivor_val = self.page.locator('#idless-survivor-container input').input_value()
        self.assertEqual(survivor_val, 'survivor_init')
        events = self.page.evaluate("() => window.__survivorEvents")
        self.assertEqual(events, [])

    def test_combobox_dynamic_options_reorder_on_input_never_clicks_master(self):
        # Item 3: Test [Bachelor,Master] -> [Master,Bachelor] oninput, assert Master click 0 / value never masters, correct Bachelor selected
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'dyn-reorder-container';
            container.innerHTML = `
                <div class="select__container" id="dyn-reorder-widget">
                    <input id="dyn-search-input" role="combobox" aria-controls="dyn-reorder-menu">
                    <input type="hidden" name="dyn_degree" id="dyn-hidden" value="initial">
                    <div class="select__single-value" id="dyn-sv"></div>
                    <div class="select__menu" id="dyn-reorder-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="bachelor" id="opt-dyn-b">Bachelor</div>
                        <div class="select__option" role="option" data-value="master" id="opt-dyn-m">Master</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);

            window.__masterClicked = false;
            window.__bachelorClicked = false;

            const inp = document.getElementById('dyn-search-input');
            const menu = document.getElementById('dyn-reorder-menu');
            const optB = document.getElementById('opt-dyn-b');
            const optM = document.getElementById('opt-dyn-m');

            inp.addEventListener('click', () => { menu.style.display = 'block'; });

            optM.addEventListener('click', () => {
                window.__masterClicked = true;
                document.getElementById('dyn-hidden').value = 'master';
                document.getElementById('dyn-sv').innerText = 'Master';
            });
            optB.addEventListener('click', () => {
                window.__bachelorClicked = true;
                document.getElementById('dyn-hidden').value = 'bachelor';
                document.getElementById('dyn-sv').innerText = 'Bachelor';
            });

            inp.addEventListener('input', () => {
                menu.style.display = 'block';
                menu.appendChild(optM);
                menu.appendChild(optB);
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-dyn-reorder',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_dyn_reorder',
                    'text': 'Degree',
                    'input_type': 'combobox',
                    'answer': 'Bachelor',
                    'selected_option': {'label': 'Bachelor', 'value': 'bachelor', 'id': 'opt-dyn-b'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'dyn-search-input'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['filled'], 1)
        self.assertEqual(report['summary']['failed'], 0)

        master_clicked = self.page.evaluate("() => window.__masterClicked")
        bachelor_clicked = self.page.evaluate("() => window.__bachelorClicked")
        self.assertFalse(master_clicked, "Master was clicked at index 0 despite Bachelor being intended!")
        self.assertTrue(bachelor_clicked, "Bachelor was not clicked!")
        self.assertEqual(self.page.locator('#dyn-hidden').input_value(), 'bachelor')
        self.assertEqual(self.page.locator('#dyn-sv').inner_text(), 'Bachelor')

    def test_candidate_schema_valid_first_invalid_second_rejects_both_top_and_metadata(self):
        # Item 4: candidate schema runtime contract for kind/by; reject unknown, require non-empty string payload by-specific.
        from job_applier.filling.engine import validate_answers_plan
        from unittest.mock import patch

        self.assertIn("missing 'by'/'kind'", validate_answers_plan({'answers': [{'text': 'T', 'locator_candidates': [{}]}]}))
        self.assertIn("unsupported locator kind 'unknown_kind'", validate_answers_plan({'answers': [{'text': 'T', 'locator_candidates': [{'by': 'unknown_kind', 'value': 'v'}]}]}))
        self.assertIn("'value' must be a non-empty string", validate_answers_plan({'answers': [{'text': 'T', 'locator_candidates': [{'by': 'id'}]}]}))
        self.assertIn("'value' must be a non-empty string", validate_answers_plan({'answers': [{'text': 'T', 'locator_candidates': [{'by': 'id', 'value': ''}]}]}))
        self.assertIn("'value' must be a non-empty string", validate_answers_plan({'answers': [{'text': 'T', 'locator_candidates': [{'by': 'name', 'value': '   '}]}]}))
        self.assertIn("'role' must be a non-empty string", validate_answers_plan({'answers': [{'text': 'T', 'locator_candidates': [{'by': 'role'}]}]}))
        self.assertIn("'role' must be a non-empty string", validate_answers_plan({'answers': [{'text': 'T', 'locator_candidates': [{'by': 'role', 'role': ''}]}]}))
        self.assertIn("requires a non-empty string payload in 'value' or 'selector'", validate_answers_plan({'answers': [{'text': 'T', 'locator_candidates': [{'by': 'css'}]}]}))

        meta_valid_first_invalid_second = {
            'answers': [
                {
                    'text': 'Question 1',
                    'control_metadata': [
                        {
                            'locator_candidates': [
                                {'by': 'id', 'value': 'valid_first'},
                                {'by': 'role', 'role': ''},
                            ]
                        }
                    ]
                }
            ]
        }
        err_meta = validate_answers_plan(meta_valid_first_invalid_second)
        self.assertIsNotNone(err_meta)
        self.assertIn("control_metadata[0]['locator_candidates'][1] 'role' must be a non-empty string", err_meta)

        with tempfile.TemporaryDirectory() as td:
            plan_file = Path(td) / 'plan_meta_invalid.json'
            plan_file.write_text(json.dumps(meta_valid_first_invalid_second), encoding='utf-8')
            out_dir = Path(td) / 'cli_out'

            import job_applier.filling.__main__ as fill_cli
            import io
            import contextlib
            with patch('job_applier.filling.__main__.sync_playwright', create=True) as mock_pw:
                with contextlib.redirect_stdout(io.StringIO()):
                    ret = fill_cli.main(['http://127.0.0.1:9999/dummy.html', '--answers', str(plan_file), '--out', str(out_dir)])
                self.assertEqual(ret, 1)
                mock_pw.assert_not_called()
                self.assertFalse((out_dir / 'fill_report.json').exists())

    def test_select_synchronous_focus_reorder_yes_no_to_no_yes_selects_yes_and_never_emits_no(self):
        # P1-3: Native SELECT after focus handler reorders options captured numeric index is invalid.
        # Resolve intended unique actual value+label after focus and immediately before selection.
        # Choose by value rather than index if unique and verify intended enabled live before action.
        # Never click No for Yes. Test synchronous focus reorder YesNo -> NoYes and events actual selected values:
        # no 'no' ever selected/emitted.
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'reorder-select-container';
            container.innerHTML = `
                <label for="work_auth_reorder">Work Authorization</label>
                <select id="work_auth_reorder" name="work_auth">
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                </select>
            `;
            document.body.appendChild(container);

            window.__reorderSelectEvents = [];
            const sel = document.getElementById('work_auth_reorder');
            sel.addEventListener('focus', () => {
                // Synchronously reorder options: Yes/No -> No/Yes
                sel.innerHTML = '<option value="no">No</option><option value="yes">Yes</option>';
            });
            ['input', 'change'].forEach(evt => {
                sel.addEventListener(evt, () => {
                    window.__reorderSelectEvents.push({
                        event: evt,
                        value: sel.value,
                        selectedIndex: sel.selectedIndex
                    });
                });
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-reorder-select',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_work_auth_reorder',
                    'text': 'Work Authorization',
                    'input_type': 'select',
                    'answer': 'Yes',
                    'selected_option': {'label': 'Yes', 'value': 'yes'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'work_auth_reorder'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 0)
        self.assertEqual(report['summary']['filled'], 1)

        # Verified live DOM value
        sel_val = self.page.locator('#work_auth_reorder').input_value()
        self.assertEqual(sel_val, 'yes')

        # Events emitted: input and change must both have value 'yes', never 'no'
        events = self.page.evaluate("() => window.__reorderSelectEvents")
        self.assertGreater(len(events), 0)
        for ev in events:
            self.assertEqual(ev['value'], 'yes', f"Found unexpected option value in emitted event: {ev}")
            self.assertNotEqual(ev['value'], 'no', "Emitted event had 'no' selected")

    def test_combobox_filtering_removes_value_attribute_rejects_before_click_with_zero_clicks_and_hidden_unchanged(self):
        # P2-5: Final revalidation missing value None must mismatch expected non-empty, not exempt.
        # Filtering removes value attribute keeps ID + label before click:
        # wrong option click is 0 and hidden input unchanged.
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'filter-remove-val-container';
            container.innerHTML = `
                <div class="select__container" id="filter-val-widget">
                    <input id="filter-val-search" role="combobox" aria-controls="filter-val-menu">
                    <input type="hidden" name="country_filter" id="filter-val-hidden" value="initial_country">
                    <div class="select__menu" id="filter-val-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="us" id="opt-filter-us">United States</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);

            window.__filterValOptionClicks = 0;
            const opt = document.getElementById('opt-filter-us');
            opt.addEventListener('click', () => { window.__filterValOptionClicks++; });

            const inp = document.getElementById('filter-val-search');
            // When search input is typed/input into, dynamic filtering removes value/data-value attribute
            // but keeps id and label intact
            inp.addEventListener('input', () => {
                opt.removeAttribute('data-value');
                opt.removeAttribute('value');
            });
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-filter-val',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_filter_val',
                    'text': 'Country',
                    'input_type': 'combobox',
                    'answer': 'United States',
                    'selected_option': {'id': 'opt-filter-us', 'label': 'United States', 'value': 'us'},
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'filter-val-search'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        err = report['fields'][0].get('error', '')
        self.assertTrue(
            "missing value attribute" in err.lower() or "mismatch" in err.lower(),
            f"Expected value mismatch/missing error, got: {err}"
        )

        # Zero clicks on option
        clicks = self.page.evaluate("() => window.__filterValOptionClicks")
        self.assertEqual(clicks, 0)

        # Hidden input remains unchanged
        hidden_val = self.page.locator('#filter-val-hidden').input_value()
        self.assertEqual(hidden_val, 'initial_country')

    def test_effective_candidate_kind_empty_by_or_kind_all_4_cases(self):
        # P2-4: effective candidate kind empty by or kind None .strip crash53:
        # pickkind with explicit None handling, reject empty whitespace before strip;
        # both supplied conflict handling preserved.
        # All 4 cases (valid first, malformed second):
        # 1. Top-level locator_candidates with 'by'
        # 2. Top-level locator_candidates with 'kind'
        # 3. control_metadata locator_candidates with 'by'
        # 4. control_metadata locator_candidates with 'kind'
        from job_applier.filling.engine import validate_answers_plan
        from unittest.mock import patch
        import job_applier.filling.__main__ as fill_cli

        cases = [
            (
                "top-level by",
                {
                    'answers': [{
                        'text': 'Field 1',
                        'locator_candidates': [
                            {'by': 'id', 'value': 'field_1'},
                            {'by': '', 'value': 'malformed'},
                        ]
                    }]
                },
                "locator_candidates[1] locator kind must be a non-empty string"
            ),
            (
                "top-level kind",
                {
                    'answers': [{
                        'text': 'Field 1',
                        'locator_candidates': [
                            {'kind': 'id', 'value': 'field_1'},
                            {'kind': '   ', 'value': 'malformed'},
                        ]
                    }]
                },
                "locator_candidates[1] locator kind must be a non-empty string"
            ),
            (
                "metadata by",
                {
                    'answers': [{
                        'text': 'Field 1',
                        'control_metadata': [{
                            'id': 'c1',
                            'locator_candidates': [
                                {'by': 'id', 'value': 'field_1'},
                                {'by': '', 'value': 'malformed'},
                            ]
                        }]
                    }]
                },
                "control_metadata[0]['locator_candidates'][1] locator kind must be a non-empty string"
            ),
            (
                "metadata kind",
                {
                    'answers': [{
                        'text': 'Field 1',
                        'control_metadata': [{
                            'id': 'c1',
                            'locator_candidates': [
                                {'kind': 'id', 'value': 'field_1'},
                                {'kind': '   ', 'value': 'malformed'},
                            ]
                        }]
                    }]
                },
                "control_metadata[0]['locator_candidates'][1] locator kind must be a non-empty string"
            ),
        ]

        for case_name, plan, exp_err in cases:
            # 1. Validator returns error string, does NOT throw
            err = validate_answers_plan(plan)
            self.assertIsNotNone(err, f"Case '{case_name}' expected error string, got None")
            self.assertIn(exp_err, err, f"Case '{case_name}' error mismatch")

            # 2. CLI structured JSON 1, browser mock not called, no artifacts
            with tempfile.TemporaryDirectory() as td:
                plan_file = Path(td) / 'plan.json'
                plan_file.write_text(json.dumps(plan), encoding='utf-8')
                out_dir = Path(td) / 'cli_out'

                import io
                import contextlib
                buf = io.StringIO()
                with patch('job_applier.filling.__main__.sync_playwright', create=True) as mock_pw:
                    with contextlib.redirect_stdout(buf):
                        exit_code = fill_cli.main(['http://127.0.0.1:9999/dummy.html', '--answers', str(plan_file), '--out', str(out_dir)])
                    self.assertEqual(exit_code, 1, f"Case '{case_name}' CLI exit code was {exit_code}")
                    mock_pw.assert_not_called()
                    self.assertFalse((out_dir / 'fill_report.json').exists(), f"Case '{case_name}' created report artifact")
                    self.assertFalse((out_dir / 'screenshot.png').exists(), f"Case '{case_name}' created screenshot artifact")

                    cli_json = json.loads(buf.getvalue())
                    self.assertEqual(cli_json.get('status'), 'error')
                    self.assertIn(exp_err, cli_json.get('error', ''))

    def test_regression_issue1_native_form_null_authoritative_rejects_missing_or_empty_form_attr(self):
        # Issue 1: Native input/radio inside Form A with form="missing" or form="" has el.form == null.
        # Real collect -> resolve -> set form='missing' or form='' -> fill must reject with ownership mismatch,
        # zero events, and live DOM values completely unchanged.
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'issue1-native-form-container';
            container.innerHTML = `
                <form id="form-alpha">
                    <label for="t_alpha">First Name</label>
                    <input type="text" id="t_alpha" name="first_name_alpha" value="init_alpha">
                    <fieldset id="grp_alpha">
                        <legend>Will you require sponsorship?</legend>
                        <label for="r_alpha_yes"><input type="radio" id="r_alpha_yes" name="sponsor_alpha" value="true"> Yes</label>
                        <label for="r_alpha_no"><input type="radio" id="r_alpha_no" name="sponsor_alpha" value="false"> No</label>
                    </fieldset>
                </form>
            `;
            document.body.appendChild(container);

            window.__issue1_t_events = [];
            window.__issue1_r_events = [];
            ['input', 'change'].forEach(evt => {
                document.getElementById('t_alpha').addEventListener(evt, () => window.__issue1_t_events.push(evt));
                document.getElementById('r_alpha_no').addEventListener(evt, () => window.__issue1_r_events.push(evt));
            });
        }""")

        # 1. Real collect
        extraction = collect(self.page, probe_options=False)
        q_text = next(q for q in extraction['questions'] if q['text'] == 'First Name' and any(c['id'] for c in q['control_metadata'] if c['dom']['id'] == 't_alpha'))
        q_radio = next(q for q in extraction['questions'] if 'sponsorship' in q['text'].lower() and any(c['id'] for c in q['control_metadata'] if c['dom']['id'] == 'r_alpha_no'))

        self.assertEqual(q_text['control_metadata'][0]['dom']['form_id'], 'form-alpha')
        self.assertEqual(q_radio['control_metadata'][0]['dom']['form_id'], 'form-alpha')

        # 2. Resolve
        bank = {
            'questions': [
                {'fact': 'contact.first_name', 'input_types': ['text'], 'aliases': ['First Name']},
                {'fact': 'work.us_sponsorship_now_or_future', 'input_types': ['single_choice', 'radio'], 'aliases': ['Will you require sponsorship?']},
            ],
            'facts': {
                'contact.first_name': {'value': 'Grace', 'confirmed': True, 'source': 'vault'},
                'work.us_sponsorship_now_or_future': {'value': False, 'confirmed': True, 'source': 'vault'},
            }
        }
        class NullSemanticMatcher:
            threshold = 0.82
            margin = 0.06
            def rank(self, question, bank):
                return []
        from job_applier.resolution.engine import resolve_cascade
        resolved = resolve_cascade([q_text, q_radio], bank, NullSemanticMatcher())['results']
        ready_answers = [a for a in resolved if a['status'] == 'ready']
        self.assertEqual(len(ready_answers), 2)

        # 3. Dynamic DOM mutation before filling: set form='missing' on text input and form='' on radio input while physically inside form-alpha!
        self.page.evaluate("""() => {
            document.getElementById('t_alpha').setAttribute('form', 'missing');
            document.getElementById('r_alpha_no').setAttribute('form', '');
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': extraction['snapshot_id'],
            'scope': 'job_application',
            'answers': ready_answers,
        }

        # 4. Fill form: MUST reject both controls because live el.form is null (authoritative, no closest fallback)
        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['filled'], 0)
        self.assertEqual(report['summary']['failed'], 2)

        t_err = next(f for f in report['fields'] if f['text'] == 'First Name')['error']
        r_err = next(f for f in report['fields'] if 'sponsorship' in f['text'].lower())['error']
        self.assertTrue('form owner missing' in t_err.lower() or 'form owner mismatch' in t_err.lower(), f"Unexpected error: {t_err}")
        self.assertTrue('form owner missing' in r_err.lower() or 'form owner mismatch' in r_err.lower(), f"Unexpected error: {r_err}")

        # Controls must remain completely UNTOUCHED: no events and initial values preserved
        self.assertEqual(self.page.locator('#t_alpha').input_value(), 'init_alpha')
        self.assertFalse(self.page.locator('#r_alpha_no').is_checked())
        self.assertEqual(self.page.evaluate("() => window.__issue1_t_events"), [])
        self.assertEqual(self.page.evaluate("() => window.__issue1_r_events"), [])

    def test_regression_issue2_stale_question_meaning_rejects_label_change_and_allows_normalized_whitespace(self):
        # Issue 2: Same stable ID/name/form but changed label/aria-label/referenced label
        # Must compare live accessible label via DOM helper to captured label.
        # FirstName -> LastName must reject before mutation, zero events, unfilled.
        # Wording same with whitespace / trailing asterisk must pass conservative normalization.
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'issue2-stale-meaning-container';
            container.innerHTML = `
                <form id="form-meaning">
                    <label id="lbl-fn" for="input-fn">First Name</label>
                    <input type="text" id="input-fn" name="first_name" value="init_fn">

                    <label id="lbl-ws" for="input-ws">Email Address</label>
                    <input type="email" id="input-ws" name="email" value="init_email">
                </form>
            `;
            document.body.appendChild(container);

            window.__issue2_fn_events = [];
            ['input', 'change'].forEach(evt => {
                document.getElementById('input-fn').addEventListener(evt, () => window.__issue2_fn_events.push(evt));
            });
        }""")

        extraction = collect(self.page, probe_options=False)
        q_fn = next(q for q in extraction['questions'] if q['text'] == 'First Name' and any(c['id'] for c in q['control_metadata'] if c['dom']['id'] == 'input-fn'))
        q_ws = next(q for q in extraction['questions'] if q['text'] == 'Email Address' and any(c['id'] for c in q['control_metadata'] if c['dom']['id'] == 'input-ws'))

        bank = {
            'questions': [
                {'fact': 'contact.first_name', 'input_types': ['text'], 'aliases': ['First Name']},
                {'fact': 'contact.email', 'input_types': ['text', 'email'], 'aliases': ['Email Address']},
            ],
            'facts': {
                'contact.first_name': {'value': 'Grace', 'confirmed': True, 'source': 'vault'},
                'contact.email': {'value': 'grace@example.com', 'confirmed': True, 'source': 'vault'},
            }
        }
        class NullSemanticMatcher:
            threshold = 0.82
            margin = 0.06
            def rank(self, question, bank):
                return []
        from job_applier.resolution.engine import resolve_cascade
        resolved = resolve_cascade([q_fn, q_ws], bank, NullSemanticMatcher())['results']

        # Mutate DOM labels:
        # 1) #input-fn label is changed to "Last Name"
        # 2) #input-ws label is changed to "Email Address  \n *" (whitespace and asterisk variation)
        self.page.evaluate("""() => {
            document.getElementById('lbl-fn').textContent = 'Last Name';
            document.getElementById('lbl-ws').textContent = 'Email Address  \\n *';
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': extraction['snapshot_id'],
            'scope': 'job_application',
            'answers': resolved,
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        # input-fn must be rejected (stale meaning)
        fn_field = next(f for f in report['fields'] if f['text'] == 'First Name')
        self.assertEqual(fn_field['status'], 'failed')
        self.assertTrue('semantic' in fn_field['error'].lower() or 'label' in fn_field['error'].lower(), f"Unexpected error: {fn_field['error']}")
        self.assertEqual(self.page.locator('#input-fn').input_value(), 'init_fn')
        self.assertEqual(self.page.evaluate("() => window.__issue2_fn_events"), [])

        # input-ws must succeed because conservative normalization handles whitespace and required asterisk
        ws_field = next(f for f in report['fields'] if f['text'] == 'Email Address')
        self.assertEqual(ws_field['status'], 'filled')
        self.assertEqual(self.page.locator('#input-ws').input_value(), 'grace@example.com')

    def test_regression_issue3_combobox_label_only_missing_or_changed_live_value_rejects_before_click(self):
        # Issue 3: Label-only combobox plan omits selected_option.value.
        # Preflight option has data-value="bachelor".
        # On input, JS removes the data-value attribute OR changes it to "phd", keeping id and label intact.
        # Must compare live value against originally observed preflight chosen_opt.value ALWAYS.
        # Rejection must happen BEFORE click: clicks == 0, hidden input unchanged.
        self.page.evaluate("""() => {
            const container = document.createElement('div');
            container.id = 'issue3-labelonly-combo-container';
            container.innerHTML = `
                <div class="select__container" id="issue3-widget">
                    <label for="issue3-search">Degree</label>
                    <input id="issue3-search" role="combobox" aria-controls="issue3-menu">
                    <input type="hidden" name="degree_hidden" id="issue3-hidden" value="initial_hidden">
                    <div class="select__menu" id="issue3-menu" style="display:none;" role="listbox">
                        <div class="select__option" role="option" data-value="bachelor" id="opt-deg-b">Bachelor's Degree</div>
                        <div class="select__option" role="option" data-value="master" id="opt-deg-m">Master's Degree</div>
                    </div>
                </div>
            `;
            document.body.appendChild(container);

            window.__issue3_opt_clicks = 0;
            const optB = document.getElementById('opt-deg-b');
            optB.addEventListener('click', () => {
                window.__issue3_opt_clicks++;
                document.getElementById('issue3-hidden').value = optB.getAttribute('data-value') || 'empty';
            });

            const inp = document.getElementById('issue3-search');
            const menu = document.getElementById('issue3-menu');
            inp.addEventListener('click', () => { menu.style.display = 'block'; });
            // When search input receives input, remove data-value attribute but keep id and label!
            inp.addEventListener('input', () => {
                menu.style.display = 'block';
                optB.removeAttribute('data-value');
            });
        }""")

        # Label-only plan: selected_option.value is omitted entirely!
        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-issue3-labelonly',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_deg_labelonly',
                    'text': 'Degree',
                    'input_type': 'combobox',
                    'answer': "Bachelor's Degree",
                    'selected_option': {
                        'id': 'opt-deg-b',
                        'label': "Bachelor's Degree",
                        # NO 'value' key!
                    },
                    'status': 'ready',
                    'locator_candidates': [{'by': 'id', 'value': 'issue3-search'}],
                }
            ],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)

        err = report['fields'][0]['error']
        self.assertTrue('missing value attribute' in err.lower() or 'value mismatch' in err.lower(), f"Unexpected error: {err}")

        # Rejection happened BEFORE click! Zero clicks and hidden input unchanged!
        clicks = self.page.evaluate("() => window.__issue3_opt_clicks")
        self.assertEqual(clicks, 0, "Option was clicked despite missing/changed live value!")
        self.assertEqual(self.page.locator('#issue3-hidden').input_value(), 'initial_hidden')


if __name__ == '__main__':
    unittest.main()
