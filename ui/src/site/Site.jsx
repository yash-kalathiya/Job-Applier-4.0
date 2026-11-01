import { Suspense, lazy, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useInView, useMotionValueEvent, useScroll, useTransform, useReducedMotion } from 'motion/react'
import { Check, ChevronRight, Copy, Laptop, Lock, KeyRound, ShieldCheck } from 'lucide-react'
import { Toaster } from 'sonner'
import { Avatar } from '../components/ui'
import { REPO_URL, useStars } from '../lib/star'
import './site.css'

/* public home of Job Applier 4.0, built the way Apple builds a product page. Plain surfaces, the
   system font, one blue, real product UI instead of decoration. The app runs on each person's own computer, on the
   Claude Code or Codex plan they already pay for, so the page's one job is a calm, one-line setup. */

const INSTALL = 'curl -fsSL https://raw.githubusercontent.com/yash-kalathiya/Job-Applier-4.0/main/install.sh | bash'
const INSTALL_WIN = 'irm https://raw.githubusercontent.com/yash-kalathiya/Job-Applier-4.0/main/scripts/install-remote.ps1 | iex'
const IS_WIN = typeof navigator !== 'undefined' && /windows/i.test(navigator.userAgent)

const FAQ = [
  ['Do I need an API key?', 'No. Job Applier 4.0 runs on the Claude Code or Codex subscription you already have. If you can use either one in a terminal, you can use Job Applier 4.0.'],
  ['Where does my data live?', 'On your computer, in a folder called ~/.job-applier.'],
  ['Will it submit applications without me?', 'Only if you turn that on. Otherwise it fills every form and stops on the review screen, so you press Submit.'],
  ['What will it never do?', 'Type your passwords, solve CAPTCHAs, create accounts, accept legal agreements, or invent a single fact about you. Those come to you instead.'],
  ['Does it work on Windows?', 'Yes. Mac, Windows and Linux. On Windows, paste the PowerShell command.'],
  ['Is it only for software jobs?', 'No. It knows what a strong resume looks like in your field, from nursing and finance to design, research and engineering.'],
  ['What does it cost?', 'Nothing. Job Applier 4.0 is free.'],
]
// Apple's motion: long, eased, small. Nothing bounces; things settle.
function Reveal({ children, className, delay = 0 }) {
  return (
    <motion.div className={className} initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-40px' }} transition={{ duration: 0.9, ease: [0.25, 0.1, 0.25, 1], delay }}>{children}</motion.div>
  )
}
const EASE = [0.25, 0.1, 0.25, 1]
const rise = (delay = 0) => ({ initial: { opacity: 0, y: 28 }, animate: { opacity: 1, y: 0 }, transition: { duration: 1.1, ease: EASE, delay } })

