import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import * as Dialog from '@radix-ui/react-dialog'
import { toast } from 'sonner'
import { ArrowDown, ArrowUp, Check, CheckCircle2, FileDown, Palette, PenLine, Plus, ScanSearch, Trash2, AlertTriangle, Sparkles, Upload } from 'lucide-react'
import { api, fileUrl } from '../lib/api'
import { useApp, Page } from '../App'
import { Badge, Button, Drop, Ring, Segmented, Title, spring } from '../components/ui'
import { Paper } from './Jobs'

const md = s => (s || '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
  .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<span class="text-signal-ink underline decoration-sky/30 underline-offset-2">$1</span>').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')

/* inline editable text: shows formatted text, edits the raw (markdown-lite) text in place */
function E({ value, onChange, ph, className, multiline }) {
  const ref = useRef(null)
  const [focus, setFocus] = useState(false)
  useEffect(() => { if (!ref.current) return; if (focus) ref.current.textContent = value || ''; else ref.current.innerHTML = md(value) }, [focus, value])
  return <span ref={ref} contentEditable suppressContentEditableWarning data-ph={ph} className={`editable ${className || ''}`}
    onFocus={() => setFocus(true)} onBlur={e => { const v = e.currentTarget.textContent.replace(/\s+\n/g, '\n').trim(); setFocus(false); if (v !== (value || '')) onChange(v) }}
    onKeyDown={e => { if (e.key === 'Enter' && !multiline) { e.preventDefault(); e.currentTarget.blur() } }} />
}

const SECS = { experience: ['Experience', { org: 'Company', title: 'Role', location: 'City, ST', start: 'Start', end: 'End' }],
  projects: ['Projects', { name: 'Project', tagline: 'Event, award, or one-liner', date: 'Date' }],
  leadership: ['Leadership', { org: 'Organization', title: 'Role', start: 'Start', end: 'End' }],
  volunteering: ['Volunteering', { org: 'Organization', title: 'Role', start: 'Start', end: 'End' }] }

