"""Register Job Applier 4.0 with the user's agents.

Claude Code: installs the plugin (skills + MCP server) from this folder's marketplace, or falls back to
             `claude mcp add` + copying skills into ~/.claude/skills.
Codex:       adds [mcp_servers.job_applier] to ~/.codex/config.toml and copies the skills into ~/.agents/skills.
"""
import json
import os
import re
import platform
import shutil
import subprocess
import sys

from . import store

APP = store.APP
JOB_APPLIER_BIN = os.path.join(APP, 'bin', 'job-applier')


def notify(title, msg):
    msg = msg.replace('"', "'")[:200]
    try:
        if platform.system() == 'Darwin':
            subprocess.run(['osascript', '-e', f'display notification "{msg}" with title "{title}" sound name "Glass"'], capture_output=True)
        elif platform.system() == 'Windows':
            ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
                  "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(1);"
                  f"$x = $t.GetElementsByTagName('text'); $x.Item(0).AppendChild($t.CreateTextNode('{title.replace(chr(39), '')}')) > $null;"
                  f"$x.Item(1).AppendChild($t.CreateTextNode('{msg.replace(chr(39), '')}')) > $null;"
                  "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Job Applier 4.0').Show([Windows.UI.Notifications.ToastNotification]::new($t))")
            subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, creationflags=0x08000000)
        elif shutil.which('notify-send'):
            subprocess.run(['notify-send', title, msg], capture_output=True)
    except Exception:
        pass


def _skills_src():
    return os.path.join(APP, 'skills')


def _copy_skills(dest):
    os.makedirs(dest, exist_ok=True)
    for name in os.listdir(_skills_src()):
        src = os.path.join(_skills_src(), name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dest, name), dirs_exist_ok=True)


BROWSER_PROFILE = os.path.join(store.HOME, 'browser')
PLAYWRIGHT = [shutil.which('npx') or 'npx' if platform.system() == 'Windows' else 'npx', '-y', '@playwright/mcp@latest', '--user-data-dir', BROWSER_PROFILE] \
    + ([] if platform.system() == 'Linux' else ['--sandbox'])


def _pw_claude():
    return (['cmd', '/c', 'npx'] + PLAYWRIGHT[1:]) if platform.system() == 'Windows' else PLAYWRIGHT


def _add_playwright(claude, previous=None):
    subprocess.run([claude, 'mcp', 'remove', '--scope', 'user', 'playwright'], capture_output=True, timeout=60, **store.NOWIN)
    r = subprocess.run([claude, 'mcp', 'add', '--scope', 'user', 'playwright', '--'] + _pw_claude(), capture_output=True, timeout=60, **store.NOWIN)
    if r.returncode != 0 and previous:
        subprocess.run([claude, 'mcp', 'add', '--scope', 'user', 'playwright', '--', previous['command']] + list(previous.get('args') or []),
                       capture_output=True, timeout=60, **store.NOWIN)


def install_claude():
    claude = shutil.which('claude')
    if not claude:
        return 'Claude Code CLI not found (skip). Install it, then rerun: job-applier install-agents'
    if shutil.which('npx'):
        _add_playwright(claude)
    _drop_plugin(claude)
    r3 = _claude_direct(claude)
    return ('Claude Code: MCP server added and skills copied to ~/.claude/skills' if r3.returncode == 0
            else f'Claude Code: could not add MCP ({r3.stderr.strip()[:200]})')


def _python():
    py = sys.executable
    if os.path.basename(py).lower() == 'pythonw.exe':
        py = os.path.join(os.path.dirname(py), 'python.exe')
    return py


