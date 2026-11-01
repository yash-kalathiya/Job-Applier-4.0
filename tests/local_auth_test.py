"""Local auth integration checks, using an isolated data directory and random password."""
import http.client
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from job_applier import cloud, local_auth, server, store, telemetry


class LocalLogin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = patch.object(store, 'HOME', self.tmp.name); self.root.start()
        local_auth._sessions.clear(); local_auth._attempts.clear()
        self.password = secrets.token_urlsafe(20)
        local_auth.configure('test@example.com', self.password)
        self.http = server._Server(('127.0.0.1', 0), server.H)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True); self.thread.start()

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join()
        self.root.stop(); self.tmp.cleanup()

    def request(self, path, body=None, cookie=None, origin=None):
        c = http.client.HTTPConnection('127.0.0.1', self.http.server_port)
        headers = {'Content-Type': 'application/json'}
        if cookie: headers['Cookie'] = cookie
        if origin: headers['Origin'] = origin
        c.request('GET' if body is None else 'POST', path,
                  None if body is None else json.dumps(body), headers)
        r = c.getresponse(); code = r.status; cookie = r.getheader('Set-Cookie'); raw = r.read()
        c.close()
        return code, cookie, raw

    def login(self):
        code, cookie, _ = self.request('/api/auth/login', {'email': 'test@example.com', 'password': self.password})
        self.assertEqual(code, 200)
        self.assertIn('HttpOnly', cookie); self.assertIn('SameSite=Strict', cookie)
        return cookie.split(';')[0]

    def test_private_routes_require_login(self):
        for path in ['/api/state', '/api/answers', '/api/jobs', '/preview', '/file?path=x']:
            self.assertEqual(self.request(path)[0], 401, path)
        self.assertEqual(self.request('/api/profile', {})[0], 401)
        self.assertEqual(self.request('/')[0], 200)
        self.assertFalse(json.loads(self.request('/api/auth')[2])['signed_in'])

    def test_login_logout_and_expiry(self):
        cookie = self.login()
        self.assertTrue(json.loads(self.request('/api/auth', cookie=cookie)[2])['signed_in'])
        self.assertEqual(self.request('/api/answers', cookie=cookie)[0], 200)
        self.assertEqual(self.request('/api/auth/logout', {}, cookie)[0], 200)
        self.assertEqual(self.request('/api/answers', cookie=cookie)[0], 401)
        cookie = self.login()
        local_auth._sessions[cookie.split('=', 1)[1]] = 0
        self.assertEqual(self.request('/api/answers', cookie=cookie)[0], 401)

    def test_wrong_password_throttle_and_forged_cookie(self):
        for _ in range(5):
            self.assertEqual(self.request('/api/auth/login', {'email': 'test@example.com', 'password': 'incorrect'})[0], 401)
        self.assertEqual(self.request('/api/auth/login', {'email': 'test@example.com', 'password': self.password})[0], 429)
        self.assertEqual(self.request('/api/answers', cookie='job_applier_local=forged')[0], 401)

    def test_cross_origin_and_cloud_blocked(self):
        cookie = self.login()
        self.assertEqual(self.request('/api/profile', {}, cookie, 'http://localhost:9999')[0], 403)
        for path in ['/api/auth', '/api/sync']:
            self.assertEqual(self.request(path, {}, cookie)[0], 403)
        self.assertEqual(self.request('/api/auth/login')[0], 403)
        with patch('urllib.request.urlopen', side_effect=AssertionError('Network used')):
            self.assertFalse(cloud.status()['signed_in'])
            self.assertIn('skipped', cloud.push())
            self.assertIn('skipped', cloud.push_applications())
            cloud.sync_soon()
            self.assertFalse(telemetry.enabled())
            with self.assertRaises(RuntimeError): cloud._req('POST', '/')

    def test_credential_storage(self):
        p = Path(self.tmp.name) / 'local_account.json'
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.password, p.read_text())
        with self.assertRaises(FileExistsError): local_auth.configure('other@example.com', self.password)


if __name__ == '__main__': unittest.main()
