import { useEffect, useRef, useState } from 'react'
import { animate, motion, useInView, useMotionValue, useSpring, useTransform, AnimatePresence } from 'motion/react'
import * as RSwitch from '@radix-ui/react-switch'
import * as RSlider from '@radix-ui/react-slider'
import { ArrowUpRight, Check, ChevronRight, Copy, UploadCloud } from 'lucide-react'
import { cn } from '../lib/utils'

export const spring = { type: 'spring', stiffness: 420, damping: 34, mass: 0.8 }
export const soft = { type: 'spring', stiffness: 220, damping: 28 }

export function Button({ variant = 'ink', size = 'md', className, children, arrow, loading, ...p }) {
  const v = {
    ink: 'bg-signal text-white hover:bg-[#2b95ff]', signal: 'bg-signal text-white hover:bg-[#2b95ff]', sky: 'bg-signal text-white hover:bg-[#2b95ff]',
    dark: 'bg-white text-[#1d1d1f] hover:bg-white/90',
    white: 'bg-white/[.08] text-ink hover:bg-white/[.13]',
    glass: 'bg-white/20 text-white backdrop-blur-md hover:bg-white/30',
    ghost: 'text-signal-ink hover:bg-signal/[.06]',
    danger: 'text-bad hover:bg-bad/[.06]',
  }[variant]
  const s = { sm: 'h-8 px-3.5 text-[13px] gap-1', md: 'h-10 px-5 text-[14px] gap-1.5', lg: 'h-12 px-6 text-[16px] gap-1.5' }[size]
  return (
    <motion.button whileTap={{ scale: 0.96 }} transition={spring} disabled={loading || p.disabled}
      className={cn('inline-flex items-center justify-center rounded-full font-medium transition-colors duration-150 disabled:opacity-50 cursor-pointer select-none', v, s, className)} {...p}>
      {loading && <span className="size-4 animate-spin rounded-full border-2 border-current/30 border-t-current" />}
      {children}
      {arrow && <ChevronRight className="-mr-1 size-4" />}
    </motion.button>
  )
}
export function Card({ className, children, ...p }) {
  return <div className={cn('card', className)} {...p}>{children}</div>
}

export function Badge({ tone = 'gray', className, children }) {
  const t = { gray: 'bg-white/[.05] text-muted', good: 'bg-good/10 text-good', sky: 'bg-signal/10 text-signal-ink', warn: 'bg-warn/10 text-warn',
    bad: 'bg-bad/10 text-bad', ink: 'bg-ink text-white' }[tone]
  return <span className={cn('inline-flex items-center gap-1 rounded-full px-2.5 py-[3px] text-[12px] font-medium', t, className)}>{children}</span>
}
export function Field({ label, hint, children, className }) {
  return (
    <label className={cn('block', className)}>
      <div className="label mb-1">{label}</div>
      {children}
      {hint && <div className="mt-1 text-[12px] text-faint">{hint}</div>}
    </label>
  )
}

export function Switch({ checked, onChange }) {
  return (
    <RSwitch.Root checked={checked} onCheckedChange={onChange}
      className="relative h-[26px] w-[44px] shrink-0 cursor-pointer rounded-full bg-white/[.14] transition-colors data-[state=checked]:bg-good">
      <RSwitch.Thumb className="block size-[22px] translate-x-[2px] rounded-full bg-white shadow-[0_3px_8px_rgb(0_0_0/.15),0_0_0_.5px_rgb(0_0_0/.04)] transition-transform duration-200 will-change-transform data-[state=checked]:translate-x-[20px]" />
    </RSwitch.Root>
  )
}

export function Slider({ value, onChange, min = 0, max = 100, step = 5 }) {
  return (
    <RSlider.Root value={[value]} onValueChange={v => onChange(v[0])} min={min} max={max} step={step} className="relative flex h-5 w-full touch-none items-center">
      <RSlider.Track className="relative h-[4px] grow rounded-full bg-white/[.08]"><RSlider.Range className="absolute h-full rounded-full bg-signal" /></RSlider.Track>
      <RSlider.Thumb className="block size-[24px] rounded-full bg-white shadow-[0_3px_8px_rgb(0_0_0/.18),0_0_0_.5px_rgb(0_0_0/.06)] outline-none" />
    </RSlider.Root>
  )
}

