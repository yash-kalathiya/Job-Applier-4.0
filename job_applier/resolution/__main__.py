"""CLI entrypoint for Phase 2 question resolution."""
import argparse
import json
import os
from pathlib import Path
import sys

from ..safe_io import write_json_atomic
from . import SCHEMA_VERSION
from .engine import pending_questions, resolve_cascade


class NullSemanticMatcher:
    threshold = 0.82
    margin = 0.06

    def rank(self, question, bank):
        return []


def get_semantic_matcher(bank):
    try:
        from .semantic import SemanticMatcher
        from .. import store
        cache_dir = store.path('models')
        return SemanticMatcher(bank, cache_dir=cache_dir, local_only=True)
    except Exception:
        return NullSemanticMatcher()


def get_llm_matcher():
    if not os.environ.get('GROQ_API_KEY'):
        return None
    try:
        from .qwen import QwenMatcher
        return QwenMatcher()
    except Exception:
        return None


DEFAULT_TEMPLATES = [
    {
        'fact': 'contact.email',
        'input_types': ['text', 'email'],
        'aliases': ['Email', 'Email Address', 'E-mail', 'E-mail Address'],
    },
    {
        'fact': 'contact.phone',
        'input_types': ['text', 'tel'],
        'aliases': ['Phone', 'Phone Number', 'Mobile Phone', 'Cell Phone'],
    },
    {
        'fact': 'contact.first_name',
        'input_types': ['text'],
        'aliases': ['First Name', 'Legal First Name', 'Given Name', 'Preferred First Name'],
    },
    {
        'fact': 'contact.last_name',
        'input_types': ['text'],
        'aliases': ['Last Name', 'Legal Last Name', 'Family Name', 'Surname'],
    },
    {
        'fact': 'contact.name',
        'input_types': ['text'],
        'aliases': ['Full Name', 'Legal Name', 'Name', 'Your Name'],
    },
    {
        'fact': 'contact.linkedin',
        'input_types': ['text', 'url'],
        'aliases': ['LinkedIn', 'LinkedIn Profile', 'LinkedIn URL'],
    },
    {
        'fact': 'contact.github',
        'input_types': ['text', 'url'],
        'aliases': ['GitHub', 'GitHub Profile', 'GitHub URL'],
    },
    {
        'fact': 'contact.website',
        'input_types': ['text', 'url'],
        'aliases': [
            'Website',
            'Portfolio',
            'Personal Website',
            'Portfolio URL',
            'Website / portfolio',
        ],
    },
    {
        'fact': 'education.school',
        'input_types': ['text', 'combobox', 'single_choice', 'select'],
        'aliases': ['School', 'University', 'College', 'Institution', 'School / university'],
    },
    {
        'fact': 'education.degree',
        'input_types': ['combobox', 'single_choice', 'select', 'text'],
        'aliases': ['Degree', 'Highest Degree Completed', 'Degree Level', 'Degree Type'],
    },
    {
        'fact': 'education.major',
        'input_types': ['text', 'combobox', 'single_choice', 'select'],
        'aliases': [
            'Major',
            'Major / field of study',
            'Field of Study',
            'Area of Study',
            'Discipline',
        ],
    },
    {
        'fact': 'education.gpa',
        'input_types': ['text'],
        'aliases': ['GPA', 'Grade Point Average', 'Cumulative GPA'],
    },
    {
        'fact': 'work.authorized_us',
        'input_types': ['single_choice', 'combobox', 'select', 'radio'],
        'aliases': [
            'Are you legally authorized to work in the United States?',
            'Legally authorized to work in United States',
            'Authorized to work in the United States',
            'Legally authorized to work in the US',
            'Work Authorization',
        ],
    },
    {
        'fact': 'work.us_sponsorship_now_or_future',
        'input_types': ['single_choice', 'combobox', 'select', 'radio'],
        'aliases': [
            'Will you now or in the future require visa sponsorship?',
            'Will you require sponsorship?',
            'Will you now or in the future require sponsorship?',
            'Visa Sponsorship',
        ],
    },
    {
        'fact': 'personal.relocate',
        'input_types': ['single_choice', 'combobox', 'select', 'radio'],
        'aliases': ['Are you willing to relocate?', 'Willing to relocate'],
    },
    {
        'fact': 'application.resume',
        'input_types': ['file'],
        'aliases': ['Resume/CV', 'Upload Resume', 'Resume', 'CV'],
    },
]


