"""Phase 3 form filling engine driven by Playwright with observation & submit-blocker guard.

Safety boundaries note:
Never submits forms or sends data to external services.
Blocks POST, PUT, DELETE, and PATCH network requests and prevents form submission.
Limitation note: While HTTP mutation requests (POST/PUT/DELETE/PATCH) and form submissions
are intercepted and strictly blocked, remote side effects via GET/HEAD/OPTIONS requests or
established WebSockets cannot be guaranteed impossible. Fresh browser contexts and service workers
should remain blocked. Never exercise real submissions.
"""
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, List, Optional

from . import SCHEMA_VERSION
from ..safe_io import write_bytes_atomic, write_json_atomic


class UnsupportedFrameError(ValueError):
    """Raised when target child frame has ambiguous identity or cannot be distinguished from duplicate peers."""
    pass


SUPPORTED_LOCATOR_KINDS = {'id', 'name', 'role', 'css', 'snapshot_dom_path'}


def _validate_and_normalize_candidates(cands: Any, ans_idx: int, prefix: str) -> Optional[str]:
    if not isinstance(cands, list):
        return f"Malformed answer at index {ans_idx}: '{prefix}' must be a list, got {type(cands).__name__}"
    for c_idx, cand in enumerate(cands):
        ctx = f"{prefix}[{c_idx}]"
        if not isinstance(cand, dict):
            return f"Malformed answer at index {ans_idx}: {ctx} must be a dict, got {type(cand).__name__}"
        by_val = cand.get('by')
        kind_val = cand.get('kind')
        if by_val is None and kind_val is None:
            return f"Malformed answer at index {ans_idx}: {ctx} missing 'by'/'kind' locator kind"
        if by_val is not None and not isinstance(by_val, str):
            return f"Malformed answer at index {ans_idx}: {ctx} kind/by must be a string, got {type(by_val).__name__}"
        if kind_val is not None and not isinstance(kind_val, str):
            return f"Malformed answer at index {ans_idx}: {ctx} kind/by must be a string, got {type(kind_val).__name__}"
        if by_val is not None and kind_val is not None and by_val != kind_val:
            return f"Malformed answer at index {ans_idx}: {ctx} contradictory 'by' ({by_val!r}) and 'kind' ({kind_val!r})"

        for attr in ('value', 'role', 'name', 'selector'):
            attr_val = cand.get(attr)
            if attr_val is not None and not isinstance(attr_val, str):
                return f"Malformed answer at index {ans_idx}: {ctx} '{attr}' must be a string, got {type(attr_val).__name__}"

        raw_kind = by_val if by_val is not None else kind_val
        if raw_kind is None or not raw_kind.strip():
            return f"Malformed answer at index {ans_idx}: {ctx} locator kind must be a non-empty string"
        effective_by = raw_kind.strip()
        if effective_by not in SUPPORTED_LOCATOR_KINDS:
            return f"Malformed answer at index {ans_idx}: {ctx} unsupported locator kind '{effective_by}'"

        cand['by'] = effective_by
        if 'kind' in cand:
            cand['kind'] = effective_by

        if effective_by == 'role':
            role_val = cand.get('role')
            if role_val is None or not isinstance(role_val, str) or not role_val.strip():
                return f"Malformed answer at index {ans_idx}: {ctx} 'role' must be a non-empty string"
            name_val = cand.get('name')
            if name_val is not None and not isinstance(name_val, str):
                return f"Malformed answer at index {ans_idx}: {ctx} 'name' must be a string"
        elif effective_by in ('id', 'name'):
            val = cand.get('value')
            if val is None or not isinstance(val, str) or not val.strip():
                return f"Malformed answer at index {ans_idx}: {ctx} 'value' must be a non-empty string"
        elif effective_by in ('css', 'snapshot_dom_path'):
            v = cand.get('value')
            s = cand.get('selector')
            v_str = (v or '').strip() if isinstance(v, str) else ''
            s_str = (s or '').strip() if isinstance(s, str) else ''
            if not v_str and not s_str:
                return f"Malformed answer at index {ans_idx}: {ctx} requires a non-empty string payload in 'value' or 'selector'"
    return None


def validate_answers_plan(plan: Any) -> Optional[str]:
    """Validate answers plan structure before browser startup or DOM interaction."""
    if not isinstance(plan, dict):
        return f"Malformed answers plan: expected JSON object, got {type(plan).__name__}"

    for plan_field in ('schema', 'snapshot_id', 'scope'):
        pv = plan.get(plan_field)
        if pv is not None and not isinstance(pv, str):
            return f"Malformed answers plan: field '{plan_field}' must be a string, got {type(pv).__name__}"

    answers = plan.get('answers')
    if answers is None:
        return "Malformed answers plan: missing 'answers' field"
    if not isinstance(answers, list):
        return f"Malformed answers plan: 'answers' must be a list, got {type(answers).__name__}"

    for i, ans in enumerate(answers):
        if not isinstance(ans, dict):
            return f"Malformed answer at index {i}: expected JSON object, got {type(ans).__name__}"

        # text null is invalid! Must be a non-null string
        text_val = ans.get('text')
        if text_val is None or not isinstance(text_val, str):
            return f"Malformed answer at index {i}: 'text' must be a non-null string, got {type(text_val).__name__}"

        # primitive strings including consumed top-level fields
        for field in (
            'id', 'question_id', 'input_type', 'native_input_type', 'status',
            'fact_key', 'tier', 'frame_id', 'form_id', 'form_path',
        ):
            val = ans.get(field)
            if val is not None and not isinstance(val, str):
                return f"Malformed answer at index {i}: field '{field}' must be a string, got {type(val).__name__}"

        ans_val = ans.get('answer')
        if ans_val is not None and isinstance(ans_val, (dict, list)):
            return f"Malformed answer at index {i}: 'answer' must be a primitive value, got {type(ans_val).__name__}"

        # selected_option
        sel_opt = ans.get('selected_option')
        if sel_opt is not None:
            if not isinstance(sel_opt, dict):
                return f"Malformed answer at index {i}: 'selected_option' must be a dict, got {type(sel_opt).__name__}"
            for k in ('id', 'label'):
                v = sel_opt.get(k)
                if v is not None and not isinstance(v, str):
                    return f"Malformed answer at index {i}: selected_option['{k}'] must be a string, got {type(v).__name__}"
            v_val = sel_opt.get('value')
            if v_val is not None and isinstance(v_val, (dict, list)):
                return f"Malformed answer at index {i}: selected_option['value'] must be a primitive, got {type(v_val).__name__}"

        # options dict / items list dict
        opts = ans.get('options')
        if opts is not None:
            if not isinstance(opts, dict):
                return f"Malformed answer at index {i}: 'options' must be a dict, got {type(opts).__name__}"
            items = opts.get('items')
            if items is not None:
                if not isinstance(items, list):
                    return f"Malformed answer at index {i}: options['items'] must be a list, got {type(items).__name__}"
                for k, item in enumerate(items):
                    if not isinstance(item, dict):
                        return f"Malformed answer at index {i}: options['items'][{k}] must be a dict, got {type(item).__name__}"
                    for sk in ('id', 'label'):
                        sv = item.get(sk)
                        if sv is not None and not isinstance(sv, str):
                            return f"Malformed answer at index {i}: options['items'][{k}]['{sk}'] must be a string, got {type(sv).__name__}"
                    sv_val = item.get('value')
                    if sv_val is not None and isinstance(sv_val, (dict, list)):
                        return f"Malformed answer at index {i}: options['items'][{k}]['value'] must be a primitive, got {type(sv_val).__name__}"
                    if 'disabled' in item and item['disabled'] is not None and not isinstance(item['disabled'], bool):
                        return f"Malformed answer at index {i}: options['items'][{k}]['disabled'] must be a boolean, got {type(item['disabled']).__name__}"

        # locator_scope: form / group / path member types
        scope = ans.get('locator_scope')
        if scope is not None:
            if not isinstance(scope, dict):
                return f"Malformed answer at index {i}: 'locator_scope' must be a dict, got {type(scope).__name__}"
            for sk in ('form', 'form_id', 'frame', 'frame_url', 'frame_name', 'frame_element_id'):
                sv = scope.get(sk)
                if sv is not None and not isinstance(sv, str):
                    return f"Malformed answer at index {i}: locator_scope['{sk}'] must be a string, got {type(sv).__name__}"
            if 'ambiguous_peer' in scope and scope['ambiguous_peer'] is not None and not isinstance(scope['ambiguous_peer'], bool):
                return f"Malformed answer at index {i}: locator_scope['ambiguous_peer'] must be a boolean, got {type(scope['ambiguous_peer']).__name__}"
            if 'has_form' in scope and scope['has_form'] is not None and not isinstance(scope['has_form'], bool):
                return f"Malformed answer at index {i}: locator_scope['has_form'] must be a boolean, got {type(scope['has_form']).__name__}"
            grp = scope.get('group')
            if grp is not None:
                if not isinstance(grp, dict):
                    return f"Malformed answer at index {i}: locator_scope['group'] must be a dict, got {type(grp).__name__}"
                for gk in ('path', 'name', 'id', 'label', 'form'):
                    gv = grp.get(gk)
                    if gv is not None and not isinstance(gv, str):
                        return f"Malformed answer at index {i}: locator_scope['group']['{gk}'] must be a string, got {type(gv).__name__}"

        # frame_descriptor: id, url, name, frame_id, element_id, ambiguous_peer
        frame_desc = ans.get('frame_descriptor')
        if frame_desc is not None:
            if not isinstance(frame_desc, dict):
                return f"Malformed answer at index {i}: 'frame_descriptor' must be a dict, got {type(frame_desc).__name__}"
            for fk in ('id', 'url', 'name', 'frame_id', 'element_id'):
                fv = frame_desc.get(fk)
                if fv is not None and not isinstance(fv, str):
                    return f"Malformed answer at index {i}: frame_descriptor['{fk}'] must be a string, got {type(fv).__name__}"
            if 'ambiguous_peer' in frame_desc and frame_desc['ambiguous_peer'] is not None and not isinstance(frame_desc['ambiguous_peer'], bool):
                return f"Malformed answer at index {i}: frame_descriptor['ambiguous_peer'] must be a boolean, got {type(frame_desc['ambiguous_peer']).__name__}"

        # locator_candidates: list of dicts with kind/by and candidate fields
        cands = ans.get('locator_candidates')
        if cands is not None:
            cand_err = _validate_and_normalize_candidates(cands, i, 'locator_candidates')
            if cand_err:
                return cand_err

        # control_metadata: list of dicts with dom and locator metadata shape
        ctrl_meta = ans.get('control_metadata')
        if ctrl_meta is not None:
            if not isinstance(ctrl_meta, list):
                return f"Malformed answer at index {i}: 'control_metadata' must be a list, got {type(ctrl_meta).__name__}"
            for j, cm in enumerate(ctrl_meta):
                if not isinstance(cm, dict):
                    return f"Malformed answer at index {i}: control_metadata[{j}] must be a dict, got {type(cm).__name__}"
                for ck in ('id', 'input_type', 'native_input_type', 'ax_role', 'label'):
                    cv = cm.get(ck)
                    if cv is not None and not isinstance(cv, str):
                        return f"Malformed answer at index {i}: control_metadata[{j}]['{ck}'] must be a string, got {type(cv).__name__}"
                dom_m = cm.get('dom')
                if dom_m is not None:
                    if not isinstance(dom_m, dict):
                        return f"Malformed answer at index {i}: control_metadata[{j}]['dom'] must be a dict, got {type(dom_m).__name__}"
                    for dk in ('id', 'name', 'tag', 'type', 'path', 'form_path', 'form_id', 'value', 'option_value', 'label'):
                        dv = dom_m.get(dk)
                        if dv is not None and not isinstance(dv, str):
                            return f"Malformed answer at index {i}: control_metadata[{j}]['dom']['{dk}'] must be a string, got {type(dv).__name__}"
                    if 'has_form' in dom_m and dom_m['has_form'] is not None and not isinstance(dom_m['has_form'], bool):
                        return f"Malformed answer at index {i}: control_metadata[{j}]['dom']['has_form'] must be a boolean, got {type(dom_m['has_form']).__name__}"
                    d_grp = dom_m.get('group')
                    if d_grp is not None:
                        if not isinstance(d_grp, dict):
                            return f"Malformed answer at index {i}: control_metadata[{j}]['dom']['group'] must be a dict, got {type(d_grp).__name__}"
                        for dgk in ('path', 'name', 'label', 'form', 'id'):
                            dgv = d_grp.get(dgk)
                            if dgv is not None and not isinstance(dgv, str):
                                return f"Malformed answer at index {i}: control_metadata[{j}]['dom']['group']['{dgk}'] must be a string, got {type(dgv).__name__}"
                cm_cands = cm.get('locator_candidates')
                if cm_cands is not None:
                    cm_err = _validate_and_normalize_candidates(cm_cands, i, f"control_metadata[{j}]['locator_candidates']")
                    if cm_err:
                        return cm_err

    return None

