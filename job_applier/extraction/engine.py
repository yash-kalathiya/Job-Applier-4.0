"""Read form questions using DOM details and locator-scoped accessibility snapshots.

No profile, answer resolver, language model, uploads, or submission actions live here.
AX evidence is joined to DOM evidence by the same live locator, never label similarity.
"""
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import SCHEMA_VERSION

SELECTOR = ('input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]),'
            'textarea,select,[role=combobox],[role=radio],[role=checkbox],[role=switch],[role=slider],'
            '[role=spinbutton],[role=textbox],[contenteditable=true]')
DOM_SCRIPT = Path(__file__).with_name('dom.js').read_text(encoding='utf-8')
INSTRUCTIONS_SCRIPT = """forms => forms.flatMap(form => {
  return [...form.querySelectorAll('p,[role=alert]')]
    .filter(e => e.getBoundingClientRect().height > 0)
    .map(e => ({
      text: (e.innerText || '').trim(),
      links: [...e.querySelectorAll('a[href]')].map(a => ({label:a.textContent.trim(), url:a.href}))
    }))
    .filter(e => e.text && !/^[*\\s]+$/.test(e.text));
})"""
FIELD_ROLES = {'textbox', 'searchbox', 'combobox', 'listbox', 'radio', 'checkbox', 'switch', 'spinbutton', 'slider'}
GUARD_SCRIPT = """(() => {
  document.addEventListener('submit', e => { e.preventDefault(); e.stopImmediatePropagation(); }, true);
  HTMLFormElement.prototype.submit = function() { throw new Error('Phase 1 blocks submission'); };
  HTMLFormElement.prototype.requestSubmit = function() { throw new Error('Phase 1 blocks submission'); };
  document.addEventListener('click', e => {
    const b = e.target.closest('button,input[type=submit],input[type=image]');
    if (b && (b.type === 'submit' || b.type === 'image')) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
})()"""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def accessibility(raw):
    """Parse only the root semantic control; retain the full snapshot as evidence."""
    for line in raw.splitlines():
        m = re.match(r'^\s*- ([\w-]+)(.*)', line)
        if not m or m[1] not in FIELD_ROLES:
            continue
        tail = m[2].strip()
        name = ''
        if tail.startswith('"'):
            try:
                name, _ = json.JSONDecoder().raw_decode(tail)
            except ValueError:
                pass
        states = re.findall(r'\[([^\]]+)\]', tail)
        return {'role': m[1], 'name': name, 'states': states, 'snapshot': raw}
    return {'role': None, 'name': '', 'states': [], 'snapshot': raw}


def identity(dom):
    return tuple(dom.get(k) for k in ('path', 'tag', 'type', 'id', 'name', 'label'))


def clean_label(value):
    return re.sub(r'\s+', ' ', re.sub(r'\s*\*\s*$', '', value or '')).strip()


def install_observation_guard(context):
    """Use on a fresh extraction context. Block side-effecting HTTP and form submits."""
    blocked = []
    context.add_init_script(GUARD_SCRIPT)

    def route_request(route):
        request = route.request
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            blocked.append({'method': request.method, 'resource_type': request.resource_type})
            route.abort('blockedbyclient')
        else:
            route.continue_()

    context.route('**/*', route_request)
    context.on('page', lambda page: page.on('dialog', lambda dialog: dialog.dismiss()))
    return blocked


def wait_for_controls(page, timeout_ms=15000):
    """Wait for a short stable control inventory, including embedded forms."""
    deadline = time.monotonic() + timeout_ms / 1000
    previous, stable_since = None, time.monotonic()
    while time.monotonic() < deadline:
        counts = []
        for frame in page.frames:
            try:
                counts.append((frame.url, frame.locator(SELECTOR).count()))
            except Exception:
                continue
        if counts != previous:
            stable_since, previous = time.monotonic(), counts
        if any(count for _, count in counts) and time.monotonic() - stable_since >= 0.8:
            return True
        page.wait_for_timeout(150)
    return False