export default function Studio({ arg }) {
  const { vault: v0, profile, templates, setState } = useApp()
  const [v, setV] = useState(() => structuredClone(v0))
  const [mode, setMode] = useState('write')
  const [tpl, setTpl] = useState(profile.apply?.template || 'classic')
  const [rep, setRep] = useState(null)
  const [saved, setSaved] = useState(true)
  const [importing, setImporting] = useState(arg === 'import' || !(v0.experience?.length || v0.projects?.length))
  const t = useRef()
  // the app keeps one copy of the vault; update it too, so leaving and coming back never shows (and then re-saves) an old one
  const save = nv => {
    setV(nv); setSaved(false); setState?.(s => s ? { ...s, vault: nv } : s); clearTimeout(t.current)
    t.current = setTimeout(async () => {
      try { await api('/api/vault', nv); setSaved(true); api('/api/ats').then(setRep).catch(() => {}) }
      catch (e) { toast.error("Couldn't save your resume", { description: e.message }) }
    }, 650)
  }
  useEffect(() => () => {   // leaving the page with an edit still pending: save it now instead of dropping it
    if (t.current) { clearTimeout(t.current); api('/api/vault', vRef.current).catch(() => {}) }
  }, [])
  const vRef = useRef(v); vRef.current = v
  useEffect(() => { api('/api/ats').then(setRep) }, [])
  const set = (path, val) => { const nv = structuredClone(v); let o = nv; for (const k of path.slice(0, -1)) o = o[k] ??= {}; o[path.at(-1)] = val; save(nv) }
  const pick = async id => {
    setTpl(id)
    try {
      await api('/api/profile', { apply: { template: id } })
      setState?.(s => s ? { ...s, profile: { ...s.profile, apply: { ...s.profile.apply, template: id } } } : s)
      toast.success('Template set', { description: templates.find(x => x.id === id)?.label })
    } catch (e) { toast.error(e.message) }
  }
  const download = async () => {
    const id = toast.loading('Rendering your PDF…')
    try {
      const r = await api('/api/render', { template: tpl })
      toast.success('Your PDF is ready', { id, action: { label: 'Open', onClick: () => window.open(fileUrl(r.pdf)) } })   // a click, so popup blockers allow it
    } catch (e) { toast.error("Couldn't make the PDF", { id, description: e.message }) }
  }
  const fails = (rep?.lint || []).filter(c => c.level !== 'pass')

  return (
    <div className="relative">
      
      <Page wide>
        <Title sub="Put everything here, even what won't fit. Your twin picks the best of it for every job."
          right={<>
            <span className="mr-2 flex items-center gap-1.5 text-[13px] text-white/85">{saved ? <><CheckCircle2 className="size-4" />Saved</> : 'Saving…'}</span>
            <Button variant="white" onClick={() => setImporting(true)}><Upload className="size-4" />Import</Button>
            <Button variant="sky" onClick={download}><FileDown className="size-4" />Download PDF</Button></>}>
          Resume
        </Title>
        <div className="mb-5 flex justify-center">
          <div className="glass rounded-full p-1"><Segmented id="mode" value={mode} onChange={setMode} options={[['write', 'Write', PenLine], ['check', 'Check', ScanSearch], ['style', 'Style', Palette]]} /></div>
        </div>
        <AnimatePresence mode="wait">
          {mode === 'write' && (
            <motion.div key="w" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} className="grid gap-6 lg:grid-cols-[1fr_300px]">
              <Doc v={v} set={set} save={save} />
              <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
                <div className="card p-5"><div className="flex items-center gap-4"><Ring value={rep?.score ?? 0} size={70} />
                  <div><div className="font-display text-[22px] font-semibold tracking-[-0.035em] leading-tight">Resume score</div><div className="text-[12.5px] text-muted">{fails.length ? `${fails.length} things to fix` : 'Looking sharp'}</div></div></div>
                  <button onClick={() => setMode('check')} className="mt-3 text-[13px] font-medium text-signal-ink hover:underline">See the checks →</button></div>
                <div className="card p-5"><div className="text-[15px] font-semibold text-white">How it works</div>
                  <ul className="mt-2 space-y-2 text-[13px] leading-relaxed text-muted">
                    <li>Click any line to edit it. <b className="text-fg">**bold**</b> works.</li>
                    <li>Add every version of a bullet you like: different angles help.</li>
                    <li>For each job, your twin keeps the best 2-4 per role and fits one page.</li></ul></div>
              </aside>
            </motion.div>)}
          {mode === 'check' && (
            <motion.div key="c" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="mx-auto max-w-[760px]">
              <div className="card p-7"><div className="flex items-center gap-5"><Ring value={rep?.score ?? 0} size={104} stroke={9} />
                <div><div className="font-display text-[34px] font-semibold tracking-[-0.035em] leading-none">{(rep?.score ?? 0) >= 85 ? 'Recruiter-ready.' : 'Almost there.'}</div>
                  <div className="mt-2 text-[14px] text-muted">The checks recruiters and ATS parsers actually care about.</div></div></div>
                <div className="mt-6 divide-y divide-line">{(rep?.lint || []).map((c, i) => (
                  <motion.div key={c.id} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.035 }} className="flex items-start gap-3 py-3 text-[14px]">
                    {c.level === 'pass' ? <span className="mt-0.5 grid size-5 place-items-center rounded-full bg-good text-white"><Check className="size-3" strokeWidth={3} /></span>
                      : <AlertTriangle className={`mt-0.5 size-5 ${c.level === 'fail' ? 'text-bad' : 'text-warn'}`} />}<span className={c.level === 'pass' ? 'text-muted' : 'text-fg'}>{c.msg}</span></motion.div>))}</div>
              </div>
            </motion.div>)}
          {mode === 'style' && (
            <motion.div key="s" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
              <Coverflow templates={templates} tpl={tpl} pick={pick} />
            </motion.div>)}
        </AnimatePresence>
      </Page>
      <Import open={importing} setOpen={setImporting} onDone={nv => { if (nv) { setV(nv); setState(s => ({ ...s, vault: nv })) } }} />
    </div>
  )
}

