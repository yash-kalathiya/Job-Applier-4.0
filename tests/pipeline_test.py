"""Integration pipeline tests: extract -> resolve -> fill compatibility.

Verifies end-to-end form lifecycle:
1. Extraction (Phase 1 collect) captures controls, frame descriptors, and form ownership.
2. Resolution (Phase 2 exact/cascade) matches facts while retaining metadata.
3. Filling (Phase 3 fill_form) safely fills intended targets while preserving duplicates.
No manually injected targeting; synthetic fixtures only; no external network requests.
"""
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlparse
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright
from job_applier.extraction.engine import collect
from job_applier.resolution.engine import resolve_cascade
from job_applier.filling.engine import fill_form, install_observation_guard


class MutationCollectorHandler(http.server.BaseHTTPRequestHandler):
    runs_lock = threading.Lock()
    active_run_id = 'run-initial'
    runs = {}
    recorded_mutations = []
    latest_control_states = {}
    server_fault_mode = None

    @classmethod
    def reset_collector(cls):
        with cls.runs_lock:
            cls.recorded_mutations = []
            cls.latest_control_states = {}
            cls.server_fault_mode = None
            cls.active_run_id = cls.start_new_run()

    @classmethod
    def start_new_run(cls, run_id=None, expected_frames=('main', 'sub-frame')):
        with cls.runs_lock:
            if not run_id:
                run_id = f"run-{uuid.uuid4().hex[:8]}"
            cls.active_run_id = run_id
            cls.runs[run_id] = {
                'expected_frames': set(expected_frames),
                'terminal_frames': {},
                'latest_states': {},
                'completed_event': threading.Event(),
                'locked_final_state': None,
                'generation': 0,
            }
            cls.recorded_mutations = []
            cls.latest_control_states = {}
            return run_id

    @classmethod
    def wait_for_terminal_completion(cls, run_id, timeout=10.0):
        with cls.runs_lock:
            if run_id not in cls.runs:
                raise ValueError(f"Unknown run ID {run_id}")
            run_info = cls.runs[run_id]
        ok = run_info['completed_event'].wait(timeout)
        if not ok:
            raise TimeoutError(f"Timed out waiting for terminal completion of run {run_id} across frames {run_info['expected_frames']}")
        with cls.runs_lock:
            return dict(run_info['locked_final_state'])

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/record':
            qs = parse_qs(parsed.query)
            field = qs.get('field', [''])[0]
            val = qs.get('val', [''])[0]
            frame = qs.get('frame', ['main'])[0]
            with MutationCollectorHandler.runs_lock:
                MutationCollectorHandler.recorded_mutations.append({
                    'field': field,
                    'val': val,
                    'frame': frame,
                })
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"recorded"}')
            return

        if parsed.path == '/state':
            qs = parse_qs(parsed.query)
            run_id = qs.get('run_id', [''])[0]
            is_terminal = qs.get('terminal', ['false'])[0].lower() == 'true'
            data_str = qs.get('data', [''])[0]
            if data_str:
                try:
                    state_data = json.loads(data_str)
                    frame_name = state_data.get('frame', 'main')
                    controls = state_data.get('controls', [])
                    with MutationCollectorHandler.runs_lock:
                        target_run_id = run_id or MutationCollectorHandler.active_run_id
                        if target_run_id and target_run_id in MutationCollectorHandler.runs:
                            run = MutationCollectorHandler.runs[target_run_id]
                            for ctrl in controls:
                                ctrl_key = (
                                    frame_name,
                                    ctrl.get('owner_id', ''),
                                    ctrl.get('id') or ctrl.get('name', ''),
                                )
                                run['latest_states'][ctrl_key] = ctrl
                                if target_run_id == MutationCollectorHandler.active_run_id:
                                    MutationCollectorHandler.latest_control_states[ctrl_key] = ctrl
                            if is_terminal:
                                run['terminal_frames'][frame_name] = controls
                                if set(run['expected_frames']).issubset(set(run['terminal_frames'].keys())):
                                    if run['locked_final_state'] is None:
                                        run['generation'] += 1
                                        stable_copy = {}
                                        for f_name, f_ctrls in run['terminal_frames'].items():
                                            for c in f_ctrls:
                                                k = (f_name, c.get('owner_id', ''), c.get('id') or c.get('name', ''))
                                                stable_copy[k] = dict(c)
                                        run['locked_final_state'] = stable_copy
                                        if target_run_id == MutationCollectorHandler.active_run_id:
                                            MutationCollectorHandler.latest_control_states = stable_copy
                                        run['completed_event'].set()
                except Exception:
                    pass
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"state_received"}')
            return

        if parsed.path in ('/', '/pipeline.html'):
            fixture_file = ROOT / 'tests/fixtures/pipeline.html'
            content = fixture_file.read_text(encoding='utf-8')

            with MutationCollectorHandler.runs_lock:
                active_run = MutationCollectorHandler.active_run_id

            # Script to instrument a document/frame: listens to real input/change events and collects full final state via GET
            instrument = f"""
            <script>
            (function() {{
                window.__RUN_ID__ = {json.dumps(active_run)};
                function _reportMutation(name, val) {{
                    try {{
                        const fr = (window.frameElement && window.frameElement.id) ? window.frameElement.id : (window.name || 'main');
                        fetch('/record?field=' + encodeURIComponent(name) + '&val=' + encodeURIComponent(val) + '&frame=' + encodeURIComponent(fr));
                    }} catch(e) {{}}
                }}
                function _sendControlState(isTerminal) {{
                    try {{
                        const fr = (window.frameElement && window.frameElement.id) ? window.frameElement.id : (window.name || 'main');
                        const inputs = Array.from(document.querySelectorAll('input, select, textarea'));
                        const payload = inputs.map(el => {{
                            const isNative = 'form' in el || ['input', 'select', 'textarea', 'button'].includes((el.tagName || '').toLowerCase());
                            const form = isNative ? el.form : el.closest('form');
                            let v = el.value;
                            if (el.type === 'checkbox') {{
                                v = el.checked ? (el.value || 'true') : 'false';
                            }}
                            return {{
                                frame: fr,
                                id: el.id || '',
                                name: el.name || '',
                                owner_id: form ? (form.id || '') : '',
                                value: v,
                                checked: Boolean(el.checked)
                            }};
                        }});
                        const runId = window.__RUN_ID__ || '';
                        const encoded = encodeURIComponent(JSON.stringify({{frame: fr, controls: payload, ts: Date.now()}}));
                        fetch('/state?run_id=' + encodeURIComponent(runId) + '&terminal=' + (isTerminal ? 'true' : 'false') + '&data=' + encoded);
                    }} catch(e) {{}}
                }}

                function _checkTerminalTrigger(e) {{
                    if (e.target && (e.target.id === 'portfolio_ext' || e.target.name === 'portfolio')) {{
                        queueMicrotask(function() {{
                            queueMicrotask(function() {{
                                try {{
                                    var ifr = document.getElementById('sub-frame');
                                    if (ifr && ifr.contentWindow) {{
                                        ifr.contentWindow.postMessage({{ type: 'TRIGGER_TERMINAL_SNAPSHOT', runId: window.__RUN_ID__ }}, '*');
                                        if (ifr.contentWindow.__sendControlState) {{
                                            ifr.contentWindow.__sendControlState(true);
                                        }}
                                    }}
                                }} catch(err) {{}}
                                _sendControlState(true);
                            }});
                        }});
                    }}
                }}

                document.addEventListener('input', function(e) {{
                    if (e.target && (e.target.id || e.target.name)) {{
                        _reportMutation(e.target.id || e.target.name, e.target.value);
                        setTimeout(function() {{ _sendControlState(false); }}, 0);
                        _checkTerminalTrigger(e);
                    }}
                }}, true);
                document.addEventListener('change', function(e) {{
                    if (e.target && (e.target.id || e.target.name)) {{
                        var v = (e.target.type === 'checkbox') ? (e.target.checked ? (e.target.value || 'true') : 'false') : e.target.value;
                        _reportMutation(e.target.id || e.target.name, v);
                        setTimeout(function() {{ _sendControlState(false); }}, 0);
                        _checkTerminalTrigger(e);
                    }}
                }}, true);

                window.addEventListener('message', function(ev) {{
                    if (ev.data && ev.data.type === 'TRIGGER_TERMINAL_SNAPSHOT') {{
                        _sendControlState(true);
                        if (window.parent && window.parent !== window) {{
                            window.parent.postMessage({{ type: 'TERMINAL_SNAPSHOT_ACK', runId: ev.data.runId }}, '*');
                        }}
                    }}
                }});

                window.addEventListener('load', function() {{ _sendControlState(false); }});
                window.__sendControlState = _sendControlState;
                setInterval(function() {{ _sendControlState(false); }}, 80);
            }})();
            </script>
            """

            # Also instrument the child iframe srcdoc so iframe events don't get lost
            if 'srcdoc="' in content:
                # Inject instrument inside srcdoc before </body></html>
                srcdoc_instrument = instrument.replace('"', '&quot;').replace('\n', ' ')
                content = content.replace('</body></html>"', srcdoc_instrument + '</body></html>"')

            # Instrument main document
            if '</body>' in content:
                content = content.replace('</body>', instrument + '</body>')
            else:
                content += instrument

            fault_mode = MutationCollectorHandler.server_fault_mode
            if fault_mode == 'wrong_target_same_frame':
                fault_script = """
                <script>
                (function() {
                    function onLastField(e) {
                        if (e.target && (e.target.id === 'portfolio_ext' || e.target.name === 'portfolio')) {
                            queueMicrotask(function() {
                                var el = document.getElementById('fn2');
                                if (el) {
                                    el.value = 'deliberate_silent_corruption';
                                }
                            });
                        }
                    }
                    document.addEventListener('input', onLastField, true);
                    document.addEventListener('change', onLastField, true);
                })();
                </script>
                """
                content = content.replace('</body>', fault_script + '</body>')
            elif fault_mode == 'wrong_target_child_frame':
                fault_script = """
                <script>
                (function() {
                    function onLastField(e) {
                        if (e.target && (e.target.id === 'portfolio_ext' || e.target.name === 'portfolio')) {
                            queueMicrotask(function() {
                                try {
                                    var ifr = document.getElementById('sub-frame');
                                    var doc = ifr ? (ifr.contentDocument || (ifr.contentWindow && ifr.contentWindow.document)) : null;
                                    if (doc) {
                                        var el = doc.getElementById('frame_fn');
                                        if (el) {
                                            el.value = 'deliberate_child_frame_corruption';
                                            if (ifr.contentWindow && ifr.contentWindow.__sendControlState) {
                                                ifr.contentWindow.__sendControlState();
                                            }
                                        }
                                    }
                                } catch(e) {}
                            });
                        }
                    }
                    document.addEventListener('input', onLastField, true);
                    document.addEventListener('change', onLastField, true);
                })();
                </script>
                """
                content = content.replace('</body>', fault_script + '</body>')
            elif fault_mode == 'fault_both_unchecked':
                fault_script = """
                <script>
                (function() {
                    function onLastField(e) {
                        if (e.target && (e.target.id === 'portfolio_ext' || e.target.name === 'portfolio')) {
                            queueMicrotask(function() {
                                var rNo = document.getElementById('sponsor_no');
                                var rYes = document.getElementById('sponsor_yes');
                                if (rNo) rNo.checked = false;
                                if (rYes) rYes.checked = false;
                            });
                        }
                    }
                    document.addEventListener('input', onLastField, true);
                    document.addEventListener('change', onLastField, true);
                })();
                </script>
                """
                content = content.replace('</body>', fault_script + '</body>')
            elif fault_mode == 'fault_yes_selected':
                fault_script = """
                <script>
                (function() {
                    function onLastField(e) {
                        if (e.target && (e.target.id === 'portfolio_ext' || e.target.name === 'portfolio')) {
                            queueMicrotask(function() {
                                var rNo = document.getElementById('sponsor_no');
                                var rYes = document.getElementById('sponsor_yes');
                                if (rNo) rNo.checked = false;
                                if (rYes) rYes.checked = true;
                            });
                        }
                    }
                    document.addEventListener('input', onLastField, true);
                    document.addEventListener('change', onLastField, true);
                })();
                </script>
                """
                content = content.replace('</body>', fault_script + '</body>')

            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass


