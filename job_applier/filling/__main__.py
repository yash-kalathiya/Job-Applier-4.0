"""CLI entrypoint for Phase 3 form filling: job-applier fill URL --answers ANSWERS.json --out DIR"""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

from . import SCHEMA_VERSION
from .engine import fill_form, install_observation_guard, validate_answers_plan, write_json_atomic


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description=(
            'Job Applier 4.0 Phase 3: fill application form with '
            'observation & submit-blocker guard.'
        )
    )
    parser.add_argument(
        'url', help='Public application URL, or file:// for a local fixture'
    )
    parser.add_argument(
        '--answers', required=True, help='Path to answers.json (Phase 2 resolution output)'
    )
    parser.add_argument(
        '--out', required=True, help='Output directory for fill report and screenshot'
    )
    parser.add_argument('--headed', action='store_true', help='Run browser in headed mode')
    parser.add_argument(
        '--screenshot',
        dest='screenshot',
        action='store_true',
        default=True,
        help='Capture full-page screenshot (default)',
    )
    parser.add_argument(
        '--no-screenshot',
        dest='screenshot',
        action='store_false',
        help='Disable screenshot capture',
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        default=False,
        help='Allow overwriting existing evidence files',
    )
    parser.add_argument(
        '--allow-review',
        action='store_true',
        default=False,
        help='Allow filling answers with status review',
    )

    args = parser.parse_args(argv)

    parsed_url = urlparse(args.url)
    if parsed_url.scheme not in {'https', 'http', 'file'}:
        parser.error('URL must use https://, http://, or file://')

    answers_path = Path(args.answers).expanduser().resolve()
    if not answers_path.is_file():
        parser.error(f'Answers file not found: {args.answers}')

    try:
        with open(answers_path, 'r', encoding='utf-8') as f:
            answers_plan = json.load(f)
    except Exception as exc:
        print(json.dumps({
            'report': None,
            'screenshot': None,
            'status': 'error',
            'error': f'Failed to parse answers JSON: {exc}',
            'total_answers': 0,
            'filled': 0,
            'skipped': 0,
            'failed': 0,
        }, indent=2))
        return 1

    val_err = validate_answers_plan(answers_plan)
    if val_err:
        print(json.dumps({
            'report': None,
            'screenshot': None,
            'status': 'error',
            'error': val_err,
            'total_answers': 0,
            'filled': 0,
            'skipped': 0,
            'failed': 0,
        }, indent=2))
        return 1

    out_lexical = os.path.abspath(os.path.expanduser(args.out))
    out = Path(out_lexical)
    report_path = out / 'fill_report.json'
    screenshot_path = (out / 'screenshot.png') if args.screenshot else None

    total_answers = len(answers_plan.get('answers') or [])

    # Do not silently overwrite prior evidence without --overwrite
    if not args.overwrite:
        if report_path.is_file():
            print(json.dumps({
                'report': str(report_path),
                'screenshot': None,
                'status': 'error',
                'error': f'Refusing to overwrite existing report {report_path}. Pass --overwrite.',
                'total_answers': total_answers,
                'filled': 0,
                'skipped': 0,
                'failed': 0,
            }, indent=2))
            return 1
        if screenshot_path and screenshot_path.exists():
            print(json.dumps({
                'report': str(report_path),
                'screenshot': str(screenshot_path),
                'status': 'error',
                'error': f'Refusing to overwrite existing screenshot {screenshot_path}. Pass --overwrite.',
                'total_answers': total_answers,
                'filled': 0,
                'skipped': 0,
                'failed': 0,
            }, indent=2))
            return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(json.dumps({
            'report': str(report_path),
            'screenshot': None,
            'status': 'error',
            'error': 'Playwright is required for form filling. Install in an isolated environment first.',
            'total_answers': total_answers,
            'filled': 0,
            'skipped': 0,
            'failed': total_answers,
        }, indent=2))
        return 1

    context = None
    browser = None
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    headless=not args.headed,
                    chromium_sandbox=True,
                )
                context = browser.new_context(
                    viewport={'width': 1360, 'height': 1000},
                    service_workers='block',
                )
                install_observation_guard(context)
                page = context.new_page()
                page.goto(args.url, wait_until='domcontentloaded', timeout=45000)

                report = fill_form(page, answers_plan, options={
                    'screenshot': args.screenshot,
                    'screenshot_path': str(screenshot_path) if screenshot_path else None,
                    'overwrite': args.overwrite,
                    'allow_review': args.allow_review,
                })
            finally:
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        pass
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        pass
    except Exception as exc:
        report = {
            'schema': SCHEMA_VERSION,
            'snapshot_id': answers_plan.get('snapshot_id'),
            'summary': {
                'total_answers': total_answers,
                'filled': 0,
                'skipped': 0,
                'failed': total_answers,
            },
            'fields': [],
            'error': str(exc),
            'screenshot_path': None,
        }
        try:
            write_json_atomic(report_path, report, overwrite=args.overwrite)
        except Exception:
            pass
        print(json.dumps({
            'report': str(report_path),
            'screenshot': None,
            'status': 'error',
            'error': str(exc),
            'total_answers': total_answers,
            'filled': 0,
            'skipped': 0,
            'failed': total_answers,
        }, indent=2))
        return 1

    try:
        write_json_atomic(report_path, report, overwrite=args.overwrite)
    except Exception as exc:
        summary = report.get('summary', {})
        print(json.dumps({
            'report': str(report_path),
            'screenshot': (
                str(screenshot_path) if screenshot_path and screenshot_path.exists() else None
            ),
            'status': 'error',
            'error': f'Failed to write fill report: {exc}',
            'total_answers': total_answers,
            'filled': summary.get('filled', 0),
            'skipped': summary.get('skipped', 0),
            'failed': summary.get('failed', 0),
        }, indent=2))
        return 1

    summary = report.get('summary', {})
    print(json.dumps({
        'report': str(report_path),
        'screenshot': (
            str(screenshot_path) if screenshot_path and screenshot_path.exists() else None
        ),
        'status': 'success' if summary.get('failed', 0) == 0 else 'partial',
        **summary,
    }, indent=2))

    return 0 if summary.get('failed', 0) == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
