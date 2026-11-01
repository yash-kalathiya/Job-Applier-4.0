import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { toast } from 'sonner'
import { Check, ChevronDown, ChevronRight, CircleSlash, Copy, Hand, Minus, Plus, Star } from 'lucide-react'
import { api } from '../lib/api'
import { parseRun } from '../lib/runlog'
import { useApp, Page } from '../App'
import { Avatar, Segmented, burst, spring } from '../components/ui'
import { REPO_URL } from '../lib/star'
import { ItemActions } from '../components/ItemActions'

/* Autopilot, Apple-style: one quiet hero that says what your twin is doing, grouped lists for everything else. */

const SIZES = [5, 10, 25, 50, 100, 250]
const BLUE = '#0a84ff', GREEN = '#30d158', ORANGE = '#ff9f0a', RED = '#ff453a'
const safeGet = k => { try { return localStorage.getItem(k) } catch { return null } }
const safeSet = (k, v) => { try { localStorage.setItem(k, v) } catch {} }

export default function Agents() {
  const { app_dir, profile, go } = useApp()
  const [q, setQ] = useState(null)
  const [run, setRun] = useState(null)
  const [agents, setAgents] = useState(null)
  const [agent, setAgent] = useState(profile.apply?.agent || safeGet('at:agent') || 'claude')   // Settings' choice comes first
  const [n, setN] = useState(+(safeGet('at:n') || 25))
  const [inbox, setInbox] = useState({ items: [], pending: [] })
  const [apps, setApps] = useState([])
  const [raw, setRaw] = useState(false)
  const [gaps, setGaps] = useState([])
  useEffect(() => { api('/api/questions').then(d => setGaps(d.missing || [])).catch(() => {}) }, [])
  const since = useRef(+(safeGet('at:runStart') || 0) || Date.now() / 1000 - 3 * 3600)
  const refresh = () => { api('/api/inbox').then(setInbox); api('/api/applications').then(setApps) }

  useEffect(() => {
    api('/api/queue?n=60').then(setQ); refresh()
    api('/api/agents').then(a => {
      setAgents(a)
      if (!a[agent]?.signed_in) { const ok = Object.keys(a).find(k => a[k].signed_in); if (ok) setAgent(ok) }
    }).catch(() => {})
  }, [])
  useEffect(() => { if (!run?.running) return; const t = setInterval(refresh, 5000); return () => clearInterval(t) }, [run?.running])
  useEffect(() => {   // fast while a run is going, slow otherwise, so runs started elsewhere (Needs you, a message) show up too
    let t, live = true
    const poll = async () => {
      try { const r = await api('/api/run'); if (!live) return; setRun(r); if (!r.running) refresh(); t = setTimeout(poll, r.running ? 2000 : 6000) }
      catch { if (live) t = setTimeout(poll, 6000) }
    }
    poll(); return () => { live = false; clearTimeout(t) }
  }, [])
  useEffect(() => {   // the agent you pick here is the one everything uses (Needs you buttons, messages, email history)
    safeSet('at:agent', agent)
    if (agent && agent !== profile.apply?.agent) api('/api/profile', { apply: { agent } }).catch(() => {})
  }, [agent])
  useEffect(() => safeSet('at:n', n), [n])

  const live = parseRun(run?.log)
  const session = apps.filter(a => a.at >= since.current).sort((a, b) => b.at - a.at)
  const total = live.n || n
  const running = !!run?.running
  const st = agents?.[agent]
  const label = agent === 'claude' ? 'Claude Code' : 'Codex'
  const pending = inbox.pending.filter(p => !inbox.items.some(i => i.job_id === p.job_id))
  const needs = inbox.items.length + pending.length

  const start = async () => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') Notification.requestPermission()   // so it can tell you when it needs you
    try {
      const r = await api('/api/run', { agent, n })
      setRun(r)
      if (r.busy) { toast("Your twin is already working", { description: 'It finishes what it is doing first. You can watch it here.' }); return }
      since.current = Date.now() / 1000; safeSet('at:runStart', since.current)
      toast.success(`${label} is applying`, { description: `Working through your next ${n} jobs.` })
    } catch (e) { toast.error(e.message) }
  }
  const stop = async () => { setRun(await api('/api/run/stop', {})); toast('Stopped. Your queue keeps its place.') }
  const step = d => setN(SIZES[Math.max(0, Math.min(SIZES.length - 1, SIZES.indexOf(n) + d))] ?? 25)

  const now = run?.now
  const headline = running ? now?.step || live.step || 'Getting ready'
    : session.length ? `${session.length} handled.` : `${(q?.total ?? 0).toLocaleString()} roles ready.`
  const subline = running ? (now?.company ? `${now.company.replace(/^\W+/, '')} · ${now.title} · ` : '') + `${session.length} of ${total} done`
    : session.length ? `${session.filter(a => a.status === 'Needs User').length} waiting on you, ${session.filter(a => a.status === 'Skipped').length} skipped.`
    : q?.dream ? `${q.dream} at your dream companies.` : 'Every open role that fits you.'

  return (
    <Page>
      <div className="mx-auto max-w-[1080px]">
        <h1 className="text-[44px] font-bold leading-none tracking-[-0.035em] text-white">Autopilot</h1>

        <section className="mt-7 rounded-[22px] bg-[#1c1c1e] p-7 ring-1 ring-white/[.06]">
          <div className="flex flex-wrap items-start justify-between gap-8">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-[13px] font-medium" style={{ color: running ? GREEN : 'var(--color-muted)' }}>
                {running ? `${label} is applying` : 'Ready'}
              </div>
              <div className="relative mt-3 h-[52px] overflow-hidden">
                <AnimatePresence mode="popLayout" initial={false}>
                  <motion.div key={headline} initial={{ y: 28, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -28, opacity: 0 }} transition={spring}
                    className="truncate text-[40px] font-semibold leading-[52px] tracking-[-0.03em] text-white">{headline}</motion.div>
                </AnimatePresence>
              </div>
              <div className="mt-1 text-[15px] text-muted">{subline}</div>
              {running && <div className="mt-2 text-[13px] text-faint">Watch it live in the Chrome window your twin opened. Don't close that window; it's the twin's.</div>}
              {running && (
                <div className="mt-6 h-[5px] max-w-[460px] overflow-hidden rounded-full bg-white/[.08]">
                  <motion.div className="h-full rounded-full" style={{ background: BLUE }} initial={{ width: 0 }}
                    animate={{ width: `${Math.max(3, (session.length / Math.max(1, total)) * 100)}%` }} transition={{ type: 'spring', stiffness: 120, damping: 24 }} />
                </div>)}
            </div>

            <div className="flex w-full flex-col gap-3 sm:w-auto sm:items-end">
              <div className="flex flex-wrap items-center gap-3">
                <Segmented id="ag" value={agent} onChange={setAgent} options={[['claude', 'Claude Code'], ['codex', 'Codex']]} />
                <div className="flex h-8 items-center rounded-[10px] bg-white/[.06]">
                  <button onClick={() => step(-1)} disabled={running} className="grid h-8 w-8 place-items-center text-white/80 hover:text-white disabled:opacity-40" aria-label="Fewer jobs"><Minus className="size-3.5" /></button>
                  <span className="w-[74px] text-center text-[13px] font-medium tabular-nums text-white">{n} jobs</span>
                  <button onClick={() => step(1)} disabled={running} className="grid h-8 w-8 place-items-center text-white/80 hover:text-white disabled:opacity-40" aria-label="More jobs"><Plus className="size-3.5" /></button>
                </div>
              </div>
              <div className="min-h-[18px] text-[12.5px]" style={{ color: !st || st.signed_in ? 'var(--color-muted)' : ORANGE }}>
                {!st ? '' : !st.installed ? `${label} isn't installed` : st.signed_in ? `Signed in · runs on your ${label} plan, no API key`
                  : `Signed out. Run ${agent === 'claude' ? '`claude` then /login' : '`codex login`'}`}
              </div>
              <motion.button whileTap={{ scale: 0.96 }} transition={spring} onClick={running ? stop : start} disabled={!running && st && !st.signed_in}
                className="mt-1 h-12 w-full rounded-full px-9 text-[16px] font-semibold text-white transition-colors disabled:opacity-40 sm:w-auto"
                style={{ background: running ? 'rgb(255 255 255 / .1)' : BLUE }}>
                {running ? 'Stop' : 'Start'}
              </motion.button>
              <div className="text-[12.5px] text-faint">{profile.apply?.auto_submit ? 'Submits on its own.' : 'Stops at the review screen so you press submit.'}</div>
              {gaps.length > 0 && <button onClick={() => go('settings')} className="text-right text-[12.5px] text-[#ff9f0a] hover:underline">
                {gaps.length} application answer{gaps.length === 1 ? '' : 's'} missing. Add them so it never has to stop and ask →</button>}
            </div>
          </div>
        </section>

        <StarAsk count={apps.filter(a => a.status === 'Applied' || a.status === 'Needs User').length} />

        <div className="mt-8 grid gap-8 lg:grid-cols-[1.25fr_1fr]">
          <div className="min-w-0 space-y-8">
            {session.length > 0 && (
              <Group title={running ? 'This run' : 'Last run'}>
                <AnimatePresence initial={false}>
                  {session.slice(0, 12).map(a => <ResultRow key={a.id} a={a} onClick={() => go('jobs', a.job_id)} />)}
                </AnimatePresence>
              </Group>)}
            <Group title="Up next" detail={q ? `${q.total.toLocaleString()} in queue` : ''}
              action={<button onClick={() => go('settings')} className="text-[13px]" style={{ color: BLUE }}>Preferences</button>}>
              <div className="max-h-[520px] overflow-y-auto [&>*+*]:border-t [&>*+*]:border-white/[.06]">
                {(q?.jobs || []).slice(0, 40).map(j => (
                  <Row key={j.id} onClick={() => go('jobs', j.id)} left={<Avatar name={j.company} size={32} />} title={j.title} sub={`${j.company} · ${j.ats}`}
                    right={<span className="flex items-center gap-2">{j.dream && <Star className="size-3.5" style={{ color: ORANGE, fill: ORANGE }} />}
                      <span className="w-9 text-right text-[13px] tabular-nums text-muted">{Math.round(j.fit)}%</span>
                      <ChevronRight className="size-4 text-white/25" /></span>} />))}
                {!q && <div className="p-5 text-[13px] text-faint">Loading…</div>}
              </div>
            </Group>
          </div>

          <div className="min-w-0 space-y-8">
            <Group title="Needs you" detail={needs ? <span className="rounded-full px-2 py-0.5 text-[12px] font-semibold text-white" style={{ background: RED }}>{needs}</span> : null}
              footer="Answers you give here are saved, so your twin never asks the same thing twice.">
              <AnimatePresence initial={false}>
                {inbox.items.map(i => <NeedsYou key={'i' + i.id} item={i} onDone={refresh} />)}
                {pending.map(p => (
                  <div key={'p' + p.job_id} className="px-4 py-3.5">
                    <div className="flex items-center gap-3.5"><Avatar name={p.company} size={32} />
                      <div className="min-w-0 flex-1"><div className="truncate text-[14.5px] text-white">{p.company} · {p.title}</div>
                        <div className="line-clamp-2 text-[12.5px] text-muted">{p.notes}</div></div></div>
                    <div className="mt-2 pl-[46px]"><ItemActions item={{ ...p, id: 'p' + p.job_id }} onDone={refresh} /></div>
                  </div>))}
              </AnimatePresence>
              {!needs && <div className="flex items-center gap-2 px-4 py-4 text-[14px] text-muted"><Check className="size-4" style={{ color: GREEN }} />Nothing right now.</div>}
            </Group>

            <Group title="Or use it from your terminal" footer="It never types passwords, solves CAPTCHAs, creates accounts or invents a fact.">
              {[['Check your setup', 'job-applier doctor'], [`Tell ${label} directly`, 'apply to my top 25 with job-applier'],
                ['Start Autopilot from a terminal', `job-applier run --agent ${agent} --n ${n}`]].map(([l, t]) => <CopyRow key={t} label={l} text={t} />)}
            </Group>

            {run?.log && (
              <div>
                <button onClick={() => setRaw(!raw)} className="flex items-center gap-1 px-1 text-[13px] text-muted hover:text-white">
                  <ChevronDown className={'size-3.5 transition-transform ' + (raw ? 'rotate-180' : '')} />Technical log</button>
                <AnimatePresence initial={false}>{raw && (
                  <motion.pre initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                    className="mt-2 max-h-[260px] overflow-auto whitespace-pre-wrap rounded-[16px] bg-black/40 p-4 font-mono text-[11px] leading-relaxed text-white/60">{live.clean}</motion.pre>)}
                </AnimatePresence>
              </div>)}
          </div>
        </div>
      </div>
    </Page>
  )
}

