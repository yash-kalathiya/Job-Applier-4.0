"""How Job Applier 4.0 adapts to each user.

1. Field rules: what the ideal resume looks like differs by field (section order, template, what to emphasize).
2. Preferences the user states once ("always include my Habitat for Humanity work", "never use the Modern
   template", "keep it formal") are stored and applied to every tailored resume.
3. Outcomes: when the user marks applications as Interview / Offer / Rejected, Job Applier 4.0 learns which templates,
   fields and vault bullets actually got them interviews, and leans on those next time.
"""
import collections
import json
import os
import re

from . import store

FIELD_RULES = {
    'software': {"match": r'software|swe|sde|developer|backend|frontend|full.?stack|mobile|devops|platform|infrastructure|web',
                 "template": "classic", "order": ["education", "experience", "projects", "skills", "research", "leadership", "awards"],
                 "emphasize": "shipped systems, scale (users, requests, latency), languages and frameworks named inside bullets, GitHub/live links, hackathon wins"},
    'ml': {"match": r'machine learning|\bml\b|\bai\b|deep learning|llm|computer vision|nlp|applied scien|research engineer',
           "template": "classic", "order": ["education", "experience", "research", "projects", "skills", "awards", "leadership"],
           "emphasize": "models trained, dataset and compute scale, metrics moved, papers and venues, frameworks (PyTorch etc.)"},
    'quant': {"match": r'quant|trading|trader|strats|market making',
              "template": "classic", "order": ["education", "experience", "projects", "awards", "skills", "research", "leadership"],
              "emphasize": "math/CS competitions and rankings, probability and statistics, performance work in C++/Python, honest backtest results, GPA and test scores"},
    'data': {"match": r'data scien|data analy|analytics|business intelligence|data engineer',
             "template": "accent", "order": ["education", "experience", "projects", "skills", "research", "leadership", "awards"],
             "emphasize": "business questions answered, decisions changed, dataset size, SQL/Python/BI tools, experiments run"},
    'hardware': {"match": r'hardware|electrical|embedded|firmware|fpga|asic|robot|mechatronic|controls|mechanical|aerospace|manufactur',
                 "template": "compact", "order": ["education", "experience", "projects", "skills", "research", "awards", "leadership"],
                 "emphasize": "what was built and tested, hardware platforms, measured results, tools (CAD, Altium, oscilloscopes, ROS), competitions"},
    'finance': {"match": r'investment bank|banking|private equity|asset management|wealth|equity research|capital markets|corporate finance|accounting|audit|'
                         r'summer analyst|global markets|sales (?:&|and) trading|\bm&a\b|leveraged finance|restructuring|treasury|fp&a|fixed income|'
                         r'\btax\b|actuar|underwriting|real estate|private credit|venture capital',
                "template": "finance", "order": ["education", "experience", "leadership", "skills", "awards", "projects", "research"],
                "emphasize": "GPA and test scores, deals/valuation/modeling work, Excel and financial modeling, leadership, an 'Additional' skills and interests line"},
    'consulting': {"match": r'consult|strategy|advisory', "template": "harvard",
                   "order": ["education", "experience", "leadership", "awards", "skills", "projects", "research"],
                   "emphasize": "problem solved, recommendation made, measurable impact, leadership and teamwork, structured thinking"},
    'product': {"match": r'product manag|product owner|\bpm\b|technical program', "template": "minimal",
                "order": ["education", "experience", "projects", "leadership", "skills", "awards", "research"],
                "emphasize": "products shipped, user metrics, decisions and tradeoffs, cross-functional leadership"},
    'built': {"match": r'architect|civil|structural|construction|urban plan|landscape|interior design|transportation engineer|geotech',
              "template": "compact", "order": ["education", "experience", "projects", "skills", "awards", "leadership", "research"],
              "emphasize": "a portfolio link, projects with scope (square feet, budget, site), software (AutoCAD, Revit, Rhino, Civil 3D), site work, EIT/FE progress"},
    'design': {"match": r'design|ux|ui|graphic|visual|creative|illustrat|motion', "template": "minimal",
               "order": ["education", "experience", "projects", "skills", "awards", "leadership", "research"],
               "emphasize": "a portfolio link at the top, projects with outcomes, tools (Figma, Adobe), user research and iteration"},
    'marketing': {"match": r'marketing|brand|social media|content|growth|communications|public relations|seo',
                  "template": "modern", "order": ["education", "experience", "projects", "leadership", "skills", "awards", "research"],
                  "emphasize": "campaign results (reach, engagement, conversion, followers), channels and tools, content produced"},
    'science': {"match": r'research (?:intern|assistant)|\blab\b|laborator|biolog|biotech|chemist|molecular|genetic|neuroscien|microbio|life science|materials scien|physics',
                "template": "harvard", "order": ["education", "research", "experience", "skills", "awards", "leadership", "volunteering"],
                "emphasize": "lab techniques and instruments by name (PCR, HPLC, cell culture, microscopy), research questions and findings, posters and papers, data analysis (R, Python, GraphPad)"},
    'healthcare': {"match": r'health|clinical|nurs|medical|medicine|veterinar|patient|pharm|hospital|dental|biolog|biotech|lab',
                   "template": "harvard", "order": ["education", "certifications", "experience", "research", "volunteering", "skills", "awards", "leadership"],
                   "emphasize": "clinical hours and settings, certifications and licenses (CPR/BLS, CNA, EMT), research and lab techniques, patient-facing service"},
    'policy': {"match": r'policy|government|public affairs|legislat|advocacy|nonprofit|non-profit|social impact|ngo',
               "template": "harvard", "order": ["education", "experience", "leadership", "research", "volunteering", "skills", "awards"],
               "emphasize": "research and writing, community impact, organizing and advocacy, languages, quantitative analysis (Stata, R, GIS)"},
    'education': {"match": r'teach|tutor|education|curriculum|instruct', "template": "harvard",
                  "order": ["education", "experience", "volunteering", "leadership", "certifications", "skills", "awards"],
                  "emphasize": "students taught, outcomes, curriculum built, certifications, languages"},
    'legal': {"match": r'legal|\blaw\b|paralegal|compliance|litigation|counsel|pre-law|judicial', "template": "harvard",
              "order": ["education", "experience", "leadership", "research", "awards", "skills", "volunteering"],
              "emphasize": "research and writing, analysis of rules or cases, attention to detail, GPA and honors, leadership, languages"},
    'media': {"match": r'journalis|reporter|editorial|newsroom|\beditor\b|broadcast|film|video|production|entertainment|podcast|animation|publishing',
              "template": "modern", "order": ["education", "experience", "projects", "skills", "awards", "leadership", "research"],
              "emphasize": "a portfolio or clips link at the top, published work and where it ran, audience reached, tools (Premiere, Final Cut, Adobe, CMS)"},
    'sales': {"match": r'\bsales\b|business development|account executive|account manag|partnerships|customer success', "template": "modern",
              "order": ["education", "experience", "leadership", "skills", "awards", "projects", "research"],
              "emphasize": "revenue or quota numbers, accounts or customers handled, outreach volume, persuasion and relationships, CRM tools (Salesforce, HubSpot)"},
    'operations': {"match": r'operations|supply chain|logistics|procurement|sourcing|inventory|distribution|project manag|program coordinat',
                   "template": "classic", "order": ["education", "experience", "projects", "skills", "leadership", "awards", "research"],
                   "emphasize": "processes improved and by how much (time, cost, error rate), scale handled, Excel/SQL/ERP tools, coordination across teams"},
    'people': {"match": r'human resources|\bhr\b|people (?:ops|operations|partner)|recruit|talent acquisition|learning and development', "template": "modern",
               "order": ["education", "experience", "leadership", "skills", "volunteering", "awards", "projects"],
               "emphasize": "people supported, programs run, hiring or onboarding numbers, communication, HRIS tools (Workday, Greenhouse)"},
    'general': {"match": r'.', "template": "classic", "order": ["education", "experience", "projects", "leadership", "skills", "awards", "research"],
                "emphasize": "the posting's top requirements, measurable results, and transferable skills"},
}