DOM_SCRIPT = (Path(__file__).resolve().parent.parent / 'extraction' / 'dom.js').read_text(encoding='utf-8')


def _normalize_semantic_label(val: Optional[str]) -> str:
    if not val:
        return ""
    # strip trailing required markers like * or (required) or (optional)
    s = re.sub(r'[\s*]+$', '', val)
    s = re.sub(r'\s*\((?:required|optional)\)\s*$', '', s, flags=re.I)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


GUARD_SCRIPT = """(() => {
  if (window.__job_applier_guard && window.__job_applier_guard.installed) return;
  const guard = {
    installed: true,
    blocked_submits: 0,
    submit_attempts: []
  };
  window.__job_applier_guard = guard;

  // Backward-compatibility properties
  window.__job_applier_guard_installed = true;
  window.__job_applier_submit_blocked = false;
  window.__job_applier_blocked_submits = 0;

  function recordSubmitBlock(source) {
    guard.blocked_submits++;
    guard.submit_attempts.push({ source: source, time: Date.now() });
    window.__job_applier_submit_blocked = true;
    window.__job_applier_blocked_submits = guard.blocked_submits;
  }

  // Intercept and prevent form submit events
  document.addEventListener('submit', e => {
    e.preventDefault();
    e.stopImmediatePropagation();
    recordSubmitBlock('submit_event');
    return false;
  }, true);

  // Override submit and requestSubmit on HTMLFormElement
  HTMLFormElement.prototype.submit = function() {
    recordSubmitBlock('form_prototype_submit');
    throw new Error('Phase 3 observation guard strictly blocks form submission');
  };

  HTMLFormElement.prototype.requestSubmit = function() {
    recordSubmitBlock('form_prototype_requestSubmit');
    throw new Error('Phase 3 observation guard strictly blocks form submission');
  };

  // Intercept clicks on any submit buttons
  document.addEventListener('click', e => {
    const b = e.target.closest('button, input[type=submit], input[type=image], [role=button]');
    if (!b) return;
    const tag = b.tagName.toLowerCase();
    const type = (b.getAttribute('type') || '').toLowerCase();
    const isSubmit = (tag === 'input' && (type === 'submit' || type === 'image')) ||
                     (tag === 'button' && (type === 'submit' || type === '')) ||
                     /submit/i.test(b.innerText || '') ||
                     /submit/i.test(b.value || '') ||
                     /submit/i.test(b.getAttribute('aria-label') || '');
    if (isSubmit) {
      e.preventDefault();
      e.stopImmediatePropagation();
      recordSubmitBlock('click_submit_button');
    }
  }, true);
})();"""




def install_observation_guard(target: Any) -> List[Dict[str, Any]]:
    """Install observation guard on a Playwright BrowserContext or Page.

    Blocks POST, PUT, DELETE, PATCH requests and prevents form submissions.
    Preserves one authoritative Python network ledger spanning navigation and fill.
    """
    existing_ledger = getattr(target, '_job_applier_blocked_requests', None)
    if existing_ledger is None and hasattr(target, 'context'):
        existing_ledger = getattr(target.context, '_job_applier_blocked_requests', None)

    blocked: List[Dict[str, Any]] = existing_ledger if existing_ledger is not None else []
    target._job_applier_blocked_requests = blocked
    if hasattr(target, 'context') and getattr(target, 'context', None):
        target.context._job_applier_blocked_requests = blocked

    def route_request(route: Any) -> None:
        req = route.request
        if (
            req.method in {'POST', 'PUT', 'DELETE', 'PATCH'}
            or req.method not in {'GET', 'HEAD', 'OPTIONS'}
        ):
            blocked.append({
                'method': req.method,
                'url': req.url,
                'resource_type': req.resource_type,
            })
            route.abort('blockedbyclient')
        else:
            route.continue_()

    target.route('**/*', route_request)
    if hasattr(target, 'add_init_script'):
        target.add_init_script(GUARD_SCRIPT)

    # Attach dialog dismiss handler and guard to future context pages
    if hasattr(target, 'on'):
        try:
            target.on(
                'page',
                lambda new_p: (
                    new_p.on('dialog', lambda d: d.dismiss()),
                    new_p.add_init_script(GUARD_SCRIPT),
                    setattr(new_p, '_job_applier_blocked_requests', blocked),
                ),
            )
        except Exception:
            pass

    # If target is a Page or has active pages, inject script and dialog handler immediately
    pages = [target] if hasattr(target, 'evaluate') else getattr(target, 'pages', [])
    def _safe_eval_guard(f):
        try:
            f.evaluate(GUARD_SCRIPT)
        except Exception:
            pass

    for p in pages:
        if hasattr(p, 'on'):
            try:
                p.on('frameattached', _safe_eval_guard)
                p.on('framenavigated', _safe_eval_guard)
                p.on('dialog', lambda dialog: dialog.dismiss())
            except Exception:
                pass
        for f in getattr(p, 'frames', [p]):
            try:
                f.evaluate(GUARD_SCRIPT)
            except Exception:
                pass

    return blocked


def _clean_label(text: str) -> str:
    cleaned = re.sub(r'[*:\s]+$', '', text or '').strip()
    return cleaned


def _slug_candidates(text: str, fact_key: Optional[str] = None) -> List[str]:
    candidates = []
    clean = _clean_label(text)
    base = re.sub(r'\s*\([^)]*\)\s*$', '', clean).strip()
    for s in (base, clean):
        if not s:
            continue
        slug_under = re.sub(r'[^a-zA-Z0-9]+', '_', s.lower()).strip('_')
        slug_dash = re.sub(r'[^a-zA-Z0-9]+', '-', s.lower()).strip('-')
        slug_compact = re.sub(r'[^a-zA-Z0-9]+', '', s.lower())
        for slug in (slug_under, slug_dash, slug_compact):
            if slug and slug not in candidates:
                candidates.append(slug)
    if fact_key:
        last = fact_key.split('.')[-1].lower()
        if last not in candidates:
            candidates.append(last)
    return candidates


def _resolve_scope_root(page: Any, q: Dict[str, Any]) -> Any:
    """Resolve frame root for question or raise ValueError if frame is unsupported/missing/stale."""
    desc = q.get('frame_descriptor') or {}
    scope = q.get('locator_scope') or {}
    frame_id = q.get('frame_id') or scope.get('frame') or desc.get('id') or desc.get('frame_id')
    expected_url = desc.get('url') or scope.get('frame_url')
    expected_name = desc.get('name') or scope.get('frame_name')
    expected_el_id = desc.get('element_id') or scope.get('frame_element_id')

    frames = getattr(page, 'frames', [page])
    main_frame = getattr(page, 'main_frame', page)

    ambiguous_peer = desc.get('ambiguous_peer') or scope.get('ambiguous_peer')
    if ambiguous_peer:
        raise UnsupportedFrameError(
            f"Child frame {frame_id!r} had duplicate identical peers with same URL/name at capture; "
            f"cannot distinguish captured child from survivor/replacement; skipping unsupported"
        )

    # 1. No frame identity provided at all (legacy plan)
    if not frame_id and not expected_url and not expected_name and not expected_el_id:
        if len(frames) == 1:
            return main_frame
        raise UnsupportedFrameError(
            f"Ambiguous target frame: legacy plan has no frame identity and page has {len(frames)} frames"
        )

    # 2. Main document target: explicit main frame ID or no frame identifier
    is_explicit_child = (
        frame_id is not None
        and str(frame_id).lower() not in ('frame-0', 'main', 'top', '')
    ) or bool(expected_el_id)
    if not is_explicit_child and (frame_id in ('frame-0', 'main', 'top') or (not frame_id and len(frames) == 1)):
        if expected_url and main_frame and getattr(main_frame, 'url', None) != expected_url:
            raise ValueError(
                f"Stale frame targeting: expected main frame URL {expected_url!r}, "
                f"but live main frame URL is {getattr(main_frame, 'url', '')!r}"
            )
        if expected_name and main_frame and getattr(main_frame, 'name', '') != expected_name:
            raise ValueError(
                f"Stale frame targeting: expected main frame name {expected_name!r}, "
                f"but live main frame name is {getattr(main_frame, 'name', '')!r}"
            )
        return main_frame

    # 3. Explicit child NEVER main even if URL equals descriptor or about:blank
    child_frames = [fr for fr in frames if fr != main_frame]
    if not child_frames:
        raise ValueError(
            f"Unsupported/stale frame identity: {frame_id!r} (url={expected_url!r}, name={expected_name!r}, element_id={expected_el_id!r}); no child frames exist in live page"
        )

    matched_frames = []
    for f in child_frames:
        f_url = getattr(f, 'url', '')
        f_name = getattr(f, 'name', '')
        f_id = None
        try:
            el = f.frame_element()
            f_id = el.get_attribute('id')
        except Exception:
            pass

        # All supplied constraints must agree
        matches = True
        if expected_el_id and f_id != expected_el_id:
            matches = False
        if expected_url and f_url != expected_url:
            matches = False
        if expected_name and f_name != expected_name:
            matches = False
        if desc.get('id') and not str(desc['id']).startswith('frame-'):
            if desc['id'] not in (f_name, f_id):
                matches = False
        if frame_id and not str(frame_id).startswith('frame-'):
            if frame_id not in (f_name, f_id):
                matches = False

        if matches:
            matched_frames.append(f)

    if len(matched_frames) == 1:
        return matched_frames[0]
    elif len(matched_frames) > 1:
        raise ValueError(
            f"Ambiguous child frame: multiple frames ({len(matched_frames)}) matched {frame_id!r} "
            f"(url={expected_url!r}, name={expected_name!r}, element_id={expected_el_id!r}); identical ambiguous child frames abstain"
        )

    raise ValueError(
        f"Unsupported/stale frame identity: {frame_id!r} (url={expected_url!r}, name={expected_name!r}, element_id={expected_el_id!r}); refusing to fill alternate frame"
    )


def _matches_form(el_loc: Any, expected_form_path: Optional[str]) -> bool:
    if not expected_form_path:
        return True
    try:
        return el_loc.evaluate("""(el, expected) => {
            const isNative = 'form' in el || ['input', 'select', 'textarea', 'button', 'fieldset'].includes((el.tagName || '').toLowerCase());
            const form = isNative ? el.form : el.closest('form');
            if (!form) return false;
            if (expected.startsWith('#') && form.id === expected.slice(1)) return true;
            if (form.id === expected) return true;
            try {
                if (form.matches(expected)) return true;
            } catch (_) {}
            const parts = [];
            let curr = form;
            while (curr && curr.nodeType === 1) {
                const parent = curr.parentElement;
                const siblings = curr.parentNode?.children ? [...curr.parentNode.children].filter(x => x.tagName === curr.tagName) : [curr];
                parts.unshift(curr.tagName.toLowerCase() + ':nth-of-type(' + (siblings.indexOf(curr) + 1) + ')');
                curr = parent;
            }
            return parts.join(' > ') === expected;
        }""", expected_form_path)
    except Exception:
        return True


def _find_candidate_locator(root: Any, candidates: List[Any], form_path: Optional[str] = None) -> Optional[Any]:
    for cand in candidates:
        try:
            loc = None
            if isinstance(cand, str):
                loc = root.locator(cand)
            elif isinstance(cand, dict):
                by = cand.get('by') or cand.get('kind')
                if by == 'id':
                    loc = root.locator(f"#{cand['value']}")
                elif by == 'role':
                    loc = root.get_by_role(cand['role'], name=cand.get('name'))
                elif by in ('snapshot_dom_path', 'css'):
                    loc = root.locator(cand.get('value') or cand.get('selector'))
                elif by == 'name':
                    loc = root.locator(f"[name='{cand['value']}']")
            if loc is not None:
                count = loc.count()
                if count == 1:
                    if form_path and not _matches_form(loc.first, form_path):
                        continue
                    return loc.first
                elif count > 1:
                    if form_path:
                        matching_indices = []
                        for i in range(count):
                            if _matches_form(loc.nth(i), form_path):
                                matching_indices.append(i)
                        if len(matching_indices) == 1:
                            return loc.nth(matching_indices[0])
                        elif len(matching_indices) > 1:
                            raise ValueError(
                                f"Ambiguous locator candidate '{cand}' in form '{form_path}' matched {len(matching_indices)} elements"
                            )
                    raise ValueError(
                        f"Ambiguous locator candidate '{cand}' matched {count} elements"
                    )
        except Exception as e:
            if "Ambiguous locator candidate" in str(e):
                raise
            continue
    return None


def _find_group_container(root: Any, text: str) -> Optional[Any]:
    clean = _clean_label(text)
    base = re.sub(r'\s*\([^)]*\)\s*$', '', clean).strip()
    for pattern in (clean, base):
        if not pattern:
            continue
        for selector in (
            'fieldset',
            '[role="radiogroup"]',
            '[role="group"]',
            '.field',
            '.form-group',
        ):
            try:
                matches = root.locator(selector).filter(
                    has_text=re.compile(rf'^\s*{re.escape(pattern)}', re.I)
                )
                cnt = matches.count()
                if cnt == 1:
                    return matches.first
                elif cnt > 1:
                    raise ValueError(
                        f"Duplicate/ambiguous group containers matching '{pattern}' (found {cnt})"
                    )
            except Exception as e:
                if "Duplicate/ambiguous" in str(e):
                    raise
                continue
    return None