function Doc({ v, set, save }) {
  const b = v.basics || {}
  const links = b.links || []
  const mv = (sec, i, d) => { const nv = structuredClone(v); const a = nv[sec]; if (!a[i + d]) return; [a[i], a[i + d]] = [a[i + d], a[i]]; save(nv) }
  const del = (sec, i) => { const nv = structuredClone(v); nv[sec].splice(i, 1); save(nv) }
  const add = sec => { const nv = structuredClone(v); (nv[sec] ??= []).unshift({ bullets: [''] }); if (!(nv.order || []).includes(sec)) nv.order = [...(nv.order || []), sec]; save(nv) }
  const bul = (sec, i, j, op) => { const nv = structuredClone(v); const a = nv[sec][i].bullets ??= []
    if (op === 'add') a.splice(j + 1, 0, ''); else if (op === 'del') a.splice(j, 1); else if (a[j + op] !== undefined) [a[j], a[j + op]] = [a[j + op], a[j]]; save(nv) }
  return (
    <div className="relative mx-auto w-full max-w-[860px] rounded-[10px] bg-white px-[7%] py-12 text-[15px] leading-[1.45] text-[#16161a] shadow-[0_30px_80px_rgb(0_0_0/.45)] [--color-ink:#16161a] [--color-fg:#16161a] [--color-muted:#5d5f6b] [--color-faint:#9b9daa] [--color-line-2:rgb(0_0_0/.14)] [--color-signal-ink:#1d4ed8]" style={{ fontFamily: 'Charter, "Iowan Old Style", Georgia, serif' }}>
      <div className="text-center">
        <E value={b.name} ph="Your Name" onChange={x => set(['basics', 'name'], x)} className="block text-[42px] leading-none" />
        <div className="mt-3 flex flex-wrap justify-center gap-x-1 font-sans text-[13px] text-muted">
          {['phone', 'email', 'location'].map((k, i) => <span key={k} className="flex items-center gap-1">{i > 0 && <span className="text-faint">·</span>}<E value={b[k]} ph={k} onChange={x => set(['basics', k], x)} /></span>)}
          {links.map((l, i) => <span key={i} className="flex items-center gap-1"><span className="text-faint">·</span>
            <E value={l.label || l.url} ph="link" onChange={x => { const nl = [...links]; nl[i] = x ? { label: x.replace(/^https?:\/\/(www\.)?/, ''), url: x.startsWith('http') ? x : (l.url || 'https://' + x) } : null; set(['basics', 'links'], nl.filter(Boolean)) }} /></span>)}
          <button onClick={() => set(['basics', 'links'], [...links, { label: '', url: '' }])} className="ml-1 text-signal-ink opacity-60 hover:opacity-100"><Plus className="size-3.5" /></button>
        </div>
      </div>

      <Sec title="Education">
        {(v.education || []).map((e, i) => (
          <div key={i} className="group relative mb-3">
            <Row l={<E value={e.school} ph="School" onChange={x => set(['education', i, 'school'], x)} className="font-sans text-[14.5px] font-semibold" />} r={<E value={e.location} ph="City, ST" onChange={x => set(['education', i, 'location'], x)} />} />
            <Row l={<span className="font-sans text-[13.5px] italic text-muted"><E value={e.degree} ph="Degree" onChange={x => set(['education', i, 'degree'], x)} />{' in '}<E value={e.major} ph="Major" onChange={x => set(['education', i, 'major'], x)} />
              {' · GPA '}<E value={e.gpa} ph="—" onChange={x => set(['education', i, 'gpa'], x)} /></span>}
              r={<span><E value={e.start} ph="Start" onChange={x => set(['education', i, 'start'], x)} /> – <E value={e.end} ph="Graduation" onChange={x => set(['education', i, 'end'], x)} /></span>} />
            <div className="mt-0.5 font-sans text-[13px] text-muted"><E value={(e.honors || []).join(' · ')} ph="Honors, scholarships, test scores (optional)" onChange={x => set(['education', i, 'honors'], x.split(/\s*·\s*/).filter(Boolean))} /></div>
          </div>))}
        {!(v.education || []).length && <AddBtn onClick={() => set(['education'], [{}])}>Add school</AddBtn>}
      </Sec>

      {Object.entries(SECS).map(([sec, [title, f]]) => (
        <Sec key={sec} title={title} onAdd={() => add(sec)}>
          {(v[sec] || []).map((e, i) => (
            <motion.div layout transition={spring} key={e.id || i} className="group relative mb-4 rounded-lg">
              <div className="absolute -left-12 top-0 hidden flex-col gap-0.5 font-sans group-hover:flex">
                <Tool onClick={() => mv(sec, i, -1)}><ArrowUp className="size-3.5" /></Tool><Tool onClick={() => mv(sec, i, 1)}><ArrowDown className="size-3.5" /></Tool>
                <Tool onClick={() => del(sec, i)} danger><Trash2 className="size-3.5" /></Tool></div>
              {sec === 'projects' ? (
                <Row l={<span><E value={e.name} ph={f.name} onChange={x => set([sec, i, 'name'], x)} className="font-sans text-[14.5px] font-semibold" />
                  <span className="font-sans text-[13px] text-muted"> · <E value={e.tagline} ph={f.tagline} onChange={x => set([sec, i, 'tagline'], x)} /></span></span>}
                  r={<E value={e.date} ph="Date" onChange={x => set([sec, i, 'date'], x)} />} />
              ) : <>
                <Row l={<E value={e.org} ph={f.org} onChange={x => set([sec, i, 'org'], x)} className="font-sans text-[14.5px] font-semibold" />}
                  r={<span><E value={e.start} ph="Start" onChange={x => set([sec, i, 'start'], x)} /> – <E value={e.end} ph="Present" onChange={x => set([sec, i, 'end'], x)} /></span>} />
                <Row l={<E value={e.title} ph={f.title} onChange={x => set([sec, i, 'title'], x)} className="font-sans text-[13.5px] italic text-muted" />}
                  r={f.location ? <E value={e.location} ph={f.location} onChange={x => set([sec, i, 'location'], x)} className="text-muted" /> : null} /></>}
              <ul className="mt-1 space-y-0.5 pl-5">
                {(e.bullets || []).map((x, j) => (
                  <li key={j} className="group/b relative list-disc font-sans text-[13.5px] leading-[1.5] marker:text-faint">
                    <E value={x} ph="What you did, how, and the result (add a number)" multiline onChange={y => { const nv = structuredClone(v); nv[sec][i].bullets[j] = y; save(nv) }} className="block" />
                    <span className="absolute -right-24 top-0 hidden gap-0.5 group-hover/b:flex">
                      <Tool onClick={() => bul(sec, i, j, -1)}><ArrowUp className="size-3" /></Tool><Tool onClick={() => bul(sec, i, j, 1)}><ArrowDown className="size-3" /></Tool>
                      <Tool onClick={() => bul(sec, i, j, 'add')}><Plus className="size-3" /></Tool><Tool onClick={() => bul(sec, i, j, 'del')} danger><Trash2 className="size-3" /></Tool></span>
                  </li>))}
              </ul>
              <button onClick={() => bul(sec, i, (e.bullets || []).length - 1, 'add')} className="ml-5 mt-1 hidden font-sans text-[12px] font-medium text-signal-ink group-hover:inline-flex">+ bullet</button>
            </motion.div>))}
          {!(v[sec] || []).length && <AddBtn onClick={() => add(sec)}>Add {title.toLowerCase().replace(/s$/, '')}</AddBtn>}
        </Sec>))}

      <Sec title="Skills">
        <div className="space-y-1 font-sans text-[13.5px]">
          {(v.skills || []).map((s, i) => (
            <div key={i} className="group flex gap-1.5"><E value={s.label} ph="Label" onChange={x => set(['skills', i, 'label'], x)} className="shrink-0 font-semibold" />:
              <E value={(s.items || []).join(', ')} ph="comma, separated, skills" onChange={x => set(['skills', i, 'items'], x.split(/\s*,\s*/).filter(Boolean))} className="flex-1" />
              <button onClick={() => { const nv = structuredClone(v); nv.skills.splice(i, 1); save(nv) }} className="hidden text-faint hover:text-bad group-hover:block"><Trash2 className="size-3.5" /></button></div>))}
          <AddBtn onClick={() => set(['skills'], [...(v.skills || []), { label: '', items: [] }])}>Add skill line</AddBtn>
        </div>
      </Sec>
      {['awards', 'certifications'].map(k => (
        <Sec key={k} title={k === 'awards' ? 'Awards' : 'Licenses & Certifications'}>
          <div className="font-sans text-[13.5px]"><E value={(v[k] || []).map(a => typeof a === 'string' ? a : a.title).join('\n')} multiline ph="One per line"
            onChange={x => set([k], x.split('\n').map(s => s.trim()).filter(Boolean))} className="block whitespace-pre-line" /></div>
        </Sec>))}
    </div>
  )
}
const Row = ({ l, r }) => <div className="flex items-baseline justify-between gap-4"><div className="min-w-0">{l}</div><div className="shrink-0 text-right font-sans text-[13px]">{r}</div></div>
const Tool = ({ children, onClick, danger }) => <button onClick={onClick} className={`grid size-6 place-items-center rounded-md bg-white text-muted shadow-sm ring-1 ring-line transition hover:text-ink ${danger ? 'hover:!text-bad' : ''}`}>{children}</button>
const AddBtn = ({ children, onClick }) => <button onClick={onClick} className="inline-flex items-center gap-1 font-sans text-[13px] font-medium text-signal-ink opacity-70 transition hover:opacity-100"><Plus className="size-3.5" />{children}</button>
function Sec({ title, children, onAdd }) {
  return (
    <section className="group/s mt-7">
      <div className="mb-2.5 flex items-center gap-3"><h3 className="text-[22px] leading-none">{title}</h3><div className="h-px flex-1 bg-line-2" />
        {onAdd && <button onClick={onAdd} className="flex items-center gap-1 font-sans text-[12px] font-medium text-signal-ink opacity-0 transition group-hover/s:opacity-100"><Plus className="size-3.5" />Add</button>}</div>
      {children}
    </section>
  )
}