def assert_expected_target_states(states):
    """Reusable verifier for the 6 target controls in app-form, including both yes/no radio states."""
    expected_targets = {
        ('main', 'app-form', 'fn1'): 'Grace',
        ('main', 'app-form', 'email1'): 'grace@example.com',
        ('main', 'app-form', 'phone1'): '+15559876543',
        ('main', 'app-form', 'work_auth_sel'): 'yes',
        ('main', 'app-form', 'sponsor_no'): {'value': 'false', 'checked': True},
        ('main', 'app-form', 'sponsor_yes'): {'value': 'true', 'checked': False},
        ('main', 'app-form', 'portfolio_ext'): 'https://grace.example.com',
    }
    for triple, exp in expected_targets.items():
        if triple not in states:
            raise AssertionError(f"Target prerequisite missing state for {triple}")
        actual_ctrl = states[triple]
        if isinstance(exp, dict):
            if 'value' in exp and actual_ctrl.get('value') != exp['value']:
                raise AssertionError(
                    f"Target prerequisite value mismatch for {triple}: expected {exp['value']!r}, got {actual_ctrl.get('value')!r}"
                )
            if 'checked' in exp and actual_ctrl.get('checked') != exp['checked']:
                raise AssertionError(
                    f"Target prerequisite checked mismatch for {triple}: expected {exp['checked']!r}, got {actual_ctrl.get('checked')!r}"
                )
        else:
            actual_val = actual_ctrl.get('value')
            if actual_val != exp:
                raise AssertionError(
                    f"Target prerequisite value mismatch for {triple}: expected {exp!r}, got {actual_val!r}"
                )


def assert_nontarget_states_unmutated(states, allowed_triples):
    """Verify every non-target control across all frames remains untouched."""
    for triple, ctrl in states.items():
        if triple not in allowed_triples:
            actual_val = ctrl.get('value', '')
            actual_checked = ctrl.get('checked', False)
            if actual_val != '' or actual_checked:
                raise AssertionError(
                    f"Oracle detected wrong-target or silent mutation on non-target {triple}: "
                    f"value={actual_val!r}, checked={actual_checked!r}"
                )


