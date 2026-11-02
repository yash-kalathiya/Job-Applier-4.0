"""CLI: python -m job_applier.extraction URL --out artifacts/phase1/example"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from .engine import collect, install_observation_guard, wait_for_controls
from .report import report_html
from ..safe_io import write_bytes_atomic, write_json_atomic


def main(argv=None):
    parser = argparse.ArgumentParser(description='Job Applier 4.0 Phase 1: inspect a form without filling or submitting.')
    parser.add_argument('url', help='Public application URL, or file:// for a local fixture')
    parser.add_argument('--out', required=True, help='New directory for JSON, HTML and accessibility evidence')
    parser.add_argument('--headed', action='store_true')
    parser.add_argument('--channel', choices=['chrome', 'chromium'], default='chromium')
    parser.add_argument('--no-probe-options', action='store_true', help='Do not open custom dropdowns')
    parser.add_argument('--overwrite', action='store_true', default=False, help='Allow overwriting existing evidence files')
    args = parser.parse_args(argv)
    if urlparse(args.url).scheme not in {'https', 'http', 'file'}:
        parser.error('URL must use https://, http:// or file://')

    out_lexical = os.path.abspath(os.path.expanduser(args.out))
    if not args.overwrite and os.path.isdir(out_lexical):
        try:
            if any(os.scandir(out_lexical)):
                parser.error('Output directory is not empty; choose a new directory to preserve prior evidence or pass --overwrite.')
        except OSError:
            pass

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        parser.error('Install optional requirements-phase1.txt in an isolated environment first.')

    screenshot_bytes = b''
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
            screenshot_bytes = page.screenshot(full_page=True)
        finally:
            browser.close()

    questions_path = os.path.join(out_lexical, 'questions.json')
    index_path = os.path.join(out_lexical, 'index.html')
    access_path = os.path.join(out_lexical, 'accessibility.txt')
    screenshot_path = os.path.join(out_lexical, 'source-page.png')

    accessibility_text = '\n\n'.join(
        f['id'] + '\n' + f['accessibility_snapshot'] for f in snapshot['frames']
    )

    try:
        write_bytes_atomic(screenshot_path, screenshot_bytes, overwrite=args.overwrite)
        write_json_atomic(questions_path, snapshot, overwrite=args.overwrite)
        write_bytes_atomic(index_path, report_html(snapshot).encode('utf-8'), overwrite=args.overwrite)
        write_bytes_atomic(access_path, accessibility_text.encode('utf-8'), overwrite=args.overwrite)
    except (FileExistsError, OSError, ValueError, PermissionError) as err:
        parser.error(f'Failed to write evidence artifact: {err}')

    print(json.dumps({
        'report': index_path,
        'json': questions_path,
        'status': snapshot['status'],
        **snapshot['summary'],
    }, indent=2))
    return 0 if snapshot['questions'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