def _detect_field_kind(root: Any, q: Dict[str, Any], locator: Optional[Any] = None) -> str:
    explicit = q.get('native_input_type') or q.get('input_type')

    # If locator is already known, examine DOM properties directly
    if locator is not None:
        try:
            tag = locator.evaluate("el => el.tagName.toLowerCase()")
            el_type = locator.evaluate("el => (el.getAttribute('type') || '').toLowerCase()")
            role = locator.evaluate("el => el.getAttribute('role') || ''")
            class_name = locator.evaluate("el => el.className || ''")
            if tag == 'select':
                return 'select'
            if tag == 'textarea':
                return 'textarea'
            if role == 'combobox' or 'select__' in class_name:
                return 'combobox'
            if el_type == 'radio' or role == 'radio':
                return 'radio'
            if el_type == 'checkbox' or role == 'checkbox':
                return 'checkbox'
            if el_type == 'file':
                return 'file'
            if el_type in {'text', 'email', 'tel', 'url', 'number', 'date', 'password'}:
                return el_type
        except Exception:
            pass

    # Check candidate locators for explicit control tags/types
    candidates = list(q.get('locator_candidates') or [])
    cand_loc = None
    try:
        cand_loc = _find_candidate_locator(root, candidates)
    except Exception:
        cand_loc = None

    if cand_loc is not None:
        try:
            tag = cand_loc.evaluate("el => el.tagName.toLowerCase()")
            el_type = cand_loc.evaluate("el => (el.getAttribute('type') || '').toLowerCase()")
            role = cand_loc.evaluate("el => el.getAttribute('role') || ''")
            class_name = cand_loc.evaluate("el => el.className || ''")
            if tag == 'select':
                return 'select'
            if tag == 'textarea':
                return 'textarea'
            if role == 'combobox' or 'select__' in class_name:
                return 'combobox'
            if el_type == 'radio' or role == 'radio':
                return 'radio'
            if el_type == 'checkbox' or role == 'checkbox':
                return 'checkbox'
            if el_type == 'file':
                return 'file'
            if el_type in {'text', 'email', 'tel', 'url', 'number', 'date', 'password'}:
                return el_type
        except Exception:
            pass

    container = None
    try:
        container = _find_group_container(root, q.get('text', ''))
    except Exception:
        container = None

    if container:
        try:
            if container.locator('input[type="radio"], [role="radio"]').count() > 0:
                return 'radio'
            if container.locator('select').count() > 0:
                return 'select'
            if container.locator('[role="combobox"], [class*="select__"]').count() > 0:
                return 'combobox'
            if container.locator('input[type="file"]').count() > 0:
                return 'file'
            if container.locator('input[type="checkbox"], [role="checkbox"]').count() > 0:
                return 'checkbox'
        except Exception:
            pass

    if explicit == 'single_choice':
        return 'single_choice'

    return explicit or 'text'


def _find_input_locator(root: Any, q: Dict[str, Any], kind: str) -> Optional[Any]:
    text = q.get('text', '')
    clean = _clean_label(text)
    base = re.sub(r'\s*\([^)]*\)\s*$', '', clean).strip()

    # Scope within owning form if specified: prefer form_id over positional form_path
    scope = q.get('locator_scope') or {}
    form_id = q.get('form_id') or scope.get('form_id')
    form_path = q.get('form_path') or scope.get('form')
    ctrl_meta = q.get('control_metadata') or []
    candidates = list(q.get('locator_candidates') or [])

    if not form_id and ctrl_meta:
        for cm in ctrl_meta:
            d = cm.get('dom') or {}
            if d.get('form_id'):
                form_id = d['form_id']
                break
    if not form_path and ctrl_meta:
        for cm in ctrl_meta:
            d = cm.get('dom') or {}
            if d.get('form_path'):
                form_path = d['form_path']
                break

    scope_root = root
    if form_id:
        form_loc = root.locator(f"form#{form_id}, #{form_id}")
        form_cnt = form_loc.count()
        if form_cnt == 0:
            raise ValueError(f"Stale form scope '#{form_id}' not found in DOM")
        elif form_cnt > 1:
            raise ValueError(f"Ambiguous form scope '#{form_id}' matches {form_cnt} elements")
        scope_root = form_loc.first
    elif form_path:
        form_loc = root.locator(form_path)
        form_cnt = form_loc.count()
        if form_cnt == 0:
            raise ValueError(f"Stale form scope '{form_path}' not found in DOM")
        elif form_cnt > 1:
            raise ValueError(f"Ambiguous form scope '{form_path}' matches {form_cnt} forms")
        scope_root = form_loc.first

    cm = ctrl_meta[0] if ctrl_meta else None
    cm_dom = cm.get('dom') or {} if cm else {}
    captured_id = cm_dom.get('id') if cm else None
    captured_name = cm_dom.get('name') if cm else None
    captured_type = cm_dom.get('type') if cm else None
    captured_form_id = cm_dom.get('form_id') or form_id
    captured_form_path = cm_dom.get('form_path') or form_path
    has_metadata = bool(ctrl_meta)
    captured_had_form = bool(captured_form_id or captured_form_path)

    # If ctrl_meta is present, ID-less captured controls are unsupported
    if ctrl_meta and not captured_id:
        return ('skipped', f"Control '{text}' lacks captured DOM ID (ID-less captured controls unsupported); skipped")

    # Anonymous owning form is always unsupported before mutation
    if (form_path or captured_form_path) and not (form_id or captured_form_id):
        return ('skipped', f"Control '{text}' in anonymous form lacks stable owner ID; unsupported")

    if not captured_id and candidates:
        for c in candidates:
            if isinstance(c, dict) and c.get('by') == 'id' and c.get('value'):
                captured_id = c['value']
                break

    # If captured stable ID is available, enforce it strictly!
    if captured_id:
        id_loc = scope_root.locator(f'[id="{captured_id}"]')
        cnt = id_loc.count()
        if cnt == 0 and captured_form_id and scope_root != root:
            # Check if it's an external control associated via HTML5 form attribute
            ext_loc = root.locator(f'[id="{captured_id}"]')
            if ext_loc.count() == 1:
                id_loc = ext_loc
                cnt = 1
        if cnt == 0:
            raise ValueError(
                f"Stale control targeting: captured control '#{captured_id}' not found in scope for '{text}'; "
                f"refusing fallback to avoid mutating other controls"
            )
        elif cnt > 1:
            raise ValueError(f"Ambiguous control targeting: '#{captured_id}' matches {cnt} elements")

        target_el = id_loc.first
        ctrl_check = target_el.evaluate(r"""el => {
            const isNative = 'form' in el || ['input', 'select', 'textarea', 'button'].includes((el.tagName || '').toLowerCase());
            const form = isNative ? el.form : el.closest('form');
            return {
                tag: (el.tagName || '').toLowerCase(),
                type: (el.getAttribute('type') || '').toLowerCase(),
                name: el.getAttribute('name') || '',
                form_id: form ? (form.id || '') : '',
                has_form: Boolean(form)
            };
        }""")
        if captured_form_id:
            if not ctrl_check['has_form']:
                raise ValueError(
                    f"Control '#{captured_id}' form owner missing: expected '{captured_form_id}', but element has no owning form"
                )
            if ctrl_check['form_id'] != captured_form_id:
                raise ValueError(
                    f"Control '#{captured_id}' form owner mismatch: expected '{captured_form_id}', got '{ctrl_check['form_id']}'"
                )
        elif captured_form_path:
            if not ctrl_check['has_form']:
                raise ValueError(
                    f"Control '#{captured_id}' form owner missing: expected form '{captured_form_path}', but element has no owning form"
                )
        elif has_metadata and not captured_had_form:
            if ctrl_check['has_form']:
                raise ValueError(
                    f"Control '#{captured_id}' form owner mismatch: captured control had no owning form, "
                    f"but element acquired form '{ctrl_check['form_id'] or 'anonymous'}'"
                )
        elif ctrl_check['has_form'] and not ctrl_check['form_id']:
            return ('skipped', f"Control '{text}' in anonymous form lacks stable owner ID; unsupported")

        if captured_name:
            live_name = ctrl_check['name']
            if not live_name or live_name != captured_name:
                raise ValueError(
                    f"Control '#{captured_id}' name mismatch: expected '{captured_name}', got '{live_name}'"
                )

        return target_el

    has_targeting = bool(ctrl_meta or candidates or form_id or form_path)

    # 1. Scoped locator candidates if available
    if candidates:
        cand_loc = _find_candidate_locator(root, candidates, form_path=(f"#{form_id}" if form_id else form_path))
        if cand_loc is not None:
            ctrl_check = cand_loc.evaluate(r"""el => {
                const isNative = 'form' in el || ['input', 'select', 'textarea', 'button'].includes((el.tagName || '').toLowerCase());
                const form = isNative ? el.form : el.closest('form');
                return {
                    tag: (el.tagName || '').toLowerCase(),
                    type: (el.getAttribute('type') || '').toLowerCase(),
                    name: el.getAttribute('name') || '',
                    form_id: form ? (form.id || '') : '',
                    has_form: Boolean(form)
                };
            }""")
            if captured_form_id:
                if not ctrl_check['has_form']:
                    raise ValueError(
                        f"Candidate control form owner missing: expected '{captured_form_id}', but element has no owning form"
                    )
                if ctrl_check['form_id'] != captured_form_id:
                    raise ValueError(
                        f"Candidate control form owner mismatch: expected '{captured_form_id}', got '{ctrl_check['form_id']}'"
                    )
            elif captured_form_path:
                if not ctrl_check['has_form']:
                    raise ValueError(
                        f"Candidate control form owner missing: expected form '{captured_form_path}', but element has no owning form"
                    )
            elif has_metadata and not captured_had_form:
                if ctrl_check['has_form']:
                    raise ValueError(
                        f"Candidate control form owner mismatch: captured control had no owning form, "
                        f"but element acquired form '{ctrl_check['form_id'] or 'anonymous'}'"
                    )
            elif ctrl_check['has_form'] and not ctrl_check['form_id']:
                return ('skipped', f"Control '{text}' in anonymous form lacks stable owner ID; unsupported")

            if captured_name:
                live_name = ctrl_check['name']
                if not live_name or live_name != captured_name:
                    raise ValueError(
                        f"Candidate control name mismatch: expected '{captured_name}', got '{live_name}'"
                    )

            return cand_loc
        raise ValueError(
            f"Supplied locator targeting failed to match element for '{text}'; no heuristic fallback permitted"
        )

    if has_targeting:
        raise ValueError(
            f"Supplied locator targeting failed to match element for '{text}'; no heuristic fallback permitted"
        )

    # 2. Legacy plan without candidates: Match by label
    for lbl in (clean, base):
        if not lbl:
            continue
        try:
            loc = scope_root.get_by_label(lbl, exact=True)
            cnt = loc.count()
            if cnt == 1:
                return loc.first
            elif cnt > 1:
                raise ValueError(f"Ambiguous label '{lbl}' matches {cnt} elements")
        except Exception as e:
            if "Ambiguous label" in str(e):
                raise
            pass

    # 3. Match by placeholder
    for lbl in (clean, base):
        if not lbl:
            continue
        try:
            loc = scope_root.get_by_placeholder(lbl, exact=True)
            cnt = loc.count()
            if cnt == 1:
                return loc.first
            elif cnt > 1:
                raise ValueError(f"Ambiguous placeholder '{lbl}' matches {cnt} elements")
        except Exception as e:
            if "Ambiguous placeholder" in str(e):
                raise
            pass

    # 4. Match by exact ID or exact Name attribute slugs
    slugs = _slug_candidates(text, q.get('fact_key'))
    for slug in slugs:
        for selector in (
            f"#{slug}",
            f"[name='{slug}']",
        ):
            try:
                loc = scope_root.locator(selector)
                cnt = loc.count()
                if cnt == 1:
                    return loc.first
                elif cnt > 1:
                    raise ValueError(f"Ambiguous selector '{selector}' matches {cnt} elements")
            except Exception as e:
                if "Ambiguous selector" in str(e):
                    raise
                continue

    # 5. Container-scoped search (strictly inside question group container)
    container = _find_group_container(scope_root, text)
    if container:
        try:
            if kind == 'file':
                file_loc = container.locator("input[type='file']")
                cnt = file_loc.count()
                if cnt == 1:
                    return file_loc.first
                elif cnt > 1:
                    raise ValueError(f"Ambiguous file inputs in container for '{text}'")
            elif kind == 'select':
                sel_loc = container.locator("select")
                cnt = sel_loc.count()
                if cnt == 1:
                    return sel_loc.first
                elif cnt > 1:
                    raise ValueError(f"Ambiguous select inputs in container for '{text}'")
            elif kind == 'combobox':
                combo_loc = container.locator("[role='combobox'], .select__input")
                cnt = combo_loc.count()
                if cnt == 1:
                    return combo_loc.first
                elif cnt > 1:
                    raise ValueError(f"Ambiguous combobox inputs in container for '{text}'")
            input_loc = container.locator(
                "input:not([type='hidden']):not([type='radio']):not([type='checkbox']):not([type='file']), "
                "textarea, [contenteditable='true']"
            )
            cnt = input_loc.count()
            if cnt == 1:
                return input_loc.first
            elif cnt > 1:
                raise ValueError(f"Ambiguous inputs in container for '{text}'")
        except Exception as e:
            if "Ambiguous" in str(e):
                raise
            pass

    return None