def _degree_aliases(degree_val):
    """Return proven equivalent aliases only for confirmed actual degree value.

    Automatic cross-qualification aliases (e.g. mapping Bachelor to BS/BA, BS to BA,
    or MS to MA) are removed. Safest behavior is empty option_labels so that only
    exact normalized matches against the actual fact value succeed.
    """
    return []


def _build_bank_from_profile_and_answers(profile, raw_answers):
    name_tokens = (profile.get('name') or '').split()
    first_name = name_tokens[0] if name_tokens else None
    last_name = name_tokens[-1] if len(name_tokens) > 1 else None
    name = ' '.join(name_tokens) if name_tokens else None

    facts = {
        'contact.email': {
            'value': profile.get('email') or None,
            'confirmed': bool(profile.get('email')),
            'source': 'vault',
        },
        'contact.phone': {
            'value': profile.get('phone') or None,
            'confirmed': bool(profile.get('phone')),
            'source': 'vault',
        },
        'contact.first_name': {
            'value': first_name,
            'confirmed': bool(first_name),
            'source': 'vault',
        },
        'contact.last_name': {
            'value': last_name,
            'confirmed': bool(last_name),
            'source': 'vault',
        },
        'contact.name': {
            'value': name,
            'confirmed': bool(name),
            'source': 'vault',
        },
        'contact.linkedin': {
            'value': profile.get('linkedin') or None,
            'confirmed': bool(profile.get('linkedin')),
            'source': 'vault',
        },
        'contact.github': {
            'value': profile.get('github') or None,
            'confirmed': bool(profile.get('github')),
            'source': 'vault',
        },
        'contact.website': {
            'value': profile.get('website') or None,
            'confirmed': bool(profile.get('website')),
            'source': 'vault',
        },
        'education.school': {
            'value': profile.get('school') or None,
            'confirmed': bool(profile.get('school')),
            'source': 'vault',
        },
        'education.degree': {
            'value': profile.get('degree') or None,
            'confirmed': bool(profile.get('degree')),
            'source': 'vault',
            'option_labels': _degree_aliases(profile.get('degree')),
        },
        'education.major': {
            'value': profile.get('major') or None,
            'confirmed': bool(profile.get('major')),
            'source': 'vault',
        },
        'education.gpa': {
            'value': profile.get('gpa') or None,
            'confirmed': bool(profile.get('gpa')),
            'source': 'vault',
        },
        'work.authorized_us': {
            'value': profile.get('work_authorized_us'),
            'confirmed': profile.get('work_authorized_us') is not None,
            'source': 'vault',
        },
        'work.us_sponsorship_now_or_future': {
            'value': profile.get('needs_sponsorship'),
            'confirmed': profile.get('needs_sponsorship') is not None,
            'source': 'vault',
        },
        'personal.relocate': {
            'value': profile.get('willing_to_relocate'),
            'confirmed': profile.get('willing_to_relocate') is not None,
            'source': 'vault',
        },
        'application.resume': {
            'value': profile.get('resume_path') or '/vault/resume.pdf',
            'confirmed': True,
            'source': 'vault',
        },
    }

    templates = [dict(t) for t in DEFAULT_TEMPLATES if 'fact' in t]

    key_map = {
        'work_auth': 'work.authorized_us',
        'sponsorship': 'work.us_sponsorship_now_or_future',
        'relocate': 'personal.relocate',
        'email': 'contact.email',
        'phone': 'contact.phone',
        'first_name': 'contact.first_name',
        'last_name': 'contact.last_name',
        'full_name': 'contact.name',
        'linkedin': 'contact.linkedin',
        'github': 'contact.github',
        'website': 'contact.website',
        'school': 'education.school',
        'degree': 'education.degree',
        'major': 'education.major',
        'gpa': 'education.gpa',
    }

    for row in (raw_answers or []):
        k = row.get('key')
        val = row.get('answer')
        q_label = row.get('question')
        if not k:
            continue
        fact_key = key_map.get(k, k)
        if fact_key in facts:
            if facts[fact_key]['value'] is None and val is not None and val != '':
                if fact_key in (
                    'work.authorized_us',
                    'work.us_sponsorship_now_or_future',
                    'personal.relocate',
                ):
                    if isinstance(val, str):
                        is_yes = val.strip().lower() == 'yes'
                        is_no = val.strip().lower() == 'no'
                        val = True if is_yes else (False if is_no else val)
                facts[fact_key]['value'] = val
                facts[fact_key]['confirmed'] = True
                facts[fact_key]['source'] = row.get('source') or 'vault'
                if fact_key == 'education.degree':
                    facts[fact_key]['option_labels'] = _degree_aliases(val)
        else:
            if val is not None and val != '':
                facts[fact_key] = {
                    'value': val,
                    'confirmed': True,
                    'source': row.get('source') or 'vault',
                }
                if q_label:
                    templates.append({
                        'fact': fact_key,
                        'input_types': ['text', 'combobox', 'single_choice', 'select', 'radio'],
                        'aliases': [q_label],
                    })

    return {'questions': templates, 'facts': facts}


