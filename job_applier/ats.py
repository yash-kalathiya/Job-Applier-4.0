"""ATS engine: keyword extraction from a posting, resume-vs-posting match score, and a resume lint.

What real ATSes do (Greenhouse, Lever, Workday, iCIMS, Ashby...): parse the file into fields, let recruiters
filter on knockout questions, then search/rank by keywords. Nobody "auto-rejects for formatting", but a resume
that parses badly or lacks the posting's hard-skill terms sinks in the recruiter's search results. So we:
  1. keep every template single-column, real text, standard headings (parses cleanly everywhere)
  2. measure hard-skill coverage of the posting, weighted toward the requirements section
  3. lint for the things recruiters actually skim for (quantified impact, action verbs, length, contact line)
"""
import re
from collections import Counter

# canonical term -> aliases (lowercase). Matching is whole-word, case-insensitive.
LEXICON = {
    # languages
    'Python': ['python', 'python3'], 'Java': ['java'], 'C++': ['c++', 'cpp'], 'C': [r'\bc\b(?![+#])'],
    'C#': ['c#', 'csharp'], 'Go': ['golang', r'\bgo\b(?= |,|\))'], 'Rust': ['rust'], 'JavaScript': ['javascript', r'\bjs\b'],
    'TypeScript': ['typescript', r'\bts\b'], 'Kotlin': ['kotlin'], 'Swift': ['swift'], 'Scala': ['scala'],
    'Ruby': ['ruby'], 'PHP': ['php'], 'R': [r'\br\b(?= |,|\))'], 'MATLAB': ['matlab'], 'Julia': ['julia'],
    'SQL': ['sql'], 'Bash': ['bash', 'shell scripting'], 'Haskell': ['haskell'], 'OCaml': ['ocaml'],
    'Verilog': ['verilog'], 'SystemVerilog': ['systemverilog'], 'VHDL': ['vhdl'], 'Assembly': ['assembly'],
    'Solidity': ['solidity'], 'Lua': ['lua'], 'Dart': ['dart'], 'Objective-C': ['objective-c'], 'Perl': ['perl'],
    'HTML': ['html'], 'CSS': ['css'], 'LaTeX': ['latex'], 'Elixir': ['elixir'], 'Zig': ['zig'],
    # web / app frameworks
    'React': ['react', 'react.js', 'reactjs'], 'React Native': ['react native'], 'Next.js': ['next.js', 'nextjs'],
    'Vue': ['vue', 'vue.js'], 'Angular': ['angular'], 'Svelte': ['svelte'], 'Node.js': ['node.js', 'nodejs', r'\bnode\b'],
    'Express': ['express.js', 'expressjs'], 'Django': ['django'], 'Flask': ['flask'], 'FastAPI': ['fastapi'],
    'Spring': ['spring boot', 'spring'], 'Rails': ['rails', 'ruby on rails'], '.NET': ['.net', 'asp.net'],
    'GraphQL': ['graphql'], 'REST APIs': ['rest', 'restful', 'rest api'], 'gRPC': ['grpc'], 'WebSockets': ['websocket'],
    'SwiftUI': ['swiftui'], 'Flutter': ['flutter'], 'Electron': ['electron'], 'Tauri': ['tauri'], 'Tailwind': ['tailwind'],
    'iOS': ['ios'], 'Android': ['android'],
    # data / ml
    'PyTorch': ['pytorch', 'torch'], 'TensorFlow': ['tensorflow'], 'JAX': ['jax'], 'Keras': ['keras'],
    'scikit-learn': ['scikit-learn', 'sklearn'], 'NumPy': ['numpy'], 'pandas': ['pandas'], 'SciPy': ['scipy'],
    'Spark': ['spark', 'pyspark'], 'Hadoop': ['hadoop'], 'Kafka': ['kafka'], 'Airflow': ['airflow'], 'dbt': ['dbt'],
    'Snowflake': ['snowflake'], 'BigQuery': ['bigquery'], 'Databricks': ['databricks'], 'Tableau': ['tableau'],
    'Power BI': ['power bi'], 'Excel': ['excel'], 'Machine Learning': ['machine learning', r'\bml\b'],
    'Deep Learning': ['deep learning', 'neural network'], 'LLMs': ['llm', 'large language model', 'gpt', 'transformer'],
    'NLP': ['nlp', 'natural language'], 'Computer Vision': ['computer vision', r'\bcv\b(?= |,)', 'image processing'],
    'Reinforcement Learning': ['reinforcement learning', r'\brl\b'], 'CUDA': ['cuda'], 'OpenCV': ['opencv'],
    'Hugging Face': ['hugging face', 'huggingface'], 'RAG': ['rag', 'retrieval-augmented'], 'MLOps': ['mlops'],
    'Statistics': ['statistic', 'probability', 'hypothesis test', 'regression'], 'A/B Testing': ['a/b test', 'experimentation'],
    'Data Analysis': ['data analysis', 'data analytics'], 'ETL': ['etl', 'data pipeline'], 'ONNX': ['onnx'],
    'Triton': ['triton'], 'Distributed Training': ['distributed training'], 'Inference': ['inference'],
    # infra / tools
    'AWS': ['aws', 'amazon web services', r'\bec2\b', r'\bs3\b', 'lambda'], 'GCP': ['gcp', 'google cloud'],
    'Azure': ['azure'], 'Docker': ['docker', 'container'], 'Kubernetes': ['kubernetes', 'k8s'], 'Terraform': ['terraform'],
    'Linux': ['linux', 'unix', 'ubuntu'], 'Git': ['git', 'github', 'gitlab', 'version control'], 'CI/CD': ['ci/cd', r'\bci\b',
    'continuous integration', 'continuous delivery', 'github actions', 'jenkins'], 'PostgreSQL': ['postgres', 'postgresql'],
    'MySQL': ['mysql'], 'MongoDB': ['mongodb', 'mongo'], 'Redis': ['redis'], 'Elasticsearch': ['elasticsearch'],
    'DynamoDB': ['dynamodb'], 'Firebase': ['firebase'], 'Supabase': ['supabase'], 'Microservices': ['microservice'],
    'Distributed Systems': ['distributed system'], 'Cloud': ['cloud'], 'Networking': ['networking', 'tcp/ip', 'tcp', 'udp'],
    'Observability': ['observability', 'monitoring', 'prometheus', 'grafana', 'datadog'], 'Jira': ['jira'],
    'Agile': ['agile', 'scrum'], 'Testing': ['unit test', 'testing', 'test automation', 'pytest', 'jest', 'selenium'],
    'Debugging': ['debug'], 'Code Review': ['code review'], 'Security': ['security', 'cybersecurity'],
    # cs fundamentals
    'Data Structures': ['data structure'], 'Algorithms': ['algorithm'], 'Object-Oriented Programming': ['object-oriented',
    'object oriented', r'\boop\b'], 'Operating Systems': ['operating system'], 'Concurrency': ['concurren', 'multithread',
    'parallel'], 'Compilers': ['compiler'], 'Databases': ['database'], 'System Design': ['system design'],
    'Low Latency': ['low latency', 'low-latency', 'high performance', 'high-performance'], 'APIs': ['api'],
    # hardware / robotics
    'Embedded Systems': ['embedded'], 'Firmware': ['firmware'], 'FPGA': ['fpga'], 'RTOS': ['rtos'], 'Microcontrollers':
    ['microcontroller', r'\bmcu\b', 'arduino', 'stm32', 'esp32'], 'PCB Design': ['pcb', 'altium', 'kicad'],
    'ROS': ['ros', 'ros2'], 'SLAM': ['slam'], 'Controls': ['control system', 'controls', r'\bpid\b', 'mpc'],
    'Robotics': ['robotic'], 'Sensor Fusion': ['sensor fusion', 'kalman'], 'CAD': ['cad', 'solidworks', 'fusion 360', 'onshape'],
    'Simulation': ['simulation', 'gazebo', 'mujoco', 'isaac sim'], 'Signal Processing': ['signal processing', r'\bdsp\b'],
    'Circuit Design': ['circuit'], 'Oscilloscope': ['oscilloscope'],
    # quant / finance
    'Quantitative Research': ['quantitative research', 'quant research'], 'Trading': ['trading'], 'Backtesting': ['backtest'],
    'Derivatives': ['derivative', 'options'], 'Financial Modeling': ['financial model', r'\bdcf\b', 'valuation'],
    'Accounting': ['accounting', 'gaap'], 'Bloomberg': ['bloomberg terminal', 'bloomberg'], 'Market Making': ['market making'],
    'Risk': ['risk management', 'risk model'], 'Portfolio': ['portfolio'], 'Econometrics': ['econometric'],
    'Stochastic Calculus': ['stochastic'], 'Time Series': ['time series', 'time-series'],
    # business / general (any field)
    'Project Management': ['project management', 'project manager'], 'Salesforce': ['salesforce'], 'HubSpot': ['hubspot'],
    'CRM': ['crm'], 'SEO': ['seo', 'search engine optimization'], 'Google Analytics': ['google analytics'],
    'Social Media': ['social media', 'instagram', 'tiktok'], 'Content Creation': ['content creation', 'copywriting'],
    'Adobe Creative Suite': ['adobe', 'photoshop', 'illustrator', 'indesign', 'premiere'], 'Figma': ['figma'],
    'Canva': ['canva'], 'User Research': ['user research', 'usability'], 'Prototyping': ['prototyp', 'wireframe'],
    'Microsoft Office': ['microsoft office', 'powerpoint', 'microsoft word', 'ms word'], 'Google Workspace': ['google workspace', 'google sheets'],
    'Public Speaking': ['public speaking'], 'Writing': ['technical writing', 'copywriting', 'copyedit', 'proofread', 'writing skills'],
    'Research': ['research methods', 'literature review', 'qualitative research', 'quantitative methods'], 'Grant Writing': ['grant writing', 'grants'], 'Fundraising': ['fundrais'],
    'Event Planning': ['event planning', 'event coordination'], 'Customer Service': ['customer service', 'client service'],
    'Data Entry': ['data entry'], 'Budgeting': ['budget'], 'QuickBooks': ['quickbooks'], 'SPSS': ['spss'],
    'Stata': ['stata'], 'GIS': [r'\bgis\b', 'arcgis', 'qgis'], 'Lab Techniques': ['pcr', 'cell culture', 'western blot', 'assay'],
    'Patient Care': ['patient care', 'vital signs', 'emr', 'epic'], 'CPR': ['cpr', 'bls'], 'Spanish': ['spanish', 'bilingual'],
    'Teaching': ['teaching', 'tutoring', 'lesson plan'], 'Policy Analysis': ['policy analysis', 'policy research'],
    'Supply Chain': ['supply chain', 'logistics', 'inventory'], 'Six Sigma': ['six sigma', 'lean'],
    # product / soft (lower weight)
    'Communication': ['communicat'], 'Collaboration': ['collaborat', 'cross-functional', 'teamwork'],
    'Problem Solving': ['problem-solving', 'problem solving'], 'Leadership': ['leadership', r'\bled\b'],
    'Ownership': ['ownership', 'self-starter', 'autonom'], 'Product Sense': ['product sense', 'user empathy'],
}
SOFT = {'Communication', 'Collaboration', 'Problem Solving', 'Leadership', 'Ownership', 'Product Sense', 'APIs', 'Cloud',
        'Debugging', 'Security', 'Inference', 'Testing'}