function Import({ open, setOpen, onDone }) {
  const [busy, setBusy] = useState(false)
  const [text, setText] = useState(null)
  const [out, setOut] = useState(null)
  const send = async body => {
    setBusy(true)
    try { const r = await api('/api/import', body); setOut(r); onDone(r.vault); toast.success(r.structured ? 'Your vault is built' : 'Saved for your agent', { description: r.message }) }
    catch (e) { toast.error(e.message) }
    setBusy(false)
  }
  return (
    <Dialog.Root open={open} onOpenChange={o => { setOpen(o); if (!o) { setOut(null); setText(null) } }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/25 backdrop-blur-[2px]" />
        <Dialog.Content aria-describedby={undefined} className="fixed left-1/2 top-1/2 z-50 w-[min(640px,92vw)] -translate-x-1/2 -translate-y-1/2 rounded-[18px] bg-[#1c1c1e] ring-1 ring-white/10 p-8 shadow-[0_40px_100px_rgb(0_0_0/.28)] outline-none">
          <Dialog.Title className="font-display text-[40px] font-semibold tracking-[-0.035em] leading-tight text-ink">Bring everything you've got.</Dialog.Title>
          <p className="mb-6 mt-1 text-[14.5px] text-muted">Old resumes, your LinkedIn, project notes. Your twin pulls it all into one vault and never invents anything.</p>
          {busy ? <div className="grid place-items-center py-14"><motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1.1, ease: 'linear' }}><Sparkles className="size-8 text-signal" /></motion.div>
            <div className="mt-3 text-[14px] text-muted">Reading it like a recruiter…</div></div>
            : out ? <div className="rounded-[18px] bg-mist p-6"><div className="flex items-center gap-2 font-medium text-ink"><CheckCircle2 className="size-5 text-good" />{out.message}</div>
              {out.counts && <div className="mt-3 flex flex-wrap gap-2">{Object.entries(out.counts).map(([k, n]) => n > 0 && <Badge key={k} tone="sky">{n} {k}</Badge>)}</div>}
              {!out.structured && <div className="mt-3 text-[13px] text-muted">To structure it fully, tell Claude Code or Codex: <span className="font-mono text-fg">twin: structure my dump</span>. Or add an API key in Settings.</div>}
              <div className="mt-5 flex justify-end gap-2"><Button variant="white" onClick={() => setOut(null)}>Add more</Button><Button onClick={() => setOpen(false)} arrow>Done</Button></div></div>
            : text !== null ? <div><textarea autoFocus rows={10} value={text} onChange={e => setText(e.target.value)} placeholder="Paste anything: a resume, your LinkedIn About + Experience, notes…" className="box" />
              <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={() => setText(null)}>Back</Button><Button onClick={() => send({ text })} arrow disabled={!text.trim()}>Import</Button></div></div>
            : <Drop onFile={f => send({ name: f.name, data: f.data })} onText={() => setText('')} />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function Coverflow({ templates, tpl, pick }) {
  const idx = Math.max(0, templates.findIndex(t => t.id === tpl))
  const [i, setI] = useState(idx)
  useEffect(() => {
    const k = e => { if (e.key === 'ArrowRight') setI(x => Math.min(templates.length - 1, x + 1)); if (e.key === 'ArrowLeft') setI(x => Math.max(0, x - 1)) }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }, [templates.length])
  const cur = templates[i] || {}
  return (
    <div>
      <div className="relative h-[560px] select-none" style={{ perspective: 1600 }}
        onWheel={e => { if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && Math.abs(e.deltaX) > 18) setI(x => Math.max(0, Math.min(templates.length - 1, x + Math.sign(e.deltaX)))) }}>
        {templates.map((x, j) => {
          const d = j - i, ad = Math.abs(d)
          return (
            <motion.button key={x.id} onClick={() => d === 0 ? pick(x.id) : setI(j)}
              className="absolute left-1/2 top-4 w-[360px]" style={{ zIndex: 50 - ad, transformStyle: 'preserve-3d' }}
              animate={{ x: `calc(-50% + ${d * 230 + Math.sign(d) * 60}px)`, rotateY: d === 0 ? 0 : d > 0 ? -55 : 55, z: d === 0 ? 80 : -120 - ad * 40,
                opacity: ad > 3 ? 0 : 1, scale: d === 0 ? 1 : 0.86 }}
              transition={{ type: 'spring', stiffness: 160, damping: 22 }}>
              <div className={`overflow-hidden rounded-[10px] ${tpl === x.id ? 'ring-2 ring-signal' : ''}`} style={{ boxShadow: d === 0 ? '0 50px 120px rgb(0 0 0 / .6), 0 0 80px rgb(76 141 255 / .25)' : '0 30px 70px rgb(0 0 0 / .5)' }}>
                <Paper src={`/preview?template=${x.id}`} />
              </div>
              <div className="mt-4 text-center opacity-0 transition-opacity" style={{ opacity: d === 0 ? 1 : 0 }} />
            </motion.button>)
        })}
      </div>
      <div className="mt-2 text-center">
        <AnimatePresence mode="wait"><motion.div key={cur.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}>
          <div className="text-[30px] font-bold tracking-[-0.035em] text-white">{cur.label}</div>
          <div className="mt-1 text-[15px] text-muted">{cur.desc}</div>
          <div className="mt-1 text-[13px] text-faint">Best for {cur.best}</div>
        </motion.div></AnimatePresence>
        <div className="mt-5 flex items-center justify-center gap-3">
          <Button variant="white" onClick={() => setI(x => Math.max(0, x - 1))}>←</Button>
          <Button onClick={() => pick(cur.id)}>{tpl === cur.id ? 'Your template' : 'Use this template'}</Button>
          <Button variant="white" onClick={() => setI(x => Math.min(templates.length - 1, x + 1))}>→</Button>
        </div>
        <div className="mt-4 flex justify-center gap-1.5">{templates.map((x, j) => <button key={x.id} onClick={() => setI(j)}
          className={`h-1.5 rounded-full transition-all ${j === i ? 'w-6 bg-white' : 'w-1.5 bg-white/25'}`} />)}</div>
      </div>
    </div>
  )
}
