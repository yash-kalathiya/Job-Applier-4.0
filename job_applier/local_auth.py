"""Single-user local authentication. Credentials stay outside the source checkout."""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from http.cookies import SimpleCookie

from . import store

COOKIE = 'job_applier_local'
TTL = 12 * 3600
_lock = threading.Lock()
_sessions = {}
_attempts = []


def account():
    try:
        with open(store.path('local_account.json'), encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def configure(email, password):
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError('Use an app password with at least eight characters')
    salt = secrets.token_bytes(32)
    digest = _hash(password, salt)
    data = {'email': email.strip().lower(), 'salt': salt.hex(), 'hash': digest.hex()}
    fd = os.open(store.path('local_account.json'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def _hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1,
                          maxmem=64 * 1024 * 1024, dklen=32)


def login(email, password):
    with _lock:
        now = time.time()
        _attempts[:] = [t for t in _attempts if now - t < 60]
        if len(_attempts) >= 5:
            return 429, None
        _attempts.append(now)
        a = account()
        if not a or not isinstance(email, str) or not isinstance(password, str) or len(password) > 1024:
            return 401, None
        digest = _hash(password, bytes.fromhex(a['salt']))
        if not (hmac.compare_digest(digest.hex(), a['hash']) and
                hmac.compare_digest(email.strip().lower().encode(), a['email'].encode())):
            return 401, None
        _attempts.clear()
        for key in [k for k, expiry in _sessions.items() if expiry <= now]:
            del _sessions[key]
        token = secrets.token_urlsafe(32)
        _sessions[token] = now + TTL
        return 200, token


def _cookie(header):
    try:
        c = SimpleCookie(); c.load(header or '')
        return c[COOKIE].value if COOKIE in c else ''
    except Exception:
        return ''


def authenticated(header):
    token = _cookie(header)
    with _lock:
        expiry = _sessions.get(token, 0)
        if expiry <= time.time():
            _sessions.pop(token, None)
            return False
        return True


def logout(header):
    with _lock:
        _sessions.pop(_cookie(header), None)


def status(header):
    signed_in = authenticated(header)
    a = account() if signed_in else None
    return {'signed_in': signed_in, 'local_only': True,
            'user': {'email': a['email'], 'name': 'Yash'} if a else None}


def cookie(token='', clear=False):
    return f'{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if clear else TTL}'
