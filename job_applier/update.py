"""Self-update, so nobody has to maintain an install: on start, the app checks GitHub for a newer commit on main and,
if there is one, swaps in the new code before serving. A git checkout (a developer's copy) is never touched.

The installer records the commit it installed in INSTALLED; `job-applier update` does the same thing by hand.
"""
import json
import os
import shutil
import tarfile
import tempfile
import urllib.request

REPO = 'yash-kalathiya/Job-Applier-4.0'
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = os.path.join(APP, 'INSTALLED')


def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={'User-Agent': 'Job-Applier-updater', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def is_checkout():
    return os.path.isdir(os.path.join(APP, '.git'))


def installed():
    try:
        return open(MARK, encoding='utf-8').read().strip()
    except OSError:
        return ''


_cache = {}


def latest(max_age=1800):
    """The newest commit on main whose tests passed in CI, so a broken push never reaches anyone's install. Never older than
    what's installed (a re-run check on a newer commit must not cause a downgrade). Cached for 30 minutes: GitHub allows 60
    calls an hour per network, and a campus full of students shares one."""
    import time
    hit = _cache.get('latest')
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    cur = installed()
    sha = ''
    for c in json.loads(_get(f'https://api.github.com/repos/{REPO}/commits?sha=main&per_page=6')):
        if c['sha'] == cur:   # reached what's installed before finding a newer tested commit: stay
            sha = cur
            break
        runs = json.loads(_get(f"https://api.github.com/repos/{REPO}/commits/{c['sha']}/check-runs")).get('check_runs', [])
        if runs and all(r.get('status') == 'completed' and r.get('conclusion') in ('success', 'skipped', 'neutral') for r in runs):
            sha = c['sha']
            break
    _cache['latest'] = (time.time(), sha)
    return sha


def check():
    """{'current', 'latest', 'available', 'managed'}; never raises (offline just means no update)."""
    cur = installed()
    out = {"current": cur[:7], "latest": "", "available": False, "managed": not is_checkout()}
    if is_checkout():
        return out
    try:
        sha = latest()
        out.update(latest=sha[:7], available=bool(sha) and sha != cur)
    except Exception as e:   # offline or rate-limited: say so instead of claiming you're up to date
        out['error'] = "Couldn't reach GitHub to check for updates. It will try again later."
    return out


def ensure_command():
    """Windows: the `job-applier` command is job-applier.cmd in the app folder (on PATH). Updates before this fix replaced the
    folder without it, so put it back if it's missing."""
    if os.name != 'nt' or is_checkout():
        return
    cmd = os.path.join(APP, 'job-applier.cmd')
    if os.path.exists(cmd):
        return
    import sys
    py = sys.executable
    if os.path.basename(py).lower() == 'pythonw.exe':   # started from the Startup shortcut; the command needs a console
        py = os.path.join(os.path.dirname(py), 'python.exe')
    with open(cmd, 'w', encoding='ascii', errors='replace') as f:
        f.write(f'@"{py}" "%~dp0bin\\job-applier" %*\r\n')


def apply(sha=None):
    """Download main, replace the app folder in place (your data in ~/.job-applier is separate and untouched)."""
    if is_checkout():
        return {"updated": False, "reason": "This is a git checkout; use git pull."}
    sha = sha or latest()
    if not sha:
        return {"updated": False, "reason": "No tested version available right now."}
    if sha == installed():
        return {"updated": False, "reason": "Already on this version."}
    parent = os.path.dirname(APP)
    lock = os.path.join(parent, '.job-applier-updating')
    try:   # one updater at a time (the background service and a terminal `job-applier` could both try)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        import time
        if time.time() - os.path.getmtime(lock) < 600:
            return {"updated": False, "reason": "Another update is already running."}
        open(lock, 'w', encoding='utf-8').close()
    # download and unpack NEXT TO the app, so swapping it in is two instant renames on one disk (never a slow copy that a
    # restart could cut in half), and put the old version back if anything goes wrong
    tmp = tempfile.mkdtemp(prefix='.job-applier-update-', dir=parent)
    old = APP + '.old'
    swapped = False
    try:
        tgz = os.path.join(tmp, 'a.tgz')
        with open(tgz, 'wb') as f:
            f.write(_get(f'https://codeload.github.com/{REPO}/tar.gz/{sha}', timeout=60))
        with tarfile.open(tgz) as t:
            root = os.path.realpath(os.path.join(tmp, 'x'))
            for m in t.getmembers():   # refuse anything that would land outside the extraction folder
                if not os.path.realpath(os.path.join(root, m.name)).startswith(root + os.sep):
                    raise ValueError('unsafe path in update archive')
            t.extractall(root)
        new = next(os.path.join(root, d) for d in os.listdir(root))
        if not os.path.exists(os.path.join(new, 'bin', 'job-applier')):
            raise ValueError('incomplete download')
        for f in os.listdir(APP):   # keep what the installer made in the app folder (Windows: the job-applier.cmd command)
            if os.path.isfile(os.path.join(APP, f)) and not os.path.exists(os.path.join(new, f)) and f != 'INSTALLED':
                shutil.copy2(os.path.join(APP, f), os.path.join(new, f))
        with open(os.path.join(new, 'INSTALLED'), 'w', encoding='utf-8') as f:
            f.write(sha)
        os.chmod(os.path.join(new, 'bin', 'job-applier'), 0o755)
        shutil.rmtree(old, ignore_errors=True)
        os.rename(APP, old)
        swapped = True
        os.rename(new, APP)
        swapped = False
        shutil.rmtree(old, ignore_errors=True)
        return {"updated": True, "sha": sha[:7]}
    finally:
        if swapped and not os.path.exists(APP) and os.path.exists(old):
            os.rename(old, APP)   # the new version didn't land: put the working one back
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            os.remove(lock)
        except OSError:
            pass
