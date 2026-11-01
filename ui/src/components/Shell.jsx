import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { Command } from 'cmdk'
import { Bell, Briefcase, FileText, House, LayoutList, MessageSquareText, Play, Search, Settings2, Sparkles } from 'lucide-react'
import { cn } from '../lib/utils'
import { api } from '../lib/api'
import { spring } from './ui'
import { StarButton } from '../lib/star'
import { ItemActions } from './ItemActions'

export const NAV = [['home', 'Today'], ['jobs', 'Jobs'], ['studio', 'Resume'], ['answers', 'Answers'], ['board', 'Applications'], ['agents', 'Autopilot']]

/* Two overlapping squares: you, and your twin. */
export function Logo({ size = 22 }) {
  const s = size * 0.68
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <div className="absolute left-0 top-0 rounded-[30%] bg-ink" style={{ width: s, height: s }} />
      <div className="absolute bottom-0 right-0 rounded-[30%] bg-signal ring-2 ring-white" style={{ width: s, height: s }} />
    </div>
  )
}

export const GoogleG = ({ className = 'size-4' }) => (
  <svg viewBox="0 0 48 48" className={className}><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 38.2 44 33 44 24c0-1.3-.1-2.4-.4-3.5z"/></svg>)

function Account({ auth, signIn, signOut }) {
  const [open, setOpen] = useState(false)
  if (!auth?.signed_in) return (
    <button onClick={signIn} className="flex h-8 items-center gap-2 rounded-full bg-white px-3.5 text-[13px] font-medium text-[#1d1d1f] shadow-[0_0_0_.5px_rgb(0_0_0/.12),0_1px_3px_rgb(0_0_0/.08)] transition hover:shadow-[0_0_0_.5px_rgb(0_0_0/.2),0_3px_10px_rgb(0_0_0/.1)]">
      <GoogleG />Sign in</button>)
  const u = auth.user || {}
  return (
    <div className="relative">
      <button onClick={() => setOpen(o => !o)} className="grid size-8 place-items-center overflow-hidden rounded-full bg-signal text-[13px] font-semibold text-white ring-2 ring-white">
        {u.avatar ? <img src={u.avatar} alt="" referrerPolicy="no-referrer" className="size-full object-cover" /> : (u.name || u.email || '?')[0].toUpperCase()}</button>
      <AnimatePresence>{open && (
        <motion.div initial={{ opacity: 0, y: -6, scale: .97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -4 }} transition={spring}
          className="absolute right-0 top-11 w-64 origin-top-right overflow-hidden rounded-[16px] bg-[#232325]/95 p-1.5 ring-1 ring-white/10 shadow-[0_20px_60px_rgb(0_0_0/.2),0_0_0_.5px_rgb(0_0_0/.08)] backdrop-blur-xl">
          <div className="px-3 py-2.5"><div className="truncate text-[14px] font-semibold">{u.name || 'Signed in'}</div><div className="truncate text-[12.5px] text-muted">{u.email}</div></div>
          <div className="mx-2 h-px bg-white/[.06]" />
          <div className="px-3 py-2 text-[12.5px] text-muted">Your vault, answers and resumes stay on this computer.</div>
          <button onClick={() => { setOpen(false); signOut() }} className="w-full rounded-[10px] px-3 py-2 text-left text-[14px] text-bad hover:bg-white/[.04]">Sign out</button>
        </motion.div>)}</AnimatePresence>
    </div>
  )
}

function Inbox() {
  const [d, setD] = useState({ items: [], pending: [] })
  const [open, setOpen] = useState(false)
  useEffect(() => {
    let t
    const f = async () => {
      try {
        const r = await fetch('/api/inbox').then(r => r.json()); setD(r)
        // anything new pops up as a Job Applier 4.0 notification; clicking it opens the place to answer it
        let seen = [], first = true
        try { const raw = localStorage.getItem('ja:notified'); first = raw === null; seen = JSON.parse(raw || '[]') } catch {}
        const fresh = r.items.filter(i => !seen.includes(i.id))
        if (!first && fresh.length && typeof Notification !== 'undefined' && Notification.permission === 'granted') {   // first load just records what's there
          for (const i of fresh.slice(0, 3)) {
            const n = new Notification('Job Applier 4.0: ' + i.title, { body: i.message || 'Open Job Applier 4.0 to handle it.', tag: 'ja' + i.id })
            n.onclick = () => { window.focus(); location.hash = 'agents'; n.close() }
          }
        }
        try { localStorage.setItem('ja:notified', JSON.stringify([...seen, ...fresh.map(i => i.id)].slice(-300))) } catch {}
      } catch {}
      t = setTimeout(f, 12000)
    }
    f(); return () => clearTimeout(t)
  }, [])
  const n = d.items.length
  const done = async id => { await api(`/api/inbox/${id}/resolve`, {}); setD(x => ({ ...x, items: x.items.filter(i => i.id !== id) })) }
  return (
    <div className="relative">
      <button onClick={() => setOpen(o => !o)} className="relative grid size-8 place-items-center rounded-full bg-white/[.05] text-muted transition hover:text-ink" title="Needs you">
        <Bell className="size-4" />
        <AnimatePresence>{n > 0 && <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }} exit={{ scale: 0 }}
          className="absolute -right-1 -top-1 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-[#ff453a] px-1 text-[10.5px] font-bold text-white">{n}</motion.span>}</AnimatePresence>
      </button>
      <AnimatePresence>{open && (
        <motion.div initial={{ opacity: 0, y: -6, scale: .97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -4 }} transition={spring}
          className="absolute right-0 top-11 w-[360px] origin-top-right overflow-hidden rounded-[16px] bg-[#232325]/97 p-2 shadow-[0_30px_80px_rgb(0_0_0/.5)] ring-1 ring-white/10">
          <div className="px-3 pb-2 pt-1.5 text-[14px] font-semibold text-white">Needs you</div>
          {n === 0 && <div className="px-3 pb-4 text-[13px] text-muted">Nothing right now. Your twin will ping you (and your Mac) if a site needs a code or a sign-in.</div>}
          <div className="max-h-[360px] overflow-y-auto">
            {d.items.map(i => (
              <div key={i.id} className="rounded-[12px] px-3 py-2.5 hover:bg-white/[.04]">
                <div className="text-[13.5px] font-medium text-white">{i.title}</div>
                {i.message && <div className="mt-0.5 text-[12.5px] text-muted">{i.message}</div>}
                <ItemActions item={i} compact onDone={() => setD(x => ({ ...x, items: x.items.filter(y => y.id !== i.id) }))} />
              </div>))}
          </div>
        </motion.div>)}</AnimatePresence>
    </div>
  )
}

