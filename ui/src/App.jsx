import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Toaster, toast } from 'sonner'
import { Radar, Sparkles, FileText, Upload } from 'lucide-react'
import { api } from './lib/api'
import { Logo, TopBar, Palette, Sidebar } from './components/Shell'
import { Sky } from './components/Sky'
import Home from './pages/Home'
import Jobs from './pages/Jobs'
import Studio from './pages/Studio'
import Answers from './pages/Answers'
import Board from './pages/Board'
import Settings from './pages/Settings'
import Agents from './pages/Agents'
import Welcome from './pages/Welcome'

const Ctx = createContext(null)
export const useApp = () => useContext(Ctx)
const PAGES = { home: Home, jobs: Jobs, studio: Studio, answers: Answers, board: Board, settings: Settings, agents: Agents, welcome: Welcome }

/* After an update the open page reloads itself onto the new version, so the page and the app never disagree.
   It waits until the tab is in the background or you've been idle a minute, so nothing you're in the middle of is lost. */
function keepCurrent() {
  const mine = (document.querySelector('script[src*="assets/index-"]')?.getAttribute('src') || '').split('/').pop()
  if (!mine) return
  let stale = false, last = Date.now()
  const touch = () => { last = Date.now() }
  addEventListener('pointerdown', touch); addEventListener('keydown', touch)
  const check = async () => {
    try { const v = await api('/api/version'); if (v.ui && v.ui !== mine) stale = true } catch { /* restarting; try next time */ }
    if (stale && !location.hash.startsWith('#welcome') && (document.hidden || Date.now() - last > 60000)) location.reload()   // never mid-setup
  }
  const t = setInterval(check, 20000)
  const vis = () => { if (!document.hidden) check() }
  document.addEventListener('visibilitychange', vis)
  return () => { clearInterval(t); document.removeEventListener('visibilitychange', vis); removeEventListener('pointerdown', touch); removeEventListener('keydown', touch) }
}

export default function App() {
  const parse = () => { const raw = location.hash.slice(1); if (raw.includes('access_token=')) return { page: 'home' }; const [p, arg] = (raw || 'home').split('/'); return { page: PAGES[p] ? p : 'home', arg } }
  const [route, setRoute] = useState(parse)
  const [state, setState] = useState(null)
  const [palette, setPalette] = useState(false)
  const [jobs, setJobs] = useState([])
  const [scan, setScan] = useState(null)

  const [auth, setAuth] = useState({ signed_in: false })
  const [authReady, setAuthReady] = useState(false)
  const [loadErr, setLoadErr] = useState(null)
  const [wide, setWide] = useState(() => matchMedia('(min-width: 768px)').matches)
  useEffect(() => { const m = matchMedia('(min-width: 768px)'); const f = () => setWide(m.matches); m.addEventListener('change', f); return () => m.removeEventListener('change', f) }, [])
  const refresh = useCallback(async () => {
    try { const s = await api('/api/state'); setState(s); setLoadErr(null); return s }
    catch (e) { setLoadErr(e.message || "Couldn't reach Job Applier 4.0"); return null }
  }, [])
  useEffect(() => {
    if (location.hash.includes('access_token=')) history.replaceState(null, '', location.pathname)
    api('/api/auth').then(setAuth).catch(() => {}).finally(() => setAuthReady(true))
  }, [])
  const signIn = async (email, password) => {
    await api('/api/auth/login', { email, password })
    location.reload()
  }
  const signOut = async () => { await api('/api/auth/logout', {}); location.reload() }
  useEffect(() => {   // first time only: once setup is finished, an empty resume never sends you back into it
    if (state && !state.profile?.onboarded && (!location.hash || location.hash === '#home') && !(state.vault?.experience?.length || state.vault?.projects?.length)) location.hash = 'welcome'
  }, [state])
  const loadJobs = useCallback(() => api('/api/jobs?limit=200').then(setJobs), [])
  useEffect(() => { if (auth.signed_in) { refresh(); loadJobs().catch(() => {}) } }, [refresh, loadJobs, auth.signed_in])
  useEffect(() => { if (auth.signed_in) return keepCurrent() }, [auth.signed_in])
  useEffect(() => { const f = () => { setRoute(parse()); window.scrollTo({ top: 0 }) }; window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f) }, [])
  const go = (page, arg) => { location.hash = arg ? `${page}/${arg}` : page }

  const startScan = async () => {
    await api('/api/scan', {})
    const id = toast.loading('Scanning every career page…', { description: 'SimplifyJobs, SmartRecruiters, Greenhouse, Lever, Ashby, Workday' })
    const tick = async () => {
      const s = await api('/api/scan'); setScan(s)
      const st = s.stats || {}
      if (s.running) {
        toast.loading(`Read ${(st.fetched || 0).toLocaleString()} postings`, { id, description: `${st.done || 0} of ${st.sources || '…'} sources · ${st.new || 0} new` })
        return setTimeout(tick, 1000)
      }
      toast.success(`${st.new || 0} new jobs, ${st.matched || 0} strong matches`, { id, description: `${(st.fetched || 0).toLocaleString()} postings read` })
      refresh(); loadJobs()
    }
    tick()
  }
  const actions = [['Scan for new jobs', Radar, startScan], ['Open Resume Studio', FileText, () => go('studio')],
    ['Import a resume', Upload, () => go('studio', 'import')], ['Connect Claude or Codex', Sparkles, () => go('agents')]]

  if (!authReady) return <Loading />
  if (!auth.signed_in) return <SignInGate signIn={signIn} />
  if (!state && loadErr) return (
    <div className="grid h-full place-items-center px-6 text-center">
      <div><div className="text-[22px] font-semibold text-white">Job Applier 4.0 isn't answering</div>
        <p className="mt-2 text-[15px] text-muted">It may be restarting after an update. {loadErr}</p>
        <button onClick={refresh} className="mt-6 h-10 rounded-full bg-signal px-6 text-[15px] font-semibold text-white">Try again</button></div>
    </div>)
  if (!state || !authReady) return <Loading />
  if (!auth.signed_in) return <SignInGate signIn={signIn} />
  const Page = PAGES[route.page]
  return (
    <Ctx.Provider value={{ ...state, refresh, go, jobs, loadJobs, startScan, scan, setState, auth, signIn, signOut }}>
      {route.page !== 'welcome' && (wide   // only the layout on screen is mounted, so nothing polls twice
        ? <Sidebar page={route.page} go={go} onPalette={() => setPalette(true)} auth={auth} signIn={signIn} signOut={signOut} />
        : <TopBar page={route.page} go={go} onPalette={() => setPalette(true)} matched={state.stats?.matched} auth={auth} signIn={signIn} signOut={signOut} />)}
      <Palette open={palette} setOpen={setPalette} go={go} jobs={jobs} actions={actions} />
      <motion.main key={route.page} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.2, ease: 'easeOut' }}
        className={'relative min-h-full ' + (route.page !== 'welcome' ? 'md:pl-[220px]' : '')}>
        <Page arg={route.arg} />
      </motion.main>
      <Toaster theme="dark" position="bottom-center" toastOptions={{ style: { borderRadius: 14, background: '#2c2c2e', border: '1px solid rgb(255 255 255 / .08)', color: '#fff' } }} />
    </Ctx.Provider>
  )
}