def _is_prohibited_plan(q: Dict[str, Any], allow_review: bool = False) -> Optional[str]:
    """Check if question in plan involves credentials, legal consents, CAPTCHAs, or submit controls."""
    text = q.get('text', '')
    itype = str(q.get('input_type') or '').lower()
    fact_key = str(q.get('fact_key') or '').lower()

    if itype in ('password', 'submit', 'button', 'captcha'):
        return f"Prohibited input_type: '{itype}'"

    if re.search(r'\b(password|pin|ssn|social security)\b', text, re.I):
        return "Prohibited credentials field"

    if re.search(r'(captcha|recaptcha|hcaptcha|turnstile|bot check)', text, re.I):
        return "Prohibited CAPTCHA challenge"

    # Legal agreements (arbitration, privacy policy, terms) require explicit user-review
    # Note: --allow-review only permits proposal statuses, never blanket legal approval.
    # Keep agreements skipped independent flag in generic filler.
    is_legal = (
        fact_key == 'arbitration'
        or re.search(r'arbitrat|class[- ]action waiver|jury trial waiver|release of claims', text, re.I)
        or re.search(r'privacy\s+policy|terms\s+(of|and)|acknowledge and agree|consent', text, re.I)
    )
    if is_legal:
        return "Legal agreement or privacy policy requires explicit user review; skipped"

    return None


def _validate_dom_control(target: Any, q: Dict[str, Any], expected_kind: str, allow_review: bool = False) -> Optional[str]:
    """Validate actual live DOM element before mutation; generic filler is application-data-only."""
    try:
        info = target.evaluate(r"""el => {
            const tag = el.tagName.toLowerCase();
            const type = (el.getAttribute('type') || '').toLowerCase();
            const role = (el.getAttribute('role') || '').toLowerCase();
            const autocomplete = (el.getAttribute('autocomplete') || '').toLowerCase();
            const name = (el.getAttribute('name') || '').toLowerCase();
            const isPassword = type === 'password' || autocomplete.includes('password') || name.includes('password');
            const isSubmit = (tag === 'input' && (type === 'submit' || type === 'image')) ||
                             (tag === 'button' && (type === 'submit' || type === '')) ||
                             role === 'button';
            const isCheckbox = type === 'checkbox' || role === 'checkbox';
            const isRadio = type === 'radio' || role === 'radio';
            const isSelect = tag === 'select';
            const isFile = type === 'file';
            const isTextLike = ['text', 'email', 'tel', 'url', 'number', 'date', ''].includes(type) ||
                               tag === 'textarea' || Boolean(el.isContentEditable);

            const root = (el.getRootNode && el.getRootNode()) || el.ownerDocument;
            let missingReferences = false;
            const missingRefIds = [];

            function resolveRefIds(idStr, requireExists = false) {
                if (!idStr) return '';
                const ids = idStr.trim().split(/\s+/).filter(Boolean);
                const parts = [];
                for (const refId of ids) {
                    let refEl = null;
                    if (root && root.getElementById) {
                        refEl = root.getElementById(refId);
                    }
                    if (!refEl && el.ownerDocument && el.ownerDocument.getElementById) {
                        refEl = el.ownerDocument.getElementById(refId);
                    }
                    if (!refEl) {
                        if (requireExists) {
                            missingReferences = true;
                            missingRefIds.push(refId);
                        }
                    } else {
                        parts.push((refEl.innerText || refEl.textContent || '').trim());
                    }
                }
                return parts.join(' ');
            }

            let domText = (el.getAttribute('aria-label') || '') + ' ' + (el.innerText || el.textContent || '');
            domText += ' ' + resolveRefIds(el.getAttribute('aria-labelledby'), true);
            domText += ' ' + resolveRefIds(el.getAttribute('aria-describedby'), false);

            // Inspect EVERY associated label via [for=id]
            if (el.id) {
                const docRoot = (root.querySelectorAll ? root : el.ownerDocument);
                try {
                    const associatedLabels = docRoot.querySelectorAll(`label[for="${CSS.escape(el.id)}"]`);
                    for (const l of associatedLabels) {
                        domText += ' ' + (l.innerText || l.textContent || '');
                    }
                } catch (_) {}
            }

            // Inspect all ancestor labels up the DOM tree
            let pLabel = el.parentElement;
            while (pLabel) {
                if (pLabel.tagName && pLabel.tagName.toLowerCase() === 'label') {
                    domText += ' ' + (pLabel.innerText || pLabel.textContent || '');
                }
                pLabel = pLabel.parentElement;
            }

            // Inspect ALL ancestor fieldsets and role=group/radiogroup contexts up the DOM tree (not just closest)
            let ancestor = el.parentElement;
            while (ancestor) {
                const aTag = (ancestor.tagName || '').toLowerCase();
                const aRole = (ancestor.getAttribute('role') || '').toLowerCase();
                if (aTag === 'fieldset' || aRole === 'group' || aRole === 'radiogroup') {
                    domText += ' ' + (ancestor.getAttribute('aria-label') || '');
                    domText += ' ' + resolveRefIds(ancestor.getAttribute('aria-labelledby'), true);
                    domText += ' ' + resolveRefIds(ancestor.getAttribute('aria-describedby'), false);
                    const legends = ancestor.querySelectorAll('legend');
                    for (const leg of legends) {
                        domText += ' ' + (leg.innerText || leg.textContent || '');
                    }
                }
                ancestor = ancestor.parentElement;
            }

            return {
                tag, type, role, isPassword, isSubmit, isCheckbox, isRadio, isSelect, isFile, isTextLike,
                domText, missingReferences, missingRefIds
            };
        }""")
    except Exception as exc:
        return f"DOM element inspection failed: {exc}"

    if info.get('missingReferences'):
        return f"Missing ARIA label/description reference in DOM ({', '.join(info['missingRefIds'])}) required to establish semantics; skipped unchanged"

    if info['isPassword']:
        return "Unexpected password control in DOM; skipped unchanged"

    dom_text = info.get('domText', '')
    if re.search(r'\b(password|pin|ssn|social security)\b', dom_text, re.I):
        return "Unexpected password control in DOM; skipped unchanged"

    if info['isSubmit']:
        return "Submit control in DOM; skipped unchanged"

    # Live DOM legal agreement check: actual DOM labels/context rerendered benign -> arbitration must skip unchanged
    # No generic allow_review consent override!
    if re.search(r'arbitrat|class[- ]action waiver|jury trial waiver|release of claims', dom_text, re.I) or \
       re.search(r'privacy\s+policy|terms\s+(of|and)|acknowledge and agree|consent', dom_text, re.I):
        return "Legal agreement or privacy policy detected in live DOM; skipped unchanged"

    if re.search(r'(captcha|recaptcha|hcaptcha|turnstile|bot check)', dom_text, re.I):
        return "Prohibited CAPTCHA challenge in live DOM; skipped unchanged"

    # Type mismatch validation against actual DOM control
    if expected_kind in ('text', 'email', 'tel', 'url', 'number', 'date', 'textarea'):
        if not info['isTextLike']:
            return f"Type mismatch: expected text-like control, got <{info['tag']} type={info['type']}>; skipped unchanged"
    elif expected_kind == 'select':
        if not info['isSelect']:
            return f"Type mismatch: expected select, got <{info['tag']}>; skipped unchanged"
    elif expected_kind == 'checkbox':
        if not info['isCheckbox']:
            return f"Type mismatch: expected checkbox, got <{info['tag']} type={info['type']}>; skipped unchanged"
    elif expected_kind == 'radio':
        if not info['isRadio']:
            return f"Type mismatch: expected radio, got <{info['tag']} type={info['type']}>; skipped unchanged"
    elif expected_kind == 'file':
        if not info['isFile']:
            return f"Type mismatch: expected file input, got <{info['tag']} type={info['type']}>; skipped unchanged"

    return None


def _verify_semantic_identity(target: Any, q: Dict[str, Any], text: str) -> None:
    ctrl_meta = q.get('control_metadata') or []
    cm = ctrl_meta[0] if ctrl_meta else None
    cm_dom = (cm.get('dom') or {}) if cm else {}
    captured_meaning = (cm.get('label') or cm_dom.get('label')) if cm else None

    if captured_meaning:
        live_dom = target.evaluate(DOM_SCRIPT)
        live_label = live_dom.get('label') or ''
        live_group_label = (live_dom.get('group') or {}).get('label') or ''
        norm_captured = _normalize_semantic_label(captured_meaning)
        norm_live = _normalize_semantic_label(live_label)
        norm_live_group = _normalize_semantic_label(live_group_label)
        if norm_live != norm_captured and norm_live_group != norm_captured:
            raise ValueError(
                f"Control semantic label mismatch: expected '{captured_meaning}', got '{live_label or live_group_label}'; refusing mutation"
            )


def _fill_text_like(target: Any, value: Any) -> Any:
    target.scroll_into_view_if_needed(timeout=5000)
    target.focus(timeout=5000)
    val_str = str(value)

    tag = target.evaluate("el => el.tagName.toLowerCase()")
    is_ce = target.evaluate(
        "el => Boolean(el.isContentEditable || el.getAttribute('contenteditable') === 'true')"
    )

    if is_ce:
        target.fill(val_str, timeout=5000)
        target.dispatch_event('input')
        target.dispatch_event('change')
        readback = target.inner_text(timeout=5000).strip()
        if readback != val_str.strip():
            raise RuntimeError(
                f"Contenteditable readback mismatch: expected {val_str.strip()!r}, got {readback!r}"
            )
        return readback

    if tag not in ('input', 'textarea'):
        raise ValueError(
            f"Target <{tag}> is neither an input, textarea, nor contenteditable; refusing mutation"
        )

    target.fill(val_str, timeout=5000)
    target.dispatch_event('input')
    target.dispatch_event('change')
    readback = target.input_value(timeout=5000)
    if readback != val_str:
        raise RuntimeError(
            f"Input readback mismatch (rejected/reverted write): expected {val_str!r}, got {readback!r}"
        )
    return readback