const Fan3D = lazy(() => import('./Fan3D'))   // three.js loads after the page is up
const webgl = () => { try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')) } catch { return false } }

const COMPANIES = [['Google', 'google.com'], ['Meta', 'meta.com'], ['Apple', 'apple.com'], ['NVIDIA', 'nvidia.com'], ['Jane Street', 'janestreet.com'],
  ['Citadel', 'citadel.com'], ['Palantir', 'palantir.com'], ['Anduril', 'anduril.com'], ['Stripe', 'stripe.com'], ['Microsoft', 'microsoft.com'],
  ['Amazon', 'amazon.com'], ['Two Sigma', 'twosigma.com']]

export default function Site() {
  return (
    <div className="site min-h-screen overflow-x-clip">
      <Toaster position="bottom-center" />
      <Nav />

      <section className="px-4 pb-10 pt-28 text-center sm:pt-36">
        <motion.div {...rise(0)} className="text-[19px] font-semibold sm:text-[21px]">Job Applier 4.0</motion.div>
        <h1 className="display mx-auto mt-2 max-w-[920px] text-[44px] font-semibold leading-[1.06] sm:text-[72px] sm:leading-[1.04]">
          <motion.span {...rise(0.12)} className="block">You apply once.</motion.span>
          <motion.span {...rise(0.32)} className="block muted">Your twin does the rest.</motion.span>
        </h1>
        <motion.p {...rise(0.55)} className="mx-auto mt-5 max-w-[640px] text-[19px] leading-[1.42] sm:text-[21px]">
          It finds every role that fits you, writes a tailored resume for each one, and fills out the application.
          On the Claude Code or Codex plan you already have. Free.
        </motion.p>
        <motion.div {...rise(0.7)} className="mt-8 flex flex-wrap items-center justify-center gap-x-7 gap-y-3">
          <a href="#start" className="btn">Get Job Applier 4.0</a>
          <a href="#how" className="link inline-flex items-center text-[17px]">See how it works<ChevronRight className="size-4" /></a>
        </motion.div>
      </section>

      <OneToMany />

      <section className="px-4 pb-24"><Lid><AppWindow /></Lid></section>

      <Becomes />

      <section id="how" className="bg-[var(--bg)] px-4 pb-24">
        <Reveal className="mx-auto max-w-[980px] text-center">
          <h2 className="display text-[40px] font-semibold leading-[1.08] sm:text-[56px]">Every step of applying.<br /><span className="muted">Done for you.</span></h2>
        </Reveal>
        <div className="mx-auto mt-14 grid max-w-[1080px] gap-5 md:grid-cols-2">
          <Tile title="Finds every role." text="It reads thousands of company job boards and keeps only the roles that fit you: your field, your cycle, your locations.">
            <Roles />
          </Tile>
          <Tile title="A new resume for every job." text="Your strongest true experience, rewritten for each posting and fitted to one clean page. It never invents a fact.">
            <Stack />
          </Tile>
          <Tile title="Fills the whole form." text="Work authorization, graduation date, address, even the short essays. Answered once in setup, used everywhere.">
            <Form />
          </Tile>
          <Tile title="Only asks what matters." text="A sign-in, a code, a question only you can answer. It pings you, keeps going, and finishes when you're done.">
            <Ask />
          </Tile>
        </div>
      </section>

      <section className="px-4 pb-24">
        <Reveal className="tile mx-auto max-w-[1080px] px-6 py-14 text-center sm:px-16 sm:py-20">
          <Laptop className="mx-auto size-10 text-[var(--fg)]" strokeWidth={1.4} />
          <h2 className="display mx-auto mt-5 max-w-[720px] text-[34px] font-semibold leading-[1.1] sm:text-[48px]">Runs on the plan you already pay for.</h2>
          <p className="mx-auto mt-4 max-w-[600px] text-[19px] leading-[1.45] muted">
            Job Applier 4.0 works through Claude Code or Codex on your own computer. No API keys, no new subscription, nothing to configure.
          </p>
        </Reveal>
      </section>

      <section className="px-4 pb-24">
        <Reveal className="mx-auto max-w-[980px] text-center">
          <h2 className="display text-[34px] font-semibold leading-[1.1] sm:text-[48px]">Roles at companies like these.</h2>
        </Reveal>
        <Reveal delay={0.05} className="mx-auto mt-10 grid max-w-[980px] grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6">
          {COMPANIES.map(([c, d]) => (
            <div key={c} className="tile flex flex-col items-center gap-2 rounded-[18px] px-2 py-5">
              <Avatar name={c} domain={d} size={36} /><span className="text-[13px] font-medium">{c}</span>
            </div>))}
        </Reveal>
      </section>

      <section className="px-4 pb-24">
        <div className="mx-auto grid max-w-[1080px] gap-5 md:grid-cols-3">
          {[[Lock, 'Your data stays yours.', 'Everything lives on your computer. Sign in only to back it up.'],
            [KeyRound, 'Never your passwords.', 'It never types a password, solves a CAPTCHA or creates an account for you.'],
            [ShieldCheck, 'Never a made-up fact.', 'Every bullet and answer comes from what you told it. A fact checker blocks the rest.']].map(([I, t, d]) => (
            <Reveal key={t} className="tile px-7 py-9">
              <I className="size-7 text-[var(--fg)]" strokeWidth={1.6} />
              <div className="display mt-4 text-[24px] font-semibold leading-tight">{t}</div>
              <p className="mt-2 text-[17px] leading-[1.45] muted">{d}</p>
            </Reveal>))}
        </div>
      </section>

      <section id="start" className="px-4 pb-24">
        <Reveal className="mx-auto max-w-[760px] text-center">
          <h2 className="display text-[40px] font-semibold leading-[1.08] sm:text-[56px]">Set up in one line.</h2>
          <p className="mx-auto mt-4 max-w-[560px] text-[19px] leading-[1.45] muted">Paste this into your terminal. It installs Job Applier 4.0, connects your agent and opens the app.</p>
          <div className="mt-9 text-left"><InstallBox /></div>
          <p className="mt-3 text-[14px] faint">Mac, Windows and Linux. Needs Python 3.9+, Node.js, and Claude Code or Codex.</p>
        </Reveal>
        <div className="mx-auto mt-12 grid max-w-[760px] gap-4 sm:grid-cols-3">
          {[['1', 'Paste the command', 'in Terminal, or PowerShell on Windows.'], ['2', 'Drop in your resume', 'and answer the setup questions once.'],
            ['3', 'Press Start', 'and watch your agent apply in its own window.']].map(([n, t, d]) => (
            <Reveal key={n} className="text-center sm:text-left">
              <div className="mx-auto grid size-8 place-items-center rounded-full bg-[var(--fg)] text-[15px] font-semibold text-[var(--bg)] sm:mx-0">{n}</div>
              <div className="mt-3 text-[17px] font-semibold">{t}</div>
              <div className="text-[15px] muted">{d}</div>
            </Reveal>))}
        </div>
      </section>

      <section id="faq" className="px-4 pb-24">
        <div className="mx-auto max-w-[760px]">
          <Reveal><h2 className="display mb-6 text-[32px] font-semibold sm:text-[40px]">Questions</h2></Reveal>
          <Reveal delay={0.05}><div className="group overflow-hidden">{FAQ.map(([q, a]) => <Faq key={q} q={q} a={a} />)}</div></Reveal>
        </div>
      </section>

      <section className="px-4 pb-24">
        <Reveal className="mx-auto max-w-[760px] text-center">
          <h2 className="display text-[44px] font-semibold leading-[1.05] sm:text-[64px]">Get hired.</h2>
          <p className="mx-auto mt-4 max-w-[520px] text-[19px] muted">Job Applier 4.0 is free and has no ads. A star on GitHub is how other students find it.</p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-x-7 gap-y-3">
            <a href="#start" className="btn">Get Job Applier 4.0</a>
            <Stars />
          </div>
        </Reveal>
      </section>

      <footer className="border-t border-[var(--line)] bg-[var(--bg-2)] px-4 py-8 text-[12px] faint">
        <div className="mx-auto flex max-w-[1080px] flex-wrap items-center justify-between gap-3">
          <span>Copyright © 2026 Job Applier 4.0 Authors.</span>
          <span className="flex gap-5"><a href={REPO_URL} target="_blank" rel="noreferrer" className="hover:underline">GitHub</a></span>
        </div>
      </footer>
    </div>
  )
}

function Nav() {
  return (
    <header className="nav fixed inset-x-0 top-0 z-50">
      <div className="mx-auto flex h-12 max-w-[1080px] items-center justify-between px-4">
        <a href="#" className="flex items-center gap-2 text-[15px] font-semibold"><Logo size={18} />Job Applier 4.0</a>
        <nav className="flex items-center gap-5 text-[13px]">
          <a href="#how" className="hidden opacity-80 hover:opacity-100 sm:block">How it works</a>
          <a href="#faq" className="hidden opacity-80 hover:opacity-100 sm:block">Questions</a>
          <a href="/app" className="hidden opacity-80 hover:opacity-100 sm:block">Account</a>
          <a href="#start" className="rounded-full bg-[var(--blue)] px-3.5 py-1 text-[13px] font-medium text-white">Get</a>
        </nav>
      </div>
    </header>
  )
}

/* One resume becomes many, in 3D: pinned while you scroll, the stack fans out into versions tailored for each company. */
function OneToMany() {
  const ref = useRef(null)
  const progress = useRef(0)
  const [ok] = useState(() => typeof window !== 'undefined' && webgl())
  const [show, setShow] = useState(false)
  const near = useInView(ref, { margin: '400px 0px' })
  useEffect(() => { if (near) setShow(true) }, [near])
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })
  const [p, setP] = useState(0)
  useMotionValueEvent(scrollYProgress, 'change', v => { progress.current = v; setP(v) })
  if (!ok) return null
  return (
    <section ref={ref} className="relative h-[230vh]">
      <div className="sticky top-0 h-screen overflow-hidden">
        <div className="pointer-events-none absolute inset-x-0 top-[12vh] z-10 px-4 text-center">
          <h2 className="display text-[40px] font-semibold leading-[1.06] sm:text-[56px]">
            <span style={{ opacity: 1 - Math.min(1, p * 3) * 0.0 }}>One resume.</span><br />
            <motion.span className="muted" animate={{ opacity: p > 0.25 ? 1 : 0.25 }} transition={{ duration: 0.6, ease: EASE }}>Tailored for every role.</motion.span>
          </h2>
        </div>
        <div className="absolute inset-x-0 bottom-0 top-[20vh]">
          {show && <Suspense fallback={null}><Fan3D progress={progress} /></Suspense>}
        </div>
      </div>
    </section>
  )
}

