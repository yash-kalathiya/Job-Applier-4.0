"""Fresh-user end-to-end test: a brand-new person, an empty machine profile, no API keys.

Runs everything in a throwaway HOME and APPLYTWIN_HOME, so the real user's data and agent configs are never touched.
Covers: doctor on an empty setup, resume import, profile, queue, tailoring + PDF, the MCP server over stdio,
install-agents (Claude Code + Codex configs), the web server's endpoints, and the signed-out run guard.

    python3 tests/e2e_fresh.py
"""
import json
import os
os.environ["APPLYTWIN_NO_TELEMETRY"] = "1"   # tests never count as installs
os.environ["APPLYTWIN_SKIP_SIGNIN"] = "1"   # no Google account in tests
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

for _s in (sys.stdout, sys.stderr):   # Windows consoles default to cp1252, which can't print emoji
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, 'bin', 'job-applier')
TMP = tempfile.mkdtemp(prefix='job-applier-fresh-')
ENV = {k: v for k, v in os.environ.items() if k not in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY')}
ENV.update(HOME=TMP, USERPROFILE=TMP, JOB_APPLIER_HOME=os.path.join(TMP, '.job-applier'), APPLYTWIN_HOME=os.path.join(TMP, '.applytwin'))
PORT = 4859

RESUME = """Maya Chen
maya.chen@example.edu | (555) 201-3344 | Austin, TX | linkedin.com/in/mayachen-rn

EDUCATION
University of Texas at Austin, Bachelor of Science in Nursing, Expected May 2028. GPA 3.8

EXPERIENCE
Patient Care Technician, St. David's Medical Center, Austin, TX. June 2025 - Present
- Monitored vital signs for 12+ patients per shift on a 32-bed med-surg unit
- Assisted nurses with wound care, ambulation and EHR charting in Epic
Volunteer, Central Texas Food Bank. 2023 - 2025
- Coordinated weekend distribution for 400+ families

SKILLS
Epic EHR, BLS/CPR certified, phlebotomy, patient education, Spanish (conversational)
"""

JD = """Summer 2027 Nursing Extern. Work alongside RNs on med-surg and ICU units. Requirements: enrolled in a BSN program,
BLS certification, experience with Epic EHR, strong patient communication. Bilingual Spanish a plus."""

def _stub_agents(tmp):
    """Stand-in claude/codex that report 'signed out', so tests never run the real CLIs against a throwaway HOME
    (on macOS that makes them look for a keychain that isn't there, and the system shows a pop-up)."""
    import stat
    d = os.path.join(tmp, 'stubbin')
    os.makedirs(d, exist_ok=True)
    for name in ('claude', 'codex'):
        py = os.path.join(d, name + '_stub.py')
        open(py, 'w').write("import sys, json\na = sys.argv[1:]\n"
                            "print(json.dumps({'loggedIn': False}) if a[:2] == ['auth', 'status'] else '9.9.9 (stub)' if a[:1] == ['--version'] else 'Not logged in')\n"
                            "sys.exit(0 if a[:1] in (['--version'], ['auth'], ['mcp'], ['plugin']) else 1)\n")
        if os.name == 'nt':
            open(os.path.join(d, name + '.cmd'), 'w').write(f'@"{sys.executable}" "{py}" %*\r\n')
        else:
            p = os.path.join(d, name)
            open(p, 'w').write(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n')
            os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    return d

ENV['PATH'] = _stub_agents(TMP) + os.pathsep + ENV.get('PATH', '')

results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok)))
    print(('\033[32mPASS\033[0m ' if ok else '\033[31mFAIL\033[0m ') + name + (f'  \033[2m{detail}\033[0m' if detail else ''))


def cli(*args, timeout=180, input=None):
    r = subprocess.run([sys.executable, BIN, *args], env=ENV, capture_output=True, text=True, timeout=timeout, input=input)
    return r.returncode, r.stdout + r.stderr


AUTH_COOKIE = ''