def _fill_radio(root: Any, q: Dict[str, Any], allow_review: bool = False) -> Any:
    text = q.get('text', '')
    scope = q.get('locator_scope') or {}
    form_path = q.get('form_path') or scope.get('form')
    form_id = q.get('form_id') or scope.get('form_id')
    ctrl_meta = q.get('control_metadata') or []
    group_path = scope.get('group', {}).get('path') if isinstance(scope.get('group'), dict) else None

    if not form_id and ctrl_meta:
        for cm in ctrl_meta:
            d = cm.get('dom') or {}
            if d.get('form_id'):
                form_id = d['form_id']
                break
    if not form_path and ctrl_meta:
        for cm in ctrl_meta:
            d = cm.get('dom') or {}
            if d.get('form_path'):
                form_path = d['form_path']
                break
    if not group_path and ctrl_meta:
        for cm in ctrl_meta:
            grp = (cm.get('dom') or {}).get('group') or {}
            if grp.get('path'):
                group_path = grp['path']
                break

    has_targeting = bool(ctrl_meta or group_path or form_id or form_path or q.get('locator_candidates'))

    scope_root = root
    if form_id:
        form_loc = root.locator(f"form#{form_id}, #{form_id}")
        form_cnt = form_loc.count()
        if form_cnt == 0:
            raise ValueError(f"Stale form scope '#{form_id}' not found in DOM")
        elif form_cnt > 1:
            raise ValueError(f"Ambiguous form scope '#{form_id}' matches {form_cnt} elements")
        scope_root = form_loc.first
    elif form_path:
        form_loc = root.locator(form_path)
        form_cnt = form_loc.count()
        if form_cnt == 0:
            raise ValueError(f"Stale form scope '{form_path}' not found in DOM")
        elif form_cnt > 1:
            raise ValueError(f"Ambiguous form scope '{form_path}' matches {form_cnt} forms")
        scope_root = form_loc.first

    selected_opt = q.get('selected_option') or {}
    has_opt_label = 'label' in selected_opt and selected_opt['label'] is not None
    has_opt_val = 'value' in selected_opt and selected_opt['value'] is not None

    opt_label = selected_opt.get('label')
    opt_value = selected_opt.get('value')
    answer = q.get('answer')

    if not has_opt_label and not has_opt_val:
        if isinstance(answer, bool):
            opt_label = 'Yes' if answer else 'No'
            opt_value = 'true' if answer else 'false'
            has_opt_label = True
            has_opt_val = True
        elif answer is not None:
            opt_label = str(answer)
            has_opt_label = True

    lbl_norm = str(opt_label).strip().lower() if has_opt_label else None
    val_norm = str(opt_value).strip().lower() if has_opt_val else None

    # Determine acceptable values
    if val_norm in ('true', '1', 'yes'):
        acceptable_vals = {'true', '1', 'yes'}
    elif val_norm in ('false', '0', 'no'):
        acceptable_vals = {'false', '0', 'no'}
    elif val_norm is not None:
        acceptable_vals = {val_norm}
    else:
        acceptable_vals = set()

    radio_input = None
    target_container = None

    if ctrl_meta:
        # Require captured actual DOM ID unique plus captured stable owner ID when owner exists.
        # If only name/path anonymous ambiguous identity, SKIP unsupported BEFORE mutation.
        target_cm = None
        if selected_opt.get('id'):
            target_cm = next((cm for cm in ctrl_meta if cm.get('id') == selected_opt['id']), None)
        if not target_cm and opt_value is not None:
            target_cm = next(
                (cm for cm in ctrl_meta
                 if str((cm.get('dom') or {}).get('option_value') or (cm.get('dom') or {}).get('value') or '').strip().lower() == val_norm),
                None,
            )
        if not target_cm and opt_label is not None:
            target_cm = next(
                (cm for cm in ctrl_meta
                 if str(cm.get('label') or (cm.get('dom') or {}).get('label') or '').strip().lower() == lbl_norm),
                None,
            )

        if not target_cm:
            opts_items = (q.get('options') or {}).get('items') or []
            if opts_items and selected_opt.get('id'):
                idx = next((i for i, o in enumerate(opts_items) if o.get('id') == selected_opt['id']), None)
                if idx is not None and idx < len(ctrl_meta):
                    target_cm = ctrl_meta[idx]

        if not target_cm:
            raise ValueError(f"Could not resolve target option in captured control metadata for radio '{text}'")

        cm_dom = target_cm.get('dom') or {}
        captured_id = cm_dom.get('id')
        grp_info = cm_dom.get('group') or {}
        cm_grp_path = grp_info.get('path') or group_path
        cm_form_id = cm_dom.get('form_id') or form_id
        cm_form_path = cm_dom.get('form_path') or form_path
        cm_had_form = bool(cm_form_id or cm_form_path)

        # 1. Require captured actual DOM ID unique
        if not captured_id:
            return ('skipped', 'Radio control has only name/path anonymous ambiguous identity without captured DOM ID; unsupported')

        # 2. When owner (form) exists, require captured stable owner ID.
        # Anonymous form with only positional path is NOT stable -> skip unsupported before mutation
        if cm_form_path and not cm_form_id:
            return ('skipped', 'Radio control belongs to anonymous form without stable owner ID; unsupported')

        if cm_grp_path:
            if cm_grp_path.startswith(('html', 'body', '/')):
                grp_loc = root.locator(cm_grp_path)
            else:
                grp_loc = scope_root.locator(cm_grp_path)
            if grp_loc.count() == 0:
                raise ValueError(f"Stale radio group path '{cm_grp_path}' not found in scope for '{text}'")
            elif grp_loc.count() > 1:
                raise ValueError(f"Ambiguous radio group path '{cm_grp_path}' matches {grp_loc.count()} elements")
            if form_path or form_id:
                exp_f = f"#{form_id}" if form_id else form_path
                if not _matches_form(grp_loc.first, exp_f):
                    raise ValueError(f"Radio group '{cm_grp_path}' does not belong to expected form '{exp_f}'")
            target_container = grp_loc.first
        else:
            target_container = scope_root

        input_loc = target_container.locator(f'[id="{captured_id}"]')
        if input_loc.count() == 0:
            raise ValueError(f"Stale radio control '#{captured_id}' not found in intended owner for '{text}'")
        elif input_loc.count() > 1:
            raise ValueError(f"Ambiguous radio control '#{captured_id}' matches {input_loc.count()} elements")
        radio_input = input_loc.first

        # Verify owner identity in live DOM: if inside a form, form must have stable ID matching expected
        owner_info = radio_input.evaluate("""el => {
            const isNative = 'form' in el || ['input', 'select', 'textarea', 'button'].includes((el.tagName || '').toLowerCase());
            const f = isNative ? el.form : el.closest('form');
            return f ? { has_form: true, form_id: f.id || '', name: el.getAttribute('name') || '' } : { has_form: false, form_id: '', name: el.getAttribute('name') || '' };
        }""")
        if cm_form_id:
            if not owner_info['has_form']:
                raise ValueError(f"Radio '#{captured_id}' form owner missing: expected '{cm_form_id}', but element has no owning form")
            if owner_info['form_id'] != cm_form_id:
                raise ValueError(f"Radio '#{captured_id}' form owner mismatch: expected '{cm_form_id}', got '{owner_info['form_id']}'")
        elif cm_form_path:
            if not owner_info['has_form']:
                raise ValueError(f"Radio '#{captured_id}' form owner missing: expected form '{cm_form_path}', but element has no owning form")
        elif not cm_had_form and owner_info['has_form']:
            raise ValueError(
                f"Radio '#{captured_id}' form owner mismatch: captured radio had no owning form, "
                f"but element acquired form '{owner_info['form_id'] or 'anonymous'}'"
            )
        elif owner_info['has_form'] and not owner_info['form_id']:
            return ('skipped', 'Radio control in anonymous form without stable owner ID; unsupported')

        if cm_dom.get('name'):
            captured_name = cm_dom['name']
            live_name = owner_info.get('name', '')
            if not live_name or live_name != captured_name:
                raise ValueError(f"Radio '#{captured_id}' name mismatch: expected '{captured_name}', got '{live_name}'")

        live_dom = radio_input.evaluate(DOM_SCRIPT)
        live_opt_lbl = live_dom.get('label') or ''
        live_grp_lbl = (live_dom.get('group') or {}).get('label') or ''
        exp_grp_lbl = text or (cm_dom.get('group') or {}).get('label')
        if exp_grp_lbl and exp_grp_lbl != '(Unlabeled choice group)':
            norm_exp_grp = _normalize_semantic_label(exp_grp_lbl)
            norm_live_grp = _normalize_semantic_label(live_grp_lbl)
            if norm_live_grp and norm_live_grp != norm_exp_grp:
                raise ValueError(
                    f"Radio '#{captured_id}' group question mismatch: expected '{exp_grp_lbl}', got '{live_grp_lbl}'; refusing mutation"
                )

        # For captured-ID branch: validate actual current option label AND value vs all supplied selected_option identifiers BEFORE click
        dom_opt_info = radio_input.evaluate("""el => {
            let lbl = '';
            const root = (el.getRootNode && el.getRootNode()) || el.ownerDocument;
            if (el.id) {
                const l = root.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                if (l) lbl = (l.innerText || l.textContent || '').trim();
            }
            if (!lbl) {
                const pl = el.closest('label');
                if (pl) lbl = (pl.innerText || pl.textContent || '').trim();
            }
            return {
                value: (el.getAttribute('value') || el.value || '').trim(),
                label: lbl,
                checked: Boolean(el.checked || el.getAttribute('aria-checked') === 'true')
            };
        }""")
        dom_val = dom_opt_info['value'].strip()
        dom_lbl = dom_opt_info['label'].strip()

        if has_opt_val:
            if not dom_val or dom_val.lower() not in acceptable_vals:
                raise ValueError(
                    f"Radio option value mismatch before click: DOM '#{captured_id}' has value {dom_val!r}, "
                    f"expected value {opt_value!r}; rejecting with zero mutation"
                )
        if has_opt_label:
            lbl_matches = False
            if dom_lbl.lower() == lbl_norm:
                lbl_matches = True
            elif lbl_norm in ('yes', 'true', '1') and dom_lbl.lower() in ('yes', 'true', '1'):
                lbl_matches = True
            elif lbl_norm in ('no', 'false', '0') and dom_lbl.lower() in ('no', 'false', '0'):
                lbl_matches = True
            if not lbl_matches:
                raise ValueError(
                    f"Radio option label mismatch before click: DOM '#{captured_id}' has label {dom_lbl!r}, "
                    f"expected label {opt_label!r}; rejecting with zero mutation"
                )

    else:
        # Legacy plan without control_metadata
        if group_path:
            if group_path.startswith(('html', 'body', '/')):
                grp_loc = root.locator(group_path)
            else:
                grp_loc = scope_root.locator(group_path)
            if grp_loc.count() == 0:
                raise ValueError(f"Stale radio group path '{group_path}' in scope")
            elif grp_loc.count() > 1:
                raise ValueError(f"Ambiguous radio group path '{group_path}' matches {grp_loc.count()} elements")
            if form_path or form_id:
                exp_f = f"#{form_id}" if form_id else form_path
                if not _matches_form(grp_loc.first, exp_f):
                    raise ValueError(f"Radio group '{group_path}' does not belong to expected form '{exp_f}'")
            target_container = grp_loc.first
        else:
            target_container = _find_group_container(scope_root, text)

        if target_container is None:
            raise ValueError(f"Could not uniquely resolve group container for radio question '{text}' in scope")

        # Inspect all live radios in container
        radios_info = target_container.evaluate("""c => {
            const inputs = Array.from(c.querySelectorAll('input[type="radio"], [role="radio"]'));
            return inputs.map((el, idx) => {
                const val = el.getAttribute('value') || el.value || '';
                let lbl = '';
                if (el.id) {
                    const doc = c.ownerDocument;
                    const l = doc.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                    if (l) lbl = l.innerText || '';
                }
                if (!lbl) {
                    const pl = el.closest('label');
                    if (pl) lbl = pl.innerText || '';
                }
                const disabled = Boolean(el.disabled || (el.closest('fieldset') && el.closest('fieldset').disabled));
                return {
                    index: idx,
                    id: el.id || '',
                    name: el.getAttribute('name') || '',
                    value: val.trim(),
                    label: lbl.trim(),
                    disabled: disabled
                };
            });
        }""")

        if not radios_info:
            raise ValueError(f"No radio controls found in group container for '{text}'")

        enabled_radios = [r for r in radios_info if not r['disabled']]
        if not enabled_radios:
            raise ValueError(f"All radio controls disabled in group container for '{text}'")

        matching_by_label = []
        if lbl_norm:
            for r in enabled_radios:
                r_lbl = r['label'].strip().lower()
                if r_lbl == lbl_norm:
                    matching_by_label.append(r)

        matching_by_val = []
        if val_norm:
            for r in enabled_radios:
                r_val = r['value'].strip().lower()
                if r_val in acceptable_vals:
                    matching_by_val.append(r)

        # Reject contradictory label and value before mutation
        if has_opt_label and has_opt_val:
            if not matching_by_label:
                raise ValueError(f"Radio option label '{opt_label}' not found in group for '{text}'")
            if not matching_by_val:
                raise ValueError(f"Radio option value '{opt_value}' not found in group for '{text}'")
            if len(matching_by_label) > 1:
                raise ValueError(f"Duplicate radio option label '{opt_label}' in group for '{text}'")
            if len(matching_by_val) > 1:
                raise ValueError(f"Duplicate radio option value '{opt_value}' in group for '{text}'")
            if matching_by_label[0]['index'] != matching_by_val[0]['index']:
                raise ValueError(
                    f"Conflicting radio label '{opt_label}' (option index {matching_by_label[0]['index']}) "
                    f"and value '{opt_value}' (option index {matching_by_val[0]['index']}) in group for '{text}'; rejecting before mutation"
                )
            target_info = matching_by_label[0]
        elif has_opt_label:
            if not matching_by_label:
                raise ValueError(f"Radio option label '{opt_label}' not found in group for '{text}'")
            if len(matching_by_label) > 1:
                raise ValueError(f"Duplicate radio option label '{opt_label}' in group for '{text}'")
            target_info = matching_by_label[0]
        elif has_opt_val:
            if not matching_by_val:
                raise ValueError(f"Radio option value '{opt_value}' not found in group for '{text}'")
            if len(matching_by_val) > 1:
                raise ValueError(f"Duplicate radio option value '{opt_value}' in group for '{text}'")
            target_info = matching_by_val[0]
        else:
            raise ValueError(f"No option label or value specified for radio '{text}'")

        radio_input = target_container.locator('input[type="radio"], [role="radio"]').nth(target_info['index'])

    # Live semantics inspection before action
    dom_prohibited = _validate_dom_control(radio_input, q, 'radio', allow_review=allow_review)
    if dom_prohibited:
        return ('skipped', dom_prohibited)

    exp_f = f"#{form_id}" if form_id else form_path
    if exp_f and not _matches_form(radio_input, exp_f):
        raise RuntimeError(f"Radio option '{opt_label or opt_value}' does not belong to expected form '{exp_f}'")

    radio_input.scroll_into_view_if_needed(timeout=5000)
    radio_input.click(timeout=5000)

    # Verify real checked state
    is_checked = False
    try:
        is_checked = radio_input.is_checked(timeout=5000)
    except Exception:
        try:
            is_checked = (radio_input.get_attribute('aria-checked') == 'true')
        except Exception:
            pass

    if not is_checked:
        raise RuntimeError(f"Radio option '{opt_label or opt_value}' failed to check in live DOM")

    # Strict DOM readback: verify the checked radio inside search scope
    search_scope = target_container or scope_root
    checked_loc = search_scope.locator('input[type="radio"]:checked, [role="radio"][aria-checked="true"]')
    if checked_loc.count() != 1:
        raise RuntimeError(
            f"Expected exactly 1 checked radio in group for '{text}', found {checked_loc.count()}"
        )

    checked_el = checked_loc.first
    checked_id = checked_el.get_attribute('id')
    checked_val = (checked_el.get_attribute('value') or '').strip()
    observed_label = None

    if checked_id:
        lbl = root.locator(f'label[for="{checked_id}"]')
        if lbl.count() == 1:
            observed_label = lbl.first.inner_text(timeout=5000).strip()
    if not observed_label:
        parent_lbl = checked_el.locator('xpath=ancestor::label[1]')
        if parent_lbl.count() == 1:
            observed_label = parent_lbl.first.inner_text(timeout=5000).strip()

    # Point 5: Explicitly compare EVERY supplied normalized expected label to observed
    if has_opt_label:
        if not observed_label or observed_label.strip().lower() != lbl_norm:
            is_valid_bool = (
                lbl_norm in ('yes', 'no', 'true', 'false')
                and observed_label
                and observed_label.strip().lower() in acceptable_vals
            )
            if not is_valid_bool:
                raise RuntimeError(
                    f"DOM readback label mismatch for radio: observed label={observed_label!r}, expected={opt_label!r}"
                )
    if has_opt_val:
        if not checked_val or checked_val.strip().lower() not in acceptable_vals:
            raise RuntimeError(
                f"DOM readback value mismatch for radio: observed value={checked_val!r}, expected={opt_value!r}"
            )

    return observed_label or checked_val


