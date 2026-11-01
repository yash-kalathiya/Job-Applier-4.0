import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { Check, CircleSlash, ExternalLink, FileText, Hand, Search } from 'lucide-react'
import { Toaster, toast } from 'sonner'
import { Sky } from '../components/Sky'
import { Avatar, Segmented, spring } from '../components/ui'
import { StarButton } from '../lib/star'

/* your Job Applier 4.0 account from any device. Your agent applies from your own computer (on your
   Claude Code or Codex plan); every application it logs syncs here, with the exact resume it sent. */

const URL = 'https://advktwnedlgnhswpxokg.supabase.co'
const ANON = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFkdmt0d25lZGxnbmhzd3B4b2tnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE1NzkzMTUsImV4cCI6MjA5NzE1NTMxNX0.kPKEMNuqvvzGWKHRSnCtq4vkiYQTicX0wDSiwyYj7LE'
const INSTALL = typeof navigator !== 'undefined' && /windows/i.test(navigator.userAgent)
  ? 'irm apply.twinly.tech/install.ps1 | iex' : 'curl -fsSL apply.twinly.tech/install | bash'
const KEY = 'job_applier:session'
const BLUE = '#0a84ff', GREEN = '#30d158', ORANGE = '#ff9f0a'
const STATUS = { Applied: [GREEN, Check, 'Applied'], 'Needs User': [ORANGE, Hand, 'Needs you'], Skipped: ['#7d869f', CircleSlash, 'Skipped'] }

const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) } catch { return null } }
const save = s => { try { s ? localStorage.setItem(KEY, JSON.stringify(s)) : localStorage.removeItem(KEY) } catch {} }

async function sb(path, session, opts = {}) {
  const r = await fetch(URL + path, { ...opts, headers: { apikey: ANON, Authorization: `Bearer ${session?.access_token || ANON}`, 'Content-Type': 'application/json', ...(opts.headers || {}) } })
  if (!r.ok) throw Object.assign(new Error((await r.json().catch(() => ({}))).message || r.statusText), { status: r.status })
  return r.status === 204 ? null : r.json()
}

async function fresh(s) {
  if (!s) return null
  if (s.expires_at && s.expires_at - 60 > Date.now() / 1000) return s
  try {
    const r = await sb('/auth/v1/token?grant_type=refresh_token', null, { method: 'POST', body: JSON.stringify({ refresh_token: s.refresh_token }) })
    const n = { access_token: r.access_token, refresh_token: r.refresh_token, expires_at: Date.now() / 1000 + r.expires_in, user: r.user }
    save(n); return n
  } catch { save(null); return null }
}

const DEMO = new URLSearchParams(location.search).has('demo')
const DEMO_APPS = [['Stripe', 'Software Engineer Intern', 'Applied'], ['Figma', 'Product Design Intern', 'Applied'], ['Jane Street', 'Quant Trading Intern', 'Needs User'],
  ['Notion', 'Software Engineer Intern, Summer 2027', 'Applied'], ['Databricks', 'Data Science Intern', 'Applied'], ['Roblox', 'Engineering Intern', 'Skipped'],
  ['Pinterest', 'Machine Learning Intern', 'Applied'], ['Ramp', 'Software Engineer Intern', 'Needs User'], ['MongoDB', 'Software Engineering Intern', 'Applied']]
  .map(([company, title, status], i) => ({ id: i, job_key: 'demo' + i, company, title, status, created_at: new Date(Date.now() - i * 9e6).toISOString(),
    notes: status === 'Needs User' ? 'Ready for you to submit' : status === 'Skipped' ? 'Needs an earlier start date' : '', url: '' }))

function signIn() {
  location.href = `${URL}/auth/v1/authorize?` + new URLSearchParams({ provider: 'google', redirect_to: location.origin + '/app' })
}

