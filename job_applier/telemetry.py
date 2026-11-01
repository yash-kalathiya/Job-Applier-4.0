"""Anonymous install count, so the maintainer knows how many people use Job Applier 4.0 and on which OS.

Once at start and once a day it sends: a random ID made on this computer, the OS, the Job Applier 4.0 version, whether it's an
installed copy or a developer checkout, and which agent it uses (claude/codex). Nothing else: no name, email, resume,
jobs or applications. Turn it off in Settings (apply.telemetry = false) or with JOB_APPLIER_NO_TELEMETRY=1.
"""
import os
import platform
import threading
import time
import uuid

from . import store


def enabled():
    return False  # Local-only installation: no developer telemetry
    return not (os.environ.get('JOB_APPLIER_NO_TELEMETRY') or os.environ.get('APPLYTWIN_NO_TELEMETRY') or os.environ.get('CI')
                or store.profile().get('apply', {}).get('telemetry') is False)


def install_id():
    p = store.path('install_id')
    try:
        return str(uuid.UUID(open(p, encoding='utf-8').read().strip()))
    except (OSError, ValueError):
        i = str(uuid.uuid4())
        with open(p, 'w', encoding='utf-8') as f:
            f.write(i)
        return i


def ping():
    if not enabled():
        return False
    from . import __version__, cloud, update
    try:
        cloud._req('POST', '/rest/v1/rpc/job_applier_ping', body={
            "p_id": install_id(), "p_os": {'Darwin': 'mac', 'Windows': 'windows', 'Linux': 'linux'}.get(platform.system(), platform.system().lower()),
            "p_version": __version__, "p_kind": 'checkout' if update.is_checkout() else 'installed',
            "p_agent": store.profile().get('apply', {}).get('agent') or ''}, timeout=10)
        return True
    except Exception:
        return False   # offline or blocked: never matters


def start():
    def loop():
        while True:
            ping()
            time.sleep(24 * 3600)
    threading.Thread(target=loop, daemon=True).start()