def _fill_checkbox(target: Any, value: Any) -> bool:
    target.scroll_into_view_if_needed(timeout=5000)
    should_check = bool(value and str(value).lower() not in {'false', '0', 'no'})
    if should_check:
        target.check(timeout=5000)
    else:
        target.uncheck(timeout=5000)
    target.dispatch_event('change')
    actual = target.is_checked(timeout=5000)
    if actual != should_check:
        raise RuntimeError(
            f"Checkbox readback mismatch: expected {should_check!r}, got {actual!r}"
        )
    return actual


def _fill_select(target: Any, q: Dict[str, Any]) -> Any:
    answer = q.get('answer')
    selected_opt = q.get('selected_option') or {}
    has_opt_label = 'label' in selected_opt and selected_opt['label'] is not None
    has_opt_val = 'value' in selected_opt and selected_opt['value'] is not None

    opt_label = selected_opt.get('label')
    opt_val = selected_opt.get('value')

    if not has_opt_label and not has_opt_val:
        if isinstance(answer, bool):
            opt_label = 'Yes' if answer else 'No'
            opt_val = 'true' if answer else 'false'
            has_opt_label = True
            has_opt_val = True
        else:
            opt_label = str(answer)
            has_opt_label = True

    # Focus target before inspecting options to trigger any focus-based reordering handlers
    target.scroll_into_view_if_needed(timeout=5000)
    target.focus(timeout=5000)

    # Inspect options in live DOM immediately after focus and before selection
    options_info = target.evaluate("""el => Array.from(el.options).map((o, idx) => ({
        index: idx,
        label: (o.text || '').trim(),
        value: o.value,
        disabled: Boolean(o.disabled || (o.parentElement && o.parentElement.disabled))
    }))""")

    enabled = [o for o in options_info if not o['disabled']]
    if not enabled:
        raise ValueError("Select element has no enabled options")

    # Check matching enabled options for label
    label_matches = []
    if has_opt_label:
        lbl_norm = str(opt_label).strip().lower()
        label_matches = [o for o in enabled if o['label'].strip().lower() == lbl_norm]
        if len(label_matches) > 1:
            raise ValueError(
                f"Duplicate enabled option label '{opt_label}' in select (found {len(label_matches)}); rejecting before mutation"
            )

    # Check matching enabled options for value
    val_matches = []
    if has_opt_val:
        val_norm = str(opt_val).strip().lower()
        val_matches = [o for o in enabled if str(o['value']).strip().lower() == val_norm]
        if len(val_matches) > 1:
            raise ValueError(
                f"Duplicate enabled option value '{opt_val}' in select (found {len(val_matches)}); rejecting before mutation"
            )

    target_option = None
    if has_opt_label and has_opt_val:
        if len(label_matches) == 0:
            raise ValueError(f"Option label '{opt_label}' not found in select")
        if len(val_matches) == 0:
            raise ValueError(f"Option value '{opt_val}' not found in select")
        if label_matches[0]['index'] != val_matches[0]['index']:
            raise ValueError(
                f"Conflicting label '{opt_label}' (option index {label_matches[0]['index']}) "
                f"and value '{opt_val}' (option index {val_matches[0]['index']}) in select; rejecting before mutation"
            )
        target_option = label_matches[0]
    elif has_opt_label:
        if len(label_matches) == 0:
            raise ValueError(f"Option label '{opt_label}' not found in select")
        target_option = label_matches[0]
    elif has_opt_val:
        if len(val_matches) == 0:
            raise ValueError(f"Option value '{opt_val}' not found in select")
        target_option = val_matches[0]

    # Verify intended enabled live before action
    if target_option['disabled']:
        raise ValueError(f"Option '{target_option['label']}' is disabled in live select")

    # Choose by unique value rather than stale index if unique, else index
    val_str = str(target_option['value'])
    matching_val_count = sum(1 for o in options_info if str(o['value']) == val_str)
    if matching_val_count == 1:
        target.select_option(value=val_str, timeout=5000)
    else:
        target.select_option(index=target_option['index'], timeout=5000)

    target.dispatch_event('input')
    target.dispatch_event('change')

    readback_script = """el => {
        const idx = el.selectedIndex;
        if (idx < 0 || idx >= el.options.length) return null;
        const opt = el.options[idx];
        return {
            index: idx,
            label: (opt.text || '').trim(),
            value: opt.value,
            disabled: Boolean(opt.disabled || el.disabled)
        };
    }"""

    actual = target.evaluate(readback_script)
    if not actual:
        raise RuntimeError("Select readback failed: no option currently selected in live DOM")

    if actual['index'] != target_option['index']:
        raise RuntimeError(
            f"Select readback index mismatch: expected {target_option['index']}, got {actual['index']}"
        )

    if actual['disabled']:
        raise RuntimeError(
            f"Select readback failed: option index {actual['index']} is disabled in live DOM"
        )

    if actual['label'].strip().lower() != target_option['label'].strip().lower():
        raise RuntimeError(
            f"Select readback label mismatch: expected {target_option['label']!r}, got {actual['label']!r}"
        )

    if actual['value'].strip().lower() != str(target_option['value']).strip().lower():
        raise RuntimeError(
            f"Select readback value mismatch: expected {target_option['value']!r}, got {actual['value']!r}"
        )

    # Delayed reverts bounded check: verify selection stability after change events (bounded timing limit: 150ms)
    try:
        p = getattr(target, 'page', None)
        if p:
            p.wait_for_timeout(150)
    except Exception:
        pass

    post_check = target.evaluate(readback_script)
    if not post_check or post_check['index'] != target_option['index'] or \
       post_check['label'].strip().lower() != target_option['label'].strip().lower() or \
       post_check['value'].strip().lower() != str(target_option['value']).strip().lower() or \
       post_check['disabled']:
        raise RuntimeError(
            f"Select selection reverted or mutated within 150ms bounded stability check: observed {post_check!r}"
        )

    return actual['label'] or actual['value']