def inspect_options(frame, locator, dom, limit=500):
    """Open an identified combobox without selecting, typing, or choosing an option."""
    result = {'items': [], 'complete': False, 'status': 'not_inspected', 'source': 'dom_live_listbox'}
    if dom['tag'] == 'select':
        return {'items': dom['options'], 'complete': True, 'status': 'native_complete', 'source': 'dom_select'}
    if dom['disabled'] or dom['readonly'] or not dom['visible']:
        result['status'] = 'unavailable'
        return result
    before = dom['value']
    try:
        locator.click(timeout=1800)
        # Controlled widgets may attach aria-controls only after opening.
        opened = locator.evaluate(DOM_SCRIPT)
        ids = opened['controls_ids']
        scopes = []
        for ident in ids:
            target = frame.locator('[id=' + json.dumps(ident) + ']')
            if target.count() == 1 and target.is_visible():
                scopes.append(target)
        if not scopes:
            lists = frame.get_by_role('listbox').filter(visible=True)
            if lists.count() == 1:
                scopes = [lists]
        if len(scopes) != 1:
            result['status'] = 'listbox_not_uniquely_associated'
        else:
            choices = scopes[0].get_by_role('option')
            try:
                choices.first.wait_for(state='visible', timeout=1200)
            except Exception:
                pass
            items = choices.evaluate_all("""els => els.map(e => ({id:e.id||null,
                label:(e.textContent||'').replace(/\\s+/g,' ').trim(),
                value:e.getAttribute('data-value') ?? e.getAttribute('value'),
                disabled:e.getAttribute('aria-disabled')==='true',selected:e.getAttribute('aria-selected')==='true'}))""")
            result['items'] = items[:limit]
            result['status'] = 'truncated' if len(items) > limit else 'observed_visible_only' if items else 'empty_or_search_required'
            # Visible list contents alone cannot prove all async/virtualized options exist.
            result['accessibility_snapshot'] = scopes[0].aria_snapshot(timeout=1200)
    except Exception as exc:
        result['status'] = 'inspection_failed'
        result['error'] = type(exc).__name__
    finally:
        try:
            locator.press('Escape', timeout=1200)
        except Exception:
            pass
    try:
        after = locator.evaluate(DOM_SCRIPT)
        result['value_unchanged'] = before == after['value']
    except Exception:
        result['value_unchanged'] = None
    return result


def collect(page, *, probe_options=True, max_controls=250):
    started = time.monotonic()
    controls, frames, issues, notices, instructions = [], [], [], [], []
    captured = datetime.now(timezone.utc).isoformat()
    for frame_index, frame in enumerate(page.frames):
        frame_id = 'frame-' + str(frame_index)
        record = {'id': frame_id, 'url': frame.url, 'name': frame.name, 'accessibility_snapshot': ''}
        frames.append(record)
        if re.search(r'(recaptcha|hcaptcha)', frame.url, re.I):
            notices.append({'code': 'verification_frame_not_inspected', 'frame': frame_id})
            continue
        try:
            record['accessibility_snapshot'] = frame.locator('body').aria_snapshot(timeout=2500)
            locators = frame.locator(SELECTOR)
            total = locators.count()
        except Exception as exc:
            issues.append({'code': 'frame_unreadable', 'frame': frame_id, 'error': type(exc).__name__})
            continue
        try:
            for item in frame.locator('form').evaluate_all(INSTRUCTIONS_SCRIPT):
                instructions.append({'frame': frame_id, **item})
        except Exception as exc:
            issues.append({'code': 'instructions_unreadable', 'frame': frame_id, 'error': type(exc).__name__})
        if total > max_controls:
            issues.append({'code': 'control_limit', 'frame': frame_id, 'observed': total, 'limit': max_controls})
        seen = set()
        for index in range(min(total, max_controls)):
            locator = locators.nth(index)
            try:
                dom = locator.evaluate(DOM_SCRIPT, timeout=1800)
                if dom['path'] in seen:
                    continue
                if dom['type'] == 'password':
                    issues.append({'code': 'sign_in_required', 'frame': frame_id})
                    continue
                if not dom['visible'] and not dom['file_trigger_visible']:
                    continue
                if dom['parent_combobox_path']:
                    # Parent widget is already represented; avoid counting its text input twice.
                    continue
                seen.add(dom['path'])
                raw = locator.aria_snapshot(timeout=1800)
                ax = accessibility(raw)
                if dom['group']:
                    try:
                        ax['group_snapshot'] = frame.locator(dom['group']['path']).aria_snapshot(timeout=1800)
                    except Exception:
                        ax['group_snapshot'] = ''
                after = locator.evaluate(DOM_SCRIPT, timeout=1800)
                if identity(dom) != identity(after):
                    issues.append({'code': 'control_changed_during_capture', 'frame': frame_id, 'path': dom['path']})
                    continue
                ident = 'control-' + digest([frame_id, dom['form_path'], dom['path']])
                warnings = []
                dom_name, ax_name = clean_label(dom['label']), clean_label(ax['name'])
                if dom_name and ax_name and dom_name.casefold() != ax_name.casefold():
                    warnings.append('label_conflict')
                if not ax['role']:
                    warnings.append('accessibility_control_missing')
                if not dom_name and not ax_name:
                    warnings.append('question_label_missing')
                kind = ax['role'] or dom['type']
                options = {'items': dom['options'], 'complete': dom['tag'] == 'select',
                           'status': 'native_complete' if dom['tag'] == 'select' else 'not_applicable', 'source': 'dom'}
                if kind in {'combobox', 'listbox'} and dom['tag'] != 'select':
                    options = inspect_options(frame, locator, dom) if probe_options else {
                        'items': [], 'complete': False, 'status': 'not_inspected', 'source': 'none'}
                    if options.get('value_unchanged') is False:
                        warnings.append('option_inspection_changed_value')
                        issues.append({'code': 'option_inspection_changed_value', 'control': ident})
                        probe_options = False
                question_text = clean_label(dom['group']['label']) if dom['type'] == 'file' and dom['group'] and dom['group']['label'] else dom_name or ax_name or dom['placeholder'] or '(Unlabeled control)'
                controls.append({'id': ident, 'frame_id': frame_id, 'input_type': kind,
                    'question_text': question_text,
                    'required': dom['required'], 'options': options, 'warnings': warnings,
                    'evidence': {'dom': dom, 'accessibility': ax, 'join_method': 'same_locator_identity_checked'},
                    'locator_candidates': ([{'by': 'role', 'role': ax['role'], 'name': ax_name}] if ax_name else []) +
                        ([{'by': 'id', 'value': dom['id']}] if dom['id'] else []) +
                        [{'by': 'snapshot_dom_path', 'value': dom['path']}],
                    'locator_scope': {'frame': frame_id, 'form': dom['form_path'], 'group': dom['group']}})
            except Exception as exc:
                issues.append({'code': 'control_unreadable', 'frame': frame_id, 'index': index, 'error': type(exc).__name__})
    questions = group_questions(controls)
    if not questions:
        issues.append({'code': 'no_application_questions'})
    revision = digest(questions)
    return {'schema_version': SCHEMA_VERSION, 'snapshot_id': revision, 'captured_at': captured,
            'page': {'url': page.url, 'title': page.title()},
            'coverage': 'Currently rendered controls only; hidden branches and later steps are not explored.',
            'status': 'partial' if issues else 'captured', 'issues': issues, 'notices': notices,
            'instructions': instructions, 'frames': frames,
            'questions': questions, 'controls': controls,
            'summary': {'questions': len(questions), 'controls': len(controls),
                'combined_controls': sum(bool(c['evidence']['accessibility']['role']) for c in controls),
                'conflicts': sum('label_conflict' in c['warnings'] for c in controls),
                'options_incomplete': sum(q['options']['complete'] is False and q['input_type'] in {'combobox','listbox','single_choice','multiple_choice'} for q in questions),
                'llm_calls': 0, 'llm_tokens': 0, 'elapsed_ms': round((time.monotonic() - started)*1000)}}