/* The heart of it, pinned while you scroll: a job's requirements light up one by one, and the resume rewrites itself
   to prove each one. A well-known public resume; every rewrite keeps the original facts, as the real fact checker requires. */
const ROLE = { company: 'NASA', domain: 'nasa.gov', title: 'Human Spaceflight Program Lead' }
// Elon Musk's public record, tailored for one role: every "after" line is a real, public fact about him
const STEPS = [
  { req: 'Has built and scaled organizations',
    before: 'Started a few companies.',
    after: <>Co-founded <b>Zip2</b>, sold to Compaq for <b>$307M</b>, and <b>X.com</b>, which became <b>PayPal</b>.</> },
  { req: 'Launch vehicle experience',
    before: 'Worked on rockets.',
    after: <>Founded <b>SpaceX</b> in 2002; Falcon 9 became the first orbital-class rocket to <b>land and reuse</b> its first stage.</> },
  { req: 'Engineering at scale',
    before: 'Runs a car company.',
    after: <>CEO of <b>Tesla</b> since 2008, scaling it to <b>millions of electric vehicles</b> a year.</> },
]

function Becomes() {
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })
  const [p, setP] = useState(0)
  useMotionValueEvent(scrollYProgress, 'change', setP)
  const still = useReducedMotion()
  const at = i => (still ? 1 : Math.min(1, Math.max(0, (p - (0.12 + i * 0.24)) / 0.14)))
  const done = STEPS.filter((_, i) => at(i) >= 1).length
  const match = Math.round(38 + (94 - 38) * Math.min(1, (at(0) + at(1) + at(2)) / 3))
  const role = at(0) > 0.5
  return (
    <section ref={ref} className="relative h-auto px-4 md:h-[320vh]">
      <div className="mx-auto max-w-[1080px] md:sticky md:top-0 md:flex md:h-screen md:flex-col md:justify-center md:py-10">
        <div className="text-center">
          <h2 className="display text-[40px] font-semibold leading-[1.06] sm:text-[56px]">The right candidate.<br /><span className="muted">For every single role.</span></h2>
          <p className="mx-auto mt-4 max-w-[600px] text-[19px] leading-[1.45] muted">Your twin reads what this team screens for, then rewrites your real experience to prove it. Nothing invented.</p>
        </div>
        <div className="mt-10 grid gap-5 md:grid-cols-[0.9fr_1.1fr]">
          <div className="tile p-6 sm:p-8">
            <div className="flex items-center gap-3"><Avatar name={ROLE.company} domain={ROLE.domain} size={36} />
              <div><div className="text-[15px] font-semibold">{ROLE.title}</div><div className="text-[13px] muted">{ROLE.company}</div></div></div>
            <div className="mt-6 text-[12px] font-semibold uppercase tracking-[0.05em] faint">What they screen for</div>
            <div className="mt-3 space-y-2.5">
              {STEPS.map((s, i) => (
                <div key={s.req} className="flex items-center gap-3 rounded-[12px] px-3 py-2.5 transition-colors duration-500"
                  style={{ background: at(i) > 0 ? 'var(--bg-3)' : 'transparent' }}>
                  <span className="grid size-6 shrink-0 place-items-center rounded-full text-[12px] font-semibold transition-colors duration-500"
                    style={{ background: at(i) >= 1 ? 'var(--green)' : at(i) > 0 ? 'var(--blue)' : 'var(--line)', color: at(i) > 0 ? '#fff' : 'var(--fg-3)' }}>
                    {at(i) >= 1 ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}</span>
                  <span className={'text-[16px] transition-colors duration-500 ' + (at(i) > 0 ? '' : 'faint')}>{s.req}</span>
                </div>))}
            </div>
            <div className="mt-8 flex items-end justify-between">
              <div className="text-[13px] muted">Match for this role</div>
              <div className="display text-[44px] font-semibold tabular-nums leading-none" style={{ color: done === 3 ? 'var(--green)' : 'var(--fg)' }}>{match}%</div>
            </div>
          </div>
          <div className="sheet p-6 text-left sm:p-8" style={{ fontFamily: 'Georgia, "Times New Roman", serif' }}>
            <div className="text-center text-[22px] font-bold tracking-[0.04em]">ELON MUSK</div>
            <div className="relative mt-1 h-[20px] overflow-hidden text-center text-[13px] font-semibold">
              <AnimatePresence mode="popLayout" initial={false}>
                <motion.div key={role ? 'r' : 'g'} initial={{ y: 14, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -14, opacity: 0 }}
                  transition={{ duration: 0.5, ease: EASE }}>
                  {role ? 'Human Spaceflight · Reusable Rockets · Engineering Leadership' : 'Entrepreneur'}
                </motion.div>
              </AnimatePresence>
            </div>
            <div className="mt-5 border-b border-[var(--line)] pb-1 text-[12px] font-semibold tracking-[0.08em]">EXPERIENCE & PROJECTS</div>
            <div className="mt-3 space-y-4">
              {STEPS.map((s, i) => {
                const k = at(i)
                return (
                  <div key={s.req} className="relative grid text-[15px] leading-[1.45]">
                    <div className="col-start-1 row-start-1 flex gap-2 muted" style={{ opacity: 1 - k, filter: `blur(${k * 3}px)` }}>
                      <span>•</span><span>{s.before}</span></div>
                    <div className="col-start-1 row-start-1 flex gap-2" style={{ opacity: k, transform: `translateY(${(1 - k) * 8}px)` }}>
                      <span style={{ color: 'var(--blue)' }}>•</span><span>{s.after}</span></div>
                  </div>)
              })}
            </div>
            <div className="mt-6 flex flex-wrap gap-2" style={{ fontFamily: 'inherit' }}>
              {['reusable rockets', 'human spaceflight', 'scaling teams', 'physics', 'manufacturing'].map((w, i) => (
                <span key={w} className="rounded-full px-3 py-1 text-[12.5px] font-semibold text-[var(--bg)] transition-all duration-500"
                  style={{ background: 'var(--fg)', opacity: done > i * 0.6 ? 1 : 0, transform: `scale(${done > i * 0.6 ? 1 : 0.85})`,
                    fontFamily: '-apple-system, BlinkMacSystemFont, system-ui, sans-serif' }}>{w}</span>))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

/* As it scrolls in, the window tilts up toward you and settles flat, the way Apple opens a MacBook on its pages. */
function Lid({ children }) {
  const ref = useRef(null)
  const still = useReducedMotion()
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start end', 'center center'] })
  const rotateX = useTransform(scrollYProgress, [0, 1], [24, 0])
  const scale = useTransform(scrollYProgress, [0, 1], [0.86, 1])
  const opacity = useTransform(scrollYProgress, [0, 0.35], [0.3, 1])
  return (
    <div ref={ref} style={{ perspective: 1800 }}>
      <motion.div style={still ? {} : { rotateX, scale, opacity, transformOrigin: 'center bottom' }}>{children}</motion.div>
    </div>
  )
}

/* The app itself, at work: what you'd see on your Mac while your twin applies. It really runs through its steps. */
function AppWindow() {
  const queue = [['Google', 'google.com', 'Software Engineering Intern', 98], ['OpenAI', 'openai.com', 'Research Engineer Intern', 97],
    ['Jane Street', 'janestreet.com', 'Software Engineer Intern', 96], ['Citadel', 'citadel.com', 'Quantitative Research Intern', 95],
    ['Two Sigma', 'twosigma.com', 'Quant Research Intern', 94], ['Anthropic', 'anthropic.com', 'Software Engineer Intern', 94]]
  const STEPS = ['Opening the posting', 'Tailoring your resume', 'Filling the application', 'Submitted']
  const box = useRef(null)
  const seen = useInView(box, { margin: '-20% 0px' })
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!seen) return
    const t = setInterval(() => setTick(x => x + 1), 1700)
    return () => clearInterval(t)
  }, [seen])
  const job = Math.floor(tick / STEPS.length) % (queue.length - 3)
  const step = STEPS[tick % STEPS.length]
  const cur = queue[job]
  const next = queue.slice(job + 1, job + 5)
  const done = [['Apple', 'apple.com', 'Software Engineering Intern'], ['Palantir', 'palantir.com', 'Forward Deployed Engineer Intern'],
    ['Meta', 'meta.com', 'Software Engineer Intern'], ...queue.slice(0, job).map(([c, d, t]) => [c, d, t])].slice(-3).reverse()
  const count = 3 + job + (step === 'Submitted' ? 1 : 0)
  const nav = ['Today', 'Jobs', 'Resume', 'Answers', 'Applications', 'Autopilot']
  return (
    <div ref={box} className="mx-auto w-full max-w-[1120px] overflow-hidden rounded-[14px] text-left shadow-[0_30px_80px_rgb(0_0_0/.22),0_0_0_1px_rgb(0_0_0/.08)]"
      style={{ background: '#1c1c1e', color: '#f5f5f7', colorScheme: 'dark' }}>
      <div className="grid md:grid-cols-[200px_1fr] [&>*]:min-w-0">
        {/* the real app's sidebar */}
        <aside className="hidden flex-col border-r border-white/[.07] px-3 pb-4 pt-3 md:flex" style={{ background: '#232325' }}>
          <div className="flex gap-2 px-1 pb-5 pt-1">{['#ff5f57', '#febc2e', '#28c840'].map(c => <span key={c} className="size-3 rounded-full" style={{ background: c }} />)}</div>
          <div className="mb-4 flex items-center gap-2 px-2.5"><Logo size={18} /><span className="text-[14px] font-semibold">Job Applier 4.0</span></div>
          {nav.map(n => (
            <div key={n} className={'flex h-8 items-center rounded-[7px] px-2.5 text-[13px] ' + (n === 'Autopilot' ? 'bg-[#0a84ff] text-white' : 'text-white/80')}>{n}</div>))}
          <div className="mt-auto px-2.5 text-[13px] text-white/60">Settings</div>
        </aside>
        <div className="min-w-0">
          <div className="flex h-11 items-center gap-2 border-b border-white/[.07] px-4 md:hidden">
            {['#ff5f57', '#febc2e', '#28c840'].map(c => <span key={c} className="size-3 rounded-full" style={{ background: c }} />)}
            <span className="mx-auto pr-14 text-[13px] font-medium text-white/60">Job Applier 4.0</span>
          </div>
          <div className="grid gap-7 p-5 sm:p-8 lg:grid-cols-[1.2fr_1fr] [&>*]:min-w-0">
            <div>
              <div className="text-[28px] font-bold tracking-[-0.02em]">Autopilot</div>
              <div className="mt-4 rounded-[14px] p-5" style={{ background: '#2c2c2e' }}>
                <div className="text-[12.5px] font-medium text-[#30d158]">Claude Code is applying</div>
                <div className="relative mt-1 h-[34px] overflow-hidden">
                  <AnimatePresence mode="popLayout" initial={false}>
                    <motion.div key={step + job} initial={{ y: 20, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -20, opacity: 0 }}
                      transition={{ duration: 0.55, ease: EASE }} className="flex items-center gap-2 text-[26px] font-semibold tracking-[-0.02em]">
                      {step}{step === 'Submitted' && <Check className="size-6 text-[#30d158]" />}
                    </motion.div>
                  </AnimatePresence>
                </div>
                <div className="flex items-center gap-2 text-[13.5px] text-white/60">
                  <Avatar name={cur[0]} domain={cur[1]} size={18} />{cur[0]} · {cur[2]} · {count} of 25</div>
                <div className="mt-4 h-[4px] overflow-hidden rounded-full bg-white/[.08]">
                  <motion.div className="h-full rounded-full bg-[#0a84ff]" animate={{ width: `${(count / 25) * 100}%` }} transition={{ duration: 0.9, ease: EASE }} /></div>
              </div>
              <div className="mt-6 px-1 text-[12px] font-semibold uppercase tracking-[0.05em] text-white/45">Up next</div>
              <div className="mt-2 overflow-hidden rounded-[14px]" style={{ background: '#2c2c2e' }}>
                <AnimatePresence initial={false}>
                  {next.map(([c, d, t, f]) => (
                    <motion.div layout key={c} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}
                      transition={{ duration: 0.6, ease: EASE }} className="flex items-center gap-3 border-b border-white/[.06] px-4 py-2.5 last:border-0">
                      <Avatar name={c} domain={d} size={28} />
                      <div className="min-w-0 flex-1"><div className="truncate text-[14px] font-medium">{t}</div><div className="text-[12.5px] text-white/55">{c}</div></div>
                      <div className="text-[13.5px] tabular-nums text-white/60">{f}%</div>
                    </motion.div>))}
                </AnimatePresence>
              </div>
            </div>
            <div>
              <div className="px-1 pt-1 text-[12px] font-semibold uppercase tracking-[0.05em] text-white/45 lg:mt-12">Needs you</div>
              <div className="mt-2 rounded-[14px] p-4" style={{ background: '#2c2c2e' }}>
                <div className="flex items-center gap-3"><Avatar name="NVIDIA" domain="nvidia.com" size={28} />
                  <div className="min-w-0"><div className="text-[14px] font-medium">Sign in to Workday</div><div className="truncate text-[12.5px] text-white/55">NVIDIA · Deep Learning Software Intern</div></div></div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <span className="rounded-full bg-[#0a84ff] px-3 py-1.5 text-[12.5px] font-medium text-white">I signed in, finish it</span>
                  <span className="rounded-full bg-white/[.08] px-3 py-1.5 text-[12.5px] font-medium">Skip this job</span>
                </div>
                <div className="mt-3 rounded-full bg-white/[.06] px-3.5 py-2 text-[12.5px] text-white/40">Message your twin about this one…</div>
              </div>
              <div className="mt-6 px-1 text-[12px] font-semibold uppercase tracking-[0.05em] text-white/45">Submitted today</div>
              <div className="mt-2 overflow-hidden rounded-[14px]" style={{ background: '#2c2c2e' }}>
                <AnimatePresence initial={false}>
                  {done.map(([c, d, t]) => (
                    <motion.div layout key={c} initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                      transition={{ duration: 0.6, ease: EASE }} className="flex items-center gap-3 border-b border-white/[.06] px-4 py-2.5 last:border-0">
                      <Avatar name={c} domain={d} size={28} />
                      <div className="min-w-0 flex-1"><div className="truncate text-[14px] font-medium">{t}</div><div className="text-[12.5px] text-white/55">{c}</div></div>
                      <Check className="size-4 text-[#30d158]" />
                    </motion.div>))}
                </AnimatePresence>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function Tile({ title, text, children }) {
  return (
    <Reveal className="tile flex flex-col overflow-hidden px-7 pt-9 sm:px-10 sm:pt-11">
      <div className="display text-[28px] font-semibold leading-tight sm:text-[32px]">{title}</div>
      <p className="mt-2 max-w-[440px] text-[17px] leading-[1.45] muted">{text}</p>
      <div className="mt-8 flex flex-1 items-end">{children}</div>
    </Reveal>
  )
}