ACTION_VERBS = set('''accelerated achieved architected automated benchmarked boosted built championed coded collaborated
compiled composed configured created cut debugged decreased delivered deployed designed developed devised diagnosed
directed doubled drove eliminated engineered established evaluated executed expanded founded generated grew halved
implemented improved increased integrated introduced launched led maintained managed mentored migrated modeled optimized
orchestrated organized overhauled partnered piloted pioneered planned presented profiled programmed prototyped published
raised rebuilt reduced refactored researched resolved restructured revamped scaled secured selected shipped simplified
spearheaded streamlined supervised taught tested traced trained transformed tripled tuned unified upgraded validated
won wrote analyzed authored captained co-founded competed contributed coordinated curated drafted earned facilitated
forecasted identified investigated measured negotiated operated performed produced proposed quantified ranked recruited
served simulated sourced structured studied surveyed synthesized visualized'''.split())
WEAK = ['responsible for', 'duties included', 'worked on', 'helped with', 'assisted with', 'participated in', 'various',
        'etc', 'hard worker', 'team player', 'detail-oriented', 'go-getter', 'synergy', 'utilized']
PRONOUNS = re.compile(r'\b(i|me|my|we|our)\b', re.I)
STD_HEADINGS = {'education', 'experience', 'work experience', 'professional experience', 'projects', 'skills',
                'technical skills', 'research', 'publications', 'leadership', 'activities', 'awards', 'honors',
                'research and publications', 'projects and competitions', 'leadership and activities',
                'certifications', 'volunteering', 'coursework', 'summary'}