def _claude_direct(claude):
    subprocess.run([claude, 'mcp', 'remove', '--scope', 'user', 'job_applier'], capture_output=True, timeout=60)
    subprocess.run([claude, 'mcp', 'remove', '--scope', 'user', 'applytwin'], capture_output=True, timeout=60)
    r = subprocess.run([claude, 'mcp', 'add', '--scope', 'user', 'job_applier', '--', _python(), JOB_APPLIER_BIN, 'mcp'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    _copy_skills(os.path.expanduser('~/.claude/skills'))
    return r


def _plugin_installed():
    try:
        d = json.load(open(os.path.expanduser('~/.claude/plugins/installed_plugins.json'), encoding='utf-8'))
        return any(k in (d.get('plugins', d) or {}) for k in ('job-applier@job-applier', 'applytwin@applytwin'))
    except (OSError, ValueError):
        return False


def _drop_plugin(claude):
    if _plugin_installed():
        subprocess.run([claude, 'plugin', 'uninstall', '--scope', 'user', 'job-applier@job-applier'], capture_output=True, timeout=60)
        subprocess.run([claude, 'plugin', 'uninstall', '--scope', 'user', 'applytwin@applytwin'], capture_output=True, timeout=60)


def refresh_agents():
    refresh_browser()
    claude = shutil.which('claude')
    if not claude:
        return
    try:
        cj = os.path.expanduser('~/.claude.json')
        cur = (json.load(open(cj, encoding='utf-8')).get('mcpServers') or {}).get('job_applier') if os.path.exists(cj) else None
        stale = _plugin_installed() or not cur or cur.get('command') != _python() or cur.get('args') != [JOB_APPLIER_BIN, 'mcp']
        if stale and (cur or _plugin_installed() or os.path.isdir(os.path.expanduser('~/.claude/skills/job-applier-apply'))):
            _drop_plugin(claude)
            _claude_direct(claude)
    except Exception:
        pass


def install_codex():
    cfg_dir = os.path.expanduser('~/.codex')
    os.makedirs(cfg_dir, exist_ok=True)
    cfg = os.path.join(cfg_dir, 'config.toml')
    txt = open(cfg, encoding='utf-8').read() if os.path.exists(cfg) else ''
    q = json.dumps
    block = (f'\n[mcp_servers.job_applier]\ncommand = {q(_python())}\nargs = [{q(JOB_APPLIER_BIN)}, "mcp"]\n'
             f'startup_timeout_sec = 20\ntool_timeout_sec = 300\ndefault_tools_approval_mode = "approve"\n')
    if '[mcp_servers.job_applier]' not in txt:
        with open(cfg, 'a', encoding='utf-8') as f:
            f.write(block)
    else:
        txt2 = re.sub(r'(\[mcp_servers\.job_applier\](?:(?!\n\[).)*?\ncommand = )"[^\n]*"', lambda m: m.group(1) + q(_python()), txt, count=1, flags=re.S)
        txt2 = re.sub(r'(\[mcp_servers\.job_applier\](?:(?!\n\[).)*?\nargs = )\[[^\n]*\]', lambda m: m.group(1) + f'[{q(JOB_APPLIER_BIN)}, "mcp"]', txt2, count=1, flags=re.S)
        if txt2 != txt:
            open(cfg, 'w', encoding='utf-8').write(txt2)
    if '[mcp_servers.playwright]' not in txt and shutil.which('npx'):
        args = ', '.join(q(x) for x in PLAYWRIGHT[1:])
        with open(cfg, 'a', encoding='utf-8') as f:
            f.write(f'\n[mcp_servers.playwright]\ncommand = {q(PLAYWRIGHT[0])}\nargs = [{args}]\nstartup_timeout_sec = 60\ndefault_tools_approval_mode = "approve"\n')
    txt = open(cfg, encoding='utf-8').read()
    for k in ('job_applier', 'playwright'):
        m = re.search(rf'\[mcp_servers\.{k}\]\n(?:(?!\n\[).)*', txt, re.S)
        if m and 'default_tools_approval_mode' not in m.group(0):
            txt = txt[:m.end()].rstrip('\n') + '\ndefault_tools_approval_mode = "approve"\n' + txt[m.end():]
    open(cfg, 'w', encoding='utf-8').write(txt)
    for d in ('~/.agents/skills', '~/.codex/skills'):
        _copy_skills(os.path.expanduser(d))
    return 'Codex: added [mcp_servers.job_applier] to ~/.codex/config.toml and skills to ~/.agents/skills'


def install():
    os.chmod(JOB_APPLIER_BIN, 0o755)
    print(install_claude())
    print(install_codex())
    print('\nDone. In Claude Code or Codex, say: "set me up with job-applier" to onboard, then "job-applier: apply to my top 10".')


def refresh_browser():
    try:
        cj = os.path.expanduser('~/.claude.json')
        cur = (json.load(open(cj, encoding='utf-8')).get('mcpServers') or {}).get('playwright') if os.path.exists(cj) else None
        claude = shutil.which('claude')
        want = _pw_claude()
        if claude and cur and BROWSER_PROFILE in (cur.get('args') or []) and [cur.get('command')] + list(cur.get('args') or []) != want \
                and not (os.path.basename(cur.get('command') or '') == want[0] and cur.get('args') == want[1:]):
            _add_playwright(claude, previous=cur)
    except Exception:
        pass
    try:
        cfg = os.path.expanduser('~/.codex/config.toml')
        if os.path.exists(cfg):
            txt = open(cfg, encoding='utf-8').read()
            m = re.search(r'(\[mcp_servers\.playwright\]\n(?:(?!\n\[).)*?\nargs = )\[[^\n]*\]', txt, re.S)
            want = '[' + ', '.join(json.dumps(x) for x in PLAYWRIGHT[1:]) + ']'
            if m and json.dumps(BROWSER_PROFILE) in m.group(0) and not m.group(0).endswith(want):
                open(cfg, 'w', encoding='utf-8').write(txt[:m.start()] + m.group(1) + want + txt[m.end():])
    except Exception:
        pass


def refresh_skills():
    for d in ('~/.claude/skills', '~/.agents/skills', '~/.codex/skills'):
        dest = os.path.expanduser(d)
        if os.path.isdir(dest) and any(n.startswith('job-applier-') for n in os.listdir(dest)):
            _copy_skills(dest)
