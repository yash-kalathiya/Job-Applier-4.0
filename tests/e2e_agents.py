"""The parts that talk to Claude Code and Codex, on every OS (Windows included), with stand-in agent commands.

Real `claude`/`codex` need a paid login, so this puts fake ones on PATH (.cmd files on Windows, which is exactly how npm
installs them there) and checks: sign-in detection, the Codex config Job Applier 4.0 writes is valid TOML (Windows paths!),
an Autopilot run delivers its instructions intact (quotes, ampersands, newlines) and logs the agent's output, a one-shot
subscription LLM call returns the agent's reply, desktop notifications don't crash, a PDF browser is found, and a
self-update can swap the app folder while the app is running.

    python3 tests/e2e_agents.py
"""
import json
import os
os.environ["JOB_APPLIER_NO_TELEMETRY"] = "1"
os.environ["APPLYTWIN_NO_TELEMETRY"] = "1"   # tests never count as installs
os.environ["JOB_APPLIER_SKIP_SIGNIN"] = "1"
os.environ["APPLYTWIN_SKIP_SIGNIN"] = "1"   # no Google account in tests
import shutil
import subprocess
import sys
import tempfile
import time
for _s in (sys.stdout, sys.stderr):   # Windows consoles default to cp1252, which can't print emoji
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN = os.name == 'nt'
TMP = tempfile.mkdtemp(prefix='job-applier-agents-')
BIN = os.path.join(TMP, 'fakebin')
os.makedirs(BIN)
os.environ.update(HOME=TMP, USERPROFILE=TMP, APPLYTWIN_HOME=os.path.join(TMP, '.applytwin'),
                  PATH=BIN + os.pathsep + os.environ.get('PATH', ''))
os.environ.pop('ANTHROPIC_API_KEY', None)
os.environ.pop('OPENAI_API_KEY', None)

# A stand-in agent: answers --version / auth status / login status, and for a run echoes back what it got on stdin.
FAKE = r'''
import json, os, sys

a = sys.argv[1:]
name = os.environ.get('FAKE_NAME', 'agent')
if a[:1] == ['--version']: print(f'9.9.9 ({name})'); sys.exit(0)
if a[:2] == ['auth', 'status']: print(json.dumps({"loggedIn": True, "authMethod": "claude.ai"})); sys.exit(0)
if a[:2] == ['login', 'status']: print('Logged in using ChatGPT'); sys.exit(0)
if a[:1] == ['mcp']: sys.exit(0)
if a[:1] == ['plugin']: sys.exit(1)
data = sys.stdin.read()
open(os.path.join(os.environ['APPLYTWIN_HOME'], f'{name}_stdin.txt'), 'w', encoding='utf-8').write(data)
if 'HANG' in data:   # an agent stuck on one application
    import time; time.sleep(120)
if '-o' in a:   # codex exec -o FILE: last message goes to the file
    open(a[a.index('-o') + 1], 'w').write('{"ok": true, "from": "%s"}' % name)
print(f'{name} received {len(data)} chars')
'''


def make_fake(name):
    py = os.path.join(BIN, f'fake_{name}.py')
    open(py, 'w').write(FAKE)
    if WIN:
        with open(os.path.join(BIN, f'{name}.cmd'), 'w') as f:
            f.write(f'@echo off\r\nset FAKE_NAME={name}\r\n"{sys.executable}" "{py}" %*\r\n')
    else:
        p = os.path.join(BIN, name)
        with open(p, 'w') as f:
            f.write(f'#!/bin/sh\nFAKE_NAME={name} exec "{sys.executable}" "{py}" "$@"\n')
        os.chmod(p, 0o755)


results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok)))
    print(('\033[32mPASS\033[0m ' if ok else '\033[31mFAIL\033[0m ') + name + (f'  \033[2m{detail}\033[0m' if detail else ''))