def _fill_combobox(root: Any, target: Any, q: Dict[str, Any]) -> Any:
    selected_opt = q.get('selected_option') or {}
    has_opt_label = 'label' in selected_opt and selected_opt['label'] is not None
    has_opt_val = 'value' in selected_opt and selected_opt['value'] is not None

    opt_label = selected_opt.get('label') or (str(q.get('answer', '')) if not has_opt_val else None)
    opt_val = selected_opt.get('value')
    if not opt_label and not opt_val:
        raise ValueError("Combobox answer or option label/value must be non-empty")

    search_text = str(opt_label or opt_val)

    # Scoped associated menu: strictly target-specific unambiguous ownership
    menu = None
    controls_id = None
    try:
        controls_id = target.get_attribute('aria-controls') or target.get_attribute('aria-owns')
        if not controls_id:
            child_input = target.locator('input')
            if child_input.count() > 0:
                controls_id = child_input.first.get_attribute('aria-controls') or child_input.first.get_attribute('aria-owns')
    except Exception:
        pass

    if controls_id:
        m = root.locator(f"#{controls_id}")
        if m.count() == 1:
            menu = m.first
        elif m.count() > 1:
            raise ValueError(f"Ambiguous menu '#{controls_id}' for combobox matches {m.count()} elements")

    if menu is None:
        child_menu = target.locator('> [role="listbox"], > .select__menu, > [class*="-menu"]')
        if child_menu.count() == 1:
            menu = child_menu.first

    target_id = target.get_attribute('id') or ''
    child_input = target.locator('input')
    input_id = target_id or (child_input.first.get_attribute('id') if child_input.count() > 0 else '')

    if menu is None:
        try:
            if input_id and '-input' in input_id:
                listbox_id = input_id.replace('-input', '-listbox')
                m = root.locator(f"#{listbox_id}")
                if m.count() == 1:
                    menu = m.first
        except Exception:
            pass

    opened_for_menu = False
    if menu is None:
        try:
            target.scroll_into_view_if_needed(timeout=5000)
            target.click(timeout=5000)
            opened_for_menu = True
            controls_id = target.get_attribute('aria-controls') or target.get_attribute('aria-owns')
            if not controls_id:
                if child_input.count() > 0:
                    controls_id = child_input.first.get_attribute('aria-controls') or child_input.first.get_attribute('aria-owns')
            if controls_id:
                m = root.locator(f"#{controls_id}")
                if m.count() == 1:
                    menu = m.first
            if menu is None and input_id:
                cand_id = f"react-select-{input_id}-listbox"
                m = root.locator(f"#{cand_id}")
                if m.count() == 1:
                    menu = m.first
            if menu is None:
                parent_menu = target.locator('xpath=ancestor::*[contains(@class, "select__container") or contains(@class, "select-shell")][1]').locator('.select__menu, [role="listbox"]')
                if parent_menu.count() == 1:
                    menu = parent_menu.first
        except Exception:
            pass

    if menu is None:
        raise ValueError(
            f"Unsupported combobox widget association for '{search_text}'; "
            f"refusing unsafe option mutation without unambiguous aria-controls/owns or direct ownership"
        )

    # Establish uniquely target-owned control wrapper
    ctrl_wrapper = None
    for selector in (
        'xpath=ancestor::*[contains(@class, "select__container")][1]',
        'xpath=ancestor::*[contains(@class, "select__control")][1]',
        'xpath=ancestor::*[contains(@class, "select__value-container")][1]',
    ):
        cand = target.locator(selector)
        if cand.count() > 0:
            ctrl_wrapper = cand.first
            break

    if ctrl_wrapper is None:
        parent_loc = target.locator('xpath=..')
        search_scope = parent_loc.first if parent_loc.count() > 0 else target
    else:
        search_scope = ctrl_wrapper

    # 1. Determine whether target has known uniquely owned committed submitted value BEFORE ANY interaction
    hidden_inputs = search_scope.locator('input[type="hidden"]')
    h_count = hidden_inputs.count()
    if h_count > 1:
        # Multiple hidden submitted inputs ambiguous => skip BEFORE ANY interaction, do not .first
        return ('skipped', f'Combobox has {h_count} ambiguous hidden submitted inputs; unsupported')

    has_named_hidden = False
    hidden_input = None
    if h_count == 1:
        h_el = hidden_inputs.first
        h_name = h_el.get_attribute('name')
        if h_name:
            has_named_hidden = True
            hidden_input = h_el

    is_native_input = target.evaluate("el => el.tagName.toLowerCase() === 'input'")

    initial_display = None
    sv_init = search_scope.locator('.select__single-value, [class*="single-value"]')
    if sv_init.count() > 0:
        for idx in range(sv_init.count()):
            candidate_sv = sv_init.nth(idx)
            if candidate_sv.is_visible():
                text_read = candidate_sv.inner_text(timeout=1000).strip()
                if text_read:
                    initial_display = text_read
                    break

    init_raw_vt = target.get_attribute('aria-valuetext')
    init_raw_vn = target.get_attribute('aria-valuenow')

    if not has_named_hidden:
        if not is_native_input or initial_display or init_raw_vt or init_raw_vn:
            return ('skipped', 'Combobox lacks uniquely owned committed submitted value (display-only .single-value does not qualify; requires unique target-owned named hidden input); unsupported needs_user')

    # Verify representations in live DOM before interaction: reject contradictory actual values
    init_dom_state = search_scope.evaluate(r"""scope => {
        const inp = scope.querySelector('input:not([type="hidden"])');
        return {
            search_val: inp ? (inp.value || '').trim() : ''
        };
    }""")
    initial_search_val = init_dom_state['search_val']
    initial_hidden = (hidden_input.get_attribute('value') or '').strip() if has_named_hidden else None
    initial_vt = (init_raw_vt or '').strip()
    initial_vn = (init_raw_vn or '').strip()

    if initial_search_val and initial_vt and initial_search_val.lower() != initial_vt.lower():
        return ('skipped', f"Combobox has contradictory initial representations (search input '{initial_search_val}' vs ARIA valuetext '{initial_vt}'); unsupported skipped")
    if initial_search_val and initial_vn and initial_search_val.lower() != initial_vn.lower():
        return ('skipped', f"Combobox has contradictory initial representations (search input '{initial_search_val}' vs ARIA valuenow '{initial_vn}'); unsupported skipped")
    if initial_vt and initial_vn and initial_vt.lower() != initial_vn.lower():
        return ('skipped', f"Combobox has contradictory initial representations (ARIA valuetext '{initial_vt}' vs valuenow '{initial_vn}'); unsupported skipped")

    # 2. Static preflight inspect options via associated DOM even if closed
    opt_selector = '[role="option"], .select__option, [class*="-option"]'
    preflight_options = menu.evaluate("""(m, sel) => {
        const opts = Array.from(m.querySelectorAll(sel));
        return opts.map((o, idx) => {
            const dataVal = o.getAttribute('data-value');
            const valAttr = o.getAttribute('value');
            const optVal = dataVal !== null ? dataVal : (valAttr !== null ? valAttr : null);
            return {
                index: idx,
                id: o.id || '',
                label: (o.innerText || o.textContent || '').trim(),
                value: optVal !== null ? optVal.trim() : null,
                disabled: Boolean(o.getAttribute('aria-disabled') === 'true' || o.disabled)
            };
        });
    }""", opt_selector)

    if not preflight_options:
        raise ValueError(f"No matching options found in combobox menu for '{search_text}'")

    enabled_opts = [o for o in preflight_options if not o['disabled']]
    lbl_norm = str(opt_label).strip().lower() if has_opt_label else None
    val_norm = str(opt_val).strip().lower() if has_opt_val else None

    matching_by_lbl = [o for o in enabled_opts if lbl_norm and o['label'].strip().lower() == lbl_norm]
    matching_by_val = [o for o in enabled_opts if val_norm and o['value'] is not None and o['value'].strip().lower() == val_norm]

    # Preflight match: reject option mismatches or contradictions statically before interaction
    if has_opt_label and has_opt_val:
        if not matching_by_lbl:
            raise ValueError(f"No matching option found for combobox label '{opt_label}'")
        if not matching_by_val:
            raise ValueError(f"No matching option found for combobox value '{opt_val}'")
        if len(matching_by_lbl) > 1:
            raise ValueError(f"Ambiguous: multiple options match combobox label '{opt_label}'")
        if len(matching_by_val) > 1:
            raise ValueError(f"Ambiguous: multiple options match combobox value '{opt_val}'")
        if matching_by_lbl[0]['index'] != matching_by_val[0]['index']:
            raise ValueError(
                f"Conflicting combobox label '{opt_label}' (option index {matching_by_lbl[0]['index']}) "
                f"and value '{opt_val}' (option index {matching_by_val[0]['index']}); rejecting before mutation"
            )
        chosen_opt = matching_by_lbl[0]
    elif has_opt_label:
        if not matching_by_lbl:
            raise ValueError(f"No matching option found for combobox label '{opt_label}'")
        if len(matching_by_lbl) > 1:
            raise ValueError(f"Ambiguous: multiple options match combobox label '{opt_label}'")
        chosen_opt = matching_by_lbl[0]
    elif has_opt_val:
        if not matching_by_val:
            raise ValueError(f"No matching option found for combobox value '{opt_val}'")
        if len(matching_by_val) > 1:
            raise ValueError(f"Ambiguous: multiple options match combobox value '{opt_val}'")
        chosen_opt = matching_by_val[0]
    else:
        raise ValueError("Combobox requires option label or value")

    # Record initial states for no-op rejection
    initial_hidden = (hidden_input.get_attribute('value') or '').strip() if has_named_hidden else None
    initial_vt = (init_raw_vt or '').strip()
    initial_vn = (init_raw_vn or '').strip()

    # Reject hiddenunknown with optionnull before interaction:
    if has_named_hidden and (chosen_opt['value'] is None or chosen_opt['value'] == '') and initial_hidden:
        return ('skipped', 'Combobox option has null value with hidden submitted input; cannot infer label equivalence; unsupported needs_user')

    # Supported shape: mutate
    target.scroll_into_view_if_needed(timeout=5000)
    if not opened_for_menu:
        target.click(timeout=5000)

    combo_input = None
    try:
        if is_native_input:
            combo_input = target
        else:
            child_input = target.locator('input:not([type="hidden"])')
            if child_input.count() > 0:
                combo_input = child_input.first
    except Exception:
        pass

    page_obj = getattr(target, 'page', getattr(root, 'page', root))
    if combo_input is not None and combo_input.count() > 0:
        combo_input.focus(timeout=5000)
        combo_input.type(search_text, delay=20)
    elif hasattr(page_obj, 'keyboard'):
        page_obj.keyboard.type(search_text, delay=20)

    try:
        menu.locator(opt_selector).first.wait_for(state='visible', timeout=5000)
    except Exception:
        pass

    # Re-enumerate live options dynamically after search input interaction: NEVER reuse nth preflight index!
    live_options = menu.evaluate("""(m, sel) => {
        const opts = Array.from(m.querySelectorAll(sel));
        return opts.map((o, idx) => {
            const dataVal = o.getAttribute('data-value');
            const valAttr = o.getAttribute('value');
            const optVal = dataVal !== null ? dataVal : (valAttr !== null ? valAttr : null);
            return {
                index: idx,
                id: o.id || '',
                label: (o.innerText || o.textContent || '').trim(),
                value: optVal !== null ? optVal.trim() : null,
                disabled: Boolean(o.getAttribute('aria-disabled') === 'true' || o.disabled)
            };
        });
    }""", opt_selector)

    if not live_options:
        raise ValueError(f"No options found in combobox menu after interaction for '{search_text}'")

    enabled_live = [o for o in live_options if not o['disabled']]
    live_matches = []
    if chosen_opt.get('id'):
        live_matches = [o for o in enabled_live if o['id'] == chosen_opt['id']]
    if not live_matches:
        if has_opt_label and has_opt_val:
            live_matches = [
                o for o in enabled_live
                if lbl_norm and o['label'].strip().lower() == lbl_norm and o['value'] is not None and o['value'].strip().lower() == val_norm
            ]
        elif has_opt_label:
            live_matches = [o for o in enabled_live if lbl_norm and o['label'].strip().lower() == lbl_norm]
        elif has_opt_val:
            live_matches = [o for o in enabled_live if val_norm and o['value'] is not None and o['value'].strip().lower() == val_norm]

    if not live_matches:
        raise ValueError(f"No matching live option found for combobox '{search_text}' after interaction")
    if len(live_matches) > 1:
        raise ValueError(f"Ambiguous: multiple live options match combobox '{search_text}' after interaction")

    matched_live_opt = live_matches[0]

    # Revalidate fields and enabled immediately before click
    if matched_live_opt['id']:
        live_opt_loc = menu.locator(f"#{matched_live_opt['id']}")
    else:
        live_opt_loc = menu.locator(opt_selector).nth(matched_live_opt['index'])

    opt_recheck = live_opt_loc.evaluate("""el => {
        const dataVal = el.getAttribute('data-value');
        const valAttr = el.getAttribute('value');
        const optVal = dataVal !== null ? dataVal : (valAttr !== null ? valAttr : null);
        return {
            id: el.id || '',
            label: (el.innerText || el.textContent || '').trim(),
            value: optVal !== null ? optVal.trim() : null,
            disabled: Boolean(el.getAttribute('aria-disabled') === 'true' || el.disabled)
        };
    }""")
    if opt_recheck['disabled']:
        raise ValueError(f"Combobox option '{matched_live_opt['label']}' is disabled")
    if matched_live_opt.get('id') and opt_recheck.get('id') and opt_recheck['id'] != matched_live_opt['id']:
        raise ValueError(
            f"Combobox option ID mismatch immediately before click: expected '{matched_live_opt['id']}', got '{opt_recheck['id']}'"
        )
    if lbl_norm and opt_recheck['label'].strip().lower() != lbl_norm:
        raise ValueError(f"Combobox option label mismatch immediately before click: expected '{opt_label}', got '{opt_recheck['label']}'")
    if val_norm:
        if opt_recheck['value'] is None:
            raise ValueError(
                f"Combobox option missing value attribute immediately before click: expected '{opt_val}', got None; rejecting before mutation"
            )
        if opt_recheck['value'].strip().lower() != val_norm:
            raise ValueError(f"Combobox option value mismatch immediately before click: expected '{opt_val}', got '{opt_recheck['value']}'")
    preflight_val = chosen_opt.get('value')
    if preflight_val is not None:
        if opt_recheck['value'] is None:
            raise ValueError(
                f"Combobox option missing value attribute immediately before click: preflight observed '{preflight_val}', got None; rejecting before click"
            )
        if opt_recheck['value'].strip().lower() != str(preflight_val).strip().lower():
            raise ValueError(
                f"Combobox option value mismatch immediately before click: preflight observed '{preflight_val}', got '{opt_recheck['value']}'; rejecting before click"
            )

    live_opt_loc.scroll_into_view_if_needed(timeout=5000)
    live_opt_loc.click(timeout=5000)

    # After action: require ALL available submitted representations to match selected actual option AND supplied intent

    # 1. Target-owned hidden submitted value
    observed_hidden = None
    if has_named_hidden:
        observed_hidden = (hidden_input.get_attribute('value') or '').strip()
        # Existing hidden input empty is failure if expected nonempty
        if observed_hidden == '':
            raise RuntimeError(f"Existing hidden input empty despite selection of '{chosen_opt['label']}'; cannot establish uniquely target-owned committed value in DOM; failure")
        if chosen_opt['value'] is not None and observed_hidden.lower() != chosen_opt['value'].lower():
            raise RuntimeError(
                f"Combobox hidden value mismatch: observed hidden={observed_hidden!r}, expected option value={chosen_opt['value']!r}"
            )
        if has_opt_val and observed_hidden.lower() != str(opt_val).strip().lower():
            raise RuntimeError(
                f"Combobox hidden value mismatch: observed hidden={observed_hidden!r}, expected supplied value={opt_val!r}"
            )
        if initial_hidden is not None and observed_hidden == initial_hidden and (chosen_opt['value'] is None or observed_hidden.lower() != chosen_opt['value'].lower()):
            raise RuntimeError(f"Combobox hidden value no-op: value remained {observed_hidden!r}")

    # 2. Visible single-value text
    observed_display = None
    sv = search_scope.locator('.select__single-value, [class*="single-value"]')
    if sv.count() > 0:
        for idx in range(sv.count()):
            candidate_sv = sv.nth(idx)
            if candidate_sv.is_visible():
                text_read = candidate_sv.inner_text(timeout=2000).strip()
                if text_read:
                    observed_display = text_read
                    break
    if observed_display:
        lbl_clean = chosen_opt['label'].lower()
        disp_clean = observed_display.lower()
        if disp_clean != lbl_clean and not lbl_clean.endswith(disp_clean) and not disp_clean.endswith(lbl_clean):
            raise RuntimeError(
                f"Combobox readback label mismatch: observed display={observed_display!r}, expected option label={chosen_opt['label']!r}"
            )
        if has_opt_label:
            opt_lbl_clean = str(opt_label).strip().lower()
            if disp_clean != opt_lbl_clean and not opt_lbl_clean.endswith(disp_clean) and not disp_clean.endswith(opt_lbl_clean):
                raise RuntimeError(
                    f"Combobox readback label mismatch: observed display={observed_display!r}, expected supplied label={opt_label!r}"
                )

    # 3. Target aria-valuetext AND aria-valuenow if present checked independently; NEVER USE 'OR'
    raw_vt = target.get_attribute('aria-valuetext')
    raw_vn = target.get_attribute('aria-valuenow')

    if raw_vt is not None:
        vt_clean = raw_vt.strip().lower()
        exp_lbl_clean = chosen_opt['label'].lower()
        exp_val_clean = chosen_opt['value'].lower() if chosen_opt['value'] is not None else None
        if vt_clean != exp_lbl_clean and (exp_val_clean is None or vt_clean != exp_val_clean):
            raise RuntimeError(
                f"Combobox ARIA valuetext/valuenow mismatch: observed aria-valuetext={raw_vt!r}, expected label={chosen_opt['label']!r}"
            )
        if has_opt_label and vt_clean != str(opt_label).strip().lower():
            raise RuntimeError(
                f"Combobox ARIA valuetext/valuenow mismatch vs intent: observed aria-valuetext={raw_vt!r}, expected label={opt_label!r}"
            )
        if initial_vt and raw_vt.strip().lower() == initial_vt.lower() and raw_vt.strip().lower() != chosen_opt['label'].lower():
            raise RuntimeError("Combobox interaction was a no-op; aria-valuetext did not update")

    if raw_vn is not None:
        vn_clean = raw_vn.strip().lower()
        exp_lbl_clean = chosen_opt['label'].lower()
        exp_val_clean = chosen_opt['value'].lower() if chosen_opt['value'] is not None else None
        if (exp_val_clean is not None and vn_clean != exp_val_clean) and vn_clean != exp_lbl_clean:
            raise RuntimeError(
                f"Combobox ARIA valuetext/valuenow mismatch: observed aria-valuenow={raw_vn!r}, expected value={chosen_opt['value']!r}"
            )
        if has_opt_val and vn_clean != str(opt_val).strip().lower():
            raise RuntimeError(
                f"Combobox ARIA valuetext/valuenow mismatch vs intent: observed aria-valuenow={raw_vn!r}, expected value={opt_val!r}"
            )
        if initial_vn and raw_vn.strip().lower() == initial_vn.lower() and (exp_val_clean is not None and raw_vn.strip().lower() != exp_val_clean):
            raise RuntimeError("Combobox interaction was a no-op; aria-valuenow did not update")

    # Reject contradictions between aria-valuetext and aria-valuenow (e.g. ariaBachelor+masters)
    if raw_vt is not None and raw_vn is not None:
        if chosen_opt['value'] is not None:
            if raw_vn.strip().lower() != chosen_opt['value'].lower() or (has_opt_label and raw_vt.strip().lower() != str(opt_label).strip().lower()):
                raise RuntimeError(
                    f"Contradiction between combobox aria-valuetext {raw_vt!r} and aria-valuenow {raw_vn!r}"
                )

    verified = observed_display or observed_hidden or (raw_vn if raw_vn is not None else (raw_vt if raw_vt is not None else None))
    if not verified:
        raise RuntimeError(
            "Combobox readback verification failed: cannot establish uniquely target-owned committed value in DOM; abstaining"
        )

    return verified