function Group({ title, detail, action, footer, children }) {
  return (
    <section>
      <div className="mb-2.5 flex items-baseline justify-between px-1">
        <div className="flex items-center gap-2"><h2 className="text-[20px] font-semibold tracking-[-0.02em] text-white">{title}</h2>
          {typeof detail === 'string' ? <span className="text-[13px] text-faint">{detail}</span> : detail}</div>
        {action}
      </div>
      <div className="overflow-hidden rounded-[18px] bg-[#1c1c1e] ring-1 ring-white/[.06] [&>*+*]:border-t [&>*+*]:border-white/[.06]">{children}</div>
      {footer && <p className="mt-2 px-1 text-[12.5px] leading-relaxed text-faint">{footer}</p>}
    </section>
  )
}

function Row({ left, title, sub, right, onClick, href }) {
  const C = href ? 'a' : 'button'
  return (
    <C {...(href ? { href, target: '_blank', rel: 'noreferrer' } : { onClick })}
      className="flex w-full items-center gap-3.5 px-4 py-3 text-left transition-colors hover:bg-white/[.035]">
      {left}
      <div className="min-w-0 flex-1"><div className="truncate text-[14.5px] text-white">{title}</div>
        {sub && <div className="truncate text-[12.5px] text-muted">{sub}</div>}</div>
      {right}
    </C>
  )
}

