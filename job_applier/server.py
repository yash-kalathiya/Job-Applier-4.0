"""Local web app: http://localhost:4747 . Standard library only, binds to 127.0.0.1."""
import json
import threading
import sys
import mimetypes
import os
import re
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import api, cloud, store, local_auth

WEB = os.path.join(store.APP, 'web')


def _q(qs, k, d=None):
    return (qs.get(k) or [d])[0]


GET = {
    r'/api/state': lambda m, qs, b: {"profile": api.get_profile(), "vault": api.get_vault(), "stats": api.stats(),
                                     "setup": api.setup_status(), "templates": api.templates(), "app_dir": store.APP, "home": store.HOME},
    r'/api/stats': lambda m, qs, b: api.stats(),
    r'/api/setup': lambda m, qs, b: api.setup_status(),
    r'/api/jobs': lambda m, qs, b: api.list_jobs(_q(qs, 'q', ''), _q(qs, 'status', 'new'),
                                                 float(_q(qs, 'min')) if _q(qs, 'min') else None, int(_q(qs, 'limit', 150)),
                                                 _q(qs, 'ats'), _q(qs, 'order', 'fit')),
    r'/api/jobs/([\w-]+)': lambda m, qs, b: api.get_job(m.group(1)),
    r'/api/jobs/([\w-]+)/questions': lambda m, qs, b: api.job_questions(m.group(1)),
    r'/api/jobs/([\w-]+)/ats': lambda m, qs, b: api.ats_report(job_id=m.group(1)),
    r'/api/templates': lambda m, qs, b: api.templates(),
    r'/api/answers': lambda m, qs, b: api.get_answers(),
    r'/api/applications': lambda m, qs, b: api.applications(history=_q(qs, 'history') == '1'),
    r'/api/scan': lambda m, qs, b: api.scan_status(),
    r'/api/dump': lambda m, qs, b: {"text": api.get_dump()},
    r'/api/ats': lambda m, qs, b: api.ats_report(),
    r'/api/next': lambda m, qs, b: api.next_jobs(int(_q(qs, 'n', 10))),
    r'/api/queue': lambda m, qs, b: api.queue(int(_q(qs, 'n', 50))),
    r'/api/run': lambda m, qs, b: api.run_status(),
    r'/api/doctor': lambda m, qs, b: api.doctor(),
    r'/api/version': lambda m, qs, b: version(),
    r'/api/questions': lambda m, qs, b: api.profile_questions(),
    r'/api/update': lambda m, qs, b: api.update_status(),
    r'/api/agents': lambda m, qs, b: api.agent_status(),
    r'/api/inbox': lambda m, qs, b: api.inbox_poll(),
    r'/api/jobs/([\w-]+)/thread': lambda m, qs, b: {"thread": api.thread(m.group(1))},
}
_UNKNOWN = set()