function useSeen() {
  const ref = useRef(null)
  return [ref, useInView(ref, { once: true, margin: '-15% 0px' })]
}

function Roles() {
  const [ref, seen] = useSeen()
  const r = [['Stripe', 'stripe.com', 'Software Engineer Intern', 'San Francisco'], ['Two Sigma', 'twosigma.com', 'Quantitative Research Intern', 'New York'],
    ['Anduril', 'anduril.com', 'Autonomy Engineer Intern', 'Costa Mesa']]
  return (
    <div ref={ref} className="sheet w-full overflow-hidden rounded-b-none [&>*+*]:border-t [&>*+*]:border-[var(--line)]">
      {r.map(([c, d, t, l], i) => (
        <motion.div key={c} initial={{ opacity: 0, x: -24 }} animate={seen ? { opacity: 1, x: 0 } : {}} transition={{ duration: 0.8, ease: EASE, delay: 0.15 + i * 0.18 }}
          className="flex items-center gap-3 px-4 py-3">
          <Avatar name={c} domain={d} size={28} />
          <div className="min-w-0 flex-1"><div className="truncate text-[14px] font-medium">{t}</div><div className="text-[12.5px] muted">{c} · {l}</div></div>
          <motion.span initial={{ opacity: 0 }} animate={seen ? { opacity: 1 } : {}} transition={{ delay: 0.7 + i * 0.18, duration: 0.5 }}
            className="text-[12.5px] font-medium" style={{ color: 'var(--green)' }}>Fits you</motion.span>
        </motion.div>))}
    </div>
  )
}

