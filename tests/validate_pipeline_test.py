"""Integration tests for end-to-end pipeline validator (job_applier.validate_pipeline).

Tests validation against local synthetic fixture tests/fixtures/greenhouse.html:
- Step 1: fetched (questions extracted and valid schema)
- Step 2: answered (questions resolved and valid schema)
- Step 3: filled (form fields filled, DOM values verified, submit blocked, screenshot captured)
- Step 4: validation summary output and artifacts
"""
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from job_applier.validate_pipeline import main, validate_pipeline  # noqa: E402


class ValidatePipelineTests(unittest.TestCase):
    def setUp(self):
        self.fixture_path = ROOT / 'tests/fixtures/greenhouse.html'
        self.fixture_url = self.fixture_path.as_uri()
        self.temp_dir = tempfile.mkdtemp(prefix='validate-pipeline-test-')

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_validate_pipeline_greenhouse_e2e(self):
        """Test full pipeline validation against greenhouse.html synthetic fixture."""
        run_dir = Path(self.temp_dir) / 'run_e2e'
        result = validate_pipeline(self.fixture_url, run_dir, overwrite=True)

        # Overall status
        self.assertEqual(result['status'], 'SUCCESS')

        # Step 1: Fetched
        self.assertTrue(result['fetched'])
        self.assertGreater(result['question_count'], 0)
        self.assertEqual(result['steps']['fetch']['status'], 'success')
        self.assertEqual(result['steps']['fetch']['schema'], 'job-applier.form-snapshot.v1')

        # Step 2: Answered
        self.assertTrue(result['answered'])
        self.assertGreater(result['ready_count'], 0)
        self.assertEqual(result['steps']['answer']['status'], 'success')
        self.assertEqual(result['steps']['answer']['schema'], 'job-applier.answer-plan.v1')

        # Step 3: Filled
        self.assertTrue(result['filled'])
        self.assertGreater(result['filled_count'], 0)
        self.assertEqual(result['filled_count'], result['verified_count'])
        self.assertTrue(result['submit_blocked'])
        self.assertEqual(result['steps']['fill']['status'], 'success')
        self.assertEqual(result['steps']['fill']['schema'], 'job-applier.fill-report.v1')

        # Screenshot generation
        screenshot_path = result['screenshot']
        self.assertIsNotNone(screenshot_path)
        self.assertTrue(Path(screenshot_path).is_file())
        self.assertGreater(Path(screenshot_path).stat().st_size, 0)

        # Artifacts on disk
        self.assertTrue((run_dir / 'questions.json').is_file())
        self.assertTrue((run_dir / 'answers.json').is_file())
        self.assertTrue((run_dir / 'fill_report.json').is_file())
        self.assertTrue((run_dir / 'screenshot.png').is_file())
        self.assertTrue((run_dir / 'validation_summary.json').is_file())

        # Verify summary on disk matches returned dict
        with open(run_dir / 'validation_summary.json', 'r', encoding='utf-8') as f:
            disk_summary = json.load(f)
        self.assertEqual(disk_summary['status'], 'SUCCESS')
        self.assertEqual(disk_summary['fetched'], True)
        self.assertEqual(disk_summary['answered'], True)
        self.assertEqual(disk_summary['filled'], True)
        self.assertEqual(disk_summary['filled_count'], result['filled_count'])

    def test_validate_pipeline_with_custom_bank(self):
        """Test pipeline validation with custom bank providing specific facts."""
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

        self.assertEqual(result['status'], 'SUCCESS')
        self.assertTrue(result['fetched'])
        self.assertTrue(result['answered'])
        self.assertTrue(result['filled'])
        self.assertGreaterEqual(result['filled_count'], 6)
        self.assertEqual(result['filled_count'], result['verified_count'])
        self.assertTrue(result['submit_blocked'])

        # Verify fill_report recorded specific filled values
        with open(run_dir / 'fill_report.json', 'r', encoding='utf-8') as f:
            report = json.load(f)
        filled_fields = {f['text']: f.get('verified_value') for f in report['fields'] if f.get('status') == 'filled'}
        self.assertEqual(filled_fields.get('First Name'), 'Marie')
        self.assertEqual(filled_fields.get('Last Name'), 'Curie')
        self.assertEqual(filled_fields.get('Email'), 'marie.curie@example.com')

    def test_validate_pipeline_cli_invocation(self):
        """Test CLI main() execution returning 0 and emitting structured JSON summary."""
        run_dir = Path(self.temp_dir) / 'run_cli'
        cli_args = [self.fixture_url, '--out', str(run_dir), '--overwrite']

        captured_stdout = io.StringIO()
        original_stdout = sys.stdout
        try:
            sys.stdout = captured_stdout
            exit_code = main(cli_args)
        finally:
            sys.stdout = original_stdout

        self.assertEqual(exit_code, 0)
        output_str = captured_stdout.getvalue().strip()
        parsed = json.loads(output_str)

        self.assertEqual(parsed['status'], 'SUCCESS')
        self.assertTrue(parsed['fetched'])
        self.assertTrue(parsed['answered'])
        self.assertTrue(parsed['filled'])
        self.assertGreater(parsed['question_count'], 0)
        self.assertGreater(parsed['filled_count'], 0)
        self.assertIsNotNone(parsed['screenshot'])

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
