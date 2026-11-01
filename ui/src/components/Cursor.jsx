import { useEffect, useRef } from 'react'

/* A glowing ring that trails the pointer and swells into a halo over anything clickable. Desktop only. */
export function Cursor() {
  const dot = useRef(null), ring = useRef(null)
  useEffect(() => {
    if (matchMedia('(pointer: coarse)').matches) return
    let x = innerWidth / 2, y = innerHeight / 2, rx = x, ry = y, s = 1, ts = 1, raf
    const move = e => {
      x = e.clientX; y = e.clientY
      const el = e.target.closest?.('a,button,[role=button],input,textarea,select,[contenteditable],.card')
      ts = !el ? 1 : el.matches('input,textarea,[contenteditable]') ? 0.5 : el.classList.contains('card') && !el.matches('button,a') ? 1.25 : 2.1
    }
    const down = () => { ts *= 0.75 }, up = () => { ts /= 0.75 }
    const loop = () => {
      rx += (x - rx) * 0.18; ry += (y - ry) * 0.18; s += (ts - s) * 0.15
      if (dot.current) dot.current.style.transform = `translate(${x}px,${y}px) translate(-50%,-50%)`
      if (ring.current) { ring.current.style.transform = `translate(${rx}px,${ry}px) translate(-50%,-50%) scale(${s})`; ring.current.style.opacity = s > 1.6 ? '0.9' : '0.55' }
      raf = requestAnimationFrame(loop)
    }
    addEventListener('pointermove', move, { passive: true }); addEventListener('pointerdown', down); addEventListener('pointerup', up)
    raf = requestAnimationFrame(loop)
    return () => { cancelAnimationFrame(raf); removeEventListener('pointermove', move); removeEventListener('pointerdown', down); removeEventListener('pointerup', up) }
  }, [])
  return (
    <div className="pointer-events-none fixed inset-0 z-[100] hidden md:block">
      <div ref={ring} className="absolute left-0 top-0 size-8 rounded-full border border-[#8ab4ff]/70 bg-[#4c8dff]/[.08] shadow-[0_0_24px_rgb(76_141_255/.45)]" style={{ transition: 'opacity .2s' }} />
      <div ref={dot} className="absolute left-0 top-0 size-1.5 rounded-full bg-white shadow-[0_0_10px_#8ab4ff]" />
    </div>
  )
}