def group_questions(controls):
    groups = {}
    for c in controls:
        d = c['evidence']['dom']
        kind = c['input_type']
        group = d['group'] or {}
        key = c['id']
        if kind == 'radio' and (d['name'] or group.get('path')):
            key = (c['frame_id'], d['form_path'], 'radio', group.get('path'), d['name'])
        elif kind == 'checkbox' and d['name'] and group.get('label'):
            key = (c['frame_id'], d['form_path'], 'checkbox', group.get('path'), d['name'])
        groups.setdefault(key, []).append(c)
    questions = []
    for members in groups.values():
        first = members[0]
        d = first['evidence']['dom']
        grouped = len(members) > 1
        text = (d['group'] or {}).get('label') if grouped else None
        text = clean_label(text or first['question_text'])
        required_values = [c['required'] for c in members]
        required = True if True in required_values else False if all(v is False for v in required_values) else None
        options = first['options']
        if grouped:
            options = {'items': [{'id': c['id'], 'label': c['question_text'],
                'value': c['evidence']['dom']['option_value'], 'disabled': c['evidence']['dom']['disabled'],
                'selected': c['evidence']['dom']['value']} for c in members],
                'complete': True, 'status': 'rendered_group', 'source': 'dom_and_accessibility'}
        warnings = sorted({w for c in members for w in c['warnings']})
        if grouped and not (d['group'] or {}).get('label'):
            text = '(Unlabeled choice group)'
            warnings.append('group_label_missing')
        questions.append({'id': 'question-' + digest([c['id'] for c in members]),
            'text': text, 'input_type': ('single_choice' if first['input_type'] == 'radio' else 'multiple_choice') if grouped else first['input_type'],
            'required': required, 'section': d['section'], 'help': d['help'],
            'control_ids': [c['id'] for c in members], 'options': options,
            'warnings': warnings, 'frame_id': first['frame_id']})
    return questions
