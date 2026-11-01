"""Self-contained, escaped HTML report for reviewing captured questions."""
from html import escape
import json


def report_html(snapshot):
    esc = lambda value: escape(str(value if value is not None else ''), quote=True)
    controls = {c['id']: c for c in snapshot['controls']}
    cards = []
    for i, question in enumerate(snapshot['questions'], 1):
        members = [controls[c] for c in question['control_ids']]
        combined = all(c['evidence']['accessibility']['role'] for c in members)
        required = 'Required' if question['required'] is True else 'Optional' if question['required'] is False else 'Required status unknown'
        options = question['options']
        choices = ''.join('<li>' + esc(o['label']) + (' <span class="muted">disabled</span>' if o.get('disabled') else '') + '</li>' for o in options['items'])
        option_html = '<ul class="options">' + choices + '</ul>' if choices else ''
        if len(options['items']) > 12:
            preview = ''.join('<li>' + esc(o['label']) + '</li>' for o in options['items'][:6])
            option_html = '<ul class="options">' + preview + '</ul><details><summary>Show all ' + str(len(options['items'])) + ' observed options</summary>' + option_html + '</details>'
        if question['input_type'] in {'combobox','listbox','single_choice','multiple_choice'}:
            option_html += '<p class="muted">Options: ' + esc(options['status'].replace('_',' ')) + (' · complete for this rendered control' if options['complete'] else ' · completeness not established') + '</p>'
        warnings = ''.join('<span class="tag warning">' + esc(w.replace('_',' ')) + '</span>' for w in question['warnings'])
        detail = json.dumps({'question': question, 'controls': members}, indent=2, ensure_ascii=False)
        native = ', '.join(sorted({c['evidence']['dom']['type'] for c in members}))
        cards.append(f'''<article class="question" data-search="{esc(question['text'].lower())}" data-warning="{'yes' if question['warnings'] else 'no'}">
          <div class="number">{i:02d}</div><div class="content"><h2>{esc(question['text'])}</h2>
          <div class="tags"><span class="tag">{esc(question['input_type'])}</span><span class="tag">{esc(required)}</span>
          <span class="tag {'combined' if combined else ''}">{'DOM + accessibility' if combined else 'DOM evidence'}</span>{warnings}</div>
          <p class="muted">Native: {esc(native)} · {esc(question['frame_id'])}{' · ' + esc(question['section']) if question['section'] else ''}</p>
          {'<p>' + esc(question['help']) + '</p>' if question['help'] else ''}{option_html}
          <details><summary>Inspect DOM, accessibility and targeting evidence</summary><pre>{esc(detail)}</pre></details></div></article>''')
    summary = snapshot['summary']
    stats = ''.join(f'<div><strong>{summary[key]}</strong><span>{label}</span></div>' for key,label in [
        ('questions','Questions'),('controls','Controls'),('combined_controls','Combined controls'),('conflicts','Label conflicts'),('llm_tokens','LLM tokens')])
    issues = ''.join('<li>' + esc(json.dumps(issue, ensure_ascii=False)) + '</li>' for issue in snapshot['issues'])
    instructions = ''
    for item in snapshot.get('instructions', []):
        links = ' '.join('<a href="' + esc(link['url']) + '" rel="noreferrer">' + esc(link['label']) + '</a>'
                         for link in item['links'] if link['url'].startswith(('https://','http://')))
        instructions += '<p>' + esc(item['text']) + ('<br>' + links if links else '') + '</p>'
    frames = ''.join('<details><summary>' + esc(f['id'] + ' · ' + f['url']) + '</summary><pre>' + esc(f['accessibility_snapshot']) + '</pre></details>' for f in snapshot['frames'])
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:">
<title>Job Applier 4.0 · Question extraction</title><style>
:root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#e7ecf7;background:#101624;color-scheme:dark}*{box-sizing:border-box}
body{margin:0}main{max-width:1120px;margin:auto;padding:48px 28px 80px}header{margin-bottom:28px}.eyebrow{color:#8fdcc7;font-size:12px;font-weight:750;letter-spacing:.14em;text-transform:uppercase}
h1{font-size:clamp(30px,5vw,48px);letter-spacing:-.045em;line-height:1.12;margin:14px 0}h2{font-size:19px;font-weight:650;margin:0 0 12px;line-height:1.5}h3{font-size:20px}
p{line-height:1.6}a{color:#a0c8ff;overflow-wrap:anywhere}.muted{color:#a6b1c5;font-size:13px}.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:28px 0}
.stats>div{background:#192235;border:1px solid #2b3750;padding:20px;border-radius:14px}.stats strong{display:block;font-size:31px}.stats span{font-size:12px;color:#b5c0d4}
.toolbar{display:flex;gap:16px;align-items:center;position:sticky;top:0;background:#101624ee;padding:16px 0;z-index:2}input[type=search]{flex:1;min-width:80px;padding:13px 15px;border:1px solid #3c4a63;border-radius:9px;background:#1a2436;color:#fff;font:inherit}
.toolbar label{font-size:13px}.question{display:flex;gap:20px;border:1px solid #2c3850;background:#172032;border-radius:15px;padding:24px;margin:16px 0}.number{font-variant-numeric:tabular-nums;color:#7588aa;font-size:21px}.content{min-width:0;flex:1}
.tags{display:flex;gap:7px;flex-wrap:wrap}.tag{background:#27354c;border:1px solid #394964;color:#d0dced;font-size:11px;padding:5px 9px;border-radius:20px}.tag.combined{background:#163b38;color:#a3e6d3;border-color:#2c5f54}.tag.warning{background:#493a26;border-color:#6f5734;color:#ffdb9b}
.options{padding-left:20px;columns:2;column-gap:30px;font-size:14px;line-height:1.7}.options li{break-inside:avoid}.notice{border-left:3px solid #6dd8b6;padding:10px 16px;background:#182b31;border-radius:0 8px 8px 0;color:#c1dfdf;font-size:14px}
details{margin-top:16px;border-top:1px solid #2e3b51;padding-top:14px}summary{cursor:pointer;font-size:13px;color:#bbcae0;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0d1422;padding:18px;border-radius:8px;font-size:12px;line-height:1.5;max-height:600px;overflow:auto}
[hidden]{display:none!important}footer{margin-top:35px;color:#9aacc3;font-size:12px}@media(max-width:640px){main{padding:26px 15px}.stats{grid-template-columns:repeat(2,1fr)}.question{padding:18px;gap:12px}.options{columns:1}.toolbar{flex-wrap:wrap}.toolbar input{flex-basis:100%}}
</style></head><body><main><header><div class="eyebrow">Job Applier 4.0 / Phase 1</div><h1>What does this application ask?</h1><p>''' + esc(snapshot['page']['title']) + '''</p><a href="''' + esc(snapshot['page']['url'] if snapshot['page']['url'].startswith(('http://','https://')) else '#') + '''" rel="noreferrer">''' + esc(snapshot['page']['url']) + '''</a></header><div class="notice">Extraction only. No answers entered, files uploaded, or application submitted. ''' + esc(snapshot['coverage']) + '''</div><section class="stats">''' + stats + '''</section>
<div class="toolbar"><input id="search" type="search" aria-label="Search extracted questions" placeholder="Search questions…"><label><input id="warnings" type="checkbox"> Show warnings only</label><span id="count" class="muted"></span></div>
<section id="questions">''' + ''.join(cards) + '''</section>''' + ('<h3>Instructions on the form</h3><div class="notice">' + instructions + '</div>' if instructions else '') + '''<h3>Capture details</h3><p class="muted">''' + esc(snapshot['captured_at']) + ' · ' + esc(snapshot['status']) + ' · ' + esc(snapshot['snapshot_id']) + '''</p>''' + ('<ul>' + issues + '</ul>' if issues else '<p class="muted">No capture errors recorded. Individual warnings and incomplete option lists remain visible above.</p>') + frames + '''<footer>DOM and accessibility evidence are linked through the same live Playwright control. This report uses no model inference.</footer></main>
<script>const search=document.querySelector('#search'),warnings=document.querySelector('#warnings'),cards=[...document.querySelectorAll('.question')];function filter(){let n=0;for(const c of cards){c.hidden=!c.dataset.search.includes(search.value.toLowerCase())||(warnings.checked&&c.dataset.warning!=='yes');if(!c.hidden)n++;}document.querySelector('#count').textContent=n+' shown';}search.addEventListener('input',filter);warnings.addEventListener('change',filter);filter();</script></body></html>'''
