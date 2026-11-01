import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { api, safeUrl } from '../lib/api'

/* The right buttons for anything that needs you. The twin fills forms in its own browser, so "Open" never means a blank
   form in yours: a filled application gets Refill / Submit it; a sign-in opens in the twin's browser (so the login sticks)
   and then "I signed in, finish it". */

export function kindOf(item) {
  const t = `${item.title || ''} ${item.message || ''} ${item.notes || ''}`
  if (/ready to submit|ready for (your )?review|filled and verified/i.test(t)) return 'ready'
  if (/sign[- ]?in|log ?in|account|password|verify your email/i.test(t)) return 'signin'
  if (item.kind === 'question') return 'question'
  return 'other'
}

export function ItemActions({ item, onDone, compact }) {
  const [busy, setBusy] = useState('')
  const kind = kindOf(item)
  const job = item.job_id
  const run = async (label, fn, msg, keep) => {
    setBusy(label)
    try {
      const r = await fn()
      if (r?.queued) toast.success('Queued', { description: 'Your twin is in the middle of a run. It does this one as soon as that run ends.' })
      else toast.success(msg.title, { description: msg.body })
      if (!keep && typeof item.id === 'number') await api(`/api/inbox/${item.id}/resolve`, {})
      onDone?.()
    }
    catch (e) { toast.error(e.message) }
    setBusy('')
  }
  const finish = submit => run(submit ? 'submit' : 'refill', () => api('/api/finish', { job_ids: [job], submit }),
    submit ? { title: 'Submitting it', body: 'Your twin is filling and submitting this one application.' }
      : { title: 'Refilling it', body: 'Your twin is filling it again in its browser and will stop at review.' })
  const openTwin = () => run('open', () => api('/api/open-twin', { url: item.url }),
    { title: "Opened in your twin's browser", body: "Sign in there, then press I signed in, finish it. Your twin uses that same browser, so the login sticks." }, true)
  const skip = () => run('skip', () => api(`/api/jobs/${job}/skip`, {}), { title: 'Skipped', body: 'Your twin won\'t apply to this one.' })
  const btn = 'h-8 rounded-full px-3.5 text-[12.5px] font-semibold transition disabled:opacity-50'
  const primary = btn + ' bg-signal text-white hover:bg-[#2b95ff]', secondary = btn + ' bg-white/[.08] text-white hover:bg-white/[.13]'
  const said = async text => {
    setBusy('said')
    try {
      const r = await api(`/api/jobs/${job}/message`, { text })
      const last = r.thread.at(-1)?.text || ''
      if (/^(Marked as applied|Skipped)/.test(last)) { toast.success(last); onDone?.() }
    } catch (e) { toast.error(e.message) }
    setBusy('')
  }
  return (<>
    <div className={'flex flex-wrap items-center gap-2 ' + (compact ? 'mt-2' : '')}>
      {kind === 'ready' && job && <>
        <button disabled={!!busy} onClick={() => finish(true)} className={primary}>{busy === 'submit' ? 'Starting…' : 'Submit it'}</button>
        <button disabled={!!busy} onClick={() => finish(false)} className={secondary}>{busy === 'refill' ? 'Starting…' : 'Refill to review'}</button>
      </>}
      {kind === 'signin' && <>
        {item.url && <button disabled={!!busy} onClick={openTwin} className={secondary}>{busy === 'open' ? 'Opening…' : "Open in twin's browser"}</button>}
        {job && <button disabled={!!busy} onClick={() => finish(false)} className={primary}>{busy === 'refill' ? 'Starting…' : 'I signed in, finish it'}</button>}
      </>}
      {kind === 'question' && job && <button disabled={!!busy} onClick={() => finish(false)} className={secondary}>{busy === 'refill' ? 'Starting…' : 'Answered, finish it'}</button>}
      {kind === 'other' && safeUrl(item.url) && <a href={safeUrl(item.url)} target="_blank" rel="noreferrer" className={secondary + ' inline-flex items-center'}>Open</a>}
      {job && (kind === 'ready' || kind === 'signin' || /captcha|submit/i.test(`${item.title} ${item.message || ''} ${item.notes || ''}`)) &&
        <button disabled={!!busy} onClick={() => said('I submitted it')} className={secondary}>I submitted it</button>}
      {job && kind !== 'other' && <button disabled={!!busy} onClick={skip} className={secondary}>{busy === 'skip' ? 'Skipping…' : 'Skip this job'}</button>}
      {(typeof item.id === 'number' || job) && <button onClick={async () => {
        if (typeof item.id === 'number') await api(`/api/inbox/${item.id}/resolve`, {})
        else await api(`/api/jobs/${job}/skip`, {})   // a job still waiting on you: dismissing it means don't apply
        onDone?.()
      }} className="h-8 px-2 text-[12.5px] text-muted hover:text-white">Dismiss</button>}
    </div>
    {job && <Talk job={job} onDone={onDone} />}
  </>)
}

