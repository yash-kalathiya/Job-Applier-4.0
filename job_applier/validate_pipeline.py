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
import copy
import io
import json
import os
from pathlib import Path, PureWindowsPath
import sys
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urlparse

from .extraction import SCHEMA_VERSION as EXTRACTION_SCHEMA
from .extraction.__main__ import main as extract_main
from .filling import SCHEMA_VERSION as FILL_SCHEMA
from .filling.__main__ import main as fill_main
from .filling.engine import validate_answers_plan
from .resolution import SCHEMA_VERSION as RESOLUTION_SCHEMA
from .resolution.__main__ import main as resolve_main
from .safe_io import write_json_atomic


def _stat_sig(path: Path) -> Optional[Tuple[int, int, int]]:
    """Return (inode, mtime_ns, size) or None if file does not exist."""
    try:
        st = path.stat()
        return (st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _is_fresh(path: Path, before_sig: Optional[Tuple[int, int, int]]) -> bool:
    """Return True if path exists as a regular file and was freshly created or rewritten."""
    try:
        if not path.is_file():
            return False
        st = path.stat()
        after_sig = (st.st_ino, st.st_mtime_ns, st.st_size)
        if before_sig is None:
            return True
        return after_sig != before_sig
    except OSError:
        return False


FILE_KINDS = {'file'}
CHECKBOX_KINDS = {'checkbox'}
CHOICE_KINDS = {'select', 'radio', 'single_choice', 'multiple_choice', 'combobox', 'listbox'}
TEXT_KINDS = {'text', 'textarea', 'contenteditable', 'textbox', 'email', 'tel', 'url', 'number', 'password', 'search'}


def _normalize_text(val: Any) -> str:
    """Normalize text by collapsing whitespace and stripping."""
    if not isinstance(val, str) or isinstance(val, bool):
        return ''
    return ' '.join(val.strip().split())


def _normalize_opt_val(val: Any) -> Tuple[bool, Optional[str], bool]:
    """Normalize option value preserving primitive 0 and False.

    Returns (has_value, normalized_str, is_blank_or_unusable).
    """
    if val is None:
        return False, None, False
    if isinstance(val, (dict, list)):
        return True, None, True
    if isinstance(val, bool):
        return True, ('true' if val else 'false'), False
    if isinstance(val, (int, float)):
        return True, str(val).strip().lower(), False
    if isinstance(val, str):
        norm = _normalize_text(val).lower()
        if not norm:
            return True, '', True
        return True, norm, False
    return True, None, True


def _normalize_opt_id(val: Any) -> Tuple[bool, Optional[str], bool]:
    """Normalize option id preserving primitive 0 and False.

    Returns (has_id, normalized_str, is_blank_or_unusable).
    """
    if val is None:
        return False, None, False
    if isinstance(val, (dict, list)):
        return True, None, True
    if isinstance(val, bool):
        return True, ('true' if val else 'false'), False
    if isinstance(val, (int, float)):
        return True, str(val).strip().lower(), False
    if isinstance(val, str):
        norm = _normalize_text(val).lower()
        if not norm:
            return True, '', True
        return True, norm, False
    return True, None, True


def _extract_opt_id(val: Any) -> str:
    """Safely extract normalized option id string preserving 0 and False."""
    has_id, norm_id, is_bad = _normalize_opt_id(val)
    if has_id and not is_bad and norm_id is not None:
        return norm_id
    return ''


def _normalize_choice_planned(planned: Any) -> str:
    """Normalize choice planned answer to lowercase stripped string."""
    if isinstance(planned, (int, float)):
        return str(planned).strip().lower()
    return _normalize_text(str(planned)).lower()


def _validate_answers_plan_adapted(plan: Any) -> Optional[str]:
    """Validate answers plan structure allowing primitive int/bool option IDs."""
    if not isinstance(plan, dict):
        return validate_answers_plan(plan)
    answers = plan.get('answers')
    if not isinstance(answers, list):
        return validate_answers_plan(plan)
    needs_adapt = False
    for ans in answers:
        if isinstance(ans, dict):
            so = ans.get('selected_option')
            if isinstance(so, dict) and isinstance(so.get('id'), (int, bool)):
                needs_adapt = True
                break
            opts = ans.get('options')
            if isinstance(opts, dict) and isinstance(opts.get('items'), list):
                for item in opts['items']:
                    if isinstance(item, dict) and isinstance(item.get('id'), (int, bool)):
                        needs_adapt = True
                        break
    if not needs_adapt:
        return validate_answers_plan(plan)
    adapted = copy.deepcopy(plan)
    for ans in adapted.get('answers', []):
        if isinstance(ans, dict):
            so = ans.get('selected_option')
            if isinstance(so, dict) and isinstance(so.get('id'), (int, bool)):
                so['id'] = str(so['id']).strip().lower()
            opts = ans.get('options')
            if isinstance(opts, dict) and isinstance(opts.get('items'), list):
                for item in opts['items']:
                    if isinstance(item, dict) and isinstance(item.get('id'), (int, bool)):
                        item['id'] = str(item['id']).strip().lower()
    return validate_answers_plan(adapted)


def _extract_planned_file_basename(planned: Any) -> Optional[str]:
    """Extract expected basename from planned file path or URI."""
    if not isinstance(planned, str) or isinstance(planned, bool) or not planned.strip():
        return None
    raw = planned.strip()
    if '://' in raw:
        raw = urlparse(raw).path
    name = PureWindowsPath(raw.replace('/', '\\')).name
    return name if name else None


def _is_valid_observed_file_basename(val: Any) -> bool:
    """Check if verified_value is strictly a file basename (not a path or URI)."""
    if not isinstance(val, str) or isinstance(val, bool):
        return False
    v = val.strip()
    if not v:
        return False
    if v.lower() in {'no observed file', 'none', 'null', 'no file'}:
        return False
    # Reject POSIX/Windows paths, relative path components, and URIs
    if '/' in v or '\\' in v or ':' in v:
        return False
    if v in {'.', '..'}:
        return False
    return True


def _determine_effective_kind(
    q_kind: str,
    native_kind: str,
    f_kind: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Determine effective control kind and check compatibility between question and fill field."""
    # 1. Semantic file check: file questions cannot be masked by text fill
    if q_kind in FILE_KINDS or native_kind in FILE_KINDS:
        if f_kind not in FILE_KINDS:
            return None, f"question is semantic file but fill reported incompatible kind '{f_kind}'"
        return 'file', None

    # 2. Checkbox check
    if q_kind in CHECKBOX_KINDS or native_kind in CHECKBOX_KINDS:
        if f_kind not in CHECKBOX_KINDS:
            return None, f"question is checkbox but fill reported incompatible kind '{f_kind}'"
        return 'checkbox', None

    # 3. Choice / combobox check (handling legacy AX textbox / combobox)
    if q_kind in CHOICE_KINDS or native_kind in CHOICE_KINDS:
        if f_kind in CHOICE_KINDS or (q_kind in {'combobox', 'listbox'} and f_kind in TEXT_KINDS):
            return 'choice', None
        return None, f"question is choice ({q_kind}) but fill reported incompatible kind '{f_kind}'"

    # 4. Text check (textbox role in AX tree maps to text)
    if q_kind in TEXT_KINDS or native_kind in TEXT_KINDS or not q_kind:
        if f_kind in TEXT_KINDS or (f_kind == 'combobox' and q_kind in {'text', 'textbox'}):
            return 'text', None
        if f_kind in CHOICE_KINDS and q_kind in TEXT_KINDS:
            return 'choice', None
        return None, f"question is text ({q_kind}) but fill reported incompatible kind '{f_kind}'"

    return None, f"unsupported control kind: question '{q_kind}', fill '{f_kind}'"


def _check_question_satisfaction(
    q: Dict[str, Any],
    ans: Optional[Dict[str, Any]],
    field: Optional[Dict[str, Any]],
    allow_review: bool,
    req_type: str,
) -> Tuple[bool, Optional[str]]:
    """Evaluate whether question q is truthfully verified satisfied."""
    qid = str(q.get('id', ''))

    if ans is None:
        return False, f"Question '{qid}' has no matching answer plan row"

    ans_status = ans.get('status')
    if ans_status == 'ready':
        pass
    elif ans_status == 'review':
        if not allow_review:
            return False, f"Question '{qid}' answer status is 'review' but allow_review is False"
    else:
        return False, f"Question '{qid}' answer status '{ans_status}' is not eligible"

    if field is None:
        return False, f"Question '{qid}' has no matching fill report field"

    f_status = field.get('status')
    if f_status != 'filled':
        reason = field.get('skip_reason') or field.get('error') or f_status
        return False, f"Question '{qid}' fill status is '{f_status}' ({reason})"

    q_kind = str(q.get('input_type') or '').strip().lower()
    native_kind = str(q.get('native_input_type') or '').strip().lower()
    f_kind = str(field.get('input_type') or '').strip().lower()
    is_password = (
        q_kind == 'password'
        or native_kind == 'password'
        or f_kind == 'password'
        or str(q.get('kind') or '').strip().lower() == 'password'
        or str(field.get('kind') or '').strip().lower() == 'password'
    )

    effective_kind, kind_err = _determine_effective_kind(q_kind, native_kind, f_kind)
    if kind_err or effective_kind is None:
        return False, f"Question '{qid}' {kind_err}"

    val = field.get('verified_value')

    # Strict control kind type BEFORE value checks
    if effective_kind == 'text':
        disp_val = "'[REDACTED]'" if is_password else repr(val)
        if not isinstance(val, str) or isinstance(val, bool):
            return False, f"Question '{qid}' text control requires non-blank string, got {type(val).__name__} ({disp_val})"
        norm_val = _normalize_text(val)
        if not norm_val:
            return False, f"Question '{qid}' verified_value is blank"

        planned = ans.get('answer')
        disp_planned = "'[REDACTED]'" if is_password else repr(planned)
        if planned is None or isinstance(planned, bool):
            return False, f"Question '{qid}' text control requires usable planned string or number, got {type(planned).__name__} ({disp_planned})"
        if isinstance(planned, (int, float)):
            norm_planned = str(planned).strip()
        elif isinstance(planned, str):
            norm_planned = _normalize_text(planned)
        else:
            return False, f"Question '{qid}' text control requires usable planned string or number, got {type(planned).__name__} ({disp_planned})"
        if not norm_planned:
            return False, f"Question '{qid}' text control planned answer is blank"
        if norm_val != norm_planned:
            return False, f"Question '{qid}' readback text {disp_val} does not match planned answer {disp_planned}"

    elif effective_kind == 'choice':
        if not isinstance(val, str) or isinstance(val, bool):
            return False, f"Question '{qid}' choice control requires non-blank string, got {type(val).__name__} ({repr(val)})"
        norm_val = _normalize_text(val).lower()
        if not norm_val:
            return False, f"Question '{qid}' verified_value is blank"

        planned = ans.get('answer')
        selected_opt = ans.get('selected_option')

        # Validate planned type if present
        if planned is not None:
            if not isinstance(planned, (str, bool, int, float)):
                return False, f"Question '{qid}' choice control planned answer must be string, bool, or number, got {type(planned).__name__} ({repr(planned)})"
            if isinstance(planned, str) and not _normalize_text(planned):
                return False, f"Question '{qid}' choice control planned answer is blank"

        if selected_opt is not None:
            if not isinstance(selected_opt, dict):
                return False, f"Question '{qid}' choice selected_option must be a dict, got {type(selected_opt).__name__}"

        has_s_id = False
        s_id = ''
        has_s_lbl = False
        s_lbl = ''
        has_s_val = False
        s_val = ''
        usable_sel_opt_count = 0

        if isinstance(selected_opt, dict) and selected_opt:
            if 'id' in selected_opt:
                raw_id = selected_opt['id']
                if raw_id is not None:
                    has_id, norm_id, is_bad = _normalize_opt_id(raw_id)
                    if is_bad or not has_id:
                        return False, f"Question '{qid}' selected_option has blank or unusable 'id'"
                    has_s_id = True
                    s_id = norm_id or ''

            if 'label' in selected_opt:
                raw_lbl = selected_opt['label']
                if raw_lbl is not None:
                    if not isinstance(raw_lbl, str) or not _normalize_text(raw_lbl):
                        return False, f"Question '{qid}' selected_option has blank or unusable 'label'"
                    has_s_lbl = True
                    s_lbl = _normalize_text(raw_lbl).lower()

            if 'value' in selected_opt:
                raw_val = selected_opt['value']
                has_v, norm_v, is_bad = _normalize_opt_val(raw_val)
                if has_v:
                    if is_bad:
                        return False, f"Question '{qid}' selected_option has blank or unusable 'value'"
                    has_s_val = True
                    s_val = norm_v or ''

            usable_sel_opt_count = (1 if has_s_id else 0) + (1 if has_s_lbl else 0) + (1 if has_s_val else 0)
            if usable_sel_opt_count == 0:
                return False, f"Question '{qid}' choice selected_option requires at least one usable recognized identifier ('id', 'label', 'value')"

        if planned is None and usable_sel_opt_count == 0:
            return False, f"Question '{qid}' choice control requires usable planned answer or selected_option"

        opts_container = q.get('options')
        opts_items = opts_container.get('items') if isinstance(opts_container, dict) else None
        has_captured_options = isinstance(opts_items, list) and len(opts_items) > 0

        acceptable: Set[str] = set()

        if has_captured_options:
            assert opts_items is not None
            # If selected_option is provided, it must identify a single captured option
            if usable_sel_opt_count > 0:
                matched_options = []
                for o in opts_items:
                    if not isinstance(o, dict):
                        continue
                    o_lbl = _normalize_text(str(o.get('label') or '')).lower() if o.get('label') is not None else ''
                    o_id = _extract_opt_id(o.get('id'))
                    has_o_val, o_val_norm, _ = _normalize_opt_val(o.get('value'))
                    o_val = o_val_norm or ''

                    match_id = (not has_s_id) or (o_id == s_id)
                    match_lbl = (not has_s_lbl) or (o_lbl == s_lbl) or (s_lbl in {'true', 'yes'} and o_lbl in {'true', 'yes'}) or (s_lbl in {'false', 'no'} and o_lbl in {'false', 'no'})
                    match_val = (not has_s_val) or (has_o_val and o_val == s_val) or (s_val in {'true', 'yes'} and o_val in {'true', 'yes'}) or (s_val in {'false', 'no'} and o_val in {'false', 'no'})

                    if match_id and match_lbl and match_val:
                        matched_options.append(o)

                if len(matched_options) == 0:
                    return False, f"Question '{qid}' selected_option label/value contradictory or not found in captured options"
                if len(matched_options) > 1:
                    return False, f"Question '{qid}' selected_option is ambiguous in captured options ({len(matched_options)} matches)"

                canonical_opt = matched_options[0]
                c_lbl = _normalize_text(str(canonical_opt.get('label') or '')).lower() if canonical_opt.get('label') is not None else ''
                c_id = _extract_opt_id(canonical_opt.get('id'))
                _, c_val_norm, _ = _normalize_opt_val(canonical_opt.get('value'))
                c_val = c_val_norm or ''

                # Verify answer intent agrees with the identified captured option
                if planned is not None:
                    if isinstance(planned, bool):
                        p_bool_set = {'true', 'yes'} if planned else {'false', 'no'}
                        if c_lbl not in p_bool_set and c_val not in p_bool_set:
                            return False, f"Question '{qid}' planned answer {repr(planned)} contradicts captured option {canonical_opt}"
                    else:
                        p_norm = _normalize_choice_planned(planned)
                        if p_norm in {'true', 'yes'}:
                            if c_lbl not in {'true', 'yes'} and c_val not in {'true', 'yes'}:
                                return False, f"Question '{qid}' planned answer {repr(planned)} contradicts captured option {canonical_opt}"
                        elif p_norm in {'false', 'no'}:
                            if c_lbl not in {'false', 'no'} and c_val not in {'false', 'no'}:
                                return False, f"Question '{qid}' planned answer {repr(planned)} contradicts captured option {canonical_opt}"
                        elif p_norm != c_lbl and p_norm != c_val and p_norm != c_id:
                            return False, f"Question '{qid}' planned answer {repr(planned)} contradicts captured option {canonical_opt}"

                if c_lbl:
                    acceptable.add(c_lbl)
                if c_val:
                    acceptable.add(c_val)
                if c_id:
                    acceptable.add(c_id)
                # Consistent boolean identity: do NOT interpret opaque option value '1' as Yes or '0' as No
                if c_lbl in {'true', 'yes'} or (not c_lbl and c_val in {'true', 'yes'}):
                    acceptable.update({'true', 'yes'})
                elif c_lbl in {'false', 'no'} or (not c_lbl and c_val in {'false', 'no'}):
                    acceptable.update({'false', 'no'})

            else:
                # No selected_option, match planned answer against captured options
                p_matches = []
                for o in opts_items:
                    if not isinstance(o, dict):
                        continue
                    o_lbl = _normalize_text(str(o.get('label') or '')).lower() if o.get('label') is not None else ''
                    o_id = _extract_opt_id(o.get('id'))
                    has_o_val, o_val_norm, _ = _normalize_opt_val(o.get('value'))
                    o_val = o_val_norm or ''

                    if isinstance(planned, bool):
                        p_set = {'true', 'yes'} if planned else {'false', 'no'}
                        if o_lbl in p_set or o_val in p_set:
                            p_matches.append(o)
                    else:
                        p_norm = _normalize_choice_planned(planned)
                        if p_norm in {'true', 'yes'}:
                            if o_lbl in {'true', 'yes'} or o_val in {'true', 'yes'}:
                                p_matches.append(o)
                        elif p_norm in {'false', 'no'}:
                            if o_lbl in {'false', 'no'} or o_val in {'false', 'no'}:
                                p_matches.append(o)
                        elif p_norm == o_lbl or p_norm == o_val or (o_id and p_norm == o_id):
                            p_matches.append(o)

                if not p_matches:
                    return False, f"Question '{qid}' planned answer {repr(planned)} not found in captured options"

                for matched_o in p_matches:
                    mo_lbl = _normalize_text(str(matched_o.get('label') or '')).lower() if matched_o.get('label') is not None else ''
                    mo_id = _extract_opt_id(matched_o.get('id'))
                    _, mo_val_norm, _ = _normalize_opt_val(matched_o.get('value'))
                    mo_val = mo_val_norm or ''
                    if mo_lbl:
                        acceptable.add(mo_lbl)
                    if mo_val:
                        acceptable.add(mo_val)
                    if mo_id:
                        acceptable.add(mo_id)
                    if mo_lbl in {'true', 'yes'} or (not mo_lbl and mo_val in {'true', 'yes'}):
                        acceptable.update({'true', 'yes'})
                    elif mo_lbl in {'false', 'no'} or (not mo_lbl and mo_val in {'false', 'no'}):
                        acceptable.update({'false', 'no'})

        else:
            # Missing captured option metadata: do not pretend metadata exists; conservative exact intent match
            if usable_sel_opt_count > 0:
                if s_lbl and s_val:
                    # Legitimate mappings: identical strings or both boolean false / both boolean true
                    both_true = s_lbl in {'true', 'yes'} and s_val in {'true', 'yes'}
                    both_false = s_lbl in {'false', 'no'} and s_val in {'false', 'no'}
                    if s_lbl != s_val and not both_true and not both_false:
                        return False, f"Question '{qid}' selected_option has contradictory or unattested label {repr(s_lbl)} and value {repr(s_val)} without captured option metadata"

                if s_id and s_lbl:
                    both_true = s_id in {'true', 'yes'} and s_lbl in {'true', 'yes'}
                    both_false = s_id in {'false', 'no'} and s_lbl in {'false', 'no'}
                    if s_id != s_lbl and not both_true and not both_false:
                        return False, f"Question '{qid}' selected_option has contradictory or unattested id {repr(s_id)} and label {repr(s_lbl)} without captured option metadata"

                if s_id and s_val:
                    both_true = s_id in {'true', 'yes'} and s_val in {'true', 'yes'}
                    both_false = s_id in {'false', 'no'} and s_val in {'false', 'no'}
                    if s_id != s_val and not both_true and not both_false:
                        return False, f"Question '{qid}' selected_option has contradictory or unattested id {repr(s_id)} and value {repr(s_val)} without captured option metadata"

                if planned is not None:
                    if isinstance(planned, bool):
                        p_bool_set = {'true', 'yes'} if planned else {'false', 'no'}
                        if (s_lbl and s_lbl not in p_bool_set) or (s_val and s_val not in p_bool_set) or (s_id and s_id not in p_bool_set):
                            return False, f"Question '{qid}' planned answer {repr(planned)} contradicts selected_option {selected_opt}"
                    else:
                        p_norm = _normalize_choice_planned(planned)
                        if p_norm in {'true', 'yes'}:
                            if (s_lbl and s_lbl not in {'true', 'yes'}) or (s_val and s_val not in {'true', 'yes'}) or (s_id and s_id not in {'true', 'yes'}):
                                return False, f"Question '{qid}' planned answer {repr(planned)} contradicts selected_option {selected_opt}"
                        elif p_norm in {'false', 'no'}:
                            if (s_lbl and s_lbl not in {'false', 'no'}) or (s_val and s_val not in {'false', 'no'}) or (s_id and s_id not in {'false', 'no'}):
                                return False, f"Question '{qid}' planned answer {repr(planned)} contradicts selected_option {selected_opt}"
                        else:
                            if s_lbl and p_norm != s_lbl:
                                return False, f"Question '{qid}' planned answer {repr(planned)} contradicts selected_option label {repr(s_lbl)}"
                            if s_val and p_norm != s_val:
                                return False, f"Question '{qid}' planned answer {repr(planned)} contradicts selected_option value {repr(s_val)}"
                            if s_id and p_norm != s_id:
                                return False, f"Question '{qid}' planned answer {repr(planned)} contradicts selected_option id {repr(s_id)}"

                if s_lbl:
                    acceptable.add(s_lbl)
                if s_val:
                    acceptable.add(s_val)
                if s_id:
                    acceptable.add(s_id)
                if s_lbl in {'true', 'yes'} or (not s_lbl and (s_val in {'true', 'yes'} or s_id in {'true', 'yes'})):
                    acceptable.update({'true', 'yes'})
                elif s_lbl in {'false', 'no'} or (not s_lbl and (s_val in {'false', 'no'} or s_id in {'false', 'no'})):
                    acceptable.update({'false', 'no'})

            else:
                if isinstance(planned, bool):
                    if planned:
                        acceptable.update({'true', 'yes'})
                    else:
                        acceptable.update({'false', 'no'})
                else:
                    p_norm = _normalize_choice_planned(planned)
                    if p_norm in {'true', 'yes'}:
                        acceptable.update({'true', 'yes'})
                    elif p_norm in {'false', 'no'}:
                        acceptable.update({'false', 'no'})
                    else:
                        acceptable.add(p_norm)

        if not acceptable or norm_val not in acceptable:
            return False, f"Question '{qid}' readback choice {repr(val)} contradicts planned answer {repr(planned or selected_opt)}"

    elif effective_kind == 'checkbox':
        if not isinstance(val, bool):
            return False, f"Question '{qid}' checkbox requires boolean verified_value, got {type(val).__name__} ({repr(val)})"

        planned = ans.get('answer')
        if isinstance(planned, bool):
            planned_bool = planned
        elif isinstance(planned, int) and not isinstance(planned, bool):
            if planned == 1:
                planned_bool = True
            elif planned == 0:
                planned_bool = False
            else:
                return False, f"Question '{qid}' checkbox has unsupported planned numeric answer {repr(planned)}"
        elif isinstance(planned, str):
            p_norm = planned.strip().lower()
            if p_norm in {'true', 'yes', '1'}:
                planned_bool = True
            elif p_norm in {'false', 'no', '0'}:
                planned_bool = False
            else:
                return False, f"Question '{qid}' checkbox has unsupported planned string answer {repr(planned)}"
        else:
            return False, f"Question '{qid}' checkbox has unsupported planned answer {type(planned).__name__} ({repr(planned)})"

        if val != planned_bool:
            return False, f"Question '{qid}' checkbox readback {val} does not match planned answer {planned_bool}"

        if req_type == 'required':
            if val is not True:
                return False, f"Question '{qid}' required checkbox is not checked (value={val})"
        elif req_type == 'unknown':
            if val is not True:
                return False, f"Question '{qid}' unknown-requiredness checkbox is False (unresolved until known optional)"

    elif effective_kind == 'file':
        if not _is_valid_observed_file_basename(val):
            return False, f"Question '{qid}' file requires observed basename string, got {repr(val)}"

        planned = ans.get('answer')
        planned_base = _extract_planned_file_basename(planned)
        if not planned_base:
            return False, f"Question '{qid}' file requires valid planned path/basename string, got {type(planned).__name__} ({repr(planned)})"
        if val.strip().lower() != planned_base.lower():
            return False, f"Question '{qid}' observed file {repr(val)} does not match planned basename {repr(planned_base)}"

    else:
        return False, f"Question '{qid}' unsupported effective control kind '{effective_kind}'"

    return True, None


_observed_satisfied = _check_question_satisfaction


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
      - required_count, required_verified, missing_required, unknown_required_unresolved
      - validation_scope: 'reported_fill_evidence'
      - final_dom_validity: 'not_reported'
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
            'required_count': 0,
            'required_verified': 0,
            'missing_required': [],
            'unknown_required_unresolved': [],
            'validation_scope': 'reported_fill_evidence',
            'final_dom_validity': 'not_reported',
            'artifacts': {
                'questions': None,
                'answers': None,
                'fill_report': None,
                'screenshot': None,
                'summary': str(out_dir / 'validation_summary.json'),
            },
            'steps': {
                'fetch': {'status': 'failed', 'error': 'URL must use https://, http://, or file://', 'cli_exit_code': 1},
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

    snapshot_questions: Dict[str, Dict[str, Any]] = {}
    req_map: Dict[str, str] = {}
    answers_by_id: Dict[str, Dict[str, Any]] = {}
    fields_by_id: Dict[str, Dict[str, Any]] = {}
    satisfaction_map: Dict[str, bool] = {}
    deficit_reasons: Dict[str, str] = {}

    fetch_details: Dict[str, Any] = {'status': 'not_run'}
    answer_details: Dict[str, Any] = {'status': 'not_run'}
    fill_details: Dict[str, Any] = {'status': 'not_run'}

    questions_path = out_dir / 'questions.json'
    answers_path = out_dir / 'answers.json'
    report_path = out_dir / 'fill_report.json'
    screenshot_path = out_dir / 'screenshot.png'
    summary_path = out_dir / 'validation_summary.json'

    questions_fresh = False
    answers_fresh = False
    report_fresh = False
    screenshot_final: Optional[str] = None
    snapshot_id: Optional[str] = None
    integrity_error = False
    fill_code = 0

    # -------------------------------------------------------------------------
    # Step 1 (Fetch): Runs extraction (job_applier.extraction.__main__.main)
    # -------------------------------------------------------------------------
    before_q_sig = _stat_sig(questions_path)
    extract_args = [url, '--out', str(out_dir)]
    if headed:
        extract_args.append('--headed')
    if overwrite:
        extract_args.append('--overwrite')

    buf = io.StringIO()
    extract_code = 0
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            extract_code = extract_main(extract_args)
    except SystemExit as exc:
        extract_code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        extract_code = 1
        errors.append(f'Step 1 (Fetch) extraction raised exception: {exc}')

    questions_fresh = _is_fresh(questions_path, before_q_sig)

    if extract_code != 0:
        fetch_details = {
            'status': 'failed',
            'error': f'Extraction failed with exit code {extract_code}',
            'cli_exit_code': extract_code,
            'output': buf.getvalue()[-500:] if buf.getvalue() else None,
        }
        errors.append(f'Step 1 (Fetch) failed with exit code {extract_code}')
    elif not questions_fresh:
        fetch_details = {
            'status': 'failed',
            'error': f'questions.json was not freshly created at {questions_path}',
            'cli_exit_code': extract_code,
            'output': buf.getvalue()[-500:] if buf.getvalue() else None,
        }
        errors.append(f'Step 1 (Fetch) failed: questions.json not freshly created at {questions_path}')
    else:
        try:
            with open(questions_path, 'r', encoding='utf-8') as f:
                snapshot = json.load(f)

            schema = snapshot.get('schema_version') or snapshot.get('schema')
            snapshot_id = snapshot.get('snapshot_id')
            questions = snapshot.get('questions')

            if schema != EXTRACTION_SCHEMA:
                errors.append(f"Step 1 (Fetch) invalid schema: expected '{EXTRACTION_SCHEMA}', got '{schema}'")
                fetch_details = {'status': 'failed', 'error': 'Invalid schema', 'schema': schema, 'cli_exit_code': extract_code}
            elif not isinstance(snapshot_id, str) or not snapshot_id.strip():
                errors.append("Step 1 (Fetch) missing or empty snapshot_id")
                fetch_details = {'status': 'failed', 'error': 'Missing snapshot_id', 'cli_exit_code': extract_code}
            elif not isinstance(questions, list) or len(questions) == 0:
                errors.append('Step 1 (Fetch) captured 0 questions')
                fetch_details = {'status': 'failed', 'error': '0 questions captured', 'question_count': 0, 'cli_exit_code': extract_code}
            else:
                seen_qids: Set[str] = set()
                q_integrity_ok = True

                for q in questions:
                    if not isinstance(q, dict):
                        errors.append('Step 1 (Fetch) question entry is not a dict')
                        q_integrity_ok = False
                        break
                    qid = q.get('id')
                    if not isinstance(qid, str) or not qid.strip():
                        errors.append(f'Step 1 (Fetch) question has malformed or empty id: {repr(qid)}')
                        q_integrity_ok = False
                        break
                    if qid in seen_qids:
                        errors.append(f'Step 1 (Fetch) duplicate question id in snapshot: {qid}')
                        q_integrity_ok = False
                        break
                    seen_qids.add(qid)
                    snapshot_questions[qid] = q

                    req_val = q.get('required')
                    if req_val is True:
                        req_map[qid] = 'required'
                    elif req_val is False:
                        req_map[qid] = 'optional'
                    elif req_val is None:
                        req_map[qid] = 'unknown'
                    else:
                        errors.append(f"Step 1 (Fetch) question '{qid}' has invalid required flag shape: {repr(req_val)}")
                        req_map[qid] = 'invalid'
                        q_integrity_ok = False

                if 'summary' in snapshot:
                    q_summary = snapshot['summary']
                    if not isinstance(q_summary, dict):
                        errors.append(f"Step 1 (Fetch) summary must be a dict, got {type(q_summary).__name__}")
                        q_integrity_ok = False
                    else:
                        for s_k, s_v in q_summary.items():
                            if s_k in {'questions', 'controls', 'combined_controls', 'conflicts', 'options_incomplete', 'llm_calls', 'llm_tokens', 'elapsed_ms'}:
                                if not (isinstance(s_v, int) and not isinstance(s_v, bool) and s_v >= 0):
                                    errors.append(f"Step 1 (Fetch) summary count '{s_k}' must be non-negative int, got {repr(s_v)}")
                                    q_integrity_ok = False
                        if 'questions' in q_summary:
                            claimed_q_count = q_summary['questions']
                            if claimed_q_count != len(questions):
                                errors.append(f'Step 1 (Fetch) summary mismatch: claimed {claimed_q_count} questions, actual {len(questions)}')
                                q_integrity_ok = False

                if q_integrity_ok:
                    fetched = True
                    question_count = len(questions)
                    fetch_details = {
                        'status': 'success',
                        'schema': schema,
                        'snapshot_id': snapshot_id,
                        'question_count': question_count,
                        'cli_exit_code': extract_code,
                        'path': str(questions_path),
                    }
                else:
                    integrity_error = True
                    fetch_details = {
                        'status': 'failed',
                        'error': 'Integrity validation failed on snapshot questions',
                        'cli_exit_code': extract_code,
                    }
        except Exception as exc:
            errors.append(f'Step 1 (Fetch) failed to read/parse questions.json: {exc}')
            fetch_details = {'status': 'failed', 'error': str(exc), 'cli_exit_code': extract_code}

    # -------------------------------------------------------------------------
    # Step 2 (Answer): Runs resolution (job_applier.resolution.__main__.main)
    # -------------------------------------------------------------------------
    if fetched and not integrity_error:
        before_a_sig = _stat_sig(answers_path)
        resolve_args = [str(questions_path), '--out', str(answers_path)]
        if bank:
            resolve_args.extend(['--bank', str(bank)])
        if overwrite:
            resolve_args.append('--overwrite')

        buf = io.StringIO()
        resolve_code = 0
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                resolve_code = resolve_main(resolve_args)
        except SystemExit as exc:
            resolve_code = exc.code if isinstance(exc.code, int) else 1
        except Exception as exc:
            resolve_code = 1
            errors.append(f'Step 2 (Answer) resolution raised exception: {exc}')

        answers_fresh = _is_fresh(answers_path, before_a_sig)

        if resolve_code != 0:
            answer_details = {
                'status': 'failed',
                'error': f'Resolution failed with exit code {resolve_code}',
                'cli_exit_code': resolve_code,
                'output': buf.getvalue()[-500:] if buf.getvalue() else None,
            }
            errors.append(f'Step 2 (Answer) failed with exit code {resolve_code}')
        elif not answers_fresh:
            answer_details = {
                'status': 'failed',
                'error': f'answers.json was not freshly created at {answers_path}',
                'cli_exit_code': resolve_code,
                'output': buf.getvalue()[-500:] if buf.getvalue() else None,
            }
            errors.append(f'Step 2 (Answer) failed: answers.json not freshly created at {answers_path}')
        else:
            try:
                with open(answers_path, 'r', encoding='utf-8') as f:
                    answers_plan = json.load(f)

                schema = answers_plan.get('schema')
                ans_snapshot_id = answers_plan.get('snapshot_id')
                schema_err = _validate_answers_plan_adapted(answers_plan)

                if schema != RESOLUTION_SCHEMA:
                    errors.append(f"Step 2 (Answer) invalid schema: expected '{RESOLUTION_SCHEMA}', got '{schema}'")
                    answer_details = {'status': 'failed', 'error': 'Invalid schema', 'schema': schema, 'cli_exit_code': resolve_code}
                elif schema_err:
                    errors.append(f'Step 2 (Answer) schema validation failed: {schema_err}')
                    answer_details = {'status': 'failed', 'error': schema_err, 'cli_exit_code': resolve_code}
                elif ans_snapshot_id != snapshot_id:
                    errors.append(f"Step 2 (Answer) lineage mismatch: expected snapshot_id '{snapshot_id}', got '{ans_snapshot_id}'")
                    answer_details = {'status': 'failed', 'error': 'Lineage mismatch', 'cli_exit_code': resolve_code}
                else:
                    answers_list = answers_plan.get('answers', [])
                    seen_ans_qids: Set[str] = set()
                    ans_integrity_ok = True

                    for ans in answers_list:
                        if not isinstance(ans, dict):
                            errors.append('Step 2 (Answer) answer row is not a dict')
                            ans_integrity_ok = False
                            break
                        aqid = ans.get('question_id')
                        if not isinstance(aqid, str) or not aqid.strip():
                            errors.append(f'Step 2 (Answer) answer row has malformed or empty question_id: {repr(aqid)}')
                            ans_integrity_ok = False
                            break
                        if aqid in seen_ans_qids:
                            errors.append(f'Step 2 (Answer) duplicate question_id in answers: {aqid}')
                            ans_integrity_ok = False
                            break
                        seen_ans_qids.add(aqid)
                        if aqid not in snapshot_questions:
                            errors.append(f"Step 2 (Answer) foreign question_id in answers not found in snapshot: {aqid}")
                            ans_integrity_ok = False
                            break
                        answers_by_id[aqid] = ans

                    ready_count = sum(1 for a in answers_list if a.get('status') == 'ready')
                    review_count = sum(1 for a in answers_list if a.get('status') == 'review')
                    needs_user_count = sum(1 for a in answers_list if a.get('status') == 'needs_user')

                    if 'summary' in answers_plan:
                        ans_summary = answers_plan['summary']
                        if not isinstance(ans_summary, dict):
                            errors.append(f"Step 2 (Answer) summary must be a dict, got {type(ans_summary).__name__}")
                            ans_integrity_ok = False
                        else:
                            for s_k in ('ready', 'review', 'needs_user', 'total'):
                                if s_k in ans_summary:
                                    s_v = ans_summary[s_k]
                                    if not (isinstance(s_v, int) and not isinstance(s_v, bool) and s_v >= 0):
                                        errors.append(f"Step 2 (Answer) summary count '{s_k}' must be non-negative int, got {repr(s_v)}")
                                        ans_integrity_ok = False
                            if 'ready' in ans_summary and ans_summary['ready'] != ready_count:
                                errors.append(f"Step 2 (Answer) summary mismatch: claimed ready={ans_summary['ready']}, derived={ready_count}")
                                ans_integrity_ok = False
                            if 'review' in ans_summary and ans_summary['review'] != review_count:
                                errors.append(f"Step 2 (Answer) summary mismatch: claimed review={ans_summary['review']}, derived={review_count}")
                                ans_integrity_ok = False
                            if 'needs_user' in ans_summary and ans_summary['needs_user'] != needs_user_count:
                                errors.append(f"Step 2 (Answer) summary mismatch: claimed needs_user={ans_summary['needs_user']}, derived={needs_user_count}")
                                ans_integrity_ok = False
                            if 'total' in ans_summary and ans_summary['total'] != len(answers_list):
                                errors.append(f"Step 2 (Answer) summary mismatch: claimed total={ans_summary['total']}, derived={len(answers_list)}")
                                ans_integrity_ok = False

                    if (ready_count + review_count == 0) and len(answers_list) > 0:
                        errors.append('Step 2 (Answer) resolved 0 answers (ready=0, review=0)')
                        answer_details = {
                            'status': 'failed',
                            'error': 'No resolved answers',
                            'ready_count': 0,
                            'review_count': 0,
                            'needs_user_count': needs_user_count,
                            'cli_exit_code': resolve_code,
                        }
                    elif ans_integrity_ok:
                        answered = True
                        answer_details = {
                            'status': 'success',
                            'schema': schema,
                            'snapshot_id': ans_snapshot_id,
                            'ready_count': ready_count,
                            'review_count': review_count,
                            'needs_user_count': needs_user_count,
                            'total_answers': len(answers_list),
                            'cli_exit_code': resolve_code,
                            'path': str(answers_path),
                        }
                    else:
                        integrity_error = True
                        answer_details = {
                            'status': 'failed',
                            'error': 'Integrity validation failed on answers',
                            'cli_exit_code': resolve_code,
                        }
            except Exception as exc:
                errors.append(f'Step 2 (Answer) failed to read/parse answers.json: {exc}')
                answer_details = {'status': 'failed', 'error': str(exc), 'cli_exit_code': resolve_code}

    # -------------------------------------------------------------------------
    # Step 3 (Fill): Runs form filling (job_applier.filling.__main__.main)
    # -------------------------------------------------------------------------
    if answered and not integrity_error:
        before_r_sig = _stat_sig(report_path)
        before_s_sig = _stat_sig(screenshot_path)

        fill_args = [url, '--answers', str(answers_path), '--out', str(out_dir)]
        if headed:
            fill_args.append('--headed')
        if overwrite:
            fill_args.append('--overwrite')
        if allow_review:
            fill_args.append('--allow-review')

        buf = io.StringIO()
        fill_code = 0
        fill_raised = False
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                fill_code = fill_main(fill_args)
        except SystemExit as exc:
            fill_code = exc.code if isinstance(exc.code, int) else 1
        except Exception as exc:
            fill_code = 1
            fill_raised = True
            errors.append(f'Step 3 (Fill) form filling raised exception: {exc}')

        report_fresh = _is_fresh(report_path, before_r_sig)

        if fill_raised or not report_fresh:
            fill_details = {
                'status': 'failed',
                'error': f'fill_report.json was not freshly created at {report_path}',
                'cli_exit_code': fill_code,
                'output': buf.getvalue()[-500:] if buf.getvalue() else None,
            }
            errors.append(f'Step 3 (Fill) failed: fill_report.json not freshly created at {report_path}')
        else:
            try:
                with open(report_path, 'r', encoding='utf-8') as f:
                    report = json.load(f)

                schema = report.get('schema')
                rep_snapshot_id = report.get('snapshot_id')
                field_integrity_ok = True
                if schema != FILL_SCHEMA:
                    errors.append(f"Step 3 (Fill) invalid schema: expected '{FILL_SCHEMA}', got '{schema}'")
                    field_integrity_ok = False
                if rep_snapshot_id != snapshot_id:
                    errors.append(f"Step 3 (Fill) lineage mismatch: expected snapshot_id '{snapshot_id}', got '{rep_snapshot_id}'")
                    field_integrity_ok = False

                fields = report.get('fields', [])
                seen_field_qids: Set[str] = set()

                for f_item in fields:
                    if not isinstance(f_item, dict):
                        errors.append('Step 3 (Fill) field entry is not a dict')
                        field_integrity_ok = False
                        break
                    fqid = f_item.get('question_id')
                    if not isinstance(fqid, str) or not fqid.strip():
                        errors.append(f'Step 3 (Fill) field entry has malformed or empty question_id: {repr(fqid)}')
                        field_integrity_ok = False
                        break
                    if fqid in seen_field_qids:
                        errors.append(f'Step 3 (Fill) duplicate question_id in fill fields: {fqid}')
                        field_integrity_ok = False
                        break
                    seen_field_qids.add(fqid)
                    if fqid not in snapshot_questions:
                        errors.append(f"Step 3 (Fill) foreign question_id in fill fields not found in snapshot: {fqid}")
                        field_integrity_ok = False
                        break
                    fields_by_id[fqid] = f_item

                filled_fields = [f for f in fields if f.get('status') == 'filled']
                skipped_fields = [f for f in fields if f.get('status') == 'skipped']
                failed_fields = [f for f in fields if f.get('status') == 'failed']

                filled_count = len(filled_fields)
                skipped_count = len(skipped_fields)
                failed_count = len(failed_fields)

                if 'summary' in report:
                    fill_summary = report['summary']
                    if not isinstance(fill_summary, dict):
                        errors.append(f"Step 3 (Fill) summary must be a dict, got {type(fill_summary).__name__}")
                        field_integrity_ok = False
                    else:
                        for s_k in ('filled', 'skipped', 'failed', 'total_answers'):
                            if s_k in fill_summary:
                                s_v = fill_summary[s_k]
                                if not (isinstance(s_v, int) and not isinstance(s_v, bool) and s_v >= 0):
                                    errors.append(f"Step 3 (Fill) summary count '{s_k}' must be non-negative int, got {repr(s_v)}")
                                    field_integrity_ok = False
                        if 'filled' in fill_summary and fill_summary['filled'] != filled_count:
                            errors.append(f"Step 3 (Fill) summary mismatch: claimed filled={fill_summary['filled']}, derived={filled_count}")
                            field_integrity_ok = False
                        if 'skipped' in fill_summary and fill_summary['skipped'] != skipped_count:
                            errors.append(f"Step 3 (Fill) summary mismatch: claimed skipped={fill_summary['skipped']}, derived={skipped_count}")
                            field_integrity_ok = False
                        if 'failed' in fill_summary and fill_summary['failed'] != failed_count:
                            errors.append(f"Step 3 (Fill) summary mismatch: claimed failed={fill_summary['failed']}, derived={failed_count}")
                            field_integrity_ok = False
                        if 'total_answers' in fill_summary:
                            tot = fill_summary['total_answers']
                            if tot != len(answers_by_id):
                                errors.append(f"Step 3 (Fill) summary mismatch: claimed total_answers={tot}, expected {len(answers_by_id)}")
                                field_integrity_ok = False

                telemetry = report.get('telemetry')
                telemetry_ok = True
                if not isinstance(telemetry, dict):
                    telemetry_ok = False
                    errors.append(f"Step 3 (Fill) telemetry must be a dict, got {type(telemetry).__name__}")
                else:
                    guard_val = telemetry.get('guard_active')
                    if guard_val is not True:
                        telemetry_ok = False
                        errors.append(f"Step 3 (Fill) telemetry guard_active must be literal True, got {repr(guard_val)}")

                    bfs = telemetry.get('blocked_form_submits')
                    if not (isinstance(bfs, int) and not isinstance(bfs, bool) and bfs >= 0):
                        telemetry_ok = False
                        errors.append(f"Step 3 (Fill) telemetry blocked_form_submits must be non-negative int, got {repr(bfs)}")

                submit_blocked = telemetry_ok

                screenshot_fresh = _is_fresh(screenshot_path, before_s_sig)
                screenshot_ok = (
                    screenshot_fresh
                    and screenshot_path.is_file()
                    and screenshot_path.stat().st_size > 0
                )
                if report.get('screenshot_path'):
                    try:
                        rep_ss = Path(os.path.abspath(os.path.expanduser(report['screenshot_path'])))
                        if rep_ss != screenshot_path.resolve():
                            screenshot_ok = False
                            errors.append(f"Step 3 (Fill) screenshot path mismatch: expected '{screenshot_path.resolve()}', got '{rep_ss}'")
                    except Exception:
                        screenshot_ok = False

                if not screenshot_ok:
                    errors.append(f'Step 3 (Fill) screenshot not freshly created, missing, empty, or canonical path mismatch at {screenshot_path}')
                else:
                    screenshot_final = str(screenshot_path.resolve())

                if filled_count == 0:
                    errors.append('Step 3 (Fill) verified 0 filled fields')
                if not submit_blocked:
                    errors.append('Step 3 (Fill) submit blocker guard was not active')

                if fill_code != 0:
                    errors.append(f'Step 3 (Fill) exited with non-zero code {fill_code}')

                for qid, q in snapshot_questions.items():
                    ans = answers_by_id.get(qid)
                    field = fields_by_id.get(qid)
                    satisfied, reason = _check_question_satisfaction(
                        q=q,
                        ans=ans,
                        field=field,
                        allow_review=allow_review,
                        req_type=req_map.get(qid, 'unknown'),
                    )
                    satisfaction_map[qid] = satisfied
                    if not satisfied and reason:
                        deficit_reasons[qid] = reason

                verified_count = sum(
                    1 for f in filled_fields
                    if f.get('question_id') in satisfaction_map and satisfaction_map[f.get('question_id')]
                )

                if (
                    field_integrity_ok
                    and screenshot_ok
                    and filled_count > 0
                    and submit_blocked
                    and schema == FILL_SCHEMA
                    and rep_snapshot_id == snapshot_id
                ):
                    filled = True
                    fill_details = {
                        'status': 'success' if fill_code == 0 else 'partial',
                        'schema': schema,
                        'snapshot_id': rep_snapshot_id,
                        'filled_count': filled_count,
                        'verified_count': verified_count,
                        'skipped_count': skipped_count,
                        'failed_count': failed_count,
                        'submit_blocked': submit_blocked,
                        'cli_exit_code': fill_code,
                        'report_path': str(report_path),
                        'screenshot_path': screenshot_final,
                    }
                else:
                    if not field_integrity_ok:
                        integrity_error = True
                    fill_details = {
                        'status': 'failed',
                        'cli_exit_code': fill_code,
                        'filled_count': filled_count,
                        'verified_count': verified_count,
                        'skipped_count': skipped_count,
                        'failed_count': failed_count,
                        'submit_blocked': submit_blocked,
                        'screenshot_ok': screenshot_ok,
                    }
            except Exception as exc:
                errors.append(f'Step 3 (Fill) failed to read/parse fill_report.json: {exc}')
                fill_details = {'status': 'failed', 'error': str(exc), 'cli_exit_code': fill_code}

    # -------------------------------------------------------------------------
    # Step 4 (Validate): Produces structured validation summary
    # -------------------------------------------------------------------------
    required_count = sum(1 for qid, rtype in req_map.items() if rtype == 'required')
    required_verified = sum(1 for qid, rtype in req_map.items() if rtype == 'required' and satisfaction_map.get(qid, False))
    missing_required = [qid for qid, rtype in req_map.items() if rtype == 'required' and not satisfaction_map.get(qid, False)]
    unknown_required_unresolved = [qid for qid, rtype in req_map.items() if rtype == 'unknown' and not satisfaction_map.get(qid, False)]

    def _sanitize_deficit_msg(qid: str, msg: str) -> str:
        q_obj = snapshot_questions.get(qid, {})
        f_obj = fields_by_id.get(qid, {})
        is_pwd = (
            str(q_obj.get('input_type') or '').lower() == 'password'
            or str(q_obj.get('native_input_type') or '').lower() == 'password'
            or str(f_obj.get('input_type') or '').lower() == 'password'
            or str(q_obj.get('kind') or '').lower() == 'password'
            or str(f_obj.get('kind') or '').lower() == 'password'
        )
        if not is_pwd:
            return msg
        ans_obj = answers_by_id.get(qid, {})
        raw_ans = ans_obj.get('answer')
        if isinstance(raw_ans, str) and raw_ans and raw_ans in msg:
            msg = msg.replace(repr(raw_ans), "'[REDACTED]'").replace(raw_ans, '[REDACTED]')
        raw_val = f_obj.get('verified_value')
        if isinstance(raw_val, str) and raw_val and raw_val in msg:
            msg = msg.replace(repr(raw_val), "'[REDACTED]'").replace(raw_val, '[REDACTED]')
        return msg

    invalid_optional_fills = []
    for qid, rtype in req_map.items():
        if rtype == 'optional':
            f_item = fields_by_id.get(qid)
            if f_item is not None and f_item.get('status') == 'filled':
                if not satisfaction_map.get(qid, False):
                    invalid_optional_fills.append(qid)
                    r_msg = _sanitize_deficit_msg(qid, deficit_reasons.get(qid, 'invalid optional fill'))
                    errors.append(f"Optional question invalid fill: id='{qid}', reason='{r_msg}'")

    for qid in missing_required:
        r_msg = _sanitize_deficit_msg(qid, deficit_reasons.get(qid, 'missing or unverified'))
        errors.append(f"Required question deficit: id='{qid}', reason='{r_msg}'")
    for qid in unknown_required_unresolved:
        r_msg = _sanitize_deficit_msg(qid, deficit_reasons.get(qid, 'unresolved unknown requiredness'))
        errors.append(f"Unknown-required question unresolved: id='{qid}', reason='{r_msg}'")

    has_required_deficit = len(missing_required) > 0
    has_unknown_unresolved = len(unknown_required_unresolved) > 0
    has_optional_fill_deficit = len(invalid_optional_fills) > 0

    if not fetched or not answered:
        status = 'FAILED'
    elif not filled:
        if filled_count > 0 or verified_count > 0:
            status = 'PARTIAL'
        else:
            status = 'FAILED'
    elif has_required_deficit or has_unknown_unresolved or has_optional_fill_deficit or fill_code != 0 or integrity_error:
        if filled_count > 0 or verified_count > 0:
            status = 'PARTIAL'
        else:
            status = 'FAILED'
    elif failed_count > 0 or question_count == 0 or len(errors) > 0 or not screenshot_final:
        if filled_count > 0 or verified_count > 0:
            status = 'PARTIAL'
        else:
            status = 'FAILED'
    else:
        status = 'SUCCESS'

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
        'required_count': required_count,
        'required_verified': required_verified,
        'missing_required': missing_required,
        'unknown_required_unresolved': unknown_required_unresolved,
        'optional_invalid_fills': invalid_optional_fills,
        'validation_scope': 'reported_fill_evidence',
        'final_dom_validity': 'not_reported',
        'artifacts': {
            'questions': str(questions_path) if (fetched and questions_fresh) else None,
            'answers': str(answers_path) if (answered and answers_fresh) else None,
            'fill_report': str(report_path) if report_fresh else None,
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
        if summary_result['status'] == 'SUCCESS':
            summary_result['status'] = 'PARTIAL' if summary_result.get('filled_count', 0) > 0 else 'FAILED'

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