function SignInGate({ signIn }) {
  const [busy, setBusy] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const go = async e => {
    e.preventDefault(); setBusy(true); setError('')
    try { await signIn(email, password) }
    catch (e) { setPassword(''); setError(e.message); setBusy(false) }
  }
  return (
    <div className="relative grid min-h-full place-items-center overflow-hidden px-6">
      <Sky height={420} />
      <div className="relative w-full max-w-[420px] text-center">
        <div className="flex justify-center"><Logo size={56} /></div>
        <h1 className="mt-7 text-[34px] font-bold tracking-tight text-white">Sign in to Job Applier 4.0</h1>
        <p className="mt-3 text-[15px] text-white/65">Your private account on this computer. Cloud sync is disabled.</p>
        <form onSubmit={go} className="mx-auto mt-8 max-w-[340px] space-y-4 text-left">
          <label className="block text-sm text-white/80">Email
            <input type="email" autoComplete="username" required value={email} onChange={e => setEmail(e.target.value)}
              className="mt-2 h-12 w-full rounded-xl border border-white/20 bg-black/30 px-4 text-white" />
          </label>
          <label className="block text-sm text-white/80">App password
            <input type="password" autoComplete="current-password" required maxLength={1024} value={password} onChange={e => setPassword(e.target.value)}
              className="mt-2 h-12 w-full rounded-xl border border-white/20 bg-black/30 px-4 text-white" />
          </label>
          {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
          <button disabled={busy} className="h-12 w-full rounded-full bg-white font-semibold text-black disabled:opacity-60">
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="mt-5 text-xs text-white/40">Use your local Job Applier 4.0 password here, separate from your email password.</p>
      </div>
    </div>
  )
}

function Loading() {
  return <div className="grid h-full place-items-center"><motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: 'linear' }}
    className="size-7 rounded-full border-[3px] border-sky/25 border-t-sky" /></div>
}

export function Page({ children, wide }) {
  return <div className={`relative mx-auto px-6 pb-24 pt-20 md:px-10 md:pt-16 ${wide ? 'max-w-[1320px]' : 'max-w-[1180px]'}`}>{children}</div>
}

