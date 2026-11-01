(element) => {
  const clean = value => (value || '').replace(/\s+/g, ' ').trim();
  const root = element.getRootNode();
  const attr = name => element.getAttribute(name);
  const referenced = name => (attr(name) || '').split(/\s+/).filter(Boolean)
    .map(id => root.getElementById?.(id)).filter(Boolean).map(e => clean(e.textContent)).join(' ');
  const path = el => {
    if (!el || el.nodeType !== 1) return '';
    const parts = [];
    while (el && el.nodeType === 1) {
      const parent = el.parentElement;
      const siblings = el.parentNode?.children ? [...el.parentNode.children].filter(x => x.tagName === el.tagName) : [el];
      parts.unshift(el.tagName.toLowerCase() + ':nth-of-type(' + (siblings.indexOf(el) + 1) + ')');
      if (!parent && el.getRootNode().host) return path(el.getRootNode().host) + ' >> ' + parts.join(' > ');
      el = parent;
    }
    return parts.join(' > ');
  };
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return !!((!el.checkVisibility || el.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) &&
      r.width && r.height && s.display !== 'none' && s.visibility !== 'hidden' &&
      Number(s.opacity) !== 0 && s.clip !== 'rect(0px, 0px, 0px, 0px)');
  };
  const labels = [...(element.labels || [])].map(e => clean(e.textContent));
  const tag = element.tagName.toLowerCase();
  const type = tag === 'input' ? element.type : (tag === 'textarea' ? 'textarea' : tag === 'select' ? 'select' : attr('role') || tag);
  const wrapper = element.closest('.field, .application-question, .input-wrapper, .select__container, [data-question-id]');
  const nearbyLabel = clean(wrapper?.querySelector('label')?.textContent);
  const group = element.closest('fieldset, [role="radiogroup"], [role="group"]');
  const groupLabel = group ? clean(group.querySelector('legend')?.textContent || group.getAttribute('aria-label') ||
    (group.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => root.getElementById?.(id)?.textContent || '').join(' ')) : '';
  const form = element.closest('form');
  const section = element.closest('section, fieldset, [role="group"], [role="radiogroup"]');
  const sectionLabel = clean(section?.querySelector('legend,h1,h2,h3,h4')?.textContent) || groupLabel;
  const label = clean(labels.join(' ')) || referenced('aria-labelledby') || attr('aria-label') || nearbyLabel || '';
  const marker = /\*\s*$|\(required\)/i.test(label) || (type === 'file' && /\*\s*$|\(required\)/i.test(groupLabel));
  const ariaRequired = attr('aria-required');
  const required = element.hasAttribute('required') ? true : ariaRequired === 'true' ? true :
    ariaRequired === 'false' ? false : marker ? true : null;
  const options = tag === 'select' ? [...element.options].map(o => ({
    id: o.id || null, label: clean(o.textContent), value: o.value,
    disabled: o.disabled || o.parentElement?.disabled || false, selected: o.selected
  })) : [];
  const box = element.getBoundingClientRect();
  const parentCombo = element.parentElement?.closest('[role="combobox"]');
  return {
    path: path(element), tag, type, id: element.id || null, name: attr('name'), role: attr('role'),
    label, labels, aria_label: attr('aria-label'), labelledby_text: referenced('aria-labelledby'),
    placeholder: attr('placeholder'), nearby_label: nearbyLabel,
    help: referenced('aria-describedby'), error: referenced('aria-errormessage'),
    group: group ? {path: path(group), label: groupLabel, role: group.getAttribute('role'),
      actions:[...group.querySelectorAll('button')].map(e=>clean(e.textContent)).filter(Boolean),
      help:[...group.querySelectorAll('p')].map(e=>clean(e.textContent)).join(' ')} : null,
    form_path: path(form), section: sectionLabel, wrapper_path: path(wrapper),
    parent_combobox_path: path(parentCombo),
    visible: visible(element), file_trigger_visible: type === 'file' &&
      ([...(element.labels || [])].some(visible) || visible(wrapper) ||
       (visible(group) && !!groupLabel && [...group.querySelectorAll('button,[role="button"]')].some(visible))),
    disabled: element.matches(':disabled') || attr('aria-disabled') === 'true',
    readonly: !!element.readOnly || attr('aria-readonly') === 'true',
    required, required_source: element.hasAttribute('required') ? 'html' : ariaRequired !== null ? 'aria' : marker ? 'label_marker' : 'unknown',
    constraints: {min: attr('min'), max: attr('max'), step: attr('step'), pattern: attr('pattern'),
      min_length: attr('minlength'), max_length: attr('maxlength'), accept: attr('accept'), multiple: !!element.multiple},
    value: type === 'password' ? null : type === 'file' ? [...element.files].map(f => ({name:f.name, size:f.size})) :
      ['radio','checkbox'].includes(type) || ['radio','checkbox','switch'].includes(attr('role')) ?
      (element.checked ?? attr('aria-checked')) : element.value ?? clean(element.textContent),
    option_value: ['radio','checkbox'].includes(type) ? element.value : null,
    options, controls_ids: (attr('aria-controls') || attr('aria-owns') || '').split(/\s+/).filter(Boolean),
    invalid: attr('aria-invalid'), box: {x:box.x,y:box.y,width:box.width,height:box.height}
  };
}