export function Segmented({ options, value, onChange, id = 'seg', className }) {
  return (
    <div className={cn('inline-flex rounded-[10px] bg-white/[.06] p-[2px]', className)}>
      {options.map(([v, label, Icon]) => (
        <button key={v} onClick={() => onChange(v)} className={cn('relative flex h-7 items-center gap-1.5 rounded-[8px] px-3.5 text-[13px] transition-colors',
          value === v ? 'font-semibold text-ink' : 'font-medium text-ink/70 hover:text-ink')}>
          {value === v && <motion.span layoutId={id} transition={spring} className="absolute inset-0 rounded-[8px] bg-white/[.16] shadow-[0_3px_8px_rgb(0_0_0/.3)]" />}
          <span className="relative flex items-center gap-1.5">{Icon && <Icon className="size-3.5" />}{label}</span>
        </button>
      ))}
    </div>
  )
}
export function NumberTicker({ value, className }) {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true })
  const mv = useMotionValue(0)
  const sp = useSpring(mv, { damping: 40, stiffness: 140 })
  useEffect(() => { if (inView) mv.set(Number(value) || 0) }, [inView, value, mv])
  useEffect(() => sp.on('change', v => { if (ref.current) ref.current.textContent = Math.round(v).toLocaleString() }), [sp])
  return <span ref={ref} className={cn('tabular-nums', className)}>0</span>
}

