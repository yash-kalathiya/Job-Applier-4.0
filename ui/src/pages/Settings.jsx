import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { X } from 'lucide-react'
import { api } from '../lib/api'
import { useApp, Page } from '../App'
import { Button, Segmented, Slider, Switch, Title } from '../components/ui'
import { ProfileQuestions, missing, useQuestions } from '../components/ProfileQuestions'

export function Chips({ value = [], onChange, placeholder, suggestions = [], large }) {
  const [t, setT] = useState('')
  const addv = x => { x = x.trim(); if (x && !value.includes(x)) onChange([...value, x]); setT('') }
  // a dozen at a time; typing narrows them, and anything you type works even if it's not listed
  const shown = suggestions.filter(s => !value.includes(s) && (!t || s.includes(t.toLowerCase()))).slice(0, t ? 8 : 12)
  return (
    <div>
      <div className={'flex flex-wrap items-center gap-1.5 bg-mist ' + (large ? 'rounded-[18px] px-3 py-2.5 backdrop-blur ' : 'rounded-[14px] px-2 py-1.5 ') + 'focus-within:bg-white/[.08] focus-within:ring-2 focus-within:ring-signal'}>
        {value.map(v => <span key={v} className={'inline-flex items-center gap-1 rounded-full bg-signal/15 pl-3 pr-1.5 font-medium text-[#9cc8ff] ' + (large ? 'py-1.5 text-[15px]' : 'py-1 text-[13px]')}>{v}
          <button onClick={() => onChange(value.filter(x => x !== v))} className="grid size-4 place-items-center rounded-full hover:bg-signal/20"><X className="size-3" /></button></span>)}
        <input value={t} onChange={e => setT(e.target.value)} placeholder={value.length ? '' : placeholder} onKeyDown={e => {
          if ((e.key === 'Enter' || e.key === ',') && t.trim()) { e.preventDefault(); addv(t) } if (e.key === 'Backspace' && !t && value.length) onChange(value.slice(0, -1)) }}
          className={'min-w-[140px] flex-1 bg-transparent px-1.5 text-white outline-none placeholder:text-faint ' + (large ? 'h-9 text-[16px]' : 'h-8 text-[14px]')} />
      </div>
      {shown.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{shown.map(s =>
        <button key={s} onClick={() => addv(s)} className={'rounded-full bg-white/[.06] text-white/70 transition hover:bg-signal/15 hover:text-white ' + (large ? 'px-3.5 py-1.5 text-[14px]' : 'px-3 py-1 text-[12.5px]')}>+ {s}</button>)}</div>}
    </div>
  )
}

export const ROLE_SUGGEST = ['software engineer', 'finance', 'investment banking', 'data science', 'machine learning', 'quant', 'consulting',
  'accounting', 'product', 'design', 'marketing', 'healthcare', 'mechanical', 'hardware', 'robotics', 'sales and trading', 'research', 'biology',
  'chemistry', 'pharma', 'public health', 'psychology', 'economics', 'statistics', 'actuarial', 'real estate', 'legal', 'policy', 'government',
  'nonprofit', 'education', 'journalism', 'media', 'communications', 'writing', 'sales', 'operations', 'supply chain', 'hr', 'civil',
  'architecture', 'environmental', 'aerospace', 'cybersecurity', 'security', 'hospitality', 'retail', 'fashion', 'sports', 'agriculture']

function Group({ title, children }) {
  return <div className="mb-8"><div className="mb-2 px-4 text-[13px] text-muted">{title}</div><div className="card divide-y divide-line overflow-hidden">{children}</div></div>
}
function Row({ label, hint, children, stack }) {
  return (
    <div className={`px-5 py-3 ${stack ? '' : 'flex min-h-[52px] items-center justify-between gap-6'}`}>
      <div className={stack ? 'mb-2.5' : 'min-w-0'}><div className="text-[15px] text-ink">{label}</div>{hint && <div className="text-[12.5px] text-muted">{hint}</div>}</div>
      <div className={stack ? '' : 'w-[52%] shrink-0'}>{children}</div>
    </div>
  )
}

