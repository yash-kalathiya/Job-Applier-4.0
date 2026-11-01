import { useRef, useState } from 'react'
import { motion, useScroll, useTransform, useSpring, useMotionValueEvent } from 'motion/react'
import { Avatar } from './ui'

/* Keynote-style scroll story, driven entirely by scroll position:
   A  everything you've done pours into one core
   B  the twin rewrites it for one job, letter by letter, as the job's keywords lock in
   C  the page multiplies into tailored copies, each sent to a real company */

export const SCRAPS = ['Built a DCF for a $40M acquisition', '320 clinical hours, BLS certified', '1st of 120 at a case competition', 'Shipped an iOS app to 1,000+ users',
  'Led workshops for 80+ students', 'Redesigned a checkout flow in Figma', 'Dean\'s List, every semester', 'Cut API latency 38%',
  'Founded a tutoring nonprofit', 'Research assistant, psych lab']
export const REWRITES = [
  ['Worked on the backend for the data team.', 'Built a C++ ingestion service processing 40K events/sec across 12 shards.'],
  ['Helped make the API faster.', 'Cut p99 API latency 38% (410 to 255 ms) with a Python read-through cache.'],
  ['Did a hackathon project.', 'Won 1st of 120 teams at HackTX with a React app now used by 2,300 people.'],
]
export const KEYWORDS = ['C++', 'Python', 'distributed systems', 'React', 'scale']
export const FRONT = { company: 'Google', domain: 'google.com', role: 'Software Engineering Intern' }
// the same person, a different resume for each: these stack up behind the one being rewritten
export const DECK = [
  { company: 'Meta', domain: 'meta.com', role: 'Software Engineer Intern', fit: 96 },
  { company: 'NVIDIA', domain: 'nvidia.com', role: 'Deep Learning Software Intern', fit: 95 },
  { company: 'Palantir', domain: 'palantir.com', role: 'Forward Deployed Engineer Intern', fit: 97 },
  { company: 'Anduril', domain: 'anduril.com', role: 'Software Engineer Intern, Autonomy', fit: 94 },
  { company: 'Jane Street', domain: 'janestreet.com', role: 'Software Engineer Intern', fit: 96 },
]
export const SENT = [['Google', 'google.com'], ['Meta', 'meta.com'], ['Apple', 'apple.com'], ['Amazon', 'amazon.com'], ['Netflix', 'netflix.com'],
  ['Microsoft', 'microsoft.com'], ['NVIDIA', 'nvidia.com'], ['Palantir', 'palantir.com'], ['Anduril', 'anduril.com'], ['Lockheed Martin', 'lockheedmartin.com', 'https://www.lockheedmartin.com/apple-touch-icon.png'],
  ['Northrop Grumman', 'northropgrumman.com'], ['Jane Street', 'janestreet.com'], ['Citadel', 'citadel.com'], ['OpenAI', 'openai.com']]

function MiniCard({ c, peek }) {
  return (
    <div className={'rounded-[16px] bg-white text-left ' + (peek ? 'px-5 pb-6 pt-[6px]' : 'p-4') + ' shadow-[0_30px_80px_rgb(0_0_0/.45)] ring-1 ring-black/[.04] sm:px-8'}>
      <div className="flex items-center gap-3">
        <Avatar name={c.company} domain={c.domain} size={peek ? 22 : 30} />
        <div className="min-w-0 flex-1"><div className={(peek ? 'text-[15px]' : 'text-[17px]') + ' font-semibold tracking-[-0.03em] text-[#1d1d1f]'}>{c.company}</div></div>
        <div className="hidden text-[13px] text-[#6b7280] sm:block">{c.role}</div>
        <div className={(peek ? 'text-[15px]' : 'text-[17px]') + ' font-semibold tabular-nums tracking-[-0.03em] text-[#1d1d1f]'}>{c.fit}%</div>
      </div>
    </div>)
}
const clamp = v => Math.min(1, Math.max(0, v))