export default function Dashboard() {
  const [session, setSession] = useState(undefined)
  const [account, setAccount] = useState(null)
  const [apps, setApps] = useState(null)
  const [filter, setFilter] = useState('all')
  const [q, setQ] = useState('')

  useEffect(() => {
    (async () => {
      if (DEMO) { setSession({ demo: true, user: { email: 'demo@jobapplier' } }); return }
      const h = new URLSearchParams(location.hash.slice(1))
      let s = load()
      if (h.get('access_token')) {
        s = { access_token: h.get('access_token'), refresh_token: h.get('refresh_token'), expires_at: Date.now() / 1000 + +(h.get('expires_in') || 3600) }
        history.replaceState(null, '', location.pathname)
        try { s.user = await sb('/auth/v1/user', s) } catch {}
        save(s)
      }
      setSession(await fresh(s))
    })()
  }, [])

  useEffect(() => {
    if (!session) return
    if (session.demo) {
      setAccount({ updated_at: new Date().toISOString(), profile: { name: 'Alex Rivera', school: 'University of Michigan', grad_year: '2028',
        search: { roles: ['software engineer', 'machine learning'], companies_priority: ['Stripe', 'Figma', 'Jane Street'] } }, vault: { experience: [1, 2, 3], projects: [1, 2] } })
      setApps(DEMO_APPS); return
    }
    // signing in here counts as signing up: make sure there's an account row (never overwrites an existing one)
    if (session.user?.id) sb('/rest/v1/job_applier_accounts?on_conflict=user_id', session, { method: 'POST',
      headers: { Prefer: 'resolution=ignore-duplicates,return=minimal' }, body: JSON.stringify([{ user_id: session.user.id }]) }).catch(() => {})
    sb(`/rest/v1/job_applier_accounts?user_id=eq.${session.user?.id}&select=profile,vault,updated_at`, session).then(r => setAccount(r[0] || {})).catch(() => setAccount({}))
    sb('/rest/v1/job_applier_applications?select=*&order=created_at.desc&limit=2000', session).then(rows => {
      const seen = new Set()   // a job can be logged more than once (filled, then submitted): show its latest status
      setApps(rows.filter(r => !seen.has(r.job_key) && seen.add(r.job_key)))
    }).catch(e => { setApps([]); if (e.status === 401) { save(null); setSession(null) } })
  }, [session])

  const shown = useMemo(() => (apps || []).filter(a => (filter === 'all' || a.status === filter) &&
    (!q || `${a.company} ${a.title}`.toLowerCase().includes(q.toLowerCase()))), [apps, filter, q])
  const count = s => (apps || []).filter(a => a.status === s).length
  const week = (apps || []).filter(a => a.status === 'Applied' && Date.now() - new Date(a.created_at) < 7 * 864e5).length
  const p = account?.profile || {}
  const first = (p.name || session?.user?.user_metadata?.full_name || '').split(' ')[0]

  const openResume = async a => {
    try {
      const r = await sb(`/storage/v1/object/sign/job_applier/${a.resume_path.split('/').map(encodeURIComponent).join('/')}`, session, { method: 'POST', body: JSON.stringify({ expiresIn: 600 }) })
      window.open(URL + '/storage/v1' + r.signedURL, '_blank')
    } catch (e) { toast.error('Could not open that resume', { description: e.message }) }
  }
  const signOut = () => { save(null); setSession(null); setApps(null); setAccount(null) }

  return (
    <div className="min-h-screen overflow-x-clip bg-paper text-fg">
      <Toaster theme="dark" position="bottom-center" />
      <header className="glass fixed inset-x-0 top-0 z-50 border-b border-white/[.06]">
        <div className="mx-auto flex h-14 max-w-[1080px] items-center justify-between px-5">
          <a href="/" className="flex items-center gap-2 text-[15px] font-semibold text-white"><Logo />Job Applier 4.0</a>
          {session && <div className="flex items-center gap-4 text-[13.5px]">
            <StarButton compact />
            <span className="hidden text-white/60 sm:block">{session.user?.email}</span>
            <button onClick={signOut} className="text-white/70 hover:text-white">Sign out</button></div>}
        </div>
      </header>
      <div className="relative"><Sky height={420} /></div>

      <main className="relative mx-auto max-w-[1080px] px-5 pb-24 pt-28">
        {session === undefined ? <div className="h-[60vh]" />
          : !session ? <SignedOut />
          : <>
            <motion.h1 initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={spring} className="text-[44px] font-bold tracking-[-0.035em] text-white">
              {first ? `Hi, ${first}.` : 'Your applications'}</motion.h1>
            {apps && apps.length > 0 && <>
              <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.08 }} className="mt-2 text-[22px] font-medium tracking-[-0.02em] text-white/85">
                <span className="text-white">{count('Applied').toLocaleString()}</span> applications sent{count('Needs User') ? <>, <span style={{ color: ORANGE }}>{count('Needs User')} waiting on you</span></> : ''}.</motion.p>
              <p className="mt-1 text-[13.5px] text-white/50">{account?.updated_at ? `Last synced ${new Date(account.updated_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}` : ''}</p>
              <section className="mt-7 grid grid-cols-2 gap-3 md:grid-cols-4">
                {[['Applied', count('Applied'), GREEN], ['Waiting on you', count('Needs User'), ORANGE], ['This week', week, BLUE], ['Skipped', count('Skipped'), '#7d869f']].map(([l, v, c], i) => (
                  <motion.div key={l} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring, delay: 0.1 + i * 0.05 }}
                    className="rounded-[20px] bg-[#111526]/90 px-5 py-4 ring-1 ring-white/[.06] backdrop-blur">
                    <div className="text-[34px] font-semibold leading-none tracking-[-0.04em] text-white tabular-nums">{v.toLocaleString()}</div>
                    <div className="mt-2 text-[13px] text-muted">{l}</div>
                  </motion.div>))}
              </section>
            </>}
            {apps && apps.length === 0 && <Connect />}
            {!apps && <div className="mt-7 h-[86px] animate-pulse rounded-[20px] bg-white/[.04]" />}

            {apps && apps.length > 0 && <div className="mt-8 grid gap-8 lg:grid-cols-[1.6fr_1fr]">
              <section className="min-w-0">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3 px-1">
                  <h2 className="text-[20px] font-semibold tracking-[-0.02em] text-white">Applications</h2>
                  <Segmented id="flt" value={filter} onChange={setFilter} options={[['all', 'All'], ['Applied', 'Applied'], ['Needs User', 'Needs you'], ['Skipped', 'Skipped']]} />
                </div>
                <div className="overflow-hidden rounded-[18px] bg-[#111526] ring-1 ring-white/[.06]">
                  <label className="flex items-center gap-2.5 border-b border-white/[.06] px-4 py-2.5">
                    <Search className="size-4 text-white/35" />
                    <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search companies and roles" className="w-full bg-transparent text-[14px] text-white outline-none placeholder:text-faint" />
                  </label>
                  <div className="max-h-[640px] overflow-y-auto [&>*+*]:border-t [&>*+*]:border-white/[.06]">
                    <AnimatePresence initial={false}>
                      {shown.slice(0, 300).map(a => <AppRow key={a.id} a={a} onResume={() => openResume(a)} />)}
                    </AnimatePresence>
                    {apps && !shown.length && <div className="px-5 py-12 text-center text-[14px] text-muted">
                      {apps.length ? 'Nothing matches.' : 'No applications yet. Start your twin on your computer and they appear here.'}</div>}
                    {!apps && <div className="px-5 py-12 text-center text-[13px] text-faint">Loading…</div>}
                  </div>
                </div>
              </section>

              <aside className="min-w-0 space-y-8">
                <Group title="Your profile" footer="Edit it in the Job Applier 4.0 app on your computer; it syncs here.">
                  {[['Name', p.name], ['School', [p.school, p.grad_year && `class of ${p.grad_year}`].filter(Boolean).join(', ')],
                    ['Looking for', (p.search?.roles || []).slice(0, 4).join(', ')], ['Dream companies', (p.search?.companies_priority || []).slice(0, 5).join(', ')],
                    ['Resume', account?.vault?.experience ? `${account.vault.experience.length} roles · ${(account.vault.projects || []).length} projects` : '']]
                    .filter(([, v]) => v).map(([k, v]) => (
                      <div key={k} className="flex items-baseline justify-between gap-4 px-4 py-3 text-[14px]"><span className="shrink-0 text-muted">{k}</span><span className="truncate text-right text-white">{v}</span></div>))}
                  {account && !p.name && <div className="px-4 py-4 text-[14px] text-muted">Sign in from the Job Applier 4.0 app on your computer to sync your profile.</div>}
                </Group>
                <Group title="Run your twin" footer="Applications are filled on your computer, through the Claude Code or Codex plan you already pay for. No API keys.">
                  <div className="px-4 py-3.5"><Install /></div>
                </Group>
              </aside>
            </div>}
          </>}
      </main>
    </div>
  )
}

