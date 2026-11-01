"""CLI: python -m job_applier.extraction URL --out artifacts/phase1/example"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from .engine import collect, install_observation_guard, wait_for_controls
from .report import report_html


def main(argv=None):
    parser = argparse.ArgumentParser(description='Job Applier 4.0 Phase 1: inspect a form without filling or submitting.')
    parser.add_argument('url', help='Public application URL, or file:// for a local fixture')
    parser.add_argument('--out', required=True, help='New directory for JSON, HTML and accessibility evidence')
    parser.add_argument('--headed', action='store_true')
    parser.add_argument('--channel', choices=['chrome', 'chromium'], default='chromium')
    parser.add_argument('--no-probe-options', action='store_true', help='Do not open custom dropdowns')
    args = parser.parse_args(argv)
    if urlparse(args.url).scheme not in {'https', 'http', 'file'}:
        parser.error('URL must use https://, http:// or file://')
    out = Path(args.out).expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('Output directory is not empty; choose a new directory to preserve prior evidence.')
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        parser.error('Install optional requirements-phase1.txt in an isolated environment first.')
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(out, 0o700)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, chromium_sandbox=True, channel=args.channel)
        try:
            context = browser.new_context(viewport={'width': 1360, 'height': 1000}, service_workers='block')
            blocked = install_observation_guard(context)
            page = context.new_page()
            response = page.goto(args.url, wait_until='domcontentloaded', timeout=45000)
            ready = wait_for_controls(page)
            snapshot = collect(page, probe_options=not args.no_probe_options)
            snapshot['runtime'] = {'playwright': importlib.metadata.version('playwright'), 'browser': browser.version,
                                   'fresh_context': True, 'profile_loaded': False}
            snapshot['observation_guard'] = {'blocked_requests': blocked, 'non_read_http_blocked': True, 'submit_blocked': True}
            if not ready:
                snapshot['issues'].append({'code': 'controls_not_ready'})
                snapshot['status'] = 'partial'
            if response and response.status >= 400:
                snapshot['issues'].append({'code': 'http_error', 'status': response.status})
                snapshot['status'] = 'partial'
            page.screenshot(path=str(out / 'source-page.png'), full_page=True)
        finally:
            browser.close()
    for name, text in [('questions.json', json.dumps(snapshot, indent=2, ensure_ascii=False)),
                       ('index.html', report_html(snapshot)),
                       ('accessibility.txt', '\n\n'.join(f['id'] + '\n' + f['accessibility_snapshot'] for f in snapshot['frames']))]:
        destination = out / name
        destination.write_text(text, encoding='utf-8')
        destination.chmod(0o600)
    (out / 'source-page.png').chmod(0o600)
    print(json.dumps({'report': str(out / 'index.html'), 'json': str(out / 'questions.json'),
                      'status': snapshot['status'], **snapshot['summary']}, indent=2))
    return 0 if snapshot['questions'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