export function Story() {
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })
  const p = useSpring(scrollYProgress, { stiffness: 120, damping: 26, mass: 0.35 })
  const [t, setT] = useState(0)
  useMotionValueEvent(p, 'change', v => setT(v))

  const h0 = { opacity: useTransform(p, [0, 0.04, 0.27, 0.31], [0, 1, 1, 0]), scale: useTransform(p, [0, 0.34], [0.92, 1.06]) }
  const h1 = { opacity: useTransform(p, [0.33, 0.37, 0.74, 0.78], [0, 1, 1, 0]), scale: useTransform(p, [0.32, 0.8], [0.92, 1.06]) }
  const h2 = { opacity: useTransform(p, [0.78, 0.82, 1], [0, 1, 1]), scale: useTransform(p, [0.77, 1], [0.94, 1.04]) }
  const coreScale = useTransform(p, [0, 0.28, 0.36], [0.2, 1.15, 0.6])
  const coreOp = useTransform(p, [0, 0.05, 0.3, 0.38], [0, 1, 1, 0])
  const card = { opacity: useTransform(p, [0.3, 0.38, 0.78, 0.85], [0, 1, 1, 0]), scale: useTransform(p, [0.3, 0.38, 0.78, 0.86], [0.6, 1, 1, 0.78]),
    rotateX: useTransform(p, [0.3, 0.4], [30, 0]) }
  const rw = i => clamp((t - 0.4 - i * 0.07) / 0.09)
  const vw = typeof window === 'undefined' ? 1200 : window.innerWidth   // spread scales with the screen, so phones stay in frame
  const rx = Math.min(560, vw * 0.36), ry = Math.min(240, vw * 0.5), fan = Math.min(150, vw / 7)
  const sent = Math.round(clamp((t - 0.83) / 0.15) * 1284)

  return (
    <section ref={ref} className="relative h-[300svh] md:h-[560vh]">
      <div className="sticky top-0 h-[100svh] overflow-hidden">
        <div className="absolute inset-0" style={{ background: 'radial-gradient(60% 50% at 50% 58%, rgb(40 80 220 / .28), transparent 70%)' }} />
        <div className="absolute inset-x-0 top-[11vh] text-center">
          {[[h0, 'Everything', "you've ever done."], [h1, 'Rewritten', 'for each job.'], [h2, 'Sent.', 'Everywhere.']].map(([st, a, b]) => (
            <motion.h2 key={a} style={st} className="absolute inset-x-0 px-4 text-[clamp(52px,8.5vw,128px)] font-bold leading-[0.92] tracking-[-0.055em] text-white">
              {a} <span className="serif-i text-[#9cc8ff]">{b}</span>
            </motion.h2>))}
        </div>

        <div className="absolute inset-0 top-[32vh]" style={{ perspective: 1500 }}>
          <motion.div style={{ scale: coreScale, opacity: coreOp, x: '-50%', y: '-50%' }} className="absolute left-1/2 top-[41%] size-[180px] rounded-full">
            <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle,#ffffff_0%,#9cc8ff_25%,#4c8dff_50%,transparent_72%)]" />
            <div className="absolute -inset-20 rounded-full bg-[radial-gradient(circle,rgb(76_141_255/.4),transparent_65%)]" />
          </motion.div>
          {SCRAPS.map((s, i) => {
            const a = (i / SCRAPS.length) * Math.PI * 2
            const k = clamp((t - 0.02 - i * 0.012) / 0.24)
            const r = Math.pow(1 - k, 3)
            return (
              <div key={s} className="absolute left-1/2 top-[41%] whitespace-nowrap rounded-full border border-white/15 bg-[#2c2c2e] px-4 py-2 text-[14px] font-medium text-white shadow-[0_10px_30px_rgb(0_0_0/.45)]"
                style={{ transform: `translate(-50%,-50%) translate(${Math.cos(a) * rx * r}px, ${Math.sin(a) * ry * r}px) scale(${0.25 + 0.75 * r})`,
                  opacity: t < 0.34 ? clamp(k * 5) * clamp(r * 20) : 0 }}>{s}</div>)
          })}

          {DECK.map((c, i) => {
            const k = clamp((t - 0.44 - i * 0.032) / 0.07)
            const e = 1 - Math.pow(1 - k, 3)
            const out = clamp((t - 0.78) / 0.07)
            const step = i + 1
            return (
              <div key={c.company} className="absolute left-1/2 top-[41%] w-[min(640px,90vw)]"
                style={{ zIndex: 1 - step, opacity: k > 0 ? clamp(k * 4) * (1 - out) : 0,
                  transform: `translate(-50%, -50%) translateY(${(1 - e) * 340 - e * step * 31 - 136}px) scale(${1 - step * 0.04 * e})` }}>
                <MiniCard c={c} peek />
              </div>)
          })}

          <motion.div style={{ ...card, x: '-50%', y: '-50%', zIndex: 2 }} className="absolute left-1/2 top-[41%] w-[min(640px,90vw)] rounded-[16px] bg-white p-6 text-left sm:p-8 shadow-[0_40px_100px_rgb(0_0_0/.5)]">
            <div className="flex flex-col gap-0.5 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3"><Avatar name={FRONT.company} domain={FRONT.domain} size={34} />
                <div className="text-[22px] font-semibold tracking-[-0.03em] text-[#1d1d1f]">{FRONT.company}</div></div>
              <div className="text-[13px] text-[#6b7280]">{FRONT.role}</div></div>
            <div className="mt-3 h-px bg-black/10" />
            <ul className="mt-4 space-y-3">
              {REWRITES.map(([a, b], i) => {
                const k = rw(i)
                return (
                  <li key={i} className="relative flex gap-2.5 text-[15.5px] leading-snug">
                    <span className="relative mt-[8px] size-1.5 shrink-0 rounded-full transition-colors duration-300" style={{ background: k >= 0.5 ? '#0a84ff' : '#c7cad3' }} />
                    <span className="relative grid flex-1">
                      <span className="col-start-1 row-start-1 text-[#9ca3af]" style={{ opacity: 1 - k, transform: `translateY(${-k * 6}px)` }}>{a}</span>
                      <span className="col-start-1 row-start-1 text-[#1d1d1f]" style={{ opacity: k, transform: `translateY(${(1 - k) * 6}px)` }}>{b}</span>
                    </span>
                  </li>)
              })}
            </ul>
            <div className="mt-6 flex flex-wrap gap-2">
              {KEYWORDS.map((w, i) => {
                const k = clamp((t - 0.44 - i * 0.035) / 0.08)
                return <span key={w} className="rounded-full px-3 py-1 text-[13px] font-semibold"
                  style={{ transform: `scale(${0.85 + 0.15 * k})`, opacity: k, background: '#1d1d1f', color: '#fff' }}>{w}</span>
              })}
            </div>
            <div className="mt-5 flex items-center justify-between text-[13px] text-[#6b7280]"><span>Keyword match for this job</span>
              <span className="text-[30px] font-semibold tabular-nums tracking-[-0.04em] text-[#1d1d1f]">{Math.round(41 + 57 * clamp((t - 0.42) / 0.22))}%</span></div>
          </motion.div>

          {SENT.map(([c, d, ic], i) => {
            const k = clamp((t - 0.82 - i * 0.006) / 0.09)
            const e = 1 - Math.pow(1 - k, 3)
            const per = Math.ceil(SENT.length / 2), row = Math.floor(i / per), spread = (i % per) - (per - 1) / 2
            return (
              <div key={c} className="absolute left-1/2 top-[22%] w-[min(170px,13vw)] rounded-[14px] bg-white p-3 shadow-[0_30px_70px_rgb(0_0_0/.55)]"
                style={{ opacity: k > 0 ? clamp(k * 3) : 0,
                  transform: `translate(-50%,-50%) translate(${spread * fan * e}px, ${(row * 150 + Math.abs(spread) * 14) * e}px) rotate(${spread * 4 * e}deg) scale(${0.5 + 0.5 * e})` }}>
                <div className="flex items-center gap-2"><Avatar name={c} domain={d} icon={ic} size={26} /><span className="text-[13px] font-semibold leading-[1.15] text-[#1d1d1f]">{c}</span></div>
                <div className="mt-2.5 space-y-1.5">{[90, 70, 82].map((w, j) => <div key={j} className="h-[4px] rounded-full bg-[#4c8dff]/35" style={{ width: `${w}%` }} />)}</div>
                <div className="mt-2.5 text-[11px] font-semibold text-[#16a34a]" style={{ opacity: k >= 1 ? 1 : 0 }}>✓ Applied</div>
              </div>)
          })}
          <div className="absolute inset-x-0 top-[66%] text-center" style={{ opacity: clamp((t - 0.85) * 8) }}>
            <div className="text-[clamp(48px,6vw,88px)] font-bold tabular-nums tracking-[-0.05em] text-white">{sent.toLocaleString()}</div>
            <div className="text-[16px] text-muted">applications sent, each with its own resume</div>
          </div>
        </div>
      </div>
    </section>
  )
}

