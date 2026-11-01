"""Resume templates -> HTML -> PDF (headless Chrome). Every template is single-column real text so it
parses in every ATS; they differ in typography, header layout, rules and density.

Bullets accept light markdown: **bold** and [text](url).
"""
import glob
import html
import os
import pathlib
import re
import shutil
import subprocess
import tempfile


def degree_line(e):
    """'Bachelor of Science' + 'Finance' -> 'Bachelor of Science in Finance'; a degree that already names its field
    ('B.S. in Management') takes the major after a comma, and a major the degree already states isn't said twice."""
    deg, major = (e.get('degree') or '').strip(), (e.get('major') or '').strip()
    if not deg or not major:
        return deg or major
    if major.lower() in deg.lower():
        return deg
    return f'{deg}, {major}' if re.search(r'\b(in|of)\s+\w', deg.split(' of ', 1)[-1] if deg.lower().startswith(('bachelor of', 'master of', 'doctor of')) else deg) else f'{deg} in {major}'

TEMPLATES = {
    'classic': {"label": "Jake's Classic", "desc": "The r/cscareerquestions favorite. Serif, small-caps headings, full rules, dense.",
                "best": "SWE, quant, research"},
    'harvard': {"label": "Harvard Traditional", "desc": "Career-office standard. Times, bold caps headings, black only.",
                "best": "Finance, consulting, any conservative firm"},
    'modern': {"label": "Awesome Modern", "desc": "Light/bold name, accent-colored headings, airy sans.",
               "best": "Startups, product, design-adjacent"},
    'banking': {"label": "Banking", "desc": "Centered headings between rules, calm blue accent.",
                "best": "Business, fintech, generalist"},
    'finance': {"label": "Finance One-Pager", "desc": "Garamond, education first, very dense. Wall Street style.",
                "best": "IB, asset management, trading"},
    'minimal': {"label": "Sans Minimal", "desc": "Left-aligned name, quiet gray headings, lots of whitespace.",
                "best": "Big tech, new grad, design"},
    'compact': {"label": "Compact Engineering", "desc": "No rules, tight spacing. Fits the most content on one page.",
                "best": "Lots of experience, hardware, robotics"},
    'latex': {"label": "LaTeX (Jake's)", "desc": "Real LaTeX typesetting, the Overleaf classic. Needs a TeX engine installed.",
              "best": "SWE, research, anyone who loves LaTeX"},
    'accent': {"label": "Accent Bar", "desc": "Teal name and a slim accent bar on each heading.",
               "best": "Data, AI, standing out while staying ATS-safe"},
}

BASE_CSS = """
@page { size: Letter; margin: 0; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; color: #111; font-variant-ligatures: none; font-feature-settings: "liga" 0, "clig" 0; }
.page { width: 8.5in; min-height: 11in; padding: var(--mt) var(--mx); font-family: var(--font); font-size: calc(var(--fs) * var(--k));
        line-height: var(--lh); }
a { color: inherit; text-decoration: none; }
h1 { margin: 0; font-size: calc(var(--name) * var(--k)); line-height: 1.1; }
.contact { margin-top: .18em; }
.contact span + span::before { content: "\\00a0|\\00a0"; color: var(--muted); }
.headline { margin-top: .12em; font-weight: 600; }
.headline span + span::before { content: "\\00a0\\00a0\\00b7\\00a0\\00a0"; font-weight: 400; }
section { margin-top: calc(var(--gap) * var(--k)); }
h2 { margin: 0 0 calc(.28em * var(--k)); font-size: calc(var(--hs) * var(--k)); }
.entry { margin-top: calc(var(--egap) * var(--k)); break-inside: avoid; }
.entry:first-of-type { margin-top: 0; }
.row { display: flex; justify-content: space-between; gap: 1em; }
.row > :last-child { white-space: nowrap; text-align: right; }
.org { font-weight: 700; }
.role { font-style: italic; }
.meta { color: var(--muted); }
ul { margin: .1em 0 0; padding-left: 1.15em; }
li { margin: calc(.05em * var(--k)) 0; padding-left: .1em; }
li::marker { content: "\\2022  "; font-size: .9em; }
.skills p { margin: .08em 0; }
.tag { color: var(--muted); }
"""