function Connect() {
  const steps = [['Install Job Applier 4.0 on your computer', 'One line in your terminal. It runs on your Claude Code or Codex plan, no API keys.', true],
    ['Open it and press Sign in', 'Use your local account.'],
    ['Press Start in Autopilot', 'Every application your agent fills shows up here, with the exact resume it sent.']]
  return (
    <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={spring} className="mt-7 max-w-[640px]">
      <p className="text-[17px] text-white/75">Your account is ready. Connect your computer and your applications appear here.</p>
      <div className="mt-5 overflow-hidden rounded-[20px] bg-[#111526]/90 ring-1 ring-white/[.06] backdrop-blur [&>*+*]:border-t [&>*+*]:border-white/[.06]">
        {steps.map(([t, d, install], i) => (
          <div key={t} className="flex gap-4 px-5 py-4">
            <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full text-[13px] font-semibold text-white ring-1 ring-white/20">{i + 1}</span>
            <div className="min-w-0 flex-1"><div className="text-[15px] font-medium text-white">{t}</div>
              <div className="mt-0.5 text-[13.5px] text-muted">{d}</div>{install && <div className="mt-3"><Install /></div>}</div>
          </div>))}
      </div>
    </motion.section>
  )
}

function SignedOut() {
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={spring} className="mx-auto max-w-[520px] pt-10 text-center">
      <h1 className="text-[48px] font-bold leading-[1] tracking-[-0.04em] text-white">Your applications, anywhere.</h1>
      <p className="mx-auto mt-4 max-w-[420px] text-[17px] text-white/75">Sign in to Job Applier 4.0 to see every application sent, and the resume sent with each one.</p>
      <motion.button whileTap={{ scale: 0.96 }} onClick={signIn} className="mx-auto mt-8 flex h-12 items-center gap-2.5 rounded-full bg-white px-7 text-[16px] font-semibold text-[#0b1020]">
        <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" /><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" /><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" /><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" /></svg>
        Sign in</motion.button>
      <p className="mt-10 text-[14px] text-white/55">New to Job Applier 4.0? Install it first:</p>
      <div className="mx-auto mt-3 max-w-[520px] text-left"><Install /></div>
    </motion.div>
  )
}