const NAV_ICONS = { home: House, jobs: Briefcase, studio: FileText, answers: MessageSquareText, board: LayoutList, agents: Play }

/* The Mac way: a translucent sidebar with the app's sections, Settings at the bottom, and a small toolbar on the right. */
export function Sidebar({ page, go, onPalette, auth, signIn, signOut }) {
  const item = (id, label, Icon) => (
    <button key={id} onClick={() => go(id)}
      className={cn('flex h-8 w-full items-center gap-2.5 rounded-[7px] px-2.5 text-left text-[13.5px] transition-colors',
        page === id ? 'bg-signal text-white' : 'text-ink/85 hover:bg-white/[.06]')}>
      <Icon className={cn('size-[15px] shrink-0', page === id ? 'text-white' : 'text-signal-ink')} strokeWidth={2} />{label}
    </button>)
  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[220px] flex-col border-r border-white/[.06] bg-[#232325]/80 px-3 pb-4 pt-5 backdrop-blur-xl md:flex">
        <button onClick={() => go('home')} className="mb-5 flex items-center gap-2 px-2.5">
          <Logo size={20} /><span className="text-[15px] font-semibold tracking-[-0.01em] text-ink">Job Applier 4.0</span>
        </button>
        <nav className="space-y-0.5">{NAV.map(([id, label]) => item(id, label, NAV_ICONS[id]))}</nav>
        <div className="mt-auto space-y-0.5">
          {item('settings', 'Settings', Settings2)}
        </div>
      </aside>
      <div className="fixed right-5 top-3 z-40 hidden items-center gap-2 md:flex">
        <button onClick={onPalette} className="flex h-8 items-center gap-2 rounded-[8px] bg-white/[.06] px-3 text-[13px] text-muted transition hover:bg-white/[.1] hover:text-ink">
          <Search className="size-3.5" /><span>Search</span><kbd className="text-[11px] text-faint">⌘K</kbd>
        </button>
        <StarButton compact />
        <Inbox />
        <Account auth={auth} signIn={signIn} signOut={signOut} />
      </div>
    </>
  )
}