def main():
    for n in ('claude', 'codex'):
        make_fake(n)
    sys.path.insert(0, ROOT)
    from job_applier import agents, api, install, render, store, tailor

    st = {n: agents.status(n, fresh=True) for n in ('claude', 'codex')}
    check('agents detected and signed in', all(s['installed'] and s['signed_in'] for s in st.values()),
          ', '.join(f"{n}: {s['version']}" for n, s in st.items()))
    d = agents.doctor()
    check('doctor sees a ready agent', next(i for i in d['items'] if i['id'] == 'agent')['ok'])

    # install-agents writes a Codex config that must parse (Windows paths have backslashes)
    out = install.install_codex()
    cfg = os.path.join(TMP, '.codex', 'config.toml')
    try:
        import tomllib
        parsed = tomllib.loads(open(cfg).read())
        mcp_key = 'job_applier' if 'job_applier' in parsed.get('mcp_servers', {}) else 'applytwin'
        ok = parsed['mcp_servers'][mcp_key]['command'] == sys.executable
        check('Codex config is valid TOML with the right paths', ok, parsed['mcp_servers'][mcp_key]['command'])
    except ModuleNotFoundError:
        check('Codex config written', '[mcp_servers.job_applier]' in open(cfg).read() or '[mcp_servers.applytwin]' in open(cfg).read(), 'tomllib needs Python 3.11+')
    check('install_claude runs', 'Claude Code' in install.install_claude())

    # an Autopilot run: the instructions must arrive whole, even with quotes, ampersands and newlines
    from job_applier import local_auth
    local_auth.configure('test@example.com', 'test-password-123')
    store.save('resume.json', {"basics": {"name": "Test"}, "experience": [{"org": "A", "title": "B", "bullets": ["c"]}]})
    for agent in ('claude', 'codex'):
        api.start_run(agent, 3)
        for _ in range(100):
            if not api.run_status()['running']:
                break
            time.sleep(0.2)
        got = open(os.path.join(os.environ['APPLYTWIN_HOME'], f'{agent}_stdin.txt'), encoding='utf-8').read()
        want = api.run_prompt(3)
        log = api.run_status()['log']
        check(f'{agent}: Autopilot instructions delivered intact', got == want and ('"' in want or "'" in want), f'{len(got)} chars')
        check(f'{agent}: run output logged', f'{agent} received' in log)

    # finishing one specific application (Refill / Submit it / I signed in, finish it) reaches the agent with that job
    from job_applier import sources
    j = sources.job('manual', 'https://jobs.lever.co/acme/1234', 'Acme', 'Software Engineer Intern', '', 'https://jobs.lever.co/acme/1234')
    store.execute('insert or replace into jobs(id,source,company,title,url,apply_url,ats,found_at,fit,status) values(?,?,?,?,?,?,?,?,?,?)',
                  (j['id'], 'manual', 'Acme', 'Software Engineer Intern', j['url'], j['url'], 'lever', time.time(), 80, 'new'))
    api.finish_jobs([j['id']], submit=True, agent='claude')
    for _ in range(100):
        if not api.run_status()['running']:
            break
        time.sleep(0.2)
    got = open(os.path.join(os.environ['APPLYTWIN_HOME'], 'claude_stdin.txt'), encoding='utf-8').read()
    check('finish one application: the agent gets that job and the submit go-ahead', j['id'] in got and 'SUBMIT each one' in got)

    # a run stuck on one application gets skipped past, and a "finish it" pressed mid-run is queued, then done right after
    j2 = sources.job('manual', 'https://jobs.lever.co/acme/5678', 'Acme', 'Data Intern', '', 'https://jobs.lever.co/acme/5678')
    store.execute('insert or replace into jobs(id,source,company,title,url,apply_url,ats,found_at,fit,status) values(?,?,?,?,?,?,?,?,?,?)',
                  (j2['id'], 'manual', 'Acme', 'Data Intern', j2['url'], j2['url'], 'lever', time.time(), 80, 'new'))
    store.save('profile.json', {**store.profile(), "apply": {**store.profile()['apply'], "stuck_minutes": 0.1}})
    api.start_run('claude', 1, prompt='HANG on this one')
    time.sleep(0.5)
    api.claim(j2['id'])
    q = api.finish_jobs([j['id']], submit=False, agent='claude')
    t0 = time.time()
    while time.time() - t0 < 60:
        got = open(os.path.join(os.environ['APPLYTWIN_HOME'], 'claude_stdin.txt'), encoding='utf-8').read()
        if 'Finish these specific' in got and 'Stop on the review screen' in got:
            break
        time.sleep(0.5)
    st = store.rows('select status from applications where job_id=? order by at desc', (j2['id'],))
    check('mid-run "finish it" is queued, not dropped', q.get('queued') and 'Stop on the review screen' in got)
    check('a stuck application is skipped (logged Needs User) after the timeout', st and st[0]['status'] == 'Needs User',
          f'{time.time() - t0:.0f}s')
    for _ in range(100):
        if not api.run_status()['running']:
            break
        time.sleep(0.2)
    store.save('profile.json', {**store.profile(), "apply": {**store.profile()['apply'], "stuck_minutes": 20}})

    # talking to the twin about one application: instant answers, "I submitted it", and real requests that reach the agent
    j3 = sources.job('manual', 'https://jobs.lever.co/acme/9999', 'Acme', 'Quant Intern', '', 'https://jobs.lever.co/acme/9999')
    store.execute('insert or replace into jobs(id,source,company,title,url,apply_url,ats,found_at,fit,status) values(?,?,?,?,?,?,?,?,?,?)',
                  (j3['id'], 'manual', 'Acme', 'Quant Intern', j3['url'], j3['url'], 'lever', time.time(), 80, 'new'))
    api.notify('Acme needs a CAPTCHA', 'Solve it in the open tab, then submit', job_id=j3['id'])
    api.log_application(j3['id'], 'Needs User', 'Filled; blocked by hCaptcha')
    t1 = api.message(j3['id'], 'did you submit this?')['thread']
    check('"did you submit this?" gets an instant, true answer', t1[-1]['role'] == 'twin' and t1[-1]['text'].startswith('No, it isn'), t1[-1]['text'][:60])
    api.message(j3['id'], 'use my "CMU" project for the why-us answer & resubmit')
    for _ in range(100):
        if not api.run_status()['running']:
            break
        time.sleep(0.2)
    got = open(os.path.join(os.environ['APPLYTWIN_HOME'], 'claude_stdin.txt'), encoding='utf-8').read()
    check('a request about one application reaches the agent with that job and your words', j3['id'] in got and 'use my "CMU" project' in got and any(k in got for k in ('job_applier_reply', 'applytwin_reply')))
    api.reply(j3['id'], 'Updated the answer and submitted it.')
    check("the twin's reply shows in that application's conversation", api.thread(j3['id'])[-1]['text'] == 'Updated the answer and submitted it.')
    t2 = api.message(j3['id'], 'I submitted it myself')['thread']
    check('"I submitted it" marks it applied and clears it from Needs you',
          t2[-1]['text'] == 'Marked as applied.' and not any(r['job_id'] == j3['id'] for r in api.pending_jobs()) and
          not any(i['job_id'] == j3['id'] for i in api.inbox()))

    # roles already applied to elsewhere (found in email) stay out of the queue, even ones a later scan finds
    r = api.import_applied([{'company': 'Initech', 'title': 'Software Engineer Intern - Summer 2027'},
                            {'company': 'Globex', 'title': 'Data Analyst Intern', 'url': 'https://boards.greenhouse.io/globex/jobs/7654321'}])
    for jid, co, title, url in (('later1', '⭐ Initech', 'Software Engineer Intern (Summer 2027)', 'https://x.com/a'),
                                ('later2', 'Globex Corp', 'Analyst Intern, Data', 'https://job-boards.greenhouse.io/globex/jobs/7654321')):
        store.execute('insert or replace into jobs(id,source,company,title,url,apply_url,ats,found_at,fit,status) values(?,?,?,?,?,?,?,?,?,?)',
                      (jid, 'test', co, title, url, url, 'greenhouse', time.time(), 90, 'new'))
    q = [j['id'] for j in api.queue(500)['jobs']]
    check('applied-elsewhere roles never come back (by name or by job link)', r['added'] == 2 and 'later1' not in q and 'later2' not in q,
          f"{r['added']} recorded")
    api.start_run('claude', 1, prompt=api.email_history_prompt())
    for _ in range(100):
        if not api.run_status()['running']:
            break
        time.sleep(0.2)
    got = open(os.path.join(os.environ['APPLYTWIN_HOME'], 'claude_stdin.txt'), encoding='utf-8').read()
    check('Find them in my email reaches the agent with the steps', 'thank you for applying' in got and any(k in got for k in ('job_applier_import_applied', 'applytwin_import_applied')))

    # in-app tailoring on the subscription (no API key) returns the agent's JSON
    agents._cache.clear()
    store.save('profile.json', {**store.profile(), "apply": {**store.profile()['apply'], "agent": "codex"}})
    r = tailor.call_llm('Reply with JSON & "quotes" please')
    check('subscription LLM call returns the reply', r and r.get('from') == 'codex', json.dumps(r))

    try:
        if os.environ.get('CI'):   # only on CI machines, so running tests locally doesn't pop a real notification
            install.notify('Job Applier 4.0 test', 'Code needed for "Acme" & co')
        check('desktop notification does not crash', True)
    except Exception as e:
        check('desktop notification does not crash', False, str(e))

    try:
        check('a PDF browser is found', bool(render.chrome()), render.chrome())
    except RuntimeError as e:
        check('a PDF browser is found', False, str(e))

    # self-update swaps the app folder in place (Windows refuses to rename folders with open files)
    app = os.path.join(TMP, 'app')
    shutil.copytree(ROOT, app, ignore=shutil.ignore_patterns('.git', 'node_modules', 'site', '__pycache__'))
    code = ("import sys, os; sys.path.insert(0, sys.argv[1]); from job_applier import update; update.APP = sys.argv[1]; "
            "src = sys.argv[2]; import shutil; "
            "update._get = lambda url, timeout=8: open(src, 'rb').read(); print(update.apply('0' * 40))")
    open(os.path.join(app, 'job-applier.cmd'), 'w').write('@echo installer-made\r\n')   # the Windows installer's command
    tgz = os.path.join(TMP, 'new.tgz')
    import tarfile
    with tarfile.open(tgz, 'w:gz') as t:
        t.add(app, arcname='job-applier-new', filter=lambda i: None if '__pycache__' in i.name else i)
    r = subprocess.run([sys.executable, '-c', code, app, tgz], capture_output=True, text=True, timeout=120)
    check('self-update swaps the app folder and keeps the command',
          "'updated': True" in r.stdout and os.path.exists(os.path.join(app, 'INSTALLED')) and (os.path.exists(os.path.join(app, 'job-applier.cmd')) or os.path.exists(os.path.join(app, 'applytwin.cmd'))),
          (r.stdout + r.stderr).strip()[-160:])

    # a failed update never leaves you without an app: a bad download changes nothing, and a swap that breaks halfway
    # puts the working version back
    code2 = ("import sys, os; sys.path.insert(0, sys.argv[1]); from job_applier import update; update.APP = sys.argv[1]; "
             "update.installed = lambda: 'x'; src = sys.argv[2]; mode = sys.argv[3]; "
             "update._get = (lambda url, timeout=8: b'not a tarball') if mode == 'bad' else (lambda url, timeout=8: open(src, 'rb').read()); "
             "real = os.rename; n = [0]\n"
             "def flaky(a, b):\n"
             "    n[0] += 1\n"
             "    if mode == 'swap' and n[0] == 2: raise OSError('disk full')\n"
             "    return real(a, b)\n"
             "os.rename = flaky\n"
             "try: print(update.apply('1' * 40))\n"
             "except Exception as e: print('error', e)\n")
    for mode in ('bad', 'swap'):
        r = subprocess.run([sys.executable, '-c', code2, app, tgz, mode], capture_output=True, text=True, timeout=120)
        check(f'a failed update ({mode}) leaves the app working', (os.path.exists(os.path.join(app, 'bin', 'job-applier')) or os.path.exists(os.path.join(app, 'bin', 'applytwin')))
              and (os.path.exists(os.path.join(app, 'job_applier', 'server.py')) or os.path.exists(os.path.join(app, 'applytwin', 'server.py'))), (r.stdout + r.stderr).strip()[-120:])

    bad = [n for n, ok in results if not ok]
    print(f'\n{len(results) - len(bad)}/{len(results)} passed' + (f"  failed: {', '.join(bad)}" if bad else ''))
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