const STATUS = { Applied: [GREEN, Check, 'Applied'], 'Needs User': [ORANGE, Hand, 'Needs you'], Skipped: ['#7d869f', CircleSlash, 'Skipped'] }

function ResultRow({ a, onClick }) {
  const [color, Icon, text] = STATUS[a.status] || ['#98a2c3', Check, a.status]
  return (
    <motion.div layout initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} transition={{ type: 'spring', stiffness: 300, damping: 30 }}>
      <Row onClick={onClick} left={<Avatar name={a.company} size={32} />} title={`${a.company}  ·  ${a.title}`} sub={a.notes}
        right={<span className="flex shrink-0 items-center gap-1.5 text-[13px] font-medium" style={{ color }}><Icon className="size-3.5" />{text}</span>} />
    </motion.div>
  )
}

function CopyRow({ label, text }) {
  const [ok, setOk] = useState(false)
  return (
    <button onClick={() => { navigator.clipboard.writeText(text); setOk(true); setTimeout(() => setOk(false), 1400) }}
      className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left hover:bg-white/[.035]">
      <span className="min-w-0"><span className="block text-[13px] text-muted">{label}</span>
        <span className="block font-mono text-[13px] text-white">{text}</span></span>
      <span className="shrink-0 text-[12.5px] font-medium" style={{ color: ok ? GREEN : BLUE }}>{ok ? 'Copied' : 'Copy'}</span>
    </button>
  )
}