export function TopBar({ page, go, onPalette, matched, auth, signIn, signOut }) {
  return (
    <header className="glass fixed inset-x-0 top-0 z-40 border-b border-white/[.06] md:hidden">
      <div className="mx-auto flex h-[52px] max-w-[1240px] items-center gap-7 px-6">
        <button onClick={() => go('home')} className="flex items-center gap-2.5">
          <Logo /><span className="text-[17px] font-semibold tracking-[-0.02em] text-ink">Job Applier 4.0</span>
        </button>
        <nav className="hidden h-full items-stretch md:flex">
          {NAV.map(([id, label]) => (
            <button key={id} onClick={() => go(id)} className={cn('relative my-auto flex h-8 items-center gap-1.5 rounded-full px-3.5 text-[13.5px] transition-colors', page === id ? 'text-ink' : 'text-ink/60 hover:text-ink')}>
              {page === id && <motion.span layoutId="nav" transition={spring} className="absolute inset-0 rounded-full bg-white/[.06]" />}
              <span className="relative">{label}</span>
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={onPalette} className="flex h-8 items-center gap-2 rounded-full bg-white/[.05] px-3.5 text-[13px] text-muted transition hover:bg-white/[.08] hover:text-ink">
            <Search className="size-3.5" /><span className="hidden sm:inline">Search</span><kbd className="text-[11px] text-faint">⌘K</kbd>
          </button>
          <button onClick={() => go('settings')} className={cn('grid size-8 place-items-center rounded-full transition', page === 'settings' ? 'bg-white text-[#1d1d1f]' : 'bg-white/[.05] text-muted hover:text-ink')} title="Settings"><Settings2 className="size-4" /></button>
          <span className="hidden md:block"><StarButton compact /></span>
          <Inbox />
          <Account auth={auth} signIn={signIn} signOut={signOut} />
        </div>
      </div>
    </header>
  )
}

export function Palette({ open, setOpen, go, jobs, actions }) {
  useEffect(() => {
    const k = e => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setOpen(o => !o) } if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }, [setOpen])
  const head = '[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:text-[12.5px] [&_[cmdk-group-heading]]:text-muted'
  const it = 'flex cursor-pointer items-center gap-3 rounded-[10px] px-3 py-2.5 text-[14px] text-fg'
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 flex items-start justify-center bg-black/20 px-4 pt-[14vh] backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)}>
          <motion.div onClick={e => e.stopPropagation()} initial={{ y: -8, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ opacity: 0 }} transition={spring}
            className="w-full max-w-[620px] overflow-hidden rounded-[18px] bg-[#1c1c1e]/92 ring-1 ring-white/10 shadow-[0_40px_100px_rgb(0_0_0/.6)] backdrop-blur-2xl">
            <Command label="Command menu" loop>
              <div className="flex items-center gap-3 border-b border-white/[.06] px-4"><Search className="size-4 text-muted" />
                <Command.Input autoFocus placeholder="Search jobs, pages, actions" className="w-full bg-transparent py-4 text-[15px] placeholder:text-faint" /></div>
              <Command.List className="max-h-[52vh] overflow-y-auto p-2">
                <Command.Empty className="p-6 text-center text-[14px] text-muted">Nothing found.</Command.Empty>
                <Command.Group heading="Actions" className={head}>
                  {actions.map(([label, Icon, fn]) => <Command.Item key={label} onSelect={() => { setOpen(false); fn() }} className={it}><Icon className="size-4 text-signal" />{label}</Command.Item>)}
                </Command.Group>
                <Command.Group heading="Go to" className={head}>
                  {[...NAV, ['settings', 'Settings'], ['welcome', 'Start over']].map(([id, label]) =>
                    <Command.Item key={id} onSelect={() => { setOpen(false); go(id) }} className={it}>{label}</Command.Item>)}
                </Command.Group>
                {jobs.length > 0 && (
                  <Command.Group heading="Top matches" className={head}>
                    {jobs.slice(0, 60).map(j => (
                      <Command.Item key={j.id} value={`${j.title} ${j.company} ${j.id}`} onSelect={() => { setOpen(false); go('jobs', j.id) }} className={cn(it, 'justify-between')}>
                        <span className="truncate"><span className="font-medium">{j.title}</span><span className="text-muted"> · {j.company}</span></span>
                        <span className="text-[12.5px] tabular-nums text-muted">{Math.round(j.fit)}</span></Command.Item>))}
                  </Command.Group>)}
              </Command.List>
            </Command>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export const ICONS = { Sparkles }