REQ_HDR = re.compile(r'(requirements|qualifications|what you.ll need|what we.re looking for|you have|you bring|'
                     r'minimum|basic|must have|preferred|nice to have|bonus|skills)', re.I)


# word stems that should match any ending ("prototyp" -> prototyping, prototypes; "autonom" -> autonomy, autonomous)
STEMS = {'autonom', 'collaborat', 'communicat', 'concurren', 'copyedit', 'econometric', 'fundrais', 'multithread', 'prototyp',
         'statistic', 'backtest', 'microservice', 'algorithm', 'derivative', 'circuit', 'database', 'robotic', 'websocket',
         'debug', 'budget', 'proofread', 'container', 'optimiz', 'optimis', 'simulat', 'automat', 'visualiz', 'forecast'}


def _compiled():
    out = {}
    for canon, aliases in LEXICON.items():
        parts = []
        for a in aliases:
            if a.startswith('\\b'):
                parts.append(a)
                continue
            # every term also matches its plural ("distributed systems", "REST APIs", "LLMs"); stems match any ending
            tail = '[a-z]*' if a in STEMS else (r"(?:e?s|'s)?" if a[-1:].isalpha() else '')
            parts.append(r'(?<![a-z0-9])' + re.escape(a) + tail + r'(?![a-z0-9])')
        out[canon] = re.compile('|'.join(parts), re.I)
    return out