export default function Settings() {
  const { profile, refresh } = useApp()
  const [p, setP] = useState(structuredClone(profile))
  const s = p.search, a = p.apply
  const set = (k, v) => setP({ ...p, [k]: v })
  const ss = (k, v) => setP({ ...p, search: { ...s, [k]: v } })
  const sa = (k, v) => setP({ ...p, apply: { ...a, [k]: v } })
  const se = (k, v) => setP({ ...p, eeo: { ...p.eeo, [k]: v } })
  const save = async () => { await api('/api/profile', p); await refresh(); toast.success('Saved', { description: 'Rescan to re-rank jobs with your new preferences.' }) }
  const T = (k, ph) => <input className="uline" value={p[k] || ''} placeholder={ph} onChange={e => set(k, e.target.value)} />
  const qs = useQuestions()
  const left = missing(qs, p)
  const Sel = (k, opts) => <select className="uline" value={p.eeo[k]} onChange={e => se(k, e.target.value)}>{opts.map(o => <option key={o}>{o}</option>)}</select>
  return (
    <div className="relative"><Page>
      <Title sub="Who you are, what you want, and how far your twin may go on its own." right={<Button onClick={save} arrow>Save</Button>}>
        Settings</Title>
      <div className="mx-auto max-w-[860px]">
        {left.length > 0 && <div className="mb-6 rounded-[14px] bg-[#ff9f0a]/10 px-4 py-3 text-[14px] text-[#ffc56b] ring-1 ring-[#ff9f0a]/25">
          {left.length} application answer{left.length === 1 ? '' : 's'} missing (marked below). Until you answer, your twin asks you instead of guessing.</div>}
        <Group title="Your twin's permissions">
          <Row label="Submit applications on its own" hint="Off: it fills everything and stops so you can press Submit."><div className="flex justify-end"><Switch checked={a.auto_submit} onChange={v => sa('auto_submit', v)} /></div></Row>
          <Row label="Read verification codes from my email" hint="When a site emails you a code, your agent finds it in your inbox and types it. Off: you get a notification instead."><div className="flex justify-end"><Switch checked={a.email_codes === 'agent'} onChange={v => sa('email_codes', v ? 'agent' : 'notify')} /></div></Row>
          <Row label="Desktop notifications" hint="Ping my Mac when my twin needs me."><div className="flex justify-end"><Switch checked={a.notify_desktop !== false} onChange={v => sa('notify_desktop', v)} /></div></Row>
          <Row label="Applies with" hint="The agent Autopilot uses."><div className="flex justify-end"><Segmented id="agentset" value={a.agent || 'claude'} onChange={v => sa('agent', v)} options={[['claude', 'Claude Code'], ['codex', 'Codex']]} /></div></Row>
          <Row label="Tailor a resume for every job" hint="A new one-page resume, rewritten for each posting."><div className="flex justify-end"><Switch checked={a.tailor_every_resume} onChange={v => sa('tailor_every_resume', v)} /></div></Row>
          <Row label={`Up to ${a.daily_limit} applications a day`}><Slider value={a.daily_limit} min={5} max={200} step={5} onChange={v => sa('daily_limit', v)} /></Row>
          <Row label={`Skip an application stuck for ${a.stuck_minutes || 20} minutes`} hint="Waiting on a sign-in or a page that won't load: it moves on and leaves that one in Needs you."><Slider value={a.stuck_minutes || 20} min={5} max={60} step={5} onChange={v => sa('stuck_minutes', v)} /></Row>
          <Row label={`At most ${a.per_company_cap} per company`} hint="Many companies cap or flag repeat applicants."><Slider value={a.per_company_cap} min={1} max={10} step={1} onChange={v => sa('per_company_cap', v)} /></Row>
        </Group>
        <Group title="What you're looking for">
          <Row label="Type"><div className="flex justify-end"><Segmented id="kind" value={s.kind} onChange={v => ss('kind', v)} options={[['internship', 'Internship'], ['new-grad', 'New grad'], ['full-time', 'Full-time']]} /></div></Row>
          <Row label="Cycle">{<input className="uline" value={s.season} onChange={e => ss('season', e.target.value)} placeholder="Summer 2027" />}</Row>
          <Row label="Roles" stack><Chips value={s.roles} onChange={v => ss('roles', v)} placeholder="Add a role" suggestions={ROLE_SUGGEST.slice(0, 10)} /></Row>
          <Row label="Dream companies" hint="Applied to first, every time they post." stack><Chips value={s.companies_priority} onChange={v => ss('companies_priority', v)} placeholder="e.g. Google, Jane Street, Mayo Clinic" /></Row>
          <Row label="Never apply to" stack><Chips value={s.companies_skip} onChange={v => ss('companies_skip', v)} placeholder="Companies to skip" /></Row>
          <Row label="Locations" stack><Chips value={s.locations} onChange={v => ss('locations', v)} placeholder="United States, Remote, New York…" suggestions={['United States', 'Remote', 'New York', 'San Francisco', 'Seattle', 'Boston']} /></Row>
          <Row label="Skip titles with" stack><Chips value={s.exclude} onChange={v => ss('exclude', v)} placeholder="senior, phd…" /></Row>
          <Row label={`Show jobs with fit ${s.min_fit}+`}><Slider value={s.min_fit} min={0} max={95} onChange={v => ss('min_fit', v)} /></Row>
        </Group>
        <div className="mb-3 px-4 text-[13px] text-muted">Your application answers, used on every form</div>
        <div className="mb-8"><ProfileQuestions qs={qs} p={p} setP={setP} showMissing /></div>
        <Group title="Job Applier 4.0">
          <Row label="Update automatically" hint="Installs each tested version on start and every hour, never mid-run."><div className="flex justify-end"><Switch checked={a.auto_update !== false} onChange={v => sa('auto_update', v)} /></div></Row>
          <UpdateRow />
          <Row label="Count my install" hint="Sends a random ID, your OS and the Job Applier 4.0 version once a day, so we know how many people use it. Never your name, resume or applications."><div className="flex justify-end"><Switch checked={a.telemetry !== false} onChange={v => sa('telemetry', v)} /></div></Row>
        </Group>
      </div>
    </Page></div>
  )
}

