import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
export const cn = (...a) => twMerge(clsx(a))
export const ago = ts => {
  if (!ts) return ''
  const s = Date.now() / 1000 - ts
  if (s < 3600) return Math.max(1, Math.round(s / 60)) + 'm'
  if (s < 86400) return Math.round(s / 3600) + 'h'
  return Math.round(s / 86400) + 'd'
}
const HUES = [234, 262, 199, 330, 160, 24, 280, 210]
export const hue = name => { let h = 0; for (const c of name || '?') h = (h * 31 + c.charCodeAt(0)) >>> 0; return HUES[h % HUES.length] }
export const plain = s => (s || '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/\*\*/g, '')