PATTERNS = _compiled()


def plain(md):
    s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', md or '')
    return s.replace('**', '').replace('__', '')


def resume_text(r):
    parts = [' '.join(r.get('basics', {}).get('headline', []))]
    for e in r.get('education', []):
        parts += [e.get('school', ''), e.get('degree', ''), e.get('major', ''), ' '.join(e.get('coursework', [])),
                  ' '.join(e.get('honors', []))]
    for sec in ('experience', 'projects', 'leadership', 'volunteering'):
        for e in r.get(sec, []):
            parts += [e.get('title', ''), e.get('org', ''), e.get('name', ''), e.get('tagline', ''),
                      ' '.join(e.get('tech', []))] + e.get('bullets', [])
    for p in r.get('research', []):
        parts += [p.get('title', ''), p.get('venue', '')]
    for s in r.get('skills', []):
        parts.append(s.get('label', '') + ': ' + ', '.join(s.get('items', [])))
    parts += [a if isinstance(a, str) else a.get('title', '') for a in r.get('awards', []) + r.get('certifications', [])]
    return plain('\n'.join(p for p in parts if p))


def requirement_text(jd):
    """The part of the posting under requirements/qualifications headers (weighted 2x)."""
    out, on = [], False
    for line in jd.splitlines():
        if len(line) < 60 and REQ_HDR.search(line):
            on = True
        elif len(line) < 40 and re.match(r'^[A-Z][A-Za-z &]+:?$', line.strip()) and not REQ_HDR.search(line):
            on = False
        if on:
            out.append(line)
    return '\n'.join(out)


def keywords(jd):
    """[(term, weight, count)] sorted by importance."""
    req = requirement_text(jd)
    res = []
    for canon, pat in PATTERNS.items():
        n = len(pat.findall(jd))
        if not n:
            continue
        w = 1.0 + min(n, 4) * 0.5 + (2.0 if pat.search(req) else 0)
        if canon in SOFT:
            w *= 0.35
        res.append((canon, round(w, 2), n))
    return sorted(res, key=lambda x: -x[1])


def match(resume, jd):
    rt = resume_text(resume)
    kws = keywords(jd)
    have, miss = [], []
    for term, w, n in kws:
        (have if PATTERNS[term].search(rt) else miss).append({"term": term, "weight": w, "hard": term not in SOFT})
    tot = sum(k['weight'] for k in have + miss) or 1
    cov = sum(k['weight'] for k in have) / tot
    title_words = set()
    return {"coverage": round(cov * 100), "matched": have, "missing": miss, "terms": len(kws)}