def _fill_file(target: Any, file_path_val: Any) -> Optional[str]:
    file_path = str(file_path_val) if file_path_val else ''
    if not file_path or not os.path.isfile(file_path):
        return None

    target.set_input_files(file_path, timeout=5000)
    files = target.evaluate("el => el.files ? Array.from(el.files).map(f => f.name) : []")
    if not files or len(files) == 0:
        raise RuntimeError(
            f"File input failed DOM readback: no files registered in DOM for {file_path}"
        )
    expected_name = os.path.basename(file_path)
    if files[0] != expected_name:
        raise RuntimeError(
            f"File input DOM readback mismatch: expected {expected_name!r}, got {files[0]!r}"
        )
    return files[0]


def _collect_guard_telemetry(page: Any) -> Dict[str, Any]:
    frames = getattr(page, 'frames', [page])
    total_blocked_submits = 0
    guard_active = False
    for f in frames:
        try:
            t = f.evaluate("() => window.__job_applier_guard || null")
            if t and t.get('installed'):
                guard_active = True
                total_blocked_submits += int(t.get('blocked_submits', 0))
        except Exception:
            pass
    return {
        'installed': guard_active,
        'blocked_submits': total_blocked_submits,
    }


def fill_form(
    page: Any,
    answers_plan: Dict[str, Any],
    options: Optional[Dict[str, Any]] = None,
    allow_review: bool = False,
) -> Dict[str, Any]:
    """Fill an application form with Playwright using a resolved answers plan.

    Strictly protects against submissions and external side effects with the observation guard.
    Returns a structured fill report following schema 'job-applier.fill-report.v1'.
    """
    options = options or {}
    screenshot_enabled = options.get('screenshot', True)
    screenshot_path = options.get('screenshot_path')
    allow_review = allow_review or options.get('allow_review', False)

    # Ensure observation guard covers all existing frames
    install_observation_guard(page)
    for f in getattr(page, 'frames', [page]):
        try:
            f.evaluate(GUARD_SCRIPT)
        except Exception:
            pass

    # Verify initial guard telemetry across frames; fail closed if unavailable
    initial_telem = _collect_guard_telemetry(page)
    if not initial_telem['installed']:
        raise RuntimeError(
            "Safety violation: observation guard telemetry unavailable; aborting form fill"
        )

    initial_blocked_submits = initial_telem['blocked_submits']

    val_err = validate_answers_plan(answers_plan)
    if val_err:
        raise ValueError(val_err)

    answers = answers_plan.get('answers') or []
    fields: List[Dict[str, Any]] = []

    for q in answers:
        qid = q.get('question_id') or q.get('id')
        q_text = q.get('text', '')
        answer = q.get('answer')
        status = q.get('status')
        explicit_kind = q.get('native_input_type') or q.get('input_type') or 'unknown'

        # 1. Plan-level prohibition check
        prohibited_reason = _is_prohibited_plan(q, allow_review=allow_review)
        if prohibited_reason:
            fields.append({
                'question_id': qid,
                'id': qid,
                'text': q_text,
                'input_type': explicit_kind,
                'answer': answer,
                'status': 'skipped',
                'verified_value': None,
                'skip_reason': prohibited_reason,
            })
            continue

        # 2. Status gating: 'ready' fills; 'review' requires explicit allow_review; 'needs_user' skipped
        if status == 'needs_user' or answer is None:
            fields.append({
                'question_id': qid,
                'id': qid,
                'text': q_text,
                'input_type': explicit_kind,
                'answer': answer,
                'status': 'skipped',
                'verified_value': None,
                'skip_reason': 'needs_user_or_unanswered',
            })
            continue

        if status == 'review':
            if not allow_review:
                fields.append({
                    'question_id': qid,
                    'id': qid,
                    'text': q_text,
                    'input_type': explicit_kind,
                    'answer': answer,
                    'status': 'skipped',
                    'verified_value': None,
                    'skip_reason': 'review_requires_explicit_approval',
                })
                continue
        elif status != 'ready':
            fields.append({
                'question_id': qid,
                'id': qid,
                'text': q_text,
                'input_type': explicit_kind,
                'answer': answer,
                'status': 'skipped',
                'verified_value': None,
                'skip_reason': f"unsupported_status_{status}",
            })
            continue

        try:
            # Resolve scope root (main frame or specific iframe)
            root = _resolve_scope_root(page, q)

            # Detect field kind
            kind = _detect_field_kind(root, q)

            if kind == 'file':
                file_str = str(answer) if answer else ''
                if not file_str or not os.path.isfile(file_str):
                    fields.append({
                        'question_id': qid,
                        'id': qid,
                        'text': q_text,
                        'input_type': 'file',
                        'answer': answer,
                        'status': 'skipped',
                        'verified_value': None,
                        'skip_reason': 'file_not_found_on_disk',
                    })
                    continue

            if kind in ('radio', 'single_choice'):
                verified_val = _fill_radio(root, q, allow_review=allow_review)
                if isinstance(verified_val, tuple) and verified_val[0] == 'skipped':
                    fields.append({
                        'question_id': qid,
                        'id': qid,
                        'text': q_text,
                        'input_type': kind,
                        'answer': answer,
                        'status': 'skipped',
                        'verified_value': None,
                        'skip_reason': verified_val[1],
                    })
                    continue
                fields.append({
                    'question_id': qid,
                    'id': qid,
                    'text': q_text,
                    'input_type': kind,
                    'answer': answer,
                    'status': 'filled',
                    'verified_value': verified_val,
                })
            else:
                target = _find_input_locator(root, q, kind)
                if isinstance(target, tuple) and target[0] == 'skipped':
                    fields.append({
                        'question_id': qid,
                        'id': qid,
                        'text': q_text,
                        'input_type': kind,
                        'answer': answer,
                        'status': 'skipped',
                        'verified_value': None,
                        'skip_reason': target[1],
                    })
                    continue
                if target is None or target.count() == 0:
                    raise ValueError(f"Control locator not found for '{q_text}'")

                # Validate live DOM control before mutation
                dom_prohibited = _validate_dom_control(target, q, kind, allow_review=allow_review)
                if dom_prohibited:
                    fields.append({
                        'question_id': qid,
                        'id': qid,
                        'text': q_text,
                        'input_type': kind,
                        'answer': answer,
                        'status': 'skipped',
                        'verified_value': None,
                        'skip_reason': dom_prohibited,
                    })
                    continue

                _verify_semantic_identity(target, q, q_text)

                # Re-verify kind with actual located element
                kind = _detect_field_kind(root, q, target)

                if kind == 'file':
                    verified_val = _fill_file(target, answer)
                    if verified_val is None:
                        fields.append({
                            'question_id': qid,
                            'id': qid,
                            'text': q_text,
                            'input_type': 'file',
                            'answer': answer,
                            'status': 'skipped',
                            'verified_value': None,
                            'skip_reason': 'file_not_found_on_disk',
                        })
                    else:
                        fields.append({
                            'question_id': qid,
                            'id': qid,
                            'text': q_text,
                            'input_type': 'file',
                            'answer': answer,
                            'status': 'filled',
                            'verified_value': verified_val,
                        })
                elif kind == 'select':
                    verified_val = _fill_select(target, q)
                    fields.append({
                        'question_id': qid,
                        'id': qid,
                        'text': q_text,
                        'input_type': 'select',
                        'answer': answer,
                        'status': 'filled',
                        'verified_value': verified_val,
                    })
                elif kind == 'combobox':
                    verified_val = _fill_combobox(root, target, q)
                    if isinstance(verified_val, tuple) and verified_val[0] == 'skipped':
                        fields.append({
                            'question_id': qid,
                            'id': qid,
                            'text': q_text,
                            'input_type': 'combobox',
                            'answer': answer,
                            'status': 'skipped',
                            'verified_value': None,
                            'skip_reason': verified_val[1],
                        })
                        continue
                    fields.append({
                        'question_id': qid,
                        'id': qid,
                        'text': q_text,
                        'input_type': 'combobox',
                        'answer': answer,
                        'status': 'filled',
                        'verified_value': verified_val,
                    })
                elif kind == 'checkbox':
                    verified_val = _fill_checkbox(target, answer)
                    fields.append({
                        'question_id': qid,
                        'id': qid,
                        'text': q_text,
                        'input_type': 'checkbox',
                        'answer': answer,
                        'status': 'filled',
                        'verified_value': verified_val,
                    })
                else:
                    verified_val = _fill_text_like(target, answer)
                    fields.append({
                        'question_id': qid,
                        'id': qid,
                        'text': q_text,
                        'input_type': kind,
                        'answer': answer,
                        'status': 'filled',
                        'verified_value': verified_val,
                    })

        except UnsupportedFrameError as exc:
            fields.append({
                'question_id': qid,
                'id': qid,
                'text': q_text,
                'input_type': explicit_kind,
                'answer': answer,
                'status': 'skipped',
                'verified_value': None,
                'skip_reason': f"unsupported_ambiguous_frame: {exc}",
            })
        except Exception as exc:
            fields.append({
                'question_id': qid,
                'id': qid,
                'text': q_text,
                'input_type': explicit_kind,
                'answer': answer,
                'status': 'failed',
                'verified_value': None,
                'error': str(exc),
            })

    # Capture full-page screenshot atomically if enabled
    final_screenshot_path = None
    if screenshot_enabled and screenshot_path:
        image_bytes = page.screenshot(full_page=True, timeout=5000)
        written = write_bytes_atomic(
            screenshot_path,
            image_bytes,
            overwrite=options.get('overwrite', False),
        )
        final_screenshot_path = str(written)

    # Collect final guard telemetry across frames
    final_telem = _collect_guard_telemetry(page)
    if not final_telem['installed']:
        raise RuntimeError(
            "Safety violation: observation guard telemetry unavailable; aborting fill report"
        )

    final_blocked_submits = final_telem['blocked_submits']
    blocked_attempts_during_fill = final_blocked_submits - initial_blocked_submits

    # Ledger of blocked network requests
    blocked_requests = getattr(
        page,
        '_job_applier_blocked_requests',
        getattr(getattr(page, 'context', None), '_job_applier_blocked_requests', []),
    )

    return {
        'schema': SCHEMA_VERSION,
        'snapshot_id': answers_plan.get('snapshot_id'),
        'summary': {
            'total_answers': len(answers),
            'filled': sum(1 for f in fields if f['status'] == 'filled'),
            'skipped': sum(1 for f in fields if f['status'] == 'skipped'),
            'failed': sum(1 for f in fields if f['status'] == 'failed'),
        },
        'telemetry': {
            'guard_active': True,
            'blocked_network_requests': list(blocked_requests or []),
            'blocked_form_submits': final_blocked_submits,
            'blocked_attempts_during_fill': blocked_attempts_during_fill,
            'remote_side_effect_limitation': (
                "Guarded: POST/PUT/DELETE/PATCH network requests blocked and form submit intercepted. "
                "Limitation: GET/HEAD/OPTIONS requests and established WebSockets are not blocked."
            ),
        },
        'fields': fields,
        'screenshot_path': final_screenshot_path,
    }
