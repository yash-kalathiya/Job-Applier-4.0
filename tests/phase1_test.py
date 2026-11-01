"""Browser regression checks with synthetic facts; no employer submissions."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from job_applier.extraction.engine import collect, install_observation_guard, accessibility
from job_applier.extraction.report import report_html


class Phase1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(chromium_sandbox=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context(service_workers='block')
        self.blocked = install_observation_guard(self.context)
        self.page = self.context.new_page()
        self.page.goto((ROOT / 'tests/fixtures/phase1.html').as_uri())

    def tearDown(self):
        self.context.close()

    def capture(self, **kwargs):
        return collect(self.page, **kwargs)

    def test_combined_evidence_and_label_conflict(self):
        data = self.capture(probe_options=False)
        email = next(c for c in data['controls'] if c['evidence']['dom']['id'] == 'email')
        self.assertEqual(email['evidence']['accessibility']['name'], 'Email *')
        self.assertEqual(email['evidence']['dom']['type'], 'email')
        self.assertTrue(email['required'])
        conflict = next(c for c in data['controls'] if c['evidence']['dom']['id'] == 'conflict')
        self.assertIn('label_conflict', conflict['warnings'])
        self.assertEqual(conflict['evidence']['accessibility']['name'], 'Preferred work location')
        self.assertEqual(data['summary']['llm_tokens'], 0)
        self.assertTrue(any(i['links'] and i['links'][0]['url'] == 'https://example.invalid/questionnaire' for i in data['instructions']))

    def test_grouping_repeated_labels_frames_and_shadow(self):
        data = self.capture(probe_options=False)
        relocation = next(q for q in data['questions'] if 'relocate' in q['text'])
        self.assertEqual(relocation['input_type'], 'single_choice')
        self.assertEqual([o['label'] for o in relocation['options']['items']], ['Yes', 'No'])
        languages = next(q for q in data['questions'] if q['text'] == 'Languages used')
        self.assertEqual(len(languages['control_ids']), 2)
        dates = [q for q in data['questions'] if q['text'] == 'Start date']
        self.assertEqual(len(dates), 2)
        self.assertNotEqual(dates[0]['id'], dates[1]['id'])
        self.assertNotEqual(dates[0]['section'], dates[1]['section'])
        self.assertTrue(any(q['text'] == 'Portfolio URL' and q['frame_id'] != 'frame-0' for q in data['questions']))
        self.assertTrue(any(q['text'] == 'GitHub URL' for q in data['questions']))

    def test_hidden_file_constraints_and_conditional_refresh(self):
        first = self.capture(probe_options=False)
        ids = {c['evidence']['dom']['id'] for c in first['controls']}
        self.assertIn('resume', ids)
        self.assertNotIn('conditional', ids)
        self.assertNotIn('validation-proxy', ids)
        cover = next(q for q in first['questions'] if q['text'] == 'Cover letter')
        self.assertTrue(cover['required'])
        gpa = next(c for c in first['controls'] if c['evidence']['dom']['id'] == 'gpa')
        self.assertEqual(gpa['evidence']['dom']['constraints']['max'], '4')
        self.assertEqual(gpa['evidence']['dom']['help'], 'Use a 4 point scale.')
        self.page.locator('#degree').select_option('ms')  # Synthetic test setup, not extractor behavior.
        second = self.capture(probe_options=False)
        self.assertTrue(any(c['evidence']['dom']['id'] == 'conditional' for c in second['controls']))
        self.assertNotEqual(first['snapshot_id'], second['snapshot_id'])

    def test_option_probe_preserves_value_and_reports_incomplete(self):
        data = self.capture()
        visa = next(q for q in data['questions'] if q['text'] == 'Visa status')
        self.assertEqual([o['label'] for o in visa['options']['items']], ['Student visa', 'Other'])
        self.assertFalse(visa['options']['complete'])
        self.assertTrue(visa['options']['value_unchanged'])
        self.assertEqual(self.page.locator('#visa').input_value(), '')
        self.assertTrue(self.page.locator('#visa-options').is_hidden())
        degree = next(q for q in data['questions'] if q['text'] == 'Degree')
        self.assertTrue(degree['options']['complete'])
        self.assertEqual(len(degree['options']['items']), 4)
        self.assertEqual(self.page.locator('#degree').input_value(), '')

    def test_submit_and_network_guard(self):
        self.page.get_by_role('button', name='Submit application').click()
        self.assertEqual(self.page.evaluate('window.submissions'), 0)
        self.assertTrue(self.page.evaluate("() => {try{document.querySelector('form').submit();return false}catch{return true}}"))
        self.page.evaluate("fetch('https://example.invalid/submit',{method:'POST',body:'synthetic'}).catch(()=>{})")
        self.page.wait_for_timeout(150)
        self.assertTrue(any(r['method'] == 'POST' for r in self.blocked))

    def test_report_is_escaped_searchable_and_responsive(self):
        data = self.capture(probe_options=False)
        data['questions'][0]['text'] = '<script>window.pwned=true</script>'
        html = report_html(data)
        self.assertNotIn('<script>window.pwned', html)
        self.page.set_content(html)
        self.assertIsNone(self.page.evaluate('window.pwned'))
        self.page.get_by_role('searchbox').fill('GPA')
        self.assertEqual(self.page.locator('.question:visible').count(), 1)
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))

    def test_parser_preserves_escaped_names(self):
        parsed = accessibility('- textbox "A \\"quoted\\" question" [disabled]')
        self.assertEqual(parsed['name'], 'A "quoted" question')
        self.assertIn('disabled', parsed['states'])


if __name__ == '__main__':
    unittest.main()