/* Shows the installed version and installs the newest tested one on demand; the app restarts and the page reloads. */
function UpdateRow() {
  const [st, setSt] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api('/api/update').then(setSt).catch(() => {}) }, [])
  const go = async () => {
    setBusy(true)
    try {
      const r = await api('/api/update', {})
      if (!r.updated) { toast(r.reason || "You're on the newest version."); setSt(r); setBusy(false); return }
      toast.success('Updating', { description: 'Job Applier 4.0 is restarting on the new version.' })
      const t0 = Date.now()
      const wait = async () => {   // reload once the restarted app answers
        await new Promise(res => setTimeout(res, 1500))
        try { await api('/api/update'); location.reload() } catch { if (Date.now() - t0 < 60000) wait(); else setBusy(false) }
      }
      wait()
    } catch (e) { toast.error(e.message); setBusy(false) }
  }
  const hint = !st ? 'Checking…' : !st.managed ? 'Developer copy: update with git pull.'
    : st.available ? `Version ${st.current || '?'} · ${st.latest} is ready` : `Version ${st.current || '?'} · up to date`
  return (
    <Row label="Version" hint={hint}>
      <div className="flex justify-end"><Button variant="white" size="sm" onClick={go} disabled={busy || (st && !st.managed)}>{busy ? 'Updating…' : st?.available ? 'Update now' : 'Check for updates'}</Button></div>
    </Row>
  )
}
