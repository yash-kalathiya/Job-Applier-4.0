"""The user's own coding agents (Claude Code, Codex): where they are, whether they're signed in, and a full setup check.

Job Applier 4.0 never needs an API key. Everything that needs a model runs on the subscription the user already pays for,
through the `claude` or `codex` command line.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

from . import store

NAMES = {'claude': 'Claude Code', 'codex': 'Codex'}
INSTALL = {'claude': 'npm install -g @anthropic-ai/claude-code', 'codex': 'npm install -g @openai/codex'}
LOGIN = {'claude': 'claude  (then type /login)', 'codex': 'codex login'}
FALLBACK_MODEL = [False]   # set once Codex rejects the configured model, so later calls go straight to a supported one
_cache = {}


def exe(name):
    return shutil.which(name)


def _run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, stdin=subprocess.DEVNULL, **store.NOWIN)
        return r.returncode, (r.stdout or '') + (r.stderr or '')
    except Exception as e:
        return 1, str(e)


def status(name, fresh=False):
    """{installed, signed_in, version, how} for one agent; cached for a few minutes because the checks spawn processes."""
    hit = _cache.get(name)
    if hit and not fresh and time.time() - hit[0] < 300:
        return hit[1]
    path = exe(name)
    out = {'name': name, 'label': NAMES[name], 'installed': bool(path), 'signed_in': False, 'version': '', 'how': ''}
    if path:
        lines = _run([path, '--version'])[1].strip().splitlines()
        out['version'] = lines[-1] if lines else ''
        if name == 'claude':
            code, txt = _run([path, 'auth', 'status'])
            try:
                d = json.loads(txt[txt.index('{'):txt.rindex('}') + 1])
                out['signed_in'] = bool(d.get('loggedIn'))
                out['how'] = d.get('authMethod', '')
            except ValueError:
                out['signed_in'] = code == 0 and 'logged in' in txt.lower()
        else:
            code, txt = _run([path, 'login', 'status'])
            out['signed_in'] = code == 0 and 'logged in' in txt.lower()
            out['how'] = next((l.strip() for l in txt.splitlines() if 'logged' in l.lower()), '')
    _cache[name] = (time.time(), out)
    return out


def preferred(profile):
    """Signed-in agents, the user's choice first."""
    first = (profile.get('apply') or {}).get('agent') or 'claude'
    order = [first] + [n for n in NAMES if n != first]
    return [n for n in order if status(n)['signed_in']]


def any_ready():
    return any(status(n)['signed_in'] for n in NAMES)


def codex_model_args():
    """The config's model can be newer than this CLI or plan allows (the desktop app sets it); pick one the CLI lists."""
    home = os.path.expanduser('~/.codex')
    try:
        want = re.search(r'^model\s*=\s*"([^"]+)"', open(os.path.join(home, 'config.toml'), encoding='utf-8').read(), re.M)
        cached = json.load(open(os.path.join(home, 'models_cache.json'), encoding='utf-8'))
        models = cached.get('models', cached) if isinstance(cached, dict) else cached
        slugs = [m.get('slug') for m in models if isinstance(m, dict)]
    except Exception:
        return []
    bad = rejected_models()
    usable = [x for x in slugs if x and 'reserve' not in x and 'review' not in x and x not in bad]
    want = want and want.group(1)
    if usable and (FALLBACK_MODEL[0] or not want or want not in slugs or want in bad):
        return ['-m', usable[0]]
    return []


def rejected_models():
    try:
        return set(json.load(open(store.path('codex_rejected.json'), encoding='utf-8')))
    except Exception:
        return set()


def reject_model(output):
    """Codex said 'The X model is not supported' (its model list includes models a plan can't use, and nothing in it says
    which): remember X so every later call, here and in Autopilot, goes to the next listed model. True if one was noted."""
    m = re.search(r"the '([^']+)' model is not supported", output or '', re.I)
    if not m:
        return False
    bad = rejected_models() | {m.group(1)}
    with open(store.path('codex_rejected.json'), 'w', encoding='utf-8') as f:
        json.dump(sorted(bad), f)
    FALLBACK_MODEL[0] = True
    return True


