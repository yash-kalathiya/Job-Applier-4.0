"""job-applier <command>

  job-applier app                 open the web app (http://localhost:4747)
  job-applier scan                scrape every source and score matches
  job-applier jobs [query]        list top matches
  job-applier extract URL --out DIRECTORY   inspect questions with DOM + accessibility (Phase 1)
  job-applier resolve QUESTIONS.json --out ANSWERS.json   match questions to facts (Phase 2)
  job-applier fill URL --answers ANSWERS.json --out DIR   fill application form (Phase 3)
  job-applier tailor JOB_ID [--template classic] [--plan plan.json]
  job-applier render [--template classic]       master resume PDF
  job-applier ats [JOB_ID]        ATS report for the vault (vs a job)
  job-applier templates           list resume templates
  job-applier mcp                 run the MCP server (used by Claude Code / Codex)
  job-applier install-agents      register Job Applier 4.0 with Claude Code and Codex on this machine
  job-applier watch [--every 120] keep scanning; notify on new matches
  job-applier import FILE      import a resume (pdf, docx, tex, txt) into your vault
  job-applier queue            show your apply queue (dream companies first)
  job-applier import-history tracker.csv   mark jobs you already applied to elsewhere
  job-applier run [--agent claude|codex] [--n 25]   let your agent work through the queue
  job-applier update           update to the latest version (installed copies also update themselves on start)
  job-applier doctor           check your setup (no API keys needed: it runs on your Claude / Codex plan)
"""
import json
import os
import sys
import time

from . import api


def _arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else default
    return default


def _p(x):
    print(json.dumps(x, indent=1, default=str, ensure_ascii=False))


def main():
    for stream in (sys.stdout, sys.stderr):   # Windows consoles default to cp1252, which can't print ✓ or →
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'app'
    if cmd in ('app', 'serve'):
        from .server import serve
        serve(int(_arg('--port', 4747)), '--no-open' not in sys.argv)
    elif cmd == 'extract':
        from .extraction.__main__ import main as extract
        sys.exit(extract(sys.argv[2:]))
    elif cmd == 'resolve':
        from .resolution.__main__ import main as resolve
        sys.exit(resolve(sys.argv[2:]))
    elif cmd == 'fill':
        from .filling.__main__ import main as fill
        sys.exit(fill(sys.argv[2:]))
    elif cmd == 'mcp':
        from .mcp import main as m
        m()
    elif cmd == 'scan':
        _p(api.scan())
    elif cmd == 'jobs':
        q = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('-') else ''
        for j in api.list_jobs(q, limit=int(_arg('--limit', 40))):
            print(f"{int(j['fit']):>3}  {j['id']}  {j['company'][:22]:<22} {j['title'][:70]}  [{j['ats']}]")
    elif cmd == 'tailor':
        plan = json.load(open(_arg('--plan'), encoding='utf-8')) if _arg('--plan') else None
        _p(api.tailor_apply(sys.argv[2], plan, _arg('--template'), 'agent' if plan else 'auto'))
    elif cmd == 'render':
        _p(api.render_resume(_arg('--template')))
    elif cmd == 'ats':
        _p(api.ats_report(sys.argv[2] if len(sys.argv) > 2 else None))
    elif cmd == 'templates':
        for t in api.templates():
            print(f"{t['id']:<9} {t['label']:<22} {t['best']}")
    elif cmd == 'import':
        import base64
        f = sys.argv[2]
        r = api.import_resume(os.path.basename(f), base64.b64encode(open(f, 'rb').read()).decode())
        print(r['message'])
    elif cmd == 'update':
        from . import update
        st = update.check()
        if not st['managed']:
            print('This is a git checkout: run git pull.')
        elif not st['available']:
            print(f"Already up to date ({st['current'] or 'unknown'}).")
        else:
            r = update.apply()
            print(f"Updated to {r['sha']}" if r.get('updated') else r.get('reason', 'No update applied.'))
    elif cmd == 'doctor':
        d = api.doctor()
        for i in d['items']:
            mark = '\033[32m✓\033[0m' if i['ok'] else ('\033[33m·\033[0m' if i['optional'] else '\033[31m✗\033[0m')
            print(f"{mark} {i['label']}" + (f"  \033[2m{i['detail']}\033[0m" if i['detail'] else ''))
            if not i['ok'] and i['fix']:
                print(f"    → {i['fix']}")
        print('\nReady to apply.' if d['ok'] else '\nFix the ✗ items above, then run `job-applier doctor` again.')
        print('\033[33m★\033[0m Star Job Applier 4.0 on GitHub: https://github.com/yash-kalathiya/Job-Applier-4.0')
        sys.exit(0 if d['ok'] else 1)
    elif cmd == 'import-history':
        _p(api.import_history(sys.argv[2]))
    elif cmd == 'queue':
        q = api.queue(int(_arg('--n', 30)))
        print(f"{q['total']} in queue ({q['dream']} at dream companies), {q['remaining_today']} left today")
        for j in q['jobs']:
            print(f"{'*' if j['dream'] else ' '} {int(j['fit']):>3}  {j['id']}  {j['company'][:22]:<22} {j['title'][:70]}")
    elif cmd == 'run':
        import shutil
        import subprocess
        agent, n = _arg('--agent', 'claude'), int(_arg('--n', 25))
        exe = shutil.which(agent) or sys.exit(f'{agent} not found on PATH')
        p = api.run_prompt(n)
        os.execv(exe, [exe, p] if agent == 'claude' else [exe, p])
    elif cmd == 'install-agents':
        from .install import install
        install()
    elif cmd == 'watch':
        every = int(_arg('--every', 120))
        seen = {j['id'] for j in api.list_jobs(status='all', limit=100000)}
        while True:
            api.scan(['smartrecruiters', 'community'])
            new = [j for j in api.list_jobs(order='new', limit=50) if j['id'] not in seen]
            for j in new:
                seen.add(j['id'])
                print(time.strftime('%H:%M'), int(j['fit']), j['company'], '|', j['title'], '|', j['apply_url'])
            if new:
                from .install import notify
                notify('Job Applier 4.0: new match', f"{new[0]['company']}: {new[0]['title']}" + (f' (+{len(new) - 1})' if len(new) > 1 else ''))
            time.sleep(every)
    else:
        print(__doc__)
