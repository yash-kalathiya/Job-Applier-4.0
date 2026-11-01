import { useEffect, useRef, useState } from 'react'
import { motion, useMotionValue, useSpring, useTransform, AnimatePresence } from 'motion/react'
import { Check } from 'lucide-react'
import { Avatar } from './ui'

/* Your resume and its twin, floating in perspective over the blue light. For each job, the lines that
   match light up on the twin, the job card glides in, and it gets marked applied. Follows the pointer. */

const LINES = [[92, 1], [76, 0], [86, 1], [62, 0], [90, 0], [70, 1], [82, 0], [56, 0], [74, 1]]

function Sheet({ active, name, front }) {
  return (
    <div className="absolute inset-0 rounded-[10px] bg-white p-5" style={{ boxShadow: front ? '0 30px 70px rgb(3 23 64 / .45), 0 0 0 .5px rgb(0 0 0 / .05)' : '0 20px 50px rgb(3 23 64 / .35)' }}>
      <div className="text-[16px] font-semibold tracking-[-0.02em] text-[#1c1c1e]">{name}</div>
      <div className="mt-1.5 h-[4px] w-24 rounded-full bg-white/[.08]" />
      {[0, 1, 2].map(sec => (
        <div key={sec} className="mt-4">
          <div className="mb-2 h-[5px] w-14 rounded-full bg-white/[.22]" />
          <div className="space-y-[7px]">
            {LINES.slice(sec * 3, sec * 3 + 3).map(([w, hot], i) => (
              <div key={i} className="relative h-[5px] overflow-hidden rounded-full bg-white/[.07]" style={{ width: `${w}%` }}>
                {hot ? <motion.div className="absolute inset-y-0 left-0 rounded-full bg-[#0071e3]" initial={{ width: 0 }}
                  animate={{ width: front && active ? '100%' : 0 }} transition={{ duration: 0.55, delay: active ? 0.3 + (sec * 3 + i) * 0.1 : 0, ease: [0.4, 0, 0.2, 1] }} /> : null}
              </div>))}
          </div>
        </div>))}
    </div>
  )
}

const JOBS = [
  { c: 'Pinterest', t: 'Software Engineer Intern', fit: 98, d: 'pinterest.com', where: 'San Francisco' },
  { c: 'Jane Street', t: 'Quant Trading Intern', fit: 94, d: 'janestreet.com', where: 'New York' },
  { c: 'Mayo Clinic', t: 'Nurse Extern', fit: 96, d: 'mayoclinic.org', where: 'Rochester' },
  { c: 'Figma', t: 'Product Design Intern', fit: 91, d: 'figma.com', where: 'San Francisco' },
]

export function Hero3D({ name }) {
  const ref = useRef(null)
  const mx = useMotionValue(0), my = useMotionValue(0)
  const rx = useSpring(useTransform(my, [-0.5, 0.5], [14, -6]), { stiffness: 100, damping: 18 })
  const ry = useSpring(useTransform(mx, [-0.5, 0.5], [-24, 16]), { stiffness: 100, damping: 18 })
  const [k, setK] = useState(0)
  const [on, setOn] = useState(false)
  useEffect(() => {
    let a = setTimeout(() => setOn(true), 400)
    const t = setInterval(() => { setOn(false); setK(x => (x + 1) % JOBS.length); clearTimeout(a); a = setTimeout(() => setOn(true), 450) }, 4200)
    return () => { clearInterval(t); clearTimeout(a) }
  }, [])
  const job = JOBS[k]
  return (
    <div ref={ref} className="relative h-[440px] w-full select-none" style={{ perspective: 1300 }}
      onPointerMove={e => { const r = ref.current.getBoundingClientRect(); mx.set((e.clientX - r.left) / r.width - 0.5); my.set((e.clientY - r.top) / r.height - 0.5) }}
      onPointerLeave={() => { mx.set(0); my.set(0) }}>
      <motion.div className="absolute left-1/2 top-1/2 h-[330px] w-[254px]" style={{ rotateX: rx, rotateY: ry, x: '-28%', y: '-50%', transformStyle: 'preserve-3d' }}>
        <motion.div className="absolute inset-0" style={{ transformStyle: 'preserve-3d', opacity: 0.92 }} initial={{ z: 0, x: 0 }}
          animate={{ z: -110, x: 84, y: -30, rotateZ: 5 }} transition={{ type: 'spring', stiffness: 60, damping: 15 }}>
          <Sheet name={name} />
        </motion.div>
        <motion.div className="absolute inset-0" style={{ transformStyle: 'preserve-3d' }} animate={{ y: [0, -7, 0] }} transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut' }}>
          <Sheet name={name} front active={on} />
        </motion.div>
        <AnimatePresence mode="popLayout">
          <motion.div key={k} className="absolute -left-[176px] top-[150px] w-[232px] rounded-[18px] bg-white p-3.5"
            style={{ transformStyle: 'preserve-3d', boxShadow: '0 24px 60px rgb(3 23 64 / .35), 0 0 0 .5px rgb(255 255 255 / .6) inset' }}
            initial={{ opacity: 0, x: -50, z: 170, rotateY: 28, scale: 0.94 }} animate={{ opacity: 1, x: 0, z: 120, rotateY: 6, scale: 1 }}
            exit={{ opacity: 0, x: 40, z: 60, rotateY: -16, scale: 0.96 }} transition={{ type: 'spring', stiffness: 120, damping: 18 }}>
            <div className="flex items-center gap-2.5"><Avatar name={job.c} domain={job.d} size={34} />
              <div className="min-w-0"><div className="truncate text-[13px] font-semibold leading-tight text-[#1c1c1e]">{job.t}</div>
                <div className="text-[12px] text-[#6b7280]">{job.c} · {job.where}</div></div></div>
            <div className="mt-3 flex items-center justify-between">
              <span className="text-[12px] text-[#6b7280]">Match</span>
              <span className="text-[22px] font-semibold leading-none tracking-[-0.03em] tabular-nums text-[#0071e3]">{job.fit}</span></div>
          </motion.div>
        </AnimatePresence>
        <AnimatePresence>{on && (
          <motion.div key={'st' + k} className="absolute -right-10 bottom-8 flex items-center gap-1.5 rounded-full bg-[#1d9a4a] py-1.5 pl-2 pr-3.5 text-[13px] font-semibold text-white"
            style={{ transform: 'translateZ(140px)', boxShadow: '0 14px 30px rgb(29 154 74 / .45)' }}
            initial={{ opacity: 0, scale: 0.6, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.9 }}
            transition={{ delay: 1.35, type: 'spring', stiffness: 380, damping: 20 }}>
            <span className="grid size-5 place-items-center rounded-full bg-white/25"><Check className="size-3.5" strokeWidth={3} /></span>Applied</motion.div>)}</AnimatePresence>
      </motion.div>
    </div>
  )
}
