"""End-to-End Pipeline Validator for Job Applier 4.0.

Validates the complete application lifecycle step-by-step:
1. Fetch (Extraction): captures controls and questions into questions.json
2. Answer (Resolution): matches questions to profile facts in answers.json
3. Fill (Filling): drives form filling with observation & submit-blocker guard,
   verifies filled values in the live DOM, blocks submissions, and captures screenshot.png
4. Validate: produces a structured validation summary with overall status (SUCCESS/PARTIAL/FAILED).
"""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from .extraction import SCHEMA_VERSION as EXTRACTION_SCHEMA
from .extraction.__main__ import main as extract_main
from .filling import SCHEMA_VERSION as FILL_SCHEMA
from .filling.__main__ import main as fill_main
from .filling.engine import validate_answers_plan
from .resolution import SCHEMA_VERSION as RESOLUTION_SCHEMA
from .resolution.__main__ import main as resolve_main
from .safe_io import write_json_atomic


def validate_pipeline(
    url: str,
    out: Union[str, Path],
    bank: Optional[Union[str, Path]] = None,
    headed: bool = False,
    overwrite: bool = False,
    allow_review: bool = False,
) -> Dict[str, Any]:
    """Execute and validate the fetch -> answer -> fill pipeline end-to-end.

    Returns a structured validation summary dictionary with:
      - fetched: bool (question count)
      - answered: bool (ready/review count)
      - filled: bool (filled field count, verified DOM values, submit blocked)
      - screenshot: path to stored screenshot
      - status: 'SUCCESS' | 'PARTIAL' | 'FAILED'
    """
    out_dir = Path(os.path.abspath(os.path.expanduser(str(out))))
    errors: List[str] = []

    parsed_url = urlparse(url)
    if parsed_url.scheme not in {'https', 'http', 'file'}:
        return {
            'status': 'FAILED',
            'fetched': False,
            'answered': False,
            'filled': False,
            'screenshot': None,
            'question_count': 0,
            'ready_count': 0,
            'review_count': 0,
            'needs_user_count': 0,
            'filled_count': 0,
            'verified_count': 0,
            'skipped_count': 0,
            'failed_count': 0,
            'submit_blocked': False,
            'artifacts': {
                'questions': None,
                'answers': None,
                'fill_report': None,
                'screenshot': None,
                'summary': str(out_dir / 'validation_summary.json'),
            },
            'steps': {
                'fetch': {'status': 'failed', 'error': 'URL must use https://, http://, or file://'},
                'answer': {'status': 'not_run'},
                'fill': {'status': 'not_run'},
            },
            'errors': ['URL must use https://, http://, or file://'],
        }

    fetched = False
    answered = False
    filled = False
    question_count = 0
    ready_count = 0
    review_count = 0
    needs_user_count = 0
    filled_count = 0
    verified_count = 0
    skipped_count = 0
    failed_count = 0
    submit_blocked = False

    fetch_details: Dict[str, Any] = {'status': 'not_run'}
    answer_details: Dict[str, Any] = {'status': 'not_run'}
    fill_details: Dict[str, Any] = {'status': 'not_run'}

    questions_path = out_dir / 'questions.json'
    answers_path = out_dir / 'answers.json'
    report_path = out_dir / 'fill_report.json'
    screenshot_path = out_dir / 'screenshot.png'
    summary_path = out_dir / 'validation_summary.json'

    # -------------------------------------------------------------------------
    # Step 1 (Fetch): Runs extraction (job_applier.extraction.__main__.main)
    # -------------------------------------------------------------------------
    extract_args = [url, '--out', str(out_dir)]
    if headed:
        extract_args.append('--headed')
    if overwrite:
        extract_args.append('--overwrite')

    buf = io.StringIO()
    extract_code = 0
    try:
        with contextlib.redirect_stdout(buf):
            extract_code = extract_main(extract_args)
    except SystemExit as exc:
        extract_code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        extract_code = 1
        errors.append(f'Step 1 (Fetch) extraction raised exception: {exc}')

    if not questions_path.is_file():
        fetch_details = {
            'status': 'failed',
            'error': f'questions.json was not created at {questions_path}',
            'cli_exit_code': extract_code,
            'output': buf.getvalue()[-500:] if buf.getvalue() else None,
        }
        errors.append(f'Step 1 (Fetch) failed: questions.json not found at {questions_path}')
    else:
        try:
            with open(questions_path, 'r', encoding='utf-8') as f:
                snapshot = json.load(f)

            schema = snapshot.get('schema_version') or snapshot.get('schema')
            questions = snapshot.get('questions')

            if schema != EXTRACTION_SCHEMA:
                errors.append(f"Step 1 (Fetch) invalid schema: expected '{EXTRACTION_SCHEMA}', got '{schema}'")
                fetch_details = {'status': 'failed', 'error': 'Invalid schema', 'schema': schema}
            elif not isinstance(questions, list) or len(questions) == 0:
                errors.append('Step 1 (Fetch) captured 0 questions')
                fetch_details = {'status': 'failed', 'error': '0 questions captured', 'question_count': 0}
            else:
                fetched = True
                question_count = len(questions)
                fetch_details = {
                    'status': 'success',
                    'schema': schema,
                    'question_count': question_count,
                    'path': str(questions_path),
                }
        except Exception as exc:
            errors.append(f'Step 1 (Fetch) failed to read/parse questions.json: {exc}')
            fetch_details = {'status': 'failed', 'error': str(exc)}

    # -------------------------------------------------------------------------
    # Step 2 (Answer): Runs resolution (job_applier.resolution.__main__.main)
    # -------------------------------------------------------------------------
    if fetched:
        resolve_args = [str(questions_path), '--out', str(answers_path)]
        if bank:
            resolve_args.extend(['--bank', str(bank)])
        if overwrite:
            resolve_args.append('--overwrite')

        buf = io.StringIO()
        resolve_code = 0
        try:
            with contextlib.redirect_stdout(buf):
                resolve_code = resolve_main(resolve_args)
        except SystemExit as exc:
            resolve_code = exc.code if isinstance(exc.code, int) else 1
        except Exception as exc:
            resolve_code = 1
            errors.append(f'Step 2 (Answer) resolution raised exception: {exc}')

        if not answers_path.is_file():
            answer_details = {
                'status': 'failed',
                'error': f'answers.json was not created at {answers_path}',
                'cli_exit_code': resolve_code,
                'output': buf.getvalue()[-500:] if buf.getvalue() else None,
            }
            errors.append(f'Step 2 (Answer) failed: answers.json not found at {answers_path}')
        else:
            try:
                with open(answers_path, 'r', encoding='utf-8') as f:
                    answers_plan = json.load(f)

                schema = answers_plan.get('schema')
                schema_err = validate_answers_plan(answers_plan)

                if schema != RESOLUTION_SCHEMA:
                    errors.append(f"Step 2 (Answer) invalid schema: expected '{RESOLUTION_SCHEMA}', got '{schema}'")
                    answer_details = {'status': 'failed', 'error': 'Invalid schema', 'schema': schema}
                elif schema_err:
                    errors.append(f'Step 2 (Answer) schema validation failed: {schema_err}')
                    answer_details = {'status': 'failed', 'error': schema_err}
                else:
                    ans_summary = answers_plan.get('summary', {})
                    ready_count = ans_summary.get('ready', 0)
                    review_count = ans_summary.get('review', 0)
                    needs_user_count = ans_summary.get('needs_user', 0)
                    answers_list = answers_plan.get('answers', [])

                    if (ready_count + review_count == 0) and len(answers_list) > 0:
                        errors.append('Step 2 (Answer) resolved 0 answers (ready=0, review=0)')
                        answer_details = {
                            'status': 'failed',
                            'error': 'No resolved answers',
                            'ready_count': 0,
                            'review_count': 0,
                            'needs_user_count': needs_user_count,
                        }
                    else:
                        answered = True
                        answer_details = {
                            'status': 'success',
                            'schema': schema,
                            'ready_count': ready_count,
                            'review_count': review_count,
                            'needs_user_count': needs_user_count,
                            'total_answers': len(answers_list),
                            'path': str(answers_path),
                        }
            except Exception as exc:
                errors.append(f'Step 2 (Answer) failed to read/parse answers.json: {exc}')
                answer_details = {'status': 'failed', 'error': str(exc)}

    # -------------------------------------------------------------------------
    # Step 3 (Fill): Runs form filling (job_applier.filling.__main__.main)
    # -------------------------------------------------------------------------
    if answered:
        fill_args = [url, '--answers', str(answers_path), '--out', str(out_dir)]
        if headed:
            fill_args.append('--headed')
        if overwrite:
            fill_args.append('--overwrite')
        if allow_review:
            fill_args.append('--allow-review')

        buf = io.StringIO()
        fill_code = 0
        try:
            with contextlib.redirect_stdout(buf):
                fill_code = fill_main(fill_args)
        except SystemExit as exc:
            fill_code = exc.code if isinstance(exc.code, int) else 1
        except Exception as exc:
            fill_code = 1
            errors.append(f'Step 3 (Fill) form filling raised exception: {exc}')

        if not report_path.is_file():
            fill_details = {
                'status': 'failed',
                'error': f'fill_report.json was not created at {report_path}',
                'cli_exit_code': fill_code,
                'output': buf.getvalue()[-500:] if buf.getvalue() else None,
            }
            errors.append(f'Step 3 (Fill) failed: fill_report.json not found at {report_path}')
        else:
            try:
                with open(report_path, 'r', encoding='utf-8') as f:
                    report = json.load(f)

                schema = report.get('schema')
                if schema != FILL_SCHEMA:
                    errors.append(f"Step 3 (Fill) invalid schema: expected '{FILL_SCHEMA}', got '{schema}'")

                fill_summary = report.get('summary', {})
                filled_count = fill_summary.get('filled', 0)
                skipped_count = fill_summary.get('skipped', 0)
                failed_count = fill_summary.get('failed', 0)

                fields = report.get('fields', [])
                filled_fields = [f for f in fields if f.get('status') == 'filled']
                verified_fields = [f for f in filled_fields if f.get('verified_value') is not None]
                verified_count = len(verified_fields)

                telemetry = report.get('telemetry', {})
                guard_active = bool(telemetry.get('guard_active'))
                submit_blocked = guard_active and ('blocked_form_submits' in telemetry)

                screenshot_ok = screenshot_path.is_file() and screenshot_path.stat().st_size > 0

                if not screenshot_ok:
                    errors.append(f'Step 3 (Fill) screenshot missing or empty at {screenshot_path}')
                if filled_count == 0:
                    errors.append('Step 3 (Fill) verified 0 filled fields')
                if verified_count != len(filled_fields):
                    errors.append(
                        f'Step 3 (Fill) DOM verification mismatch: {len(filled_fields)} filled, {verified_count} verified'
                    )
                if not submit_blocked:
                    errors.append('Step 3 (Fill) submit blocker guard was not active')

                if (
                    screenshot_ok
                    and filled_count > 0
                    and verified_count == len(filled_fields)
                    and submit_blocked
                    and schema == FILL_SCHEMA
                ):
                    filled = True
                    fill_details = {
                        'status': 'success',
                        'schema': schema,
                        'filled_count': filled_count,
                        'verified_count': verified_count,
                        'skipped_count': skipped_count,
                        'failed_count': failed_count,
                        'submit_blocked': submit_blocked,
                        'report_path': str(report_path),
                        'screenshot_path': str(screenshot_path),
                    }
                else:
                    fill_details = {
                        'status': 'failed',
                        'filled_count': filled_count,
                        'verified_count': verified_count,
                        'skipped_count': skipped_count,
                        'failed_count': failed_count,
                        'submit_blocked': submit_blocked,
                        'screenshot_ok': screenshot_ok,
                    }
            except Exception as exc:
                errors.append(f'Step 3 (Fill) failed to read/parse fill_report.json: {exc}')
                fill_details = {'status': 'failed', 'error': str(exc)}

    # -------------------------------------------------------------------------
    # Step 4 (Validate): Produces structured validation summary
    # -------------------------------------------------------------------------
    if not fetched or not answered:
        status = 'FAILED'
    elif not filled:
        if filled_count > 0:
            status = 'PARTIAL'
        else:
            status = 'FAILED'
    else:
        if failed_count == 0:
            status = 'SUCCESS'
        else:
            status = 'PARTIAL'

    screenshot_final = (
        str(screenshot_path)
        if screenshot_path.is_file() and screenshot_path.stat().st_size > 0
        else None
    )

    summary_result: Dict[str, Any] = {
        'status': status,
        'fetched': fetched,
        'answered': answered,
        'filled': filled,
        'screenshot': screenshot_final,
        'question_count': question_count,
        'ready_count': ready_count,
        'review_count': review_count,
        'needs_user_count': needs_user_count,
        'filled_count': filled_count,
        'verified_count': verified_count,
        'skipped_count': skipped_count,
        'failed_count': failed_count,
        'submit_blocked': submit_blocked,
        'artifacts': {
            'questions': str(questions_path) if questions_path.is_file() else None,
            'answers': str(answers_path) if answers_path.is_file() else None,
            'fill_report': str(report_path) if report_path.is_file() else None,
            'screenshot': screenshot_final,
            'summary': str(summary_path),
        },
        'steps': {
            'fetch': fetch_details,
            'answer': answer_details,
            'fill': fill_details,
        },
        'errors': errors,
    }

    try:
        write_json_atomic(summary_path, summary_result, overwrite=overwrite)
    except Exception as exc:
        summary_result['errors'].append(f'Failed to write validation_summary.json: {exc}')

    return summary_result


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description='Job Applier 4.0: validate fetch -> answer -> fill pipeline end-to-end'
    )
    parser.add_argument('url', help='Public application URL, or file:// for a local fixture')
    parser.add_argument(
        '--out',
        required=True,
        help='Output directory for pipeline artifacts and validation summary',
    )
    parser.add_argument(
        '--headed',
        action='store_true',
        default=False,
        help='Run browser in headed mode',
    )
    parser.add_argument(
        '--bank',
        default=None,
        help='Path to bank JSON (optional)',
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

    summary = validate_pipeline(
        url=args.url,
        out=args.out,
        bank=args.bank,
        headed=args.headed,
        overwrite=args.overwrite,
        allow_review=args.allow_review,
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary.get('status') == 'SUCCESS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