/* A conversation with your twin about this one application: ask whether it went through, tell it you submitted it yourself,
   or tell it what to change. Simple things are answered instantly; the rest goes to your agent, which replies here. */
function Talk({ job, onDone }) {
  const [msgs, setMsgs] = useState([])
  const [t, setT] = useState('')
  const [busy, setBusy] = useState(false)
  const box = useRef(null)
  const last = msgs.at(-1)
  const waiting = !!last && (last.role === 'you' || /^(On it|Queued|Submitting)/.test(last.text))   // a reply is on its way
  useEffect(() => {
    let live = true
    const load = () => api(`/api/jobs/${job}/thread`).then(r => { if (live) setMsgs(r.thread) }).catch(() => {})
    load()
    const i = waiting ? setInterval(load, 4000) : null   // only check while the twin owes you an answer
    return () => { live = false; if (i) clearInterval(i) }
  }, [job, waiting])
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight }, [msgs.length])
  const first = msgs.findIndex(m => m.role === 'you')
  const shown = first < 0 ? [] : msgs.slice(first)
  const send = async e => {
    e.preventDefault()
    const text = t.trim()
    if (!text || busy) return
    setBusy(true); setT('')
    try {
      const r = await api(`/api/jobs/${job}/message`, { text })
      setMsgs(r.thread)
      const last = r.thread.at(-1)?.text || ''
      if (/^(Marked as applied|Skipped)/.test(last)) { toast.success(last); onDone?.() }
    } catch (err) { toast.error(err.message); setT(text) }
    setBusy(false)
  }
  return (
    <div className="mt-3">
      {shown.length > 0 && (
        <div ref={box} className="mb-2 max-h-56 space-y-1.5 overflow-y-auto">
          {shown.map((m, i) => (
            <div key={i} className={'flex ' + (m.role === 'you' ? 'justify-end' : 'justify-start')}>
              <div className={'max-w-[85%] rounded-[14px] px-3 py-1.5 text-[13px] leading-snug ' +
                (m.role === 'you' ? 'bg-signal text-white' : 'bg-white/[.08] text-white/90')}>{m.text}</div>
            </div>))}
        </div>)}
      <form onSubmit={send} className="flex items-center gap-2">
        <input value={t} onChange={e => setT(e.target.value)} placeholder="Message your twin about this one, like: did you submit it?"
          className="h-9 min-w-0 flex-1 rounded-full bg-white/[.06] px-3.5 text-[13px] text-white outline-none placeholder:text-faint focus:ring-2 focus:ring-signal" />
        <button disabled={busy || !t.trim()} className="h-9 rounded-full bg-white/[.1] px-3.5 text-[12.5px] font-semibold text-white transition hover:bg-white/[.16] disabled:opacity-40">
          {busy ? 'Sending…' : 'Send'}</button>
      </form>
    </div>
  )
}