export function LogoWall({ companies }) {
  const rows = [companies.slice(0, 14), companies.slice(14, 28), companies.slice(28, 42)].filter(r => r.length)
  return (
    <div className="relative h-[300px] overflow-hidden [mask-image:linear-gradient(180deg,transparent,#000_25%,#000_75%,transparent),linear-gradient(90deg,transparent,#000_10%,#000_90%,transparent)] [mask-composite:intersect]"
      style={{ perspective: 900 }}>
      <div className="absolute inset-x-[-10%] top-1/2 -translate-y-1/2 space-y-4" style={{ transform: 'rotateX(48deg) rotateZ(-8deg)', transformStyle: 'preserve-3d' }}>
        {rows.map((r, i) => (
          <div key={i} className="flex w-max gap-4" style={{ animation: `marquee ${50 + i * 12}s linear infinite ${i % 2 ? 'reverse' : ''}` }}>
            {[...r, ...r, ...r].map((c, j) => (
              <div key={j} className="flex items-center gap-3 rounded-[16px] border border-white/10 bg-[#2c2c2e] px-4 py-3">
                <Avatar name={c} size={34} /><span className="whitespace-nowrap text-[15px] font-medium text-white/90">{c}</span></div>))}
          </div>))}
      </div>
    </div>
  )
}