def _build_default_bank():
    from .. import store
    from .. import answers as ans
    try:
        profile = store.profile()
    except Exception:
        profile = {}
    try:
        raw_answers = store.answers()
    except Exception:
        raw_answers = ans.default_bank(profile)
    return _build_bank_from_profile_and_answers(profile, raw_answers)


def load_bank(bank_path=None):
    if bank_path:
        p = Path(bank_path).expanduser().resolve()
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and 'questions' in data and 'facts' in data:
            return data
        if isinstance(data, list):
            return _build_bank_from_profile_and_answers({}, data)
        if isinstance(data, dict) and 'facts' in data:
            templates = [dict(t) for t in DEFAULT_TEMPLATES if 'fact' in t]
            return {'questions': templates, 'facts': data['facts']}
        raise ValueError(f'Unrecognized bank format in {bank_path}')
    return _build_default_bank()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description='Job Applier 4.0 Phase 2: match questions to facts (job-applier resolve)'
    )
    parser.add_argument(
        'questions',
        help='Path to questions.json (Phase 1 extraction output)',
    )
    parser.add_argument('--bank', default=None, help='Path to bank JSON (optional)')
    parser.add_argument(
        '--out',
        required=True,
        help='Path to write answers.json (or output directory)',
    )
    parser.add_argument(
        '--scope',
        default='job_application',
        help='Scope identifier string (default: job_application)',
    )
    parser.add_argument(
        '--format',
        choices=['json', 'summary'],
        default='json',
        help='Format (json or summary, default json)',
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        default=False,
        help='Allow overwriting existing output file',
    )

    args = parser.parse_args(argv)

    questions_path = Path(args.questions).expanduser().resolve()
    if not questions_path.is_file():
        parser.error(f'Questions file not found: {args.questions}')

    if args.bank:
        bank_path = Path(args.bank).expanduser().resolve()
        if not bank_path.is_file():
            parser.error(f'Bank file not found: {args.bank}')

    try:
        with open(questions_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        parser.error(f'Failed to parse questions JSON: {e}')

    raw_questions = data.get('questions') if isinstance(data, dict) else data
    questions = raw_questions if isinstance(raw_questions, list) else []
    snapshot_id = data.get('snapshot_id') if isinstance(data, dict) else None

    try:
        bank = load_bank(args.bank)
    except Exception as e:
        parser.error(f'Failed to load bank: {e}')

    semantic = get_semantic_matcher(bank)
    llm = get_llm_matcher()

    cascade = resolve_cascade(questions, bank, semantic, llm=llm)
    results = cascade.get('results', [])
    pending = pending_questions(questions, results, args.scope)

    output = {
        'schema': SCHEMA_VERSION,
        'snapshot_id': snapshot_id,
        'scope': args.scope,
        'summary': {
            'total': len(questions),
            'ready': sum(1 for r in results if r['status'] == 'ready'),
            'review': sum(1 for r in results if r['status'] == 'review'),
            'needs_user': sum(1 for r in results if r['status'] == 'needs_user'),
        },
        'answers': results,
        'pending': pending,
        'calls': cascade.get('calls', []),
        'elapsed_ms': cascade.get('elapsed_ms', 0),
    }

    out_lexical = os.path.abspath(os.path.expanduser(args.out))
    if str(args.out).endswith(('/', '\\')) or os.path.isdir(out_lexical):
        out_file = Path(out_lexical) / 'answers.json'
    elif Path(out_lexical).suffix.lower() == '.json':
        out_file = Path(out_lexical)
    else:
        out_file = Path(out_lexical) / 'answers.json'

    try:
        write_json_atomic(out_file, output, overwrite=args.overwrite)
    except (OSError, ValueError) as err:
        parser.error(f'Failed to write output: {err}')

    if args.format == 'json':
        print(json.dumps(output, indent=2, ensure_ascii=False))
    elif args.format == 'summary':
        summary = output['summary']
        lines = [
            f"Scope: {output['scope']}",
            f"Total: {summary['total']}",
            f"Ready: {summary['ready']}",
            f"Review: {summary['review']}",
            f"Needs User: {summary['needs_user']}",
            f"Elapsed: {output['elapsed_ms']}ms",
        ]
        print('\n'.join(lines))

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