def lint(resume, pages=None, pdf_text=None):
    """Checks recruiters and parsers care about. Each: {id, level: pass|warn|fail, msg}."""
    out = []

    def add(i, ok, msg, warn=False):
        out.append({"id": i, "level": 'pass' if ok else ('warn' if warn else 'fail'), "msg": msg})

    b = resume.get('basics', {})
    links = ' '.join(l.get('url', '') for l in b.get('links', []))
    add('contact', bool(b.get('email')) and bool(b.get('phone')), 'Email and phone in the header')
    add('linkedin', 'linkedin.com' in links, 'LinkedIn URL in the header', warn=True)
    add('github', any(x in links for x in ('github.com', 'gitlab.com')) or not _is_tech(resume),
        'GitHub or portfolio link (tech roles)', warn=True)
    edu = resume.get('education', [])
    add('education', bool(edu) and all(e.get('end') for e in edu), 'Education with an expected graduation date')
    bullets = [x for sec in ('experience', 'projects', 'leadership', 'volunteering') for e in resume.get(sec, []) for x in e.get('bullets', [])]
    bp = [plain(x) for x in bullets]
    if bp:
        quant = sum(bool(re.search(r'\d', x)) for x in bp) / len(bp)
        add('quantified', quant >= 0.5, f'{round(quant * 100)}% of bullets have a number (aim for 50%+: users, %, ms, $, rank)',
            warn=quant >= 0.3)
        verbs = sum((x.split() or [''])[0].lower().strip(',:;') in ACTION_VERBS for x in bp) / len(bp)
        add('verbs', verbs >= 0.7, f'{round(verbs * 100)}% of bullets start with a strong action verb (aim 70%+)', warn=verbs >= 0.5)
        long_ = [x for x in bp if len(x) > 230]
        short = [x for x in bp if len(x) < 45]
        add('length', not long_, f'{len(long_)} bullet(s) over ~2 lines; split or tighten them', warn=len(long_) <= 2)
        add('substance', not short, f'{len(short)} bullet(s) too thin to show impact', warn=True)
        weak = [w for w in WEAK if any(w in x.lower() for x in bp)]
        add('weak', not weak, 'No filler phrases' + (f' (found: {", ".join(weak)})' if weak else ''), warn=True)
        pro = [x for x in bp if PRONOUNS.search(x)]
        add('pronouns', not pro, 'No first-person pronouns in bullets', warn=True)
        dup = [w for w, c in Counter((x.split() or [''])[0].lower() for x in bp).items() if c >= 4]
        add('variety', not dup, 'Varied opening verbs' + (f' ("{dup[0]}" starts 4+ bullets)' if dup else ''), warn=True)
    else:
        add('bullets', False, 'Add experience or project bullets')
    add('skills', bool(resume.get('skills')), 'A skills section (ATS keyword search hits it first)')
    if pages is not None:
        yrs = _years_out(resume)
        add('pages', pages == 1 or (pages == 2 and yrs > 8), f'{pages} page(s): students and new grads keep it to one')
    if pdf_text is not None:
        lig = re.search('[ﬀ-ﬆ]', pdf_text)
        add('parse', not lig and len(pdf_text) > 400, 'PDF text extracts cleanly (no ligatures, real text not images)')
        add('dates', len(set(re.findall(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? 20\d\d\b', pdf_text))) > 0,
            'Dates written as Month Year', warn=True)
    return out


def _is_tech(r):
    return bool(re.search(r'software|engineer|computer|data|developer', resume_text(r), re.I))


def _years_out(r):
    yrs = [int(y) for e in r.get('experience', []) for y in re.findall(r'20\d\d', str(e.get('start', '')))]
    return (max(yrs) - min(yrs)) if yrs else 0


def report(resume, jd='', pages=None, pdf_text=None):
    """Overall 0-100: keyword coverage (60%) + lint (40%). Without a posting, lint only."""
    checks = lint(resume, pages, pdf_text)
    pts = {'pass': 1, 'warn': 0.5, 'fail': 0}
    lint_score = 100 * sum(pts[c['level']] for c in checks) / max(1, len(checks))
    out = {"lint": checks, "lint_score": round(lint_score)}
    if jd:
        m = match(resume, jd)
        out.update(m)
        out['score'] = round(0.6 * m['coverage'] + 0.4 * lint_score)
    else:
        out['score'] = round(lint_score)
    return out