/* Phones: the same three beats, stacked and revealed as you scroll, with no pinned scrolling and no empty stretches. */
export function StoryMobile() {
  const fade = { initial: { opacity: 0, y: 24 }, whileInView: { opacity: 1, y: 0 }, viewport: { once: true, margin: '-60px' }, transition: { type: 'spring', stiffness: 160, damping: 24 } }
  return (
    <div className="space-y-20 px-5 py-16">
      <motion.section {...fade}>
        <h2 className="text-[40px] font-bold leading-[0.98] tracking-[-0.045em] text-white">Everything <span className="serif-i text-[#9cc8ff]">you've ever done.</span></h2>
        <p className="mt-3 text-[16px] text-white/65">Give it your resume, old ones, anything. Your twin keeps all of it.</p>
        <div className="mt-6 flex flex-wrap gap-2">
          {SCRAPS.slice(0, 8).map((x, i) => <motion.span key={x} initial={{ opacity: 0, scale: .9 }} whileInView={{ opacity: 1, scale: 1 }} viewport={{ once: true }}
            transition={{ delay: i * .05 }} className="rounded-full border border-white/15 bg-[#2c2c2e] px-3.5 py-2 text-[13.5px] text-white">{x}</motion.span>)}
        </div>
      </motion.section>
      <motion.section {...fade}>
        <h2 className="text-[40px] font-bold leading-[0.98] tracking-[-0.045em] text-white">Rewritten <span className="serif-i text-[#9cc8ff]">for each job.</span></h2>
        <div className="mt-6 rounded-[16px] bg-white p-5 shadow-[0_30px_80px_rgb(0_0_0/.5)]">
          <div className="flex items-center gap-2.5"><Avatar name={FRONT.company} domain={FRONT.domain} size={28} />
            <div className="text-[19px] font-semibold tracking-[-0.03em] text-[#1d1d1f]">{FRONT.company}</div></div>
          <div className="mt-1 text-[13px] text-[#6b7280]">{FRONT.role}</div>
          <ul className="mt-3 space-y-2.5 border-t border-black/10 pt-3">
            {REWRITES.map(([, b]) => <li key={b} className="flex gap-2.5 text-[14.5px] leading-snug text-[#1d1d1f]"><span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-[#0a84ff]" />{b}</li>)}
          </ul>
          <div className="mt-4 flex flex-wrap gap-1.5">{KEYWORDS.map(w => <span key={w} className="rounded-full bg-[#1d1d1f] px-2.5 py-1 text-[12px] font-semibold text-white">{w}</span>)}</div>
          <div className="mt-4 flex items-center justify-between text-[13px] text-[#6b7280]"><span>Keyword match for this job</span><span className="text-[26px] font-semibold tracking-[-0.04em] text-[#1d1d1f]">98%</span></div>
        </div>
        <div className="mt-3 space-y-2.5">
          {DECK.map((c, i) => <motion.div key={c.company} initial={{ opacity: 0, y: 40 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
            transition={{ type: 'spring', stiffness: 170, damping: 22, delay: i * 0.08 }}><MiniCard c={c} /></motion.div>)}
        </div>
      </motion.section>
      <motion.section {...fade}>
        <h2 className="text-[40px] font-bold leading-[0.98] tracking-[-0.045em] text-white">Sent. <span className="serif-i text-[#9cc8ff]">Everywhere.</span></h2>
        <div className="mt-6 grid grid-cols-3 gap-2.5">
          {SENT.map(([c, d, ic], i) => <motion.div key={c} initial={{ opacity: 0, y: 10 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: i * .05 }}
            className="rounded-[12px] bg-white p-2.5"><Avatar name={c} domain={d} icon={ic} size={22} /><div className="mt-1.5 text-[12px] font-semibold leading-tight text-[#1d1d1f]">{c}</div>
            <div className="text-[10.5px] font-semibold text-[#16a34a]">✓ Applied</div></motion.div>)}
        </div>
        <div className="mt-8 text-center"><div className="text-[52px] font-bold tracking-[-0.05em] text-white">1,284</div>
          <div className="text-[15px] text-white/60">applications sent, each with its own resume</div></div>
      </motion.section>
    </div>
  )
}