def check_mutation_oracle(latest_control_states, expected_mutations, allowed_triples):
    """Verify live control state matches expected values by full triple (frame_id, owner_id, control_id)."""
    # 1. Assert each expected target exists and has exact verified value / checked status FIRST (target prerequisite)
    for triple, exp in expected_mutations.items():
        if triple not in latest_control_states:
            raise AssertionError(f"Oracle missing state for expected target {triple}")
        actual_ctrl = latest_control_states[triple]
        if isinstance(exp, dict):
            if 'value' in exp and actual_ctrl.get('value') != exp['value']:
                raise AssertionError(
                    f"Oracle value mismatch for {triple}: expected {exp['value']!r}, got {actual_ctrl.get('value')!r}"
                )
            if 'checked' in exp and actual_ctrl.get('checked') != exp['checked']:
                raise AssertionError(
                    f"Oracle checked mismatch for {triple}: expected {exp['checked']!r}, got {actual_ctrl.get('checked')!r}"
                )
        else:
            actual_val = actual_ctrl.get('value')
            if actual_val != exp:
                raise AssertionError(
                    f"Oracle value mismatch for {triple}: expected {exp!r}, got {actual_val!r}"
                )

    # 2. Assert every non-target control across all frames remains unchanged
    assert_nontarget_states_unmutated(latest_control_states, allowed_triples)


class NullSemanticMatcher:
    threshold = 0.82
    margin = 0.06

    def rank(self, question, bank):
        return []


def make_pipeline_bank():
    return {
        'questions': [
            {
                'fact': 'contact.first_name',
                'input_types': ['text'],
                'aliases': ['First Name'],
            },
            {
                'fact': 'contact.email',
                'input_types': ['text', 'email'],
                'aliases': ['Email Address', 'Email'],
            },
            {
                'fact': 'contact.phone',
                'input_types': ['text', 'tel'],
                'aliases': ['Phone Number', 'Phone'],
            },
            {
                'fact': 'work.authorized_us',
                'input_types': ['single_choice', 'combobox', 'select', 'radio'],
                'aliases': ['Authorized to work in the United States'],
            },
            {
                'fact': 'work.us_sponsorship_now_or_future',
                'input_types': ['single_choice', 'combobox', 'select', 'radio'],
                'aliases': ['Will you require sponsorship?'],
            },
            {
                'fact': 'contact.website',
                'input_types': ['text', 'url'],
                'aliases': ['Portfolio Website'],
            },
        ],
        'facts': {
            'contact.first_name': {
                'value': 'Grace',
                'confirmed': True,
                'source': 'vault',
            },
            'contact.email': {
                'value': 'grace@example.com',
                'confirmed': True,
                'source': 'vault',
            },
            'contact.phone': {
                'value': '+15559876543',
                'confirmed': True,
                'source': 'vault',
            },
            'work.authorized_us': {
                'value': True,
                'confirmed': True,
                'source': 'vault',
            },
            'work.us_sponsorship_now_or_future': {
                'value': False,
                'confirmed': True,
                'source': 'vault',
            },
            'contact.website': {
                'value': 'https://grace.example.com',
                'confirmed': True,
                'source': 'vault',
            },
        },
    }


class PipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(('127.0.0.1', 0), MutationCollectorHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.server_port = cls.server.server_address[1]
        cls.server_url = f"http://127.0.0.1:{cls.server_port}/pipeline.html"

        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(chromium_sandbox=True)
        cls.fixture_path = ROOT / 'tests/fixtures/pipeline.html'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='pipeline-test-')
        self.context = self.browser.new_context(
            viewport={'width': 1360, 'height': 1000},
            service_workers='block',
        )
        self.blocked = install_observation_guard(self.context)
        self.page = self.context.new_page()
        self.page.goto(self.fixture_path.as_uri(), wait_until='domcontentloaded')
        # Wait for subframe content to load
        self.page.wait_for_selector('iframe')

    def tearDown(self):
        self.context.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_end_to_end_extract_resolve_fill(self):
        # 1. Extraction: Phase 1 collect() without any manually injected targeting
        extraction = collect(self.page, probe_options=False)
        self.assertIn('questions', extraction)
        self.assertIn('snapshot_id', extraction)
        self.assertGreater(len(extraction['questions']), 0)

        # Verify form ownership via element.form for external input
        ext_ctrl = next(
            (c for c in extraction['controls'] if c['evidence']['dom']['id'] == 'portfolio_ext'),
            None,
        )
        self.assertIsNotNone(ext_ctrl)
        self.assertEqual(ext_ctrl['evidence']['dom']['form_id'], 'app-form')
        self.assertIn('form:nth-of-type(1)', ext_ctrl['evidence']['dom']['form_path'])

        # Verify question metadata: native types, AX roles, and frame descriptors
        fn_q = next(
            q for q in extraction['questions']
            if q['text'] == 'First Name' and q['frame_id'] == 'frame-0'
        )
        self.assertEqual(fn_q['native_input_type'], 'text')
        self.assertEqual(fn_q['frame_descriptor']['id'], 'frame-0')
        self.assertIn('url', fn_q['frame_descriptor'])
        self.assertGreater(len(fn_q['locator_candidates']), 0)

        # 2. Resolution: Phase 2 resolve_cascade()
        bank = make_pipeline_bank()
        semantic = NullSemanticMatcher()
        cascade = resolve_cascade(extraction['questions'], bank, semantic)
        answers = cascade['results']

        answers_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': extraction['snapshot_id'],
            'scope': 'job_application',
            'answers': answers,
        }

        # Check that metadata is retained in resolution outcomes
        ready_answers = [a for a in answers if a['status'] == 'ready']
        self.assertGreater(len(ready_answers), 0)
        for a in ready_answers:
            self.assertIn('native_input_type', a)
            self.assertIn('frame_descriptor', a)
            self.assertIn('locator_candidates', a)
            self.assertIn('locator_scope', a)

        # Filter plan to fill only app-form answers (scoped by frame-0 and form) to test duplicate isolation
        # Form 1 fields: fn1, email1, phone1, work_auth_sel, sponsor_group, portfolio_ext
        app_form_answers = [
            a for a in answers
            if a.get('frame_id') == 'frame-0' and 'form:nth-of-type(1)' in str(a.get('locator_scope', {}).get('form', ''))
        ]
        app_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': extraction['snapshot_id'],
            'scope': 'job_application',
            'answers': app_form_answers,
        }

        # 3. Filling: Phase 3 fill_form() without manual targeting
        report = fill_form(self.page, app_plan, options={'screenshot': False})
        self.assertEqual(report['snapshot_id'], extraction['snapshot_id'])
        self.assertEqual(report['summary']['failed'], 0)
        self.assertGreaterEqual(report['summary']['filled'], 4)

        # Verify live DOM in primary form
        self.assertEqual(self.page.locator('#fn1').input_value(), 'Grace')
        self.assertEqual(self.page.locator('#email1').input_value(), 'grace@example.com')
        self.assertEqual(self.page.locator('#phone1').input_value(), '+15559876543')
        self.assertEqual(self.page.locator('#work_auth_sel').input_value(), 'yes')
        self.assertTrue(self.page.locator("#sponsor_group input[value='false']").is_checked())
        self.assertEqual(self.page.locator('#portfolio_ext').input_value(), 'https://grace.example.com')

        # Crucial check: Duplicate controls in secondary form MUST BE UNTOUCHED!
        self.assertEqual(self.page.locator('#fn2').input_value(), '')
        self.assertEqual(self.page.locator('#email2').input_value(), '')

        # Crucial check: Duplicate controls in iframe MUST BE UNTOUCHED!
        sub_frame = next(f for f in self.page.frames if f != self.page.main_frame)
        self.assertEqual(sub_frame.locator('#frame_fn').input_value(), '')

    def test_cli_resolve_to_fill_pipeline(self):
        # Point 7: Actual extraction CLI -> resolution CLI -> fill CLI pipeline
        extract_out = Path(self.temp_dir) / 'cli_extract_out'

        # Step 1: Extraction CLI
        proc_ext = subprocess.run([
            sys.executable,
            '-m', 'job_applier.extraction',
            self.server_url,
            '--out', str(extract_out),
            '--no-probe-options',
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=45)
        self.assertEqual(proc_ext.returncode, 0, f"Extraction stderr: {proc_ext.stderr}")
        questions_path = extract_out / 'questions.json'
        self.assertTrue(questions_path.is_file())

        with open(questions_path, 'r', encoding='utf-8') as f:
            extraction = json.load(f)
        self.assertGreater(len(extraction.get('questions', [])), 0)

        # Step 2: Resolution CLI
        bank_path = Path(self.temp_dir) / 'bank.json'
        bank_path.write_text(json.dumps(make_pipeline_bank(), indent=2), encoding='utf-8')

        answers_path = Path(self.temp_dir) / 'answers.json'
        fill_out = Path(self.temp_dir) / 'cli_fill_out'

        proc_res = subprocess.run([
            sys.executable,
            '-m', 'job_applier.resolution',
            str(questions_path),
            '--bank', str(bank_path),
            '--out', str(answers_path),
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=30)
        self.assertEqual(proc_res.returncode, 0, f"Resolve stderr: {proc_res.stderr}")
        self.assertTrue(answers_path.is_file())

        with open(answers_path, 'r', encoding='utf-8') as f:
            plan = json.load(f)
        self.assertEqual(plan['snapshot_id'], extraction['snapshot_id'])
        # Verify metadata retained in CLI answers serialization
        for ans in plan['answers']:
            if ans['status'] == 'ready':
                self.assertIn('native_input_type', ans)
                self.assertIn('frame_descriptor', ans)
                self.assertIn('locator_candidates', ans)

        # Filter answers plan to target primary application form to prove duplicate isolation
        plan['answers'] = [
            a for a in plan['answers']
            if a.get('frame_id') == 'frame-0' and 'form:nth-of-type(1)' in str(a.get('locator_scope', {}).get('form', ''))
        ]
        answers_path.write_text(json.dumps(plan, indent=2), encoding='utf-8')

        # Reset recorder before fill CLI execution and start dedicated run
        run_id = MutationCollectorHandler.start_new_run()

        # Step 3: Fill CLI execution against live loopback instrumented server
        e2e_out_dir = Path(f'/tmp/opencode/m03-f9-e2e-{uuid.uuid4().hex[:8]}')
        e2e_out_dir.mkdir(parents=True, exist_ok=True)

        proc_fill = subprocess.run([
            sys.executable,
            '-m', 'job_applier.filling',
            self.server_url,
            '--answers', str(answers_path),
            '--out', str(fill_out),
            '--screenshot',
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=45)
        self.assertEqual(proc_fill.returncode, 0, f"Fill stderr: {proc_fill.stderr}")

        report_file = fill_out / 'fill_report.json'
        self.assertTrue(report_file.is_file())
        screenshot_file = fill_out / 'screenshot.png'
        self.assertTrue(screenshot_file.is_file())

        shutil.copy2(report_file, e2e_out_dir / 'fill_report.json')
        shutil.copy2(screenshot_file, e2e_out_dir / 'screenshot.png')

        # Acknowledged terminal completion handshake for dedicated runID across frames
        states = MutationCollectorHandler.wait_for_terminal_completion(run_id, timeout=10.0)

        with open(report_file, 'r', encoding='utf-8') as f:
            rep = json.load(f)
        self.assertEqual(rep['snapshot_id'], extraction['snapshot_id'])
        self.assertEqual(rep['summary']['failed'], 0)
        self.assertEqual(rep['summary']['filled'], 6)

        # Assert each intended committed value reported by CLI-owned browser
        fields_by_text = {f['text'].strip(): f for f in rep['fields']}
        self.assertEqual(fields_by_text['First Name']['verified_value'], 'Grace')
        self.assertEqual(fields_by_text['Email Address']['verified_value'], 'grace@example.com')
        self.assertEqual(fields_by_text['Phone Number']['verified_value'], '+15559876543')
        self.assertEqual(fields_by_text['Authorized to work in the United States']['verified_value'], 'Yes')
        self.assertEqual(fields_by_text['Will you require sponsorship?']['verified_value'], 'No')
        self.assertEqual(fields_by_text['Portfolio Website']['verified_value'], 'https://grace.example.com')

        self.assertGreater(len(states), 0, "Expected states to be populated by CLI browser")

        # Reusable target prerequisite verifies 6 target control states including BOTH yes/no
        assert_expected_target_states(states)

        allowed_triples = {
            ('main', 'app-form', 'fn1'),
            ('main', 'app-form', 'email1'),
            ('main', 'app-form', 'phone1'),
            ('main', 'app-form', 'work_auth_sel'),
            ('main', 'app-form', 'sponsor_no'),
            ('main', 'app-form', 'sponsor_yes'),
            ('main', 'app-form', 'portfolio_ext'),
            ('main', 'app-form', 'first_name'),
            ('main', 'app-form', 'email'),
            ('main', 'app-form', 'phone'),
            ('main', 'app-form', 'work_auth'),
            ('main', 'app-form', 'sponsor'),
            ('main', 'app-form', 'portfolio'),
        }

        # Exact values verified by full triple: target form controls match, non-targets remain untouched
        assert_nontarget_states_unmutated(states, allowed_triples)

        # Assert duplicate controls in secondary form and iframe have empty values and are untouched
        self.assertEqual(states.get(('main', 'newsletter-form', 'fn2'), {}).get('value'), '')
        self.assertEqual(states.get(('main', 'newsletter-form', 'email2'), {}).get('value'), '')
        self.assertEqual(states.get(('sub-frame', 'frame-form', 'frame_fn'), {}).get('value'), '')

        # Capture actual control states to /tmp/opencode/m03-f9-e2e
        serializable_states = {
            f"{triple[0]}:{triple[1]}:{triple[2]}": ctrl
            for triple, ctrl in states.items()
        }
        metadata_output = {
            'run_id': run_id,
            'completion_acknowledged': True,
            'frames': list(MutationCollectorHandler.runs[run_id]['terminal_frames'].keys()),
            'generation': MutationCollectorHandler.runs[run_id]['generation'],
            'target_controls': {
                'fn1': states.get(('main', 'app-form', 'fn1')),
                'email1': states.get(('main', 'app-form', 'email1')),
                'phone1': states.get(('main', 'app-form', 'phone1')),
                'work_auth_sel': states.get(('main', 'app-form', 'work_auth_sel')),
                'portfolio_ext': states.get(('main', 'app-form', 'portfolio_ext')),
            },
            'radios': {
                'sponsor_no': states.get(('main', 'app-form', 'sponsor_no')),
                'sponsor_yes': states.get(('main', 'app-form', 'sponsor_yes')),
            },
            'nontargets': {
                'fn2': states.get(('main', 'newsletter-form', 'fn2')),
                'email2': states.get(('main', 'newsletter-form', 'email2')),
                'frame_fn': states.get(('sub-frame', 'frame-form', 'frame_fn')),
            },
            'all_states': serializable_states,
        }
        (e2e_out_dir / 'actual_control_states.json').write_text(
            json.dumps(metadata_output, indent=2), encoding='utf-8'
        )

    def test_oracle_detects_wrong_target_mutation(self):
        # Item 6: extractedURL MUST equal fillURL; server-side fault flag changed only AFTER extract/resolve.
        # Inject corruption DURING intended fill microtask.
        # Fill returns 0, no failures, all 6 values correct, oracle detects only nontarget fault.
        # Test both same-frame wrong-owner and same-ID wrong-frame separately.
        bank_path = Path(self.temp_dir) / 'bank_fault.json'
        bank_path.write_text(json.dumps(make_pipeline_bank(), indent=2), encoding='utf-8')

        extract_out = Path(self.temp_dir) / 'cli_extract_fault'
        subprocess.run([
            sys.executable,
            '-m', 'job_applier.extraction',
            self.server_url,
            '--out', str(extract_out),
            '--no-probe-options',
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=45)

        answers_path = Path(self.temp_dir) / 'answers_fault.json'
        subprocess.run([
            sys.executable,
            '-m', 'job_applier.resolution',
            str(extract_out / 'questions.json'),
            '--bank', str(bank_path),
            '--out', str(answers_path),
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=30)

        with open(answers_path, 'r', encoding='utf-8') as f:
            plan = json.load(f)
        plan['answers'] = [
            a for a in plan['answers']
            if a.get('frame_id') == 'frame-0' and 'form:nth-of-type(1)' in str(a.get('locator_scope', {}).get('form', ''))
        ]
        answers_path.write_text(json.dumps(plan, indent=2), encoding='utf-8')

        expected_target_states = {
            ('main', 'app-form', 'fn1'): 'Grace',
            ('main', 'app-form', 'email1'): 'grace@example.com',
            ('main', 'app-form', 'phone1'): '+15559876543',
            ('main', 'app-form', 'work_auth_sel'): 'yes',
            ('main', 'app-form', 'sponsor_no'): {'value': 'false', 'checked': True},
            ('main', 'app-form', 'sponsor_yes'): {'value': 'true', 'checked': False},
            ('main', 'app-form', 'portfolio_ext'): 'https://grace.example.com',
        }
        allowed_triples = set(expected_target_states.keys()) | {
            ('main', 'app-form', 'first_name'),
            ('main', 'app-form', 'email'),
            ('main', 'app-form', 'phone'),
            ('main', 'app-form', 'work_auth'),
            ('main', 'app-form', 'sponsor'),
            ('main', 'app-form', 'portfolio'),
        }

        # Subtest 1: Same frame wrong owner (fn2 in newsletter-form)
        MutationCollectorHandler.server_fault_mode = 'wrong_target_same_frame'
        run_id1 = MutationCollectorHandler.start_new_run()
        fill_fault_out1 = Path(self.temp_dir) / 'cli_fill_fault_out1'

        proc_fill1 = subprocess.run([
            sys.executable,
            '-m', 'job_applier.filling',
            self.server_url,  # extractedURL equals fillURL! No query divergence!
            '--answers', str(answers_path),
            '--out', str(fill_fault_out1),
            '--no-screenshot',
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=45)
        self.assertEqual(proc_fill1.returncode, 0, f"Fill stderr: {proc_fill1.stderr}")

        with open(fill_fault_out1 / 'fill_report.json', 'r', encoding='utf-8') as f:
            rep1 = json.load(f)
        self.assertEqual(rep1['summary']['failed'], 0)
        self.assertEqual(rep1['summary']['filled'], 6)

        actual_states1 = MutationCollectorHandler.wait_for_terminal_completion(run_id1, timeout=10.0)
        self.assertIn(('main', 'newsletter-form', 'fn2'), actual_states1)
        self.assertEqual(
            actual_states1[('main', 'newsletter-form', 'fn2')].get('value'),
            'deliberate_silent_corruption'
        )

        # Explicit prerequisite call: all 6 targets verified first
        assert_expected_target_states(actual_states1)

        # Expected nontarget assertion
        with self.assertRaises(AssertionError) as ctx1:
            assert_nontarget_states_unmutated(actual_states1, allowed_triples)
        self.assertIn("Oracle detected wrong-target or silent mutation", str(ctx1.exception))
        self.assertIn("('main', 'newsletter-form', 'fn2')", str(ctx1.exception))

        # Corruption on BOTH fn1 (target) and fn2 (nontarget) must fail TARGET prerequisite
        both_corrupted1 = dict(actual_states1)
        both_corrupted1[('main', 'app-form', 'fn1')] = {'value': 'corrupted_target'}
        with self.assertRaises(AssertionError) as ctx_t1:
            assert_expected_target_states(both_corrupted1)
        self.assertIn("Target prerequisite value mismatch for ('main', 'app-form', 'fn1')", str(ctx_t1.exception))

        # Subtest 2: Same ID wrong frame (frame_fn in sub-frame)
        MutationCollectorHandler.server_fault_mode = 'wrong_target_child_frame'
        run_id2 = MutationCollectorHandler.start_new_run()
        fill_fault_out2 = Path(self.temp_dir) / 'cli_fill_fault_out2'

        proc_fill2 = subprocess.run([
            sys.executable,
            '-m', 'job_applier.filling',
            self.server_url,  # extractedURL equals fillURL! No query divergence!
            '--answers', str(answers_path),
            '--out', str(fill_fault_out2),
            '--no-screenshot',
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=45)
        self.assertEqual(proc_fill2.returncode, 0, f"Fill stderr: {proc_fill2.stderr}")

        with open(fill_fault_out2 / 'fill_report.json', 'r', encoding='utf-8') as f:
            rep2 = json.load(f)
        self.assertEqual(rep2['summary']['failed'], 0)
        self.assertEqual(rep2['summary']['filled'], 6)

        actual_states2 = MutationCollectorHandler.wait_for_terminal_completion(run_id2, timeout=10.0)
        self.assertIn(('sub-frame', 'frame-form', 'frame_fn'), actual_states2)
        self.assertEqual(
            actual_states2[('sub-frame', 'frame-form', 'frame_fn')].get('value'),
            'deliberate_child_frame_corruption'
        )

        # Explicit prerequisite call: all 6 targets verified first
        assert_expected_target_states(actual_states2)

        # Expected nontarget assertion
        with self.assertRaises(AssertionError) as ctx2:
            assert_nontarget_states_unmutated(actual_states2, allowed_triples)
        self.assertIn("Oracle detected wrong-target or silent mutation", str(ctx2.exception))
        self.assertIn("('sub-frame', 'frame-form', 'frame_fn')", str(ctx2.exception))

        # Corruption on BOTH fn1 (target) and frame_fn (nontarget) must fail TARGET prerequisite
        both_corrupted2 = dict(actual_states2)
        both_corrupted2[('main', 'app-form', 'fn1')] = {'value': 'corrupted_target'}
        with self.assertRaises(AssertionError) as ctx_t2:
            assert_expected_target_states(both_corrupted2)
        self.assertIn("Target prerequisite value mismatch for ('main', 'app-form', 'fn1')", str(ctx_t2.exception))

    def test_oracle_radio_fault_both_unchecked_rejected(self):
        # Item 5: Test actual CLI runs fixture fault both unchecked and oracle rejects
        bank_path = Path(self.temp_dir) / 'bank_r1.json'
        bank_path.write_text(json.dumps(make_pipeline_bank(), indent=2), encoding='utf-8')

        extract_out = Path(self.temp_dir) / 'cli_extract_r1'
        subprocess.run([
            sys.executable,
            '-m', 'job_applier.extraction',
            self.server_url,
            '--out', str(extract_out),
            '--no-probe-options',
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=45)

        answers_path = Path(self.temp_dir) / 'answers_r1.json'
        subprocess.run([
            sys.executable,
            '-m', 'job_applier.resolution',
            str(extract_out / 'questions.json'),
            '--bank', str(bank_path),
            '--out', str(answers_path),
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=30)

        with open(answers_path, 'r', encoding='utf-8') as f:
            plan = json.load(f)
        plan['answers'] = [
            a for a in plan['answers']
            if a.get('frame_id') == 'frame-0' and 'form:nth-of-type(1)' in str(a.get('locator_scope', {}).get('form', ''))
        ]
        answers_path.write_text(json.dumps(plan, indent=2), encoding='utf-8')

        MutationCollectorHandler.server_fault_mode = 'fault_both_unchecked'
        run_id_r1 = MutationCollectorHandler.start_new_run()
        fill_out = Path(self.temp_dir) / 'cli_fill_r1'

        proc_fill = subprocess.run([
            sys.executable,
            '-m', 'job_applier.filling',
            self.server_url,
            '--answers', str(answers_path),
            '--out', str(fill_out),
            '--no-screenshot',
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=45)
        self.assertEqual(proc_fill.returncode, 0)

        states = MutationCollectorHandler.wait_for_terminal_completion(run_id_r1, timeout=10.0)
        expected_target_states = {
            ('main', 'app-form', 'fn1'): 'Grace',
            ('main', 'app-form', 'email1'): 'grace@example.com',
            ('main', 'app-form', 'phone1'): '+15559876543',
            ('main', 'app-form', 'work_auth_sel'): 'yes',
            ('main', 'app-form', 'sponsor_no'): {'value': 'false', 'checked': True},
            ('main', 'app-form', 'sponsor_yes'): {'value': 'true', 'checked': False},
            ('main', 'app-form', 'portfolio_ext'): 'https://grace.example.com',
        }
        allowed_triples = set(expected_target_states.keys()) | {
            ('main', 'app-form', 'first_name'),
            ('main', 'app-form', 'email'),
            ('main', 'app-form', 'phone'),
            ('main', 'app-form', 'work_auth'),
            ('main', 'app-form', 'sponsor'),
            ('main', 'app-form', 'portfolio'),
        }

        with self.assertRaises(AssertionError) as ctx:
            check_mutation_oracle(states, expected_target_states, allowed_triples)
        self.assertIn("sponsor_no", str(ctx.exception))
        self.assertIn("checked mismatch", str(ctx.exception))

    def test_oracle_radio_fault_yes_selected_rejected(self):
        # Item 5: Test actual CLI runs fixture fault Yes selected and oracle rejects
        bank_path = Path(self.temp_dir) / 'bank_r2.json'
        bank_path.write_text(json.dumps(make_pipeline_bank(), indent=2), encoding='utf-8')

        extract_out = Path(self.temp_dir) / 'cli_extract_r2'
        subprocess.run([
            sys.executable,
            '-m', 'job_applier.extraction',
            self.server_url,
            '--out', str(extract_out),
            '--no-probe-options',
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=45)

        answers_path = Path(self.temp_dir) / 'answers_r2.json'
        subprocess.run([
            sys.executable,
            '-m', 'job_applier.resolution',
            str(extract_out / 'questions.json'),
            '--bank', str(bank_path),
            '--out', str(answers_path),
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=30)

        with open(answers_path, 'r', encoding='utf-8') as f:
            plan = json.load(f)
        plan['answers'] = [
            a for a in plan['answers']
            if a.get('frame_id') == 'frame-0' and 'form:nth-of-type(1)' in str(a.get('locator_scope', {}).get('form', ''))
        ]
        answers_path.write_text(json.dumps(plan, indent=2), encoding='utf-8')

        MutationCollectorHandler.server_fault_mode = 'fault_yes_selected'
        run_id_r2 = MutationCollectorHandler.start_new_run()
        fill_out = Path(self.temp_dir) / 'cli_fill_r2'

        proc_fill = subprocess.run([
            sys.executable,
            '-m', 'job_applier.filling',
            self.server_url,
            '--answers', str(answers_path),
            '--out', str(fill_out),
            '--no-screenshot',
        ], capture_output=True, text=True, encoding='utf-8', cwd=str(ROOT), timeout=45)
        self.assertEqual(proc_fill.returncode, 0)

        states = MutationCollectorHandler.wait_for_terminal_completion(run_id_r2, timeout=10.0)
        expected_target_states = {
            ('main', 'app-form', 'fn1'): 'Grace',
            ('main', 'app-form', 'email1'): 'grace@example.com',
            ('main', 'app-form', 'phone1'): '+15559876543',
            ('main', 'app-form', 'work_auth_sel'): 'yes',
            ('main', 'app-form', 'sponsor_no'): {'value': 'false', 'checked': True},
            ('main', 'app-form', 'sponsor_yes'): {'value': 'true', 'checked': False},
            ('main', 'app-form', 'portfolio_ext'): 'https://grace.example.com',
        }
        allowed_triples = set(expected_target_states.keys()) | {
            ('main', 'app-form', 'first_name'),
            ('main', 'app-form', 'email'),
            ('main', 'app-form', 'phone'),
            ('main', 'app-form', 'work_auth'),
            ('main', 'app-form', 'sponsor'),
            ('main', 'app-form', 'portfolio'),
        }

        with self.assertRaises(AssertionError) as ctx:
            check_mutation_oracle(states, expected_target_states, allowed_triples)
        self.assertIn("sponsor_no", str(ctx.exception))
        self.assertIn("checked mismatch", str(ctx.exception))

    def test_e2e_all_supported_required_fields_filled_and_negative_fixture_skipped(self):
        # Supported required questions: First Name, Email, Authorized to work
        # Verified synthetic bank matches all required questions
        extraction = collect(self.page, probe_options=False)
        app_questions = [
            q for q in extraction['questions']
            if q.get('frame_id') == 'frame-0' and 'form:nth-of-type(1)' in str(q.get('locator_scope', {}).get('form', ''))
        ]
        bank = make_pipeline_bank()
        cascade = resolve_cascade(app_questions, bank, NullSemanticMatcher())
        ready_answers = [a for a in cascade['results'] if a['status'] == 'ready']

        # Required fields in primary form: fn1, email1, work_auth_sel
        required_questions = [q for q in app_questions if q.get('required') is True]
        self.assertGreaterEqual(len(required_questions), 3)

        # Plan with all ready answers
        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': extraction['snapshot_id'],
            'scope': 'job_application',
            'answers': ready_answers,
        }
        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 0)
        # All required fields are filled!
        filled_qids = {f['question_id'] for f in report['fields'] if f['status'] == 'filled'}
        for req_q in required_questions:
            self.assertIn(req_q['id'], filled_qids, f"Required question {req_q['text']} not filled")

        # Deliberately unsupported negative fixture: arbitration agreement and missing fact
        neg_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': extraction['snapshot_id'],
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_arb_neg',
                    'text': 'I agree to mandatory arbitration',
                    'input_type': 'checkbox',
                    'answer': True,
                    'status': 'ready',
                    'fact_key': 'arbitration',
                },
                {
                    'question_id': 'q_missing_neg',
                    'text': 'Favorite Color',
                    'input_type': 'text',
                    'answer': None,
                    'status': 'needs_user',
                },
            ],
        }
        neg_report = fill_form(self.page, neg_plan, options={'screenshot': False})
        self.assertEqual(neg_report['summary']['filled'], 0)
        self.assertEqual(neg_report['summary']['skipped'], 2)
        reasons = [f['skip_reason'] for f in neg_report['fields']]
        self.assertTrue(any('legal agreement' in r.lower() for r in reasons))
        self.assertTrue(any('needs_user' in r.lower() for r in reasons))

    def test_pipeline_collect_resolve_fill_stale_radio_form_fails(self):
        extraction = collect(self.page, probe_options=False)
        sponsor_q = next(
            q for q in extraction['questions']
            if 'sponsorship' in q['text'].lower()
        )
        bank = make_pipeline_bank()
        cascade = resolve_cascade([sponsor_q], bank, NullSemanticMatcher())
        resolved = cascade['results'][0]

        # Inject Form B with the same radio legend into page
        self.page.evaluate("""() => {
            const formB = document.createElement('form');
            formB.id = 'stale-test-form-b';
            formB.innerHTML = `
                <fieldset class="field">
                    <legend>Will you require sponsorship?</legend>
                    <label><input type="radio" name="sponsor_b" value="true"> Yes</label>
                    <label><input type="radio" name="sponsor_b" value="false"> No</label>
                </fieldset>
            `;
            document.body.appendChild(formB);
        }""")

        # Remove original Form A (#app-form)
        self.page.evaluate("() => document.getElementById('app-form').remove()")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': extraction['snapshot_id'],
            'scope': 'job_application',
            'answers': [resolved],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        self.assertIn("Stale form scope", report['fields'][0].get('error', ''))

        # Form B radio must remain completely unselected
        b_checked = self.page.locator('#stale-test-form-b input[type="radio"]:checked')
        self.assertEqual(b_checked.count(), 0)

    def test_grouped_radio_metadata_survives_and_resolves(self):
        extraction = collect(self.page, probe_options=False)
        sponsor_q = next(
            q for q in extraction['questions']
            if 'sponsorship' in q['text'].lower()
        )
        self.assertEqual(sponsor_q['input_type'], 'single_choice')
        self.assertEqual(sponsor_q['native_input_type'], 'radio')
        self.assertEqual(len(sponsor_q['control_metadata']), 2)
        self.assertEqual(len(sponsor_q['options']['items']), 2)

        bank = make_pipeline_bank()
        cascade = resolve_cascade([sponsor_q], bank, NullSemanticMatcher())
        resolved = cascade['results'][0]
        self.assertEqual(resolved['status'], 'ready')
        self.assertEqual(resolved['selected_option']['value'], 'false')
        self.assertEqual(resolved['native_input_type'], 'radio')
        self.assertEqual(len(resolved['control_metadata']), 2)

    def test_removed_or_replaced_frame_identity_fails_cleanly(self):
        # A plan targeting an iframe that does not exist or has a different URL
        stale_plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': 'snap-stale-test',
            'scope': 'job_application',
            'answers': [
                {
                    'question_id': 'q_iframe_stale',
                    'text': 'First Name',
                    'input_type': 'text',
                    'answer': 'Should Not Mutate',
                    'status': 'ready',
                    'frame_id': 'frame-subframe-replaced',
                    'frame_descriptor': {
                        'id': 'frame-subframe-replaced',
                        'url': 'https://different.invalid/replaced.html',
                        'name': 'replaced_frame',
                    },
                    'locator_candidates': [{'by': 'id', 'value': 'frame_fn'}],
                },
            ],
        }
        report = fill_form(self.page, stale_plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertIn('Unsupported/stale frame identity', report['fields'][0].get('error', ''))

        # Neither the main document nor the subframe was mutated
        self.assertEqual(self.page.locator('#fn1').input_value(), '')
        sub_frame = next(f for f in self.page.frames if f != self.page.main_frame)
        self.assertEqual(sub_frame.locator('#frame_fn').input_value(), '')

    def test_pipeline_radio_stays_nested_in_form_a_gains_form_b_fails_before_click_both_groups_unchanged(self):
        # P1-1: Captured owner A, radio stays nested in A but gains form=B attribute.
        # Must fail BEFORE click. Real collect -> resolve -> mutate form attr -> fill:
        # No events, both groups unchanged. Validate owner on actual clicked radio.
        self.page.goto(self.server_url)

        # Inject secondary form B with separate radios into page
        self.page.evaluate("""() => {
            const formB = document.createElement('form');
            formB.id = 'radio-test-form-b';
            formB.innerHTML = `
                <fieldset class="field" id="sponsor_group_b">
                    <legend>Secondary Sponsorship</legend>
                    <label for="sponsor_b_yes"><input type="radio" id="sponsor_b_yes" name="sponsor_b" value="true"> Yes</label>
                    <label for="sponsor_b_no"><input type="radio" id="sponsor_b_no" name="sponsor_b" value="false"> No</label>
                </fieldset>
            `;
            document.body.appendChild(formB);

            window.__radioEventsP1 = [];
            ['sponsor_yes', 'sponsor_no', 'sponsor_b_yes', 'sponsor_b_no'].forEach(id => {
                const el = document.getElementById(id);
                if (el) {
                    ['click', 'input', 'change'].forEach(evt => {
                        el.addEventListener(evt, () => window.__radioEventsP1.push({ id, event: evt }));
                    });
                }
            });
        }""")

        extraction = collect(self.page, probe_options=False)
        sponsor_q = next(
            q for q in extraction['questions']
            if 'sponsorship' in q['text'].lower() and q.get('frame_id') == 'frame-0' and 'app-form' in str(q.get('locator_scope', {}).get('form_id', ''))
        )
        bank = make_pipeline_bank()
        cascade = resolve_cascade([sponsor_q], bank, NullSemanticMatcher())
        resolved = cascade['results'][0]
        self.assertEqual(resolved['status'], 'ready')
        self.assertEqual(resolved['selected_option']['value'], 'false')

        # Mutate DOM: radio stays physically nested inside app-form/sponsor_group, but gains form="radio-test-form-b"
        self.page.evaluate("""() => {
            document.getElementById('sponsor_no').setAttribute('form', 'radio-test-form-b');
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': extraction['snapshot_id'],
            'scope': 'job_application',
            'answers': [resolved],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        err = report['fields'][0].get('error', '')
        self.assertIn("form owner mismatch", err.lower())
        self.assertIn("app-form", err)
        self.assertIn("radio-test-form-b", err)

        # Zero events emitted on any radio
        events = self.page.evaluate("() => window.__radioEventsP1")
        self.assertEqual(events, [])

        # Both groups remain completely unchanged (neither group has checked radio)
        self.assertEqual(self.page.locator('#app-form input[type="radio"]:checked').count(), 0)
        self.assertEqual(self.page.locator('#radio-test-form-b input[type="radio"]:checked').count(), 0)

    def test_pipeline_unowned_text_input_moved_into_named_form_rejects_with_zero_events_and_no_value_change(self):
        # P1-2: Actual collect -> resolve -> move unowned identified text input into named B
        # while root old location is gone. Fill rejects with zero events and no value change.
        self.page.goto(self.server_url)

        # Inject an unowned text input outside any form
        self.page.evaluate("""() => {
            const wrap = document.createElement('div');
            wrap.id = 'unowned-wrap';
            wrap.innerHTML = `
                <label for="unowned_notes">Additional Notes</label>
                <input type="text" id="unowned_notes" name="notes" value="">
            `;
            document.body.appendChild(wrap);

            window.__unownedNotesEvents = [];
            const inp = document.getElementById('unowned_notes');
            ['input', 'change', 'click', 'focus'].forEach(evt => {
                inp.addEventListener(evt, () => window.__unownedNotesEvents.push(evt));
            });
        }""")

        extraction = collect(self.page, probe_options=False)
        notes_q = next(
            q for q in extraction['questions']
            if 'additional notes' in q['text'].lower()
        )
        self.assertFalse(bool(notes_q.get('locator_scope', {}).get('form_id')))
        self.assertFalse(bool(notes_q.get('locator_scope', {}).get('form')))

        custom_bank = make_pipeline_bank()
        custom_bank['questions'].append({
            'fact': 'notes.additional',
            'input_types': ['text'],
            'aliases': ['Additional Notes'],
        })
        custom_bank['facts']['notes.additional'] = {
            'value': 'My Note Content',
            'confirmed': True,
            'source': 'vault',
        }
        cascade = resolve_cascade([notes_q], custom_bank, NullSemanticMatcher())
        resolved = cascade['results'][0]
        self.assertEqual(resolved['status'], 'ready')

        # Mutate DOM: move unowned input into named newsletter-form, while old location is gone
        self.page.evaluate("""() => {
            const inp = document.getElementById('unowned_notes');
            document.getElementById('newsletter-form').appendChild(inp);
            document.getElementById('unowned-wrap').remove();
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': extraction['snapshot_id'],
            'scope': 'job_application',
            'answers': [resolved],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        err = report['fields'][0].get('error', '')
        self.assertIn("form owner mismatch", err.lower())
        self.assertIn("had no owning form", err.lower())
        self.assertIn("newsletter-form", err)

        # Zero events emitted
        events = self.page.evaluate("() => window.__unownedNotesEvents")
        self.assertEqual(events, [])

        # No value change
        self.assertEqual(self.page.locator('#unowned_notes').input_value(), '')

    def test_pipeline_unowned_text_input_explicit_form_attribute_reassociation_rejects_with_zero_events(self):
        # P1-2: Explicit form= reassociation on unowned control
        self.page.goto(self.server_url)

        self.page.evaluate("""() => {
            const wrap = document.createElement('div');
            wrap.id = 'unowned-wrap-attr';
            wrap.innerHTML = `
                <label for="unowned_attr_input">Special Instructions</label>
                <input type="text" id="unowned_attr_input" name="special_instructions" value="">
            `;
            document.body.appendChild(wrap);

            window.__unownedAttrEvents = [];
            const inp = document.getElementById('unowned_attr_input');
            ['input', 'change', 'click', 'focus'].forEach(evt => {
                inp.addEventListener(evt, () => window.__unownedAttrEvents.push(evt));
            });
        }""")

        extraction = collect(self.page, probe_options=False)
        instr_q = next(
            q for q in extraction['questions']
            if 'special instructions' in q['text'].lower()
        )
        custom_bank = make_pipeline_bank()
        custom_bank['questions'].append({
            'fact': 'instructions.special',
            'input_types': ['text'],
            'aliases': ['Special Instructions'],
        })
        custom_bank['facts']['instructions.special'] = {
            'value': 'Deliver fast',
            'confirmed': True,
            'source': 'vault',
        }
        cascade = resolve_cascade([instr_q], custom_bank, NullSemanticMatcher())
        resolved = cascade['results'][0]
        self.assertEqual(resolved['status'], 'ready')

        # Mutate DOM: set explicit form="newsletter-form" attribute
        self.page.evaluate("""() => {
            document.getElementById('unowned_attr_input').setAttribute('form', 'newsletter-form');
        }""")

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': extraction['snapshot_id'],
            'scope': 'job_application',
            'answers': [resolved],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 1)
        self.assertEqual(report['summary']['filled'], 0)
        err = report['fields'][0].get('error', '')
        self.assertIn("form owner mismatch", err.lower())
        self.assertIn("had no owning form", err.lower())

        events = self.page.evaluate("() => window.__unownedAttrEvents")
        self.assertEqual(events, [])
        self.assertEqual(self.page.locator('#unowned_attr_input').input_value(), '')

    def test_pipeline_genuine_external_form_control_baseline_passes(self):
        # P1-2: Genuine external form control baseline (#portfolio_ext with form="app-form") should still pass
        self.page.goto(self.server_url)

        extraction = collect(self.page, probe_options=False)
        port_q = next(
            q for q in extraction['questions']
            if 'portfolio' in q['text'].lower()
        )
        self.assertEqual(port_q.get('locator_scope', {}).get('form_id'), 'app-form')

        bank = make_pipeline_bank()
        cascade = resolve_cascade([port_q], bank, NullSemanticMatcher())
        resolved = cascade['results'][0]
        self.assertEqual(resolved['status'], 'ready')
        self.assertEqual(resolved['answer'], 'https://grace.example.com')

        plan = {
            'schema': 'job-applier.answer-plan.v1',
            'snapshot_id': extraction['snapshot_id'],
            'scope': 'job_application',
            'answers': [resolved],
        }

        report = fill_form(self.page, plan, options={'screenshot': False})
        self.assertEqual(report['summary']['failed'], 0)
        self.assertEqual(report['summary']['filled'], 1)
        self.assertEqual(self.page.locator('#portfolio_ext').input_value(), 'https://grace.example.com')

    def test_snapshot_oracle_delayed_interleaved_other_run_rejected(self):
        # Issue 4: delayed/interleaved initial/other-run snapshot tests;
        # ensure old run does not satisfy wait and intermediate snapshots do not complete run
        import urllib.request

        run_old = MutationCollectorHandler.start_new_run()
        run_cur = MutationCollectorHandler.start_new_run()
        base_url = f"http://127.0.0.1:{self.server_port}"

        # 1. Send old-run terminal snapshot for both frames
        payload_old = urllib.parse.quote(json.dumps({'frame': 'main', 'controls': [{'id': 'fn1', 'owner_id': 'app-form', 'value': 'OldRun'}]}))
        urllib.request.urlopen(f"{base_url}/state?run_id={run_old}&terminal=true&data={payload_old}")
        payload_old_sub = urllib.parse.quote(json.dumps({'frame': 'sub-frame', 'controls': []}))
        urllib.request.urlopen(f"{base_url}/state?run_id={run_old}&terminal=true&data={payload_old_sub}")

        # Old run completed, but run_cur MUST NOT complete!
        with self.assertRaises(TimeoutError):
            MutationCollectorHandler.wait_for_terminal_completion(run_cur, timeout=0.3)

        # 2. Send non-terminal snapshot for run_cur
        payload_cur_interm = urllib.parse.quote(json.dumps({'frame': 'main', 'controls': [{'id': 'fn1', 'owner_id': 'app-form', 'value': 'GraceInterm'}]}))
        urllib.request.urlopen(f"{base_url}/state?run_id={run_cur}&terminal=false&data={payload_cur_interm}")

        # Intermediate snapshot does NOT complete run_cur!
        with self.assertRaises(TimeoutError):
            MutationCollectorHandler.wait_for_terminal_completion(run_cur, timeout=0.3)

        # 3. Send terminal snapshot for main only (incomplete frames)
        payload_cur_main = urllib.parse.quote(json.dumps({'frame': 'main', 'controls': [{'id': 'fn1', 'owner_id': 'app-form', 'value': 'GraceFinal'}]}))
        urllib.request.urlopen(f"{base_url}/state?run_id={run_cur}&terminal=true&data={payload_cur_main}")

        # Sub-frame still missing, so run_cur MUST NOT complete!
        with self.assertRaises(TimeoutError):
            MutationCollectorHandler.wait_for_terminal_completion(run_cur, timeout=0.3)

        # 4. Send terminal snapshot for sub-frame
        payload_cur_sub = urllib.parse.quote(json.dumps({'frame': 'sub-frame', 'controls': [{'id': 'frame_fn', 'owner_id': 'frame-form', 'value': ''}]}))
        urllib.request.urlopen(f"{base_url}/state?run_id={run_cur}&terminal=true&data={payload_cur_sub}")

        # Now run_cur completes and locks stable copy!
        final_states = MutationCollectorHandler.wait_for_terminal_completion(run_cur, timeout=2.0)
        self.assertEqual(final_states[('main', 'app-form', 'fn1')]['value'], 'GraceFinal')


if __name__ == '__main__':
    unittest.main()
