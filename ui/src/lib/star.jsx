import { useEffect, useState } from 'react'
import { Star } from 'lucide-react'

export const REPO_URL = 'https://github.com/yash-kalathiya/Job-Applier-4.0'

export function useStars() {
  const [n, setN] = useState(null)
  useEffect(() => {
    let cached = null
    try { cached = JSON.parse(sessionStorage.getItem('ja:stars') || 'null') } catch {}
    if (cached && Date.now() - cached.t < 3600e3) { setN(cached.n); return }
    fetch('https://api.github.com/repos/yash-kalathiya/Job-Applier-4.0').then(r => r.ok ? r.json() : null).then(d => {
      if (d && typeof d.stargazers_count === 'number') {
        setN(d.stargazers_count)
        try { sessionStorage.setItem('ja:stars', JSON.stringify({ n: d.stargazers_count, t: Date.now() })) } catch {}
      }
    }).catch(() => {})
  }, [])
  return n
}

export function StarButton({ className = '', label = 'Star', compact }) {
  const n = useStars()
  return (
    <a href={REPO_URL} target="_blank" rel="noreferrer" title="Star Job Applier 4.0 on GitHub"
      className={'inline-flex h-8 items-center gap-1.5 rounded-full bg-white/[.08] px-3 text-[13px] font-medium text-white transition hover:bg-white/[.14] ' + className}>
      <Star className="size-3.5 fill-[#ffd60a] text-[#ffd60a]" />
      {!compact && <span>{label}</span>}
      {n !== null && <span className="tabular-nums text-white/60">{n.toLocaleString()}</span>}
    </a>
  )
}