def field_for(job):
    t = f"{job.get('title', '')}"
    for name, rule in FIELD_RULES.items():
        if name != 'general' and re.search(rule['match'], t, re.I):
            return name
    head = (job.get('description') or '')[:600]
    for name, rule in FIELD_RULES.items():
        if name != 'general' and re.search(rule['match'], head, re.I):
            return name
    return 'general'


# ------------------------------------------------------------------ preferences

DEFAULT = {"notes": [], "pins": [], "avoid": [], "template_by_field": {}}


def prefs():
    return store.load('learnings.json', DEFAULT)


def remember(note=None, pin=None, avoid=None, template_field=None, template=None):
    p = prefs()
    if note and note not in p['notes']:
        p['notes'].append(note)
    if pin and pin not in p['pins']:
        p['pins'].append(pin)
        p['avoid'] = [x for x in p['avoid'] if x != pin]
    if avoid and avoid not in p['avoid']:
        p['avoid'].append(avoid)
        p['pins'] = [x for x in p['pins'] if x != avoid]
    if template_field and template:
        p['template_by_field'][template_field] = template
    store.save('learnings.json', p)
    return p


def forget(note=None, pin=None, avoid=None):
    p = prefs()
    p['notes'] = [n for n in p['notes'] if n != note]
    p['pins'] = [n for n in p['pins'] if n != pin]
    p['avoid'] = [n for n in p['avoid'] if n != avoid]
    store.save('learnings.json', p)
    return p