function AppRow({ a, onResume }) {
  const [color, Icon, text] = STATUS[a.status] || ['#98a2c3', Check, a.status]
  return (
    <motion.div layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-3.5 px-4 py-3">
      <Avatar name={a.company} size={32} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14.5px] text-white">{a.title}</div>
        <div className="truncate text-[12.5px] text-muted">{a.company} · {new Date(a.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}{a.notes ? ` · ${a.notes}` : ''}</div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        {a.resume_path && <button onClick={onResume} title="The resume it sent" className="text-white/40 hover:text-white"><FileText className="size-4" /></button>}
        {a.url && <a href={a.url} target="_blank" rel="noreferrer" title="Open the posting" className="text-white/40 hover:text-white"><ExternalLink className="size-4" /></a>}
        <span className="flex w-[92px] items-center justify-end gap-1.5 text-[13px] font-medium" style={{ color }}><Icon className="size-3.5" />{text}</span>
      </div>
    </motion.div>
  )
}

function Group({ title, footer, children }) {
  return (
    <section>
      <h2 className="mb-2.5 px-1 text-[20px] font-semibold tracking-[-0.02em] text-white">{title}</h2>
      <div className="overflow-hidden rounded-[18px] bg-[#111526] ring-1 ring-white/[.06] [&>*+*]:border-t [&>*+*]:border-white/[.06]">{children}</div>
      {footer && <p className="mt-2 px-1 text-[12.5px] leading-relaxed text-faint">{footer}</p>}
    </section>
  )
}

function Install() {
  const [ok, setOk] = useState(false)
  return (
    <button onClick={() => { navigator.clipboard.writeText(INSTALL); setOk(true); setTimeout(() => setOk(false), 1500) }}
      className="flex w-full items-center gap-3 rounded-[12px] bg-black/40 px-3.5 py-3 text-left ring-1 ring-white/10 hover:ring-white/25">
      <span className="min-w-0 flex-1 break-words font-mono text-[12.5px] leading-snug text-white">{INSTALL}</span>
      <span className="shrink-0 text-[12.5px] font-semibold" style={{ color: ok ? GREEN : BLUE }}>{ok ? 'Copied' : 'Copy'}</span>
    </button>
  )
}

function Logo({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden><defs><linearGradient id="lg2" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#38bdf8" /><stop offset="1" stopColor="#a78bfa" /></linearGradient></defs>
      <rect x="4" y="4" width="38" height="38" rx="12" fill="url(#lg2)" /><rect x="22" y="22" width="38" height="38" rx="12" fill="#fff" fillOpacity=".85" /></svg>
  )
}