STYLE_CSS = {
    'classic': """:root{--font:"Latin Modern Roman","CMU Serif","Computer Modern Serif",Georgia,serif;--fs:10.4pt;--name:24pt;--hs:12pt;
      --lh:1.22;--mt:.45in;--mx:.5in;--gap:9pt;--egap:5pt;--muted:#333}
      header{text-align:center} h1{text-transform:uppercase;font-weight:700;letter-spacing:1.5px;font-size:calc(20pt * var(--k))}
      h2{text-transform:uppercase;font-weight:400;font-size:calc(10.5pt * var(--k));border-bottom:.6pt solid #000;padding-bottom:1pt;letter-spacing:1.2px}""",
    'harvard': """:root{--font:"Times New Roman",Times,serif;--fs:11pt;--name:16pt;--hs:11pt;--lh:1.2;--mt:.6in;--mx:.7in;
      --gap:10pt;--egap:6pt;--muted:#000} header{text-align:center} h1{font-weight:700}
      h2{text-transform:uppercase;font-weight:700;border-bottom:.8pt solid #000;padding-bottom:1pt}""",
    'modern': """:root{--font:"Source Sans 3","Source Sans Pro",Roboto,"Helvetica Neue",Arial,sans-serif;--fs:10pt;--name:30pt;
      --hs:13pt;--lh:1.3;--mt:.5in;--mx:.6in;--gap:11pt;--egap:6pt;--muted:#666;--accent:#DC3522}
      header{text-align:center} h1{font-weight:300;letter-spacing:.5px} h1 b{font-weight:700}
      .contact{color:#666;font-size:.92em} h2{font-weight:700;display:flex;align-items:center;gap:.4em}
      h2 .a{color:var(--accent)} h2::after{content:"";flex:1;border-bottom:.6pt solid #999}
      .meta,.row>:last-child{color:#666;font-style:italic} .org{color:#222}""",
    'banking': """:root{--font:"Helvetica Neue",Helvetica,Arial,sans-serif;--fs:10pt;--name:26pt;--hs:12pt;--lh:1.3;--mt:.5in;
      --mx:.6in;--gap:11pt;--egap:6pt;--muted:#555;--accent:#3873B3} header{text-align:center}
      h1{font-weight:400;color:#222} h2{color:var(--accent);font-weight:600;text-align:center;display:flex;align-items:center;gap:.6em}
      h2::before,h2::after{content:"";flex:1;border-bottom:.8pt solid var(--accent)} .org{color:#222}""",
    'finance': """:root{--font:"EB Garamond",Garamond,"Adobe Garamond Pro","Times New Roman",serif;--fs:11pt;--name:18pt;--hs:11pt;
      --lh:1.15;--mt:.45in;--mx:.55in;--gap:7pt;--egap:4pt;--muted:#000} header{text-align:center}
      h1{font-weight:700;letter-spacing:1px;text-transform:uppercase}
      h2{text-transform:uppercase;font-weight:700;border-bottom:.8pt solid #000;letter-spacing:.5px}""",
    'minimal': """:root{--font:Inter,"SF Pro Text",-apple-system,"Helvetica Neue",Arial,sans-serif;--fs:9.6pt;--name:22pt;--hs:8.6pt;
      --lh:1.38;--mt:.6in;--mx:.65in;--gap:13pt;--egap:7pt;--muted:#666} h1{font-weight:650;letter-spacing:-.3px}
      .contact{color:#555} h2{text-transform:uppercase;letter-spacing:.12em;color:#666;font-weight:600;
      border-bottom:1px solid #ddd;padding-bottom:3pt} .org{font-weight:600}""",
    'compact': """:root{--font:Charter,"Bitstream Charter","Source Serif 4","Source Serif Pro",Georgia,serif;--fs:9.8pt;--name:20pt;
      --hs:11pt;--lh:1.16;--mt:.4in;--mx:.45in;--gap:6pt;--egap:3pt;--muted:#333} header{text-align:center}
      h1{font-weight:700} h2{font-weight:700;margin-bottom:2pt}""",
    'accent': """:root{--font:Lato,"Helvetica Neue",Arial,sans-serif;--fs:9.9pt;--name:26pt;--hs:11.5pt;--lh:1.3;--mt:.5in;--mx:.6in;
      --gap:11pt;--egap:6pt;--muted:#555;--accent:#0E7C86} h1{color:var(--accent);font-weight:800;letter-spacing:-.2px}
      h2{border-left:3pt solid var(--accent);padding-left:6pt;font-weight:800;text-transform:uppercase;letter-spacing:.06em}
      .row>:last-child{color:#444}""",
}