function Stack() {
  const [ref, seen] = useSeen()
  const cards = [['Jane Street', 'janestreet.com', 96], ['NVIDIA', 'nvidia.com', 95], ['Meta', 'meta.com', 96], ['Google', 'google.com', 98]]
  return (
    <div ref={ref} className="relative w-full pt-[96px]">
      {cards.map(([c, d, f], i) => {
        const front = i === cards.length - 1
        return (
          <motion.div key={c} className={'sheet rounded-b-none px-5 ' + (front ? 'relative pb-6 pt-4' : 'absolute inset-x-0 pb-6 pt-[7px]')}
            initial={front ? { y: 30, opacity: 0 } : { top: 96, scale: 0.94, opacity: 0 }}
            animate={seen ? (front ? { y: 0, opacity: 1 } : { top: i * 32, scale: 0.91 + i * 0.03, opacity: 1 }) : {}}
            transition={{ duration: 0.9, ease: EASE, delay: front ? 0 : 0.35 + (cards.length - 2 - i) * 0.16 }}
            style={{ transformOrigin: 'top center' }}>
            <div className="flex items-center gap-2.5">
              <Avatar name={c} domain={d} size={front ? 28 : 22} />
              <span className={front ? 'text-[16px] font-semibold' : 'text-[14px] font-medium'}>{c}</span>
              <span className="ml-auto text-[13px] tabular-nums muted">{f}% match</span>
            </div>
            {front && <div className="mt-4 space-y-2">{[92, 78, 86].map((w, j) => (
              <motion.div key={j} className="h-[6px] rounded-full bg-[var(--bg-2)]" initial={{ width: 0 }} animate={seen ? { width: `${w}%` } : {}}
                transition={{ duration: 0.9, ease: EASE, delay: 0.3 + j * 0.15 }} />))}</div>}
          </motion.div>)
      })}
    </div>
  )
}