function NeedsYou({ item, onDone }) {
  const question = item.kind === 'question' ? (item.title || '').replace(/^Add your answer:\s*/, '') : ''
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const finish = async e => {
    setBusy(true)
    try {
      if (question && text.trim()) await api('/api/answer', { question, answer: text.trim() })
      await api(`/api/inbox/${item.id}/resolve`, {})
      if (e?.clientX) burst(e.clientX, e.clientY)
      toast.success(question && text.trim() ? 'Saved to your answers' : 'Done', { description: question && text.trim() ? 'Used here and on every similar question.' : undefined })
      onDone()
    } catch (err) { toast.error(err.message) } finally { setBusy(false) }
  }
  return (
    <motion.div layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, height: 0 }} className="px-4 py-3.5">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[14.5px] font-medium text-white">{item.title}</div>
          <div className="mt-0.5 text-[13px] leading-relaxed text-muted">{question || item.message}</div>
        </div>
        {question && <button onClick={() => setOpen(!open)} className="shrink-0 pt-0.5 text-[13px]" style={{ color: BLUE }}>{open ? 'Cancel' : 'Answer'}</button>}
      </div>
      {!open && <div className="mt-2"><ItemActions item={item} onDone={onDone} /></div>}
      <AnimatePresence initial={false}>{open && (
        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
          <textarea autoFocus value={text} onChange={e => setText(e.target.value)} rows={4} placeholder="Your answer, in your words."
            className="mt-3 w-full resize-none rounded-[12px] bg-black/30 px-3.5 py-3 text-[14px] text-white outline-none ring-1 ring-white/10 placeholder:text-faint focus:ring-2 focus:ring-[#0a84ff]" />
          <div className="mt-2 flex justify-end gap-2">
            <button onClick={finish} disabled={busy} className="h-8 rounded-full px-4 text-[13px] text-muted hover:text-white">Skip question</button>
            <motion.button whileTap={{ scale: 0.96 }} onClick={finish} disabled={busy || !text.trim()}
              className="h-8 rounded-full px-4 text-[13px] font-semibold text-white disabled:opacity-40" style={{ background: BLUE }}>Save</motion.button>
          </div>
        </motion.div>)}
      </AnimatePresence>
    </motion.div>
  )
}