SECTION_TITLES = {'education': 'Education', 'experience': 'Experience', 'projects': 'Projects', 'research': 'Research and Publications',
                  'leadership': 'Leadership and Activities', 'volunteering': 'Volunteer Experience', 'skills': 'Skills',
                  'certifications': 'Licenses and Certifications', 'awards': 'Awards and Honors'}


def md(s):
    s = html.escape(s or '', quote=False)
    s = re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)', r'<a href="\2">\1</a>', s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    return s.replace('--', '\u2013') if False else s


def dates(e):
    a, b = (e.get('start') or '').strip(), (e.get('end') or '').strip()
    return f'{a} \u2013 {b}' if a and b else (b or a)


def _heading(title, style):
    if style == 'modern':
        return f'<h2><span><span class="a">{html.escape(title[:3])}</span>{html.escape(title[3:])}</span></h2>'
    return f'<h2>{html.escape(title)}</h2>'


def build_html(r, style='classic', k=1.0, titles=None):
    style = style if style in STYLE_CSS else 'classic'  # 'latex' previews with the closest HTML look
    titles = {**SECTION_TITLES, **(r.get('titles') or {}), **(titles or {})}
    b = r.get('basics', {})
    name = html.escape(b.get('name', ''))
    if style == 'modern' and ' ' in name:
        first, last = name.rsplit(' ', 1)
        name = f'{first} <b>{last}</b>'
    contact = [b.get('phone'), b.get('email'), b.get('location')]
    items = [f'<span>{html.escape(c)}</span>' for c in contact if c]
    for l in b.get('links', []):
        label = l.get('label') or re.sub(r'^https?://(www\.)?', '', l.get('url', '')).rstrip('/')
        items.append(f'<span><a href="{html.escape(l.get("url", ""))}">{html.escape(label)}</a></span>')
    head = [f'<header><h1>{name}</h1>']
    if b.get('headline'):
        head.append('<div class="headline">' + ''.join(f'<span>{md(h)}</span>' for h in b['headline']) + '</div>')
    head.append(f'<div class="contact">{"".join(items)}</div></header>')
    out = []
    for sec in r.get('order') or list(SECTION_TITLES):
        data = r.get(sec)
        if not data:
            continue
        body = []
        if sec == 'education':
            for e in data:
                deg = degree_line(e)
                extra = '; '.join(x for x in (e.get('minor') and 'Minor in ' + e['minor'], e.get('gpa') and 'GPA: ' + e['gpa']) if x)
                body.append(f'<div class="entry"><div class="row"><span class="org">{html.escape(e.get("school", ""))}</span>'
                            f'<span>{html.escape(e.get("location", ""))}</span></div><div class="row"><span class="role">{html.escape(deg)}'
                            f'{("; " + html.escape(extra)) if extra else ""}</span><span class="meta">{html.escape(dates(e))}</span></div>')
                lines = []
                if e.get('coursework'):
                    lines.append('<b>Relevant coursework:</b> ' + html.escape(', '.join(e['coursework'])))
                if e.get('honors'):
                    lines.append(md(' \u00b7 '.join(e['honors'])))
                body += [f'<div>{l}</div>' for l in lines]
                body.append('</div>')
        elif sec in ('experience', 'leadership', 'volunteering'):
            for e in data:
                org = md(e.get('org', ''))
                if e.get('url'):
                    org = f'<a href="{html.escape(e["url"])}">{org}</a>'
                body.append(f'<div class="entry"><div class="row"><span class="org">{org}</span><span>{html.escape(dates(e))}</span></div>')
                if e.get('title') or e.get('location'):
                    body.append(f'<div class="row"><span class="role">{md(e.get("title", ""))}</span>'
                                f'<span class="meta">{html.escape(e.get("location", ""))}</span></div>')
                if e.get('bullets'):
                    body.append('<ul>' + ''.join(f'<li>{md(x)}</li>' for x in e['bullets']) + '</ul>')
                body.append('</div>')
        elif sec == 'projects':
            for p in data:
                nm = md(p.get('name', ''))
                if p.get('url'):
                    nm = f'<a href="{html.escape(p["url"])}">{nm}</a>'
                tag = ' | '.join(x for x in (md(p.get('tagline', '')), html.escape(', '.join(p.get('tech', [])))) if x)
                body.append(f'<div class="entry"><div class="row"><span><span class="org">{nm}</span>'
                            f'{(" <span class=tag>| " + tag + "</span>") if tag else ""}</span><span>{html.escape(p.get("date", ""))}</span></div>')
                if p.get('bullets'):
                    body.append('<ul>' + ''.join(f'<li>{md(x)}</li>' for x in p['bullets']) + '</ul>')
                body.append('</div>')
        elif sec == 'research':
            body.append('<ul>' + ''.join(
                f'<li>{md(p.get("role", "")) + ": " if p.get("role") else ""}'
                f'{("<a href=%s>%s</a>" % (html.escape(p["url"]), md(p.get("title", "")))) if p.get("url") else md(p.get("title", ""))}'
                f'{". <b>" + md(p["venue"]) + "</b>" if p.get("venue") else ""}</li>' for p in data) + '</ul>')
        elif sec == 'skills':
            body.append('<div class="skills">' + ''.join(
                f'<p><b>{html.escape(s.get("label", ""))}:</b> {html.escape(", ".join(s.get("items", [])))}</p>' for s in data) + '</div>')
        elif sec in ('awards', 'certifications'):
            body.append('<ul>' + ''.join(f'<li>{md(a if isinstance(a, str) else a.get("title", ""))}</li>' for a in data) + '</ul>')
        out.append(f'<section>{_heading(titles.get(sec, sec.title()), style)}{"".join(body)}</section>')
    css = BASE_CSS + STYLE_CSS[style]
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(b.get("name", "Resume"))}</title>'
            f'<style>{css}</style><style>:root{{--k:{k}}}</style></head><body><div class="page">'
            + ''.join(head) + ''.join(out) + '</div></body></html>')


