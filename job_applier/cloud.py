"""Cloud features are disabled for this user's local-only installation.

No previous Google session is loaded and no request is sent to Twinly/Supabase.
The public function names remain for callers in the CLI, MCP server and app.
"""


def _req(*args, **kwargs):
    raise RuntimeError('Cloud access is disabled in this local-only installation')


def login_url(redirect):
    raise RuntimeError('Google sign-in is disabled. Use your local Job Applier 4.0 login.')


def set_session(*args, **kwargs):
    raise RuntimeError('Cloud sign-in is disabled. Use your local Job Applier 4.0 login.')


def token():
    return None


def status():
    return {'signed_in': False, 'local_only': True, 'user': None, 'last_sync': None}


def logout():
    return status()


def push():
    return {'skipped': 'cloud disabled'}


def pull():
    return False


def upload(*args, **kwargs):
    return None


def push_applications():
    return {'skipped': 'cloud disabled'}


def sync_soon():
    pass


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return None