function Form() {
  const [ref, seen] = useSeen()
  const f = [['Authorized to work in the US?', 'Yes'], ['Expected graduation', 'May 2028'], ['Street address', '1 University Ave'],
    ['What interests you about us?', 'Your GPU kernels team…']]
  return (
    <div ref={ref} className="sheet w-full overflow-hidden rounded-b-none [&>*+*]:border-t [&>*+*]:border-[var(--line)]">
      {f.map(([q, a], i) => (
        <div key={q} className="flex items-center justify-between gap-4 px-4 py-3 text-[14px]">
          <span className="muted">{q}</span>
          <motion.span className="truncate font-medium" initial={{ opacity: 0, x: 8 }} animate={seen ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.6, ease: EASE, delay: 0.3 + i * 0.45 }}>{a}</motion.span>
        </div>))}
    </div>
  )
}

function Ask() {
  const [ref, seen] = useSeen()
  return (
    <div ref={ref} className="w-full pb-8">
      <motion.div initial={{ y: -36, opacity: 0, scale: 0.96 }} animate={seen ? { y: 0, opacity: 1, scale: 1 } : {}}
        transition={{ type: 'spring', stiffness: 260, damping: 30, delay: 0.25 }} className="sheet mx-auto max-w-[400px] rounded-[18px] px-4 py-3.5">
        <div className="flex items-center gap-3">
          <Logo size={34} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between text-[13px]"><span className="font-semibold">Job Applier 4.0</span><span className="faint">now</span></div>
            <div className="text-[14px] leading-snug">Code needed for Stripe. Check your email and type it in the open tab.</div>
          </div>
        </div>
      </motion.div>
    </div>
  )
}