def chrome():
    env = os.environ.get('JOB_APPLIER_CHROME') or os.environ.get('APPLYTWIN_CHROME')
    cands = [env] if env else []
    cands += ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
              '/Applications/Chromium.app/Contents/MacOS/Chromium',
              '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
              '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
              r'C:\Program Files\Google\Chrome\Application\chrome.exe',
              r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
              os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
              r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
              r'C:\Program Files\Microsoft\Edge\Application\msedge.exe']   # Edge ships with every Windows install
    cands += [shutil.which(x) for x in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome', 'msedge')]
    for c in cands:
        if c and os.path.exists(c):
            return c
    raise RuntimeError('No Chrome/Chromium/Edge found. Install Chrome or set JOB_APPLIER_CHROME=/path/to/chrome')


def html_to_pdf(doc, out_pdf):
    os.makedirs(os.path.dirname(os.path.abspath(out_pdf)), exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, 'resume.html')
        with open(src, 'w', encoding='utf-8') as f:
            f.write(doc)
        # --use-mock-keychain / --password-store=basic: a fresh Chrome profile otherwise asks the macOS keychain (or the
        # Linux keyring) for its password store on every launch, which pops "A keychain cannot be found" over and over
        cmd = [chrome(), '--headless=new', '--disable-gpu', '--no-sandbox', '--no-pdf-header-footer', '--use-mock-keychain',
               '--password-store=basic', '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-sync',
               '--print-to-pdf-no-header', f'--user-data-dir={td}/profile', f'--print-to-pdf={out_pdf}', pathlib.Path(src).as_uri()]   # file:///C:/... on Windows too
        subprocess.run(cmd, capture_output=True, timeout=90)
    if not os.path.exists(out_pdf):
        raise RuntimeError('Chrome did not produce a PDF')
    return out_pdf


def page_count(pdf):
    try:   # reads compressed PDFs too (LaTeX output hides its page objects from a plain text search)
        from pypdf import PdfReader
        return len(PdfReader(pdf).pages) or 1
    except Exception:
        data = open(pdf, 'rb').read()
        return len(re.findall(rb'/Type\s*/Page(?![s\w])', data)) or 1


def pdf_text(pdf):
    try:
        from pypdf import PdfReader
        return '\n'.join(p.extract_text() or '' for p in PdfReader(pdf).pages)
    except Exception:
        return None


def render(r, style, out_pdf, one_page=True, worth=None):
    """Render, shrinking type a little and then trimming the lowest-priority lines until it fits one page. worth(text) scores
    a bullet for this job (higher = keep); without it, bullets are trimmed from the end of each list."""
    import copy
    r = copy.deepcopy(r)
    dropped = []
    if style == 'latex':
        from . import latex
        try:
            return _fit(r, out_pdf, one_page, dropped, lambda rr, k: latex.compile_tex(latex.build_tex(rr, k), out_pdf), (1.0, .96, .92), worth)
        except RuntimeError:
            style = 'classic'
    # keep the type readable: shrink only a little, then cut the weakest lines; go smaller only if cutting runs out
    for k in (1.0, .97, .95):
        html_to_pdf(build_html(r, style, k), out_pdf)
        n = page_count(out_pdf)
        if n == 1 or not one_page:
            return {"pdf": out_pdf, "pages": n, "scale": k, "dropped": dropped, "resume": r}
    for k, budget in ((.95, 12), (.92, 12), (.9, 30)):
        for _ in range(budget):
            victim = _drop_one(r, worth)
            if not victim:
                break
            dropped.append(victim)
            html_to_pdf(build_html(r, style, k), out_pdf)
            if page_count(out_pdf) == 1:
                return {"pdf": out_pdf, "pages": 1, "scale": k, "dropped": dropped, "resume": r}
    return {"pdf": out_pdf, "pages": page_count(out_pdf), "scale": .9, "dropped": dropped, "resume": r}


def fits(r, style, k, out_pdf):
    """Would this resume fit on one page at type scale k? (k above 1 asks whether there's room to spare.)"""
    html_to_pdf(build_html(r, style, k), out_pdf)
    return page_count(out_pdf) == 1


def _fit(r, out_pdf, one_page, dropped, make, steps, worth=None):
    for k in steps:
        make(r, k)
        n = page_count(out_pdf)
        if n == 1 or not one_page:
            return {"pdf": out_pdf, "pages": n, "scale": k, "dropped": dropped, "resume": r}
    for _ in range(30):
        v = _drop_one(r, worth)
        if not v:
            break
        dropped.append(v)
        make(r, steps[-1])
        if page_count(out_pdf) == 1:
            return {"pdf": out_pdf, "pages": 1, "scale": steps[-1], "dropped": dropped, "resume": r}
    return {"pdf": out_pdf, "pages": page_count(out_pdf), "scale": steps[-1], "dropped": dropped, "resume": r}


def _drop_one(r, worth=None):
    """Cut the least valuable line first. Entries arrive most-relevant first (the tailor orders them), so we
    trim from the end of each section, in this order: extra bullets on later entries, then the least relevant
    whole roles/projects/skill lines, and only as a last resort papers or the top entries."""
    def bullet(sec, keep, start=0):
        items = r.get(sec) or []
        if worth:   # the least relevant bullet for this job, across every entry that can spare one
            cands = [(worth(b), idx, bi) for idx in range(start, len(items)) if len(items[idx].get('bullets', [])) > keep
                     for bi, b in enumerate(items[idx]['bullets'])]
            if cands:
                _, idx, bi = min(cands)
                return f"{sec}: {ats_plain(items[idx]['bullets'].pop(bi))[:60]}"
            return None
        for idx in range(len(items) - 1, start - 1, -1):
            if len(items[idx].get('bullets', [])) > keep:
                return f"{sec}: {ats_plain(items[idx]['bullets'].pop())[:60]}"

    def entry(sec, floor):
        items = r.get(sec) or []
        if len(items) > floor:
            x = items.pop()
            return f"{sec}: {ats_plain(x if isinstance(x, str) else x.get('name') or x.get('org') or x.get('title') or x.get('label', ''))[:60]}"

    plan = [lambda: entry('volunteering', 1), lambda: bullet('volunteering', 1), lambda: bullet('projects', 2), lambda: bullet('leadership', 1), lambda: bullet('experience', 2, 2),
            lambda: entry('leadership', 1), lambda: entry('experience', 5), lambda: bullet('projects', 1, 2),
            lambda: entry('projects', 4), lambda: entry('skills', 4), lambda: bullet('experience', 1, 3),
            lambda: entry('experience', 4), lambda: entry('awards', 1), lambda: entry('research', 3),
            lambda: entry('projects', 3), lambda: bullet('projects', 1), lambda: entry('leadership', 0),
            lambda: bullet('experience', 2), lambda: entry('skills', 3),
            lambda: entry('experience', 3), lambda: entry('projects', 2), lambda: bullet('experience', 1),
            lambda: entry('research', 2)]   # publications are among a student's strongest lines: cut them last
    for step in plan:
        v = step()
        if v:
            return v
    return None


def ats_plain(s):
    from .ats import plain
    return plain(s)