POST = {
    r'/api/profile': lambda m, qs, b: api.update_profile(b),
    r'/api/vault': lambda m, qs, b: api.save_vault(b),
    r'/api/answers': lambda m, qs, b: (store.save('answers.json', b), {"ok": True})[1],
    r'/api/answer': lambda m, qs, b: api.save_answer(b['question'], b['answer'], b.get('key')),
    r'/api/answer/test': lambda m, qs, b: api.answer_questions(b.get('questions', []), notify_user=False),   # just trying
    r'/api/dump': lambda m, qs, b: api.save_dump(b.get('text', '')),
    r'/api/scan': lambda m, qs, b: api.scan(b.get('sources'), background=True),
    r'/api/jobs': lambda m, qs, b: api.add_job(b['url'], b.get('title', ''), b.get('company', ''), b.get('description', '')),
    r'/api/jobs/([\w-]+)/skip': lambda m, qs, b: api.skip_job(m.group(1)),
    r'/api/jobs/([\w-]+)/message': lambda m, qs, b: api.message(m.group(1), b.get('text', '')),
    r'/api/jobs/([\w-]+)/status': lambda m, qs, b: api.set_job_status(m.group(1), b['status']),
    r'/api/jobs/([\w-]+)/tailor': lambda m, qs, b: api.tailor_apply(m.group(1), b.get('plan'), b.get('template'), b.get('mode', 'auto')),
    r'/api/jobs/([\w-]+)/prompt': lambda m, qs, b: api.tailor_prompt(m.group(1)),
    r'/api/jobs/([\w-]+)/log': lambda m, qs, b: api.log_application(m.group(1), b.get('status', 'Applied'), b.get('notes', '')),
    r'/api/render': lambda m, qs, b: api.render_resume(b.get('template'), b.get('job_id')),
    r'/api/ats': lambda m, qs, b: api.ats_report(b.get('job_id'), b.get('jd'), b.get('resume')),
    r'/api/import': lambda m, qs, b: api.import_resume(b.get('name', ''), b.get('data'), b.get('text')),
    r'/api/run': lambda m, qs, b: api.start_run(b.get('agent', 'claude'), int(b.get('n', 25))),
    r'/api/run/stop': lambda m, qs, b: api.stop_run(),
    r'/api/update': lambda m, qs, b: update_now(),
    r'/api/finish': lambda m, qs, b: api.finish_jobs(b.get('job_ids') or [], bool(b.get('submit'))),
    r'/api/open-twin': lambda m, qs, b: api.open_in_twin_browser(b['url']),
    r'/api/history': lambda m, qs, b: api.import_history(text=b.get('text', '')),
    r'/api/history/email': lambda m, qs, b: api.start_run(b.get('agent') or api.store.profile()['apply'].get('agent') or 'claude', 1,
                                                          prompt=api.email_history_prompt()),
    r'/api/inbox/(\d+)/resolve': lambda m, qs, b: api.resolve(m.group(1)),
}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json', cookie=None):
        data = body if isinstance(body, bytes) else (json.dumps(body, default=str) if ctype == 'application/json' else body).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype + ('; charset=utf-8' if ctype.startswith(('text', 'application/json')) else ''))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        if cookie is not None:
            self.send_header('Set-Cookie', cookie)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass   # the page went away (reload, closed tab) before the answer arrived; nothing to do
        return True   # answered (callers check this; returning None made them send a second, 404 reply)

    def _route(self, table, body=None):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        for pat, fn in table.items():
            m = re.fullmatch(pat, u.path)
            if m:
                try:
                    return self._send(200, fn(m, qs, body))
                except Exception as e:
                    traceback.print_exc()
                    return self._send(500, {"error": str(e)})
        return None

    def _trusted(self, post=False):
        """Only this computer's own pages may talk to Job Applier 4.0. Without this, any website you visit could drive it
        (cross-site requests) or reach it through DNS rebinding."""
        host = (self.headers.get('Host') or '').lower()
        name = host[:host.find(']') + 1] if host.startswith('[') else host.split(':')[0]
        if name not in ('localhost', '127.0.0.1', '[::1]'):
            return False
        # opening a page (including Google sending you back after sign-in, which Chrome marks cross-site) is fine; only the
        # API and files must come from Job Applier 4.0's own pages
        path = urllib.parse.urlparse(self.path).path
        if not post and not path.startswith(('/api/', '/file')):
            return True
        origin = self.headers.get('Origin')
        if origin is not None and origin != 'http://' + host:
            return False
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return False
        # a JSON content type makes browsers ask permission (a preflight we never grant) before any cross-site POST
        return not post or (self.headers.get('Content-Type') or '').split(';')[0].strip() == 'application/json'

    def do_GET(self):
        if not self._trusted():
            return self._send(403, {"error": "forbidden"})
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path == '/api/auth':
            return self._send(200, local_auth.status(self.headers.get('Cookie')))
        if u.path == '/api/auth/login':
            return self._send(403, {'error': 'Google sign-in is disabled. Use your local login.'})
        if (u.path.startswith('/api/') or u.path in ('/file', '/preview')) and not local_auth.authenticated(self.headers.get('Cookie')):
            return self._send(401, {'error': 'Sign in to Job Applier 4.0'})
        if u.path.startswith('/api/'):
            if self._route(GET) is None:
                if u.path not in _UNKNOWN:   # say it once per path, not on every poll
                    _UNKNOWN.add(u.path)
                    print(f'Unknown request: GET {u.path} (an old tab? reload it)', flush=True)
                self._send(404, {"error": "Job Applier 4.0 is switching to a new version. Try again in a few seconds."})
            return
        if u.path == '/preview':
            try:
                return self._send(200, api.preview_html(_q(qs, 'template', 'classic'), _q(qs, 'job')), 'text/html')
            except Exception as e:
                import html as _h
                return self._send(500, f'<pre>{_h.escape(str(e))}</pre>', 'text/html')
        if u.path == '/file':   # tailored resumes only: never the sign-in tokens or the twin's browser data
            p = os.path.realpath(_q(qs, 'path', ''))
            if (not p.startswith(os.path.realpath(store.path('resumes')) + os.sep) or not os.path.isfile(p)
                    or not p.lower().endswith(('.pdf', '.tex', '.png', '.json'))):
                return self._send(403, {"error": "forbidden"})
            return self._send(200, open(p, 'rb').read(), mimetypes.guess_type(p)[0] or 'application/octet-stream')
        rel = 'index.html' if u.path in ('/', '') else u.path.lstrip('/')
        f = os.path.realpath(os.path.join(WEB, rel))
        if not f.startswith(os.path.realpath(WEB)) or not os.path.isfile(f):
            f = os.path.join(WEB, 'index.html')
        self._send(200, open(f, 'rb').read(), mimetypes.guess_type(f)[0] or 'text/plain')

    def do_POST(self):
        if not self._trusted(post=True):
            return self._send(403, {"error": "forbidden"})
        path = urllib.parse.urlparse(self.path).path
        if path not in ('/api/auth/login', '/api/auth/logout') and not local_auth.authenticated(self.headers.get('Cookie')):
            return self._send(401, {'error': 'Sign in to Job Applier 4.0'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return self._send(400, {'error': 'Invalid request length'})
        if n < 0 or n > 20 * 1024 * 1024 or (path == '/api/auth/login' and n > 4096):
            return self._send(413, {'error': 'Request too large'})
        try:
            body = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            return self._send(400, {"error": "bad json"})
        if not isinstance(body, dict):
            return self._send(400, {'error': 'Expected a JSON object'})
        if path == '/api/auth/login':
            code, token = local_auth.login(body.get('email'), body.get('password'))
            if code != 200:
                return self._send(code, {'error': 'Too many attempts. Try again in a minute.' if code == 429 else 'Incorrect email or password'})
            return self._send(200, {'signed_in': True, 'local_only': True}, cookie=local_auth.cookie(token))
        if path == '/api/auth/logout':
            local_auth.logout(self.headers.get('Cookie'))
            return self._send(200, {'signed_in': False, 'local_only': True}, cookie=local_auth.cookie(clear=True))
        if path in ('/api/auth', '/api/sync'):
            return self._send(403, {'error': 'Cloud sign-in and sync are disabled'})
        if self._route(POST, body) is None:
            self._send(404, {"error": "Job Applier 4.0 is switching to a new version. Try again in a few seconds."})


def _restart():
    """Start again on the new code. The new process waits for this one's port instead of picking another."""
    os.environ['JOB_APPLIER_RESTART'] = '1'
    os.environ['APPLYTWIN_RESTART'] = '1'
    if os.name == 'nt':
        import subprocess
        subprocess.Popen([sys.executable] + sys.argv, env=os.environ.copy())
        os._exit(0)
    os.execv(sys.executable, [sys.executable] + sys.argv)


def _self_update(restart=True):
    """Installed copies update themselves (git checkouts never do); turn off with apply.auto_update = false.
    Returns the update result, restarting on the new code when restart=True."""
    from . import update
    if update.is_checkout() or store.profile().get('apply', {}).get('auto_update') is False:
        return {"updated": False}
    st = update.check()
    if not st['available']:
        return {"updated": False, **st}
    print(f"Updating Job Applier 4.0 ({st['current'] or 'new'} -> {st['latest']})...")
    try:
        r = update.apply()
        if r.get('updated') and restart:
            _restart()
        return r
    except Exception as e:
        print(f'Update skipped: {e}')
        return {"updated": False, "reason": str(e)}


def _update_loop(hours=1):
    """The app now runs from login for days at a time, so it also checks while running. It never restarts in the
    middle of an Autopilot run; it waits for the run to finish."""
    import time
    while True:
        time.sleep(hours * 3600)
        while api.run_status().get('running'):
            time.sleep(300)
        _self_update()


def _code_stamp():
    d = os.path.dirname(os.path.abspath(__file__))
    return max(os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d) if f.endswith('.py'))


_STARTED_CODE = _code_stamp()


def _ui_build():
    """The name of the page's current script bundle; it changes with every UI build."""
    import re
    try:
        html = open(os.path.join(WEB, 'index.html'), encoding='utf-8').read()
        return (re.search(r'assets/(index-[\w-]+\.js)', html) or [None, ''])[1]
    except OSError:
        return ''


def version():
    """The open page compares `ui` with the bundle it loaded and reloads itself when they differ."""
    from . import __version__
    return {"version": __version__, "ui": _ui_build()}


def _code_watch():
    """If the app's code on disk is newer than what's running (an update or a git pull), restart onto it between runs,
    so the page and the server never disagree (that's what made buttons say "not found")."""
    import time
    while True:
        time.sleep(5)
        try:
            if _code_stamp() > _STARTED_CODE + 1 and not api.run_status().get('running'):
                time.sleep(2)   # let a pull or update finish writing files
                print('Job Applier 4.0 code changed on disk; restarting on it.', flush=True)
                _restart()
        except Exception:
            pass


def update_now():
    """Settings > Check for updates: install the newest tested version now (even with auto-update off) and restart;
    the page reloads by itself."""
    from . import update
    if api.run_status().get('running'):
        return {"updated": False, "reason": "Autopilot is running. Update after it finishes."}
    st = update.check()
    if not st['managed']:
        return {"updated": False, **st, "reason": "This is a developer copy. Run git pull in its folder."}
    if not st['available']:
        return {"updated": False, **st, "reason": "You're on the newest version."}
    r = update.apply()
    if r.get('updated'):
        threading.Timer(1.0, _restart).start()   # answer the request first, then restart
    return {**st, **r}


class _Server(ThreadingHTTPServer):
    # Windows lets a second program bind a port that's already listening when SO_REUSEADDR is set, so a second copy of
    # Job Applier 4.0 would start beside the first instead of noticing it. Claim the port exclusively there.
    allow_reuse_address = os.name != 'nt'

    def server_bind(self):
        import socket
        if os.name == 'nt' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve(port=4747, open_browser=True):
    import time as _t
    import urllib.request
    from . import update as _upd
    _upd.ensure_command()
    srv = None
    restarting = os.environ.pop('JOB_APPLIER_RESTART', None) or os.environ.pop('APPLYTWIN_RESTART', None)
    if restarting:   # restarting after an update: wait for the old process to free the port, and don't open another tab
        open_browser = False
        for _ in range(40):
            try:
                srv = _Server(('127.0.0.1', port), H)
                break
            except OSError:
                _t.sleep(0.25)
    for p in ([] if srv else range(port, port + 20)):
        try:
            srv = _Server(('127.0.0.1', p), H)
            break
        except OSError:
            try:   # Job Applier 4.0 is already running there: just open it
                with urllib.request.urlopen(f'http://127.0.0.1:{p}/api/stats', timeout=2) as r:
                    if r.status == 200 and p == port:
                        print(f'Job Applier 4.0 is already running at http://localhost:{p}')
                        if open_browser:
                            import webbrowser
                            webbrowser.open(f'http://localhost:{p}')
                        return
            except Exception:
                pass
    if srv is None:
        raise SystemExit(f'Ports {port}-{port + 19} are all busy. Free one, or run: job-applier app --port 5050')
    port = srv.server_address[1]
    url = f'http://localhost:{port}'
    # on start: re-apply the current matching rules to saved jobs (so fixes like the skip list reach existing queues),
    # then refresh jobs if the last scan is old
    from . import install
    threading.Thread(target=lambda: (install.refresh_skills(), install.refresh_agents(), api.rescore(), api.scan_if_stale()), daemon=True).start()
    threading.Thread(target=_update_loop, daemon=True).start()
    threading.Thread(target=_code_watch, daemon=True).start()
    # update after the app is up (the page opens right away), and only in the copy that owns the port
    threading.Thread(target=lambda: (_t.sleep(3), _self_update()), daemon=True).start()
    threading.Thread(target=api.on_start, daemon=True).start()
    from . import telemetry
    telemetry.start()   # anonymous install count (random ID, OS, version); off in Settings   # keep updating while it runs for days
    print(f'Job Applier 4.0 is running at {url}  (data in {store.HOME})', flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