# ------------------------------------------------------------------ outcomes

GOOD = {'interview', 'offer', 'oa', 'phone screen', 'final round'}


def outcomes():
    """What actually worked: interview rate by field and template, and bullets that appear in winning resumes."""
    apps = store.rows("select job_id, status, resume_path from applications")
    latest = {}
    for a in apps:
        latest[a['job_id']] = a
    stats = collections.defaultdict(lambda: [0, 0])
    tpl_stats = collections.defaultdict(lambda: [0, 0])
    bullet_wins = collections.Counter()
    for jid, a in latest.items():
        st = (a['status'] or '').lower()
        sent = st in GOOD or st in ('applied', 'rejected')
        if not sent:
            continue
        j = (store.rows('select title, description from jobs where id=?', (jid,)) or [{}])[0]
        f = field_for(j)
        won = st in GOOD
        stats[f][0] += won
        stats[f][1] += 1
        tj = store.path('resumes', jid, 'tailor.json')
        if os.path.exists(tj):
            d = json.load(open(tj, encoding='utf-8'))
            tpl = d.get('render', {}).get('style') or d.get('style') or 'unknown'
            tpl_stats[tpl][0] += won
            tpl_stats[tpl][1] += 1
            if won:
                for sec in ('experience', 'projects', 'leadership'):
                    for e in d.get('resume', {}).get(sec, []):
                        for b in e.get('bullets', []):
                            bullet_wins[b] += 1
    return {"by_field": {k: {"interviews": v[0], "sent": v[1]} for k, v in stats.items()},
            "by_template": {k: {"interviews": v[0], "sent": v[1]} for k, v in tpl_stats.items()},
            "winning_bullets": [b for b, _ in bullet_wins.most_common(15)]}


def best_template(field):
    p = prefs()
    if p['template_by_field'].get(field):
        return p['template_by_field'][field]
    o = outcomes()['by_template']
    ranked = sorted(((v['interviews'] / v['sent'], k) for k, v in o.items() if v['sent'] >= 8), reverse=True)
    return ranked[0][1] if ranked and ranked[0][0] > 0 else FIELD_RULES[field]['template']


def context_for(job):
    """Everything the tailor needs to know about this user beyond their vault."""
    f = field_for(job)
    p = prefs()
    o = outcomes()
    return {"field": f, "rules": FIELD_RULES[f], "template": best_template(f), "notes": p['notes'], "pins": p['pins'],
            "avoid": p['avoid'], "winning_bullets": o['winning_bullets'], "history": o['by_field'].get(f)}