def http(path, body=None):
    headers = {'Content-Type': 'application/json'}
    if AUTH_COOKIE:
        headers['Cookie'] = AUTH_COOKIE
    req = urllib.request.Request(f'http://127.0.0.1:{PORT}{path}', data=None if body is None else json.dumps(body).encode(),
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        return json.loads(raw) if r.headers.get('Content-Type', '').startswith('application/json') else raw.decode()


def mcp_session(requests):
    p = subprocess.Popen([sys.executable, BIN, 'mcp'], env=ENV, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    out = []
    for req in requests:
        p.stdin.write(json.dumps(req) + '\n')
        p.stdin.flush()
        if 'id' in req:
            out.append(json.loads(p.stdout.readline()))
    p.terminate()
    return out


def main():
    print(f'fresh home: {TMP}\n')

    # 1. empty setup: doctor must say what's missing, with fixes, and nothing about API keys
    code, out = cli('doctor')
    check('doctor runs on an empty setup', 'Resume imported' in out, f'exit {code}')
    check('doctor flags the missing resume with a fix', 'Drop your resume' in out)
    check('doctor never asks for an API key', 'API_KEY' not in out and 'api key' not in out.lower().replace('no api key', ''))

    # 2. import a resume from a non-CS field
    path = os.path.join(TMP, 'maya_resume.txt')
    open(path, 'w').write(RESUME)
    code, out = cli('import', path, timeout=600)
    check('resume import', code == 0, out.strip().splitlines()[-1] if out.strip() else '')
    app_home = ENV.get('JOB_APPLIER_HOME') or ENV['APPLYTWIN_HOME']
    vault = json.load(open(os.path.join(app_home, 'resume.json')))
    check('vault has experience', len(vault.get('experience', [])) >= 1, f"{len(vault.get('experience', []))} entries")
    prof = json.load(open(os.path.join(app_home, 'profile.json')))
    check('profile filled from resume', prof.get('email') == 'maya.chen@example.edu', prof.get('name', ''))

    # 3. web server: pages and endpoints a new user hits
    global AUTH_COOKIE
    sys.path.insert(0, ROOT)
    from job_applier import local_auth, store
    store.HOME = app_home
    local_auth.configure('maya.chen@example.edu', 'test-password-123')

    srv = subprocess.Popen([sys.executable, BIN, 'app', '--no-open', '--port', str(PORT)], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                login_req = urllib.request.Request(f'http://127.0.0.1:{PORT}/api/auth/login',
                    data=json.dumps({'email': 'maya.chen@example.edu', 'password': 'test-password-123'}).encode(),
                    headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(login_req, timeout=10) as r:
                    AUTH_COOKIE = r.headers.get('Set-Cookie', '').split(';')[0]
                break
            except Exception:
                time.sleep(0.2)
        html = http('/')
        check('web app serves', '<div id="root"' in html or 'id="root"' in html)
        import socket
        with socket.create_connection(('127.0.0.1', PORT), timeout=10) as sk:   # exactly one reply per request (no stray 404 after it)
            sk.sendall(f'GET /api/version HTTP/1.1\r\nHost: localhost\r\nCookie: {AUTH_COOKIE}\r\nConnection: close\r\n\r\n'.encode())
            raw = b''
            while True:
                chunk = sk.recv(65536)
                if not chunk:
                    break
                raw += chunk
        with socket.create_connection(('127.0.0.1', PORT), timeout=10) as sk:   # Google sending you back after sign-in must open the app
            sk.sendall(b'GET / HTTP/1.1\r\nHost: localhost\r\nSec-Fetch-Site: cross-site\r\nSec-Fetch-Mode: navigate\r\nConnection: close\r\n\r\n')
            back = sk.recv(200)
        check('returning from Google sign-in opens the app', back.startswith(b'HTTP/1.0 200'), back[:30].decode(errors='replace'))
        check('one reply per request', raw.count(b'HTTP/1.') == 1 and raw.startswith(b'HTTP/1.0 200'), raw[:40].decode(errors='replace'))
        d = http('/api/doctor')
        check('/api/doctor', 'items' in d, f"{sum(i['ok'] for i in d['items'])}/{len(d['items'])} ok")
        a = http('/api/agents')
        check('/api/agents reports both agents', set(a) == {'claude', 'codex'},
              ', '.join(f"{k}: {'signed in' if v['signed_in'] else 'signed out' if v['installed'] else 'not installed'}" for k, v in a.items()))

        # 4. add a job by URL + description, then the queue
        j = http('/api/jobs', {'url': 'https://jobs.lever.co/examplehealth/0f6c1f0e-1111-4c2b-9d7a-123456789abc', 'title': 'Summer 2027 Nursing Extern',
                               'company': 'Example Health', 'description': JD})
        check('add a job', j.get('id'), j.get('id', ''))
        q = http('/api/queue?n=10')
        check('job reaches the queue', any(x['id'] == j['id'] for x in q['jobs']), f"{q['total']} in queue")

        # 5. tailor + PDF (heuristic when no agent is signed in in this throwaway home)
        t = http(f"/api/jobs/{j['id']}/tailor", {'mode': 'auto'})
        check('tailored resume', t.get('pdf') and os.path.exists(t['pdf']), f"mode {t.get('mode')}, {t.get('pages')} page(s)")
        check('fits on one page', t.get('pages') == 1)
        txt = open(t['pdf'], 'rb').read()
        check('PDF is real', txt[:4] == b'%PDF' and len(txt) > 5000, f'{len(txt):,} bytes')

        # 6. answers the bank already knows for a new user
        # nothing is assumed: before onboarding, work authorization is unanswered, and asking creates a 'Needs you' item
        q = http('/api/questions')
        check('onboarding lists unanswered questions', len(q['missing']) > 10, f"{len(q['missing'])} to answer")
        blank = http('/api/answer/test', {'questions': ['Are you legally authorized to work in the United States?']})[0]
        check('a blank answer is never guessed', blank.get('answer') is None)
        check('trying a question on the Answers page notifies no one', not http('/api/inbox')['items'])
        # a real form asking it (through the agent's tool) tells the user exactly what to add
        mcp_session([{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
                     {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'job_applier_answer_questions',
                      'arguments': {'questions': ['Are you legally authorized to work in the United States?']}}}])
        inbox = http('/api/inbox')['items']
        check('...and the user is told what to add', any('authorized to work' in i['title'] for i in inbox), inbox[0]['title'] if inbox else '')
        # the user answers them once (as onboarding does), and every form gets them
        prof = http('/api/state')['profile']
        prof.update(work_authorized_us=True, needs_sponsorship=False, grad_month='May', grad_year='2028')
        http('/api/profile', prof)
        ans = http('/api/answer/test', {'questions': ['Are you legally authorized to work in the United States?', 'What is your expected graduation date?',
                                                      'Will you now or in the future require sponsorship?']})
        check('answers given once are used on every form', [x.get('answer') for x in ans] == ['Yes', 'May 2028', 'No'],
              ' | '.join(str(x.get('answer')) for x in ans))

        # 7. run guard: starting an agent that isn't signed in must fail with the fix, not hang
        name = next((k for k, v in a.items() if v['installed'] and not v['signed_in']), None)
        if name:
            try:
                http('/api/run', {'agent': name, 'n': 1})
                check('signed-out run is refused', False)
            except urllib.error.HTTPError as e:
                msg = json.loads(e.read()).get('error', '')
                check('signed-out run is refused with the fix', 'signed out' in msg.lower() and ('login' in msg), msg)
    finally:
        srv.terminate()

    # 8. MCP server over stdio, the way Claude Code / Codex talk to it
    init = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'e2e', 'version': '1'}}}
    out = mcp_session([init, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                       {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'job_applier_setup_status', 'arguments': {}}}])
    tools = out[1].get('result', {}).get('tools', [])
    check('MCP initialize', out[0].get('result', {}).get('serverInfo'))
    check('MCP lists tools', len(tools) >= 30, f'{len(tools)} tools')
    check('MCP tool call works', not out[2].get('error') and out[2].get('result', {}).get('content'))

    # 9. install-agents writes working configs for both agents (into the throwaway HOME)
    code, out = cli('install-agents', timeout=300)
    check('install-agents runs', code == 0, out.strip().replace('\n', ' | ')[:160])
    ccfg = os.path.join(TMP, '.codex', 'config.toml')
    if True:
        t = open(ccfg).read() if os.path.exists(ccfg) else ''
        check('Codex config has Job Applier + browser', ('[mcp_servers.job_applier]' in t or '[mcp_servers.applytwin]' in t) and '[mcp_servers.playwright]' in t)
        check('Codex config pre-approves Job Applier tools', t.count('default_tools_approval_mode') >= 2)
        check('Codex skills installed', os.path.isdir(os.path.join(TMP, '.agents', 'skills', 'job-applier-apply')) or os.path.isdir(os.path.join(TMP, '.agents', 'skills', 'applytwin-apply')))
    check('Claude Code registration ran', 'Claude Code' in out)   # stand-in CLI: real registration is covered by e2e_agents

    code, out = cli('doctor')
    check('doctor after setup: agents connected, sign-in flagged', 'Resume imported' in out and 'connected to' in out and 'signed in' in out)

    bad = [n for n, ok in results if not ok]
    print(f'\n{len(results) - len(bad)}/{len(results)} passed' + (f"  failed: {', '.join(bad)}" if bad else ''))
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