# ------------------------------------------------------------------ doctor

def doctor():
    """Everything a new user needs, checked. Each item: {id, ok, label, detail, fix}. Nothing here needs an API key."""
    from . import store
    items = []

    def add(id, ok, label, detail='', fix='', optional=False):
        items.append({'id': id, 'ok': bool(ok), 'label': label, 'detail': detail, 'fix': fix, 'optional': optional})

    v = sys.version_info
    add('python', v >= (3, 9), 'Python 3.9+', f'{v.major}.{v.minor}.{v.micro}', 'Install Python from python.org')
    ag = [status(n, fresh=True) for n in NAMES]
    for a in ag:
        if not a['installed']:
            add(a['name'], False, f"{a['label']} installed", 'not found on PATH', INSTALL[a['name']], optional=True)
        else:
            add(a['name'], a['signed_in'], f"{a['label']} signed in", a['version'] + (f" · {a['how']}" if a['how'] else ''),
                '' if a['signed_in'] else f"Run: {LOGIN[a['name']]}", optional=True)
    add('agent', any(a['signed_in'] for a in ag), 'At least one agent ready', 'Claude Code or Codex, on your own subscription',
        'Install and sign in to Claude Code or Codex (any paid plan works, no API key)')
    add('npx', bool(shutil.which('npx')), 'Node.js (for the browser)', shutil.which('npx') or 'npx not found', 'Install Node.js from nodejs.org')
    cfg = os.path.expanduser('~/.claude.json')
    claude_mcp = os.path.exists(cfg) and any(k in open(cfg, encoding='utf-8').read() for k in ('job_applier', 'applytwin'))
    ccfg = os.path.expanduser('~/.codex/config.toml')
    ctxt = open(ccfg, encoding='utf-8').read() if os.path.exists(ccfg) else ''
    if ag[0]['installed']:
        add('claude_mcp', claude_mcp or _claude_has_mcp(), 'Job Applier 4.0 connected to Claude Code', '', 'Run: job-applier install-agents', optional=True)
    if ag[1]['installed']:
        add('codex_mcp', any(k in ctxt for k in ('[mcp_servers.job_applier]', '[mcp_servers.applytwin]')), 'Job Applier 4.0 connected to Codex', '', 'Run: job-applier install-agents', optional=True)
        add('codex_approve', 'default_tools_approval_mode' in ctxt, 'Codex can run Job Applier 4.0 unattended', '', 'Run: job-applier install-agents', optional=True)
    p = store.profile()
    vault = store.resume()
    add('resume', bool(vault.get('experience') or vault.get('projects')), 'Resume imported', '', 'Drop your resume on the Welcome page')
    from . import answers as ans
    miss = ans.gaps(p)
    add('profile', not miss, 'Application answers complete',
        'all answered' if not miss else f"{len(miss)} unanswered: " + ', '.join(m['label'] for m in miss[:4]) + ('…' if len(miss) > 4 else ''),
        'Answer them in Settings (your twin asks instead of guessing)')
    n = store.rows('select count(*) n from jobs')[0]['n'] if _has_table('jobs') else 0
    add('jobs', n > 0, 'Jobs found', f'{n:,} in your database', 'Press Scan on the Jobs page')
    ready = all(i['ok'] for i in items if not i['optional'])
    return {'ok': ready, 'items': items}


def _claude_has_mcp():
    path = exe('claude')
    if not path:
        return False
    code, txt = _run([path, 'mcp', 'get', 'job_applier'], timeout=30)
    if code == 0:
        return True
    code, txt = _run([path, 'mcp', 'get', 'applytwin'], timeout=30)
    return code == 0


def _has_table(t):
    from . import store
    return bool(store.rows("select name from sqlite_master where type='table' and name=?", (t,)))