function InstallBox() {
  const [win, setWin] = useState(IS_WIN)
  const [ok, setOk] = useState(false)
  const cmd = win ? INSTALL_WIN : INSTALL
  const copy = () => { navigator.clipboard.writeText(cmd); setOk(true); setTimeout(() => setOk(false), 1600) }
  return (
    <div>
      <div className="mx-auto mb-3 flex w-fit rounded-full bg-[var(--bg-2)] p-[3px] text-[13px]">
        {[[false, 'Mac & Linux'], [true, 'Windows']].map(([w, l]) => (
          <button key={l} onClick={() => setWin(w)} className={'rounded-full px-4 py-1.5 transition ' + (win === w ? 'bg-[var(--bg-3)] font-semibold shadow-sm' : 'muted')}>{l}</button>))}
      </div>
      <button onClick={copy} aria-label="Copy the install command"
        className="flex w-full items-center gap-3 rounded-[14px] bg-[var(--bg-2)] py-3.5 pl-4 pr-3 text-left transition hover:brightness-[.98]">
        <span className="mono min-w-0 flex-1 text-[13px] leading-snug sm:text-[15px]">{cmd}</span>
        <span className="flex shrink-0 items-center gap-1.5 text-[14px] font-medium link">
          {ok ? <Check className="size-4" /> : <Copy className="size-4" />}<span className="hidden sm:inline">{ok ? 'Copied' : 'Copy'}</span></span>
      </button>
    </div>
  )
}

function Stars() {
  const n = useStars()
  return (
    <a href={REPO_URL} target="_blank" rel="noreferrer" className="link inline-flex items-center text-[17px]">
      Star on GitHub{n ? ` (${n.toLocaleString()})` : ''}<ChevronRight className="size-4" /></a>
  )
}

function Faq({ q, a }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left text-[17px]">
        {q}<ChevronRight className="size-4 shrink-0 faint transition-transform" style={{ transform: open ? 'rotate(90deg)' : 'none' }} />
      </button>
      <motion.div initial={false} animate={{ height: open ? 'auto' : 0, opacity: open ? 1 : 0 }} transition={{ duration: 0.25, ease: 'easeOut' }} className="overflow-hidden">
        <p className="px-5 pb-5 text-[15px] leading-relaxed muted">{a}</p>
      </motion.div>
    </div>
  )
}

function Logo({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <rect x="4" y="4" width="38" height="38" rx="12" fill="#0071e3" /><rect x="22" y="22" width="38" height="38" rx="12" fill="#5ac8fa" fillOpacity=".9" />
    </svg>
  )
}