export function Ring({ value = 0, size = 64, stroke = 6, label, color, className }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r
  const col = color || (value >= 75 ? 'var(--color-good)' : value >= 50 ? 'var(--color-signal)' : 'var(--color-warn)')
  return (
    <div className={cn('relative grid place-items-center', className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(255 255 255 / .08)" strokeWidth={stroke} />
        <motion.circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={col} strokeWidth={stroke} strokeLinecap="round"
          initial={{ strokeDashoffset: c }} animate={{ strokeDashoffset: c * (1 - Math.min(100, value) / 100) }} transition={{ duration: 1.1, ease: [0.2, 0.8, 0.2, 1] }}
          strokeDasharray={c} />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center font-semibold tabular-nums tracking-[-0.02em]" style={{ fontSize: size * 0.28 }}>
        {label ?? <span><NumberTicker value={value} /></span>}
      </div>
    </div>
  )
}
export function Spotlight({ className, children, ...p }) {
  return <div className={cn('card relative overflow-hidden', className)} {...p}>{children}</div>
}
export function BorderBeam({ duration = 7, className }) {
  return (
    <div className={cn('pointer-events-none absolute inset-0 rounded-[inherit] [mask:linear-gradient(#000,#000)_content-box,linear-gradient(#000,#000)] [mask-composite:exclude] p-px', className)}>
      <motion.div className="absolute aspect-square w-24 bg-[radial-gradient(closest-side,#60a5fa,#a78bfa_45%,transparent)]"
        style={{ offsetPath: 'rect(0 auto auto 0 round 22px)' }} animate={{ offsetDistance: ['0%', '100%'] }} transition={{ duration, repeat: Infinity, ease: 'linear' }} />
    </div>
  )
}

const SUFFIX = /\b(inc|llc|ltd|corp|corporation|co|company|technologies|technology|holdings|group|plc|lp|llp|incorporated|the)\b\.?/gi
const KNOWN = { 'd. e. shaw': 'deshaw.com', 'de shaw': 'deshaw.com', 'hudson river trading': 'hudsonrivertrading.com', 'meta': 'meta.com',
  'google': 'google.com', 'alphabet': 'abc.xyz', 'amazon': 'amazon.com', 'x': 'x.com', 'mayo clinic': 'mayoclinic.org' }
export const guessDomain = name => {
  const n = (name || '').toLowerCase().trim()
  if (KNOWN[n]) return KNOWN[n]
  const base = n.replace(SUFFIX, '').replace(/[^a-z0-9]/g, '')
  return base ? base + '.com' : ''
}

export function Avatar({ name, size = 40, domain, icon }) {
  const [ok, setOk] = useState(true)
  const d = domain || guessDomain(name)
  const src = icon || (d ? `https://www.google.com/s2/favicons?domain=${d}&sz=128` : '')
  const r = Math.round(size * 0.28)
  return (
    <div className="logo relative grid shrink-0 place-items-center overflow-hidden bg-white" style={{ width: size, height: size, borderRadius: r, boxShadow: "0 0 0 .5px rgb(0 0 0 / .1), 0 1px 3px rgb(0 0 0 / .06)" }}>
      {ok && src ? <img src={src} alt="" width={size} height={size} loading="lazy" referrerPolicy="no-referrer"
        onLoad={e => { if (e.currentTarget.naturalWidth <= 16) setOk(false) }} onError={() => setOk(false)}
        style={{ width: size * 0.62, height: size * 0.62, objectFit: 'contain' }} />
        : <span className="font-semibold text-muted" style={{ fontSize: size * 0.4 }}>{(name || '?').trim()[0]?.toUpperCase()}</span>}
    </div>
  )
}

export function Fit({ v }) {
  return <Gauge v={v} />
}
export function CopyLine({ text }) {
  const [ok, setOk] = useState(false)
  return (
    <button onClick={() => { navigator.clipboard.writeText(text); setOk(true); setTimeout(() => setOk(false), 1400) }}
      className="group flex w-full items-center justify-between gap-3 rounded-[12px] bg-mist px-4 py-3 text-left font-mono text-[12.5px] text-ink transition hover:bg-white/[.07]">
      <span className="truncate">{text}</span>
      {ok ? <Check className="size-4 text-good" /> : <Copy className="size-4 text-faint group-hover:text-ink" />}
    </button>
  )
}
export function Stagger({ children, className, delay = 0.012 }) {
  return (
    <motion.div className={className} initial="h" animate="s" variants={{ s: { transition: { staggerChildren: delay } } }}>
      {children}
    </motion.div>
  )
}
export const item = { h: { opacity: 0 }, s: { opacity: 1, transition: { duration: 0.16, ease: 'easeOut' } } }

export function Hand({ children, className }) {
  return <span className={cn('text-[14px] font-semibold text-signal', className)}>{children}</span>
}
export function Title({ children, sub, right }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-6">
      <div>
        <motion.h1 initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={soft}
          className="text-[44px] font-bold leading-[1.05] tracking-[-0.035em] text-white">{children}</motion.h1>
        {sub && <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.1 }} className="mt-2 max-w-xl text-[16px] leading-snug text-muted">{sub}</motion.p>}
      </div>
      <div className="flex items-center gap-2">{right}</div>
    </div>
  )
}
export function Drop({ onFile, onText, compact }) {
  const [over, setOver] = useState(false)
  const input = useRef(null)
  const handle = async f => {
    if (!f) return
    const b = await f.arrayBuffer()
    let bin = ''; const u = new Uint8Array(b)
    for (let i = 0; i < u.length; i += 0x8000) bin += String.fromCharCode(...u.subarray(i, i + 0x8000))
    onFile({ name: f.name, data: btoa(bin) })
  }
  return (
    <motion.div onDragOver={e => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
      onDrop={e => { e.preventDefault(); setOver(false); handle(e.dataTransfer.files[0]) }} onClick={() => input.current.click()}
      animate={{ scale: over ? 1.015 : 1 }} transition={spring}
      className={cn('group relative flex cursor-pointer flex-col items-center justify-center rounded-[20px] border-2 border-dashed text-center transition-all',
        over ? 'border-signal bg-signal/[.05]' : 'border-white/15 bg-white/[.03] backdrop-blur-xl hover:border-signal/60', compact ? 'px-6 py-7' : 'px-8 py-12')}>
      <input ref={input} type="file" accept=".pdf,.txt,.md,.docx" className="hidden" onChange={e => handle(e.target.files[0])} />
      <motion.div animate={{ y: over ? -4 : 0 }} className="mb-3 grid size-12 place-items-center rounded-full bg-signal/10 text-signal"><UploadCloud className="size-6" /></motion.div>
      <div className="text-[15px] font-medium text-fg">Drop your resume here</div>
      <div className="mt-1 text-[13px] text-muted">PDF, Word or text. Old ones too: drop as many as you have.</div>
      {onText && !compact && <button onClick={e => { e.stopPropagation(); onText() }} className="mt-4 text-[14px] font-medium text-signal-ink hover:underline">or paste text, your LinkedIn, anything</button>}
    </motion.div>
  )
}

/* Fades/lifts content in the first time it scrolls into view. */
/* In the app, content is there the moment a page opens (a quick fade, nothing waits on scrolling), like a native app.
   The public site keeps its own scroll reveals. */
export function Reveal({ children, className, delay = 0 }) {
  return (
    <motion.div className={className} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      transition={{ duration: 0.18, ease: 'easeOut', delay: Math.min(delay, 0.08) }}>{children}</motion.div>
  )
}

/* Headline that assembles word by word. */
export function Words({ text, className, delay = 0, stagger = 0.06 }) {
  return (
    <span className={className}>
      {text.split(' ').map((w, i) => (
        <motion.span key={i} className="inline-block" initial={{ opacity: 0, y: '0.35em' }} animate={{ opacity: 1, y: 0 }}
          transition={{ type: 'spring', stiffness: 120, damping: 18, delay: delay + i * stagger }}>{w}&nbsp;</motion.span>))}
    </span>
  )
}

/* Leans toward the cursor a little. */
export function Magnetic({ children, className }) {
  return <div className={cn('inline-block', className)}>{children}</div>
}

/* A list whose hover highlight glides from row to row. rows: [{key, onClick, content}] */
export function GlideList({ rows, className }) {
  return (
    <div className={cn('relative', className)}>
      {rows.map((r, i) => (
        <motion.button key={r.key} onClick={r.onClick} variants={item}
          className="group relative flex w-full items-center gap-4 px-5 py-3 text-left transition-colors hover:bg-white/[.035]">
          {i > 0 && <span className="absolute inset-x-5 top-0 h-px bg-white/[.06]" />}
          <span className="relative flex w-full items-center gap-4">{r.content}</span>
        </motion.button>))}
    </div>
  )
}

/* A soft light that follows the cursor inside any panel (pure CSS vars, no re-render). */
export function Glow({ children, className, as: As = 'div', color, size, ...p }) {
  return <As className={cn('relative', className)} {...p}>{children}</As>
}

/* A rotating ring of light around anything (CTAs, drop zones). */
export function LightRing({ children, className }) {
  return <div className={className}>{children}</div>
}

/* Small fit gauge that sweeps in. */
export function Gauge({ v }) {
  const n = Math.round(v)
  return <span className={cn('w-10 shrink-0 text-right text-[13px] font-medium tabular-nums', n >= 85 ? 'text-white' : 'text-muted')}>{n}%</span>
}

/* Celebration burst. */
export function burst(x = window.innerWidth / 2, y = window.innerHeight / 2) {
  const colors = ['#4c8dff', '#a5f3fc', '#c4b5fd', '#34d399', '#fbbf24', '#f472b6']
  for (let i = 0; i < 70; i++) {
    const el = document.createElement('i')
    const a = Math.random() * Math.PI * 2, v = 6 + Math.random() * 10
    Object.assign(el.style, { position: 'fixed', left: x + 'px', top: y + 'px', width: '8px', height: '12px', background: colors[i % colors.length],
      borderRadius: '2px', zIndex: 9999, pointerEvents: 'none', transform: 'translate(-50%,-50%)' })
    document.body.appendChild(el)
    let vx = Math.cos(a) * v, vy = Math.sin(a) * v - 8, px = 0, py = 0, rot = 0, life = 0
    const tick = () => { life++; vy += 0.45; vx *= 0.985; px += vx; py += vy; rot += 12
      el.style.transform = `translate(${px - 4}px,${py - 6}px) rotate(${rot}deg)`; el.style.opacity = String(Math.max(0, 1 - life / 90))
      if (life < 90) requestAnimationFrame(tick); else el.remove() }
    requestAnimationFrame(tick)
  }
}

/* Digits roll like an odometer. */
export function Odometer({ value, className }) {
  const s = Math.round(Number(value) || 0).toLocaleString()
  return (
    <span className={cn('inline-flex overflow-hidden tabular-nums', className)} style={{ lineHeight: 1 }}>
      {s.split('').map((ch, i) => /\d/.test(ch) ? (
        <span key={i + '-' + s.length} className="relative inline-block h-[1em] overflow-hidden" style={{ width: '0.62em' }}>
          <motion.span className="absolute left-0 top-0 flex flex-col" initial={{ y: '0em' }} animate={{ y: `-${(+ch + 10)}em` }}
            transition={{ type: 'spring', stiffness: 60, damping: 16, delay: i * 0.06 }}>
            {Array.from({ length: 20 }, (_, k) => <span key={k} className="block h-[1em]">{k % 10}</span>)}
          </motion.span>
        </span>) : <span key={i}>{ch}</span>)}
    </span>
  )
}

/* Text that resolves from scrambled glyphs. */
export function Scramble({ text, className, speed = 22 }) {
  const [out, setOut] = useState(text.replace(/\S/g, ' '))
  useEffect(() => {
    const G = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    let f = 0
    const total = text.length + 12
    const id = setInterval(() => {
      f++
      setOut(text.split('').map((c, i) => c === ' ' ? ' ' : i < f - 8 ? c : i < f ? G[(i * 13 + f * 7) % G.length] : ' ').join(''))
      if (f > total) { clearInterval(id); setOut(text) }
    }, speed)
    return () => clearInterval(id)
  }, [text, speed])
  return <span className={className}>{out}</span>
}