function StarAsk({ count }) {
  // once your twin has done real work for you, ask (once) for a star; never again after a star or a dismiss
  const [gone, setGone] = useState(() => safeGet('at:starAsk') === 'done')
  if (gone || count < 3) return null
  const done = () => { safeSet('at:starAsk', 'done'); setGone(true) }
  return (
    <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={spring}
      className="mt-5 flex flex-wrap items-center gap-4 rounded-[18px] bg-[#1c1c1e] px-5 py-4 ring-1 ring-white/[.06]">
      <span className="text-[22px] text-[#ffd60a]">★</span>
      <div className="min-w-0 flex-1">
        <div className="text-[15px] font-semibold text-white">Your twin has handled {count} applications. Like it?</div>
        <div className="text-[13px] text-muted">Job Applier 4.0 is free. A star on GitHub helps other students find it.</div>
      </div>
      <a href={REPO_URL} target="_blank" rel="noreferrer" onClick={done}
        className="inline-flex h-9 items-center gap-1.5 rounded-full bg-white px-4 text-[13.5px] font-semibold text-[#1d1d1f] hover:bg-white/90"><span className="text-[#f5a524]">★</span>Star on GitHub</a>
      <button onClick={done} className="text-[13px] text-muted hover:text-white">Not now</button>
    </motion.section>
  )
}
