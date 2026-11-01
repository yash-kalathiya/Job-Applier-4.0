import { useEffect, useState } from 'react'
import { api } from '../lib/api'

/* Every question applications ask, answered once and used on every form. Used by onboarding and Settings.
   Nothing is pre-selected: an unanswered question stays blank until the person answers it. */

export function useQuestions() {
  const [qs, setQs] = useState(null)
  useEffect(() => { api('/api/questions').then(d => setQs(d.questions)) }, [])
  return qs
}

export const getv = (p, k) => k.startsWith('eeo.') ? (p.eeo || {})[k.slice(4)] : p[k]
export const setv = (p, k, v) => k.startsWith('eeo.') ? { ...p, eeo: { ...(p.eeo || {}), [k.slice(4)]: v } } : { ...p, [k]: v }
export const missing = (qs, p) => (qs || []).filter(q => !q.optional && [undefined, null, ''].includes(getv(p, q.key)))

export function ProfileQuestions({ qs, p, setP, groups, showMissing, filled = [], large }) {
  if (!qs) return <div className="skel h-64" />
  const names = groups || [...new Set(qs.map(q => q.group))]
  return (
    <div className="space-y-7">
      {names.map(g => (
        <section key={g}>
          {!large && <div className="mb-2 px-1 text-[13px] text-muted">{g}{g.startsWith('Voluntary') && ' · you can decline any of these'}</div>}
          <div className={'divide-y divide-white/[.06] overflow-hidden ring-1 ring-white/[.08] ' + (large ? 'rounded-[20px] bg-white/[.06] backdrop-blur' : 'rounded-[16px] bg-white/[.035]')}>
            {qs.filter(q => q.group === g).map(q => {
              const v = getv(p, q.key)
              const blank = [undefined, null, ''].includes(v)
              return (
                <div key={q.key} className={'flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-6 ' + (large ? 'px-5 py-3.5' : 'min-h-[52px] px-4 py-2.5')}>
                  <div className={'flex min-w-0 flex-1 flex-wrap items-center gap-x-2 text-white ' + (large ? 'text-[16px]' : 'text-[14.5px]')}>
                    <span>{q.label}</span>{q.optional && <span className="text-[12px] text-faint">optional</span>}
                    {showMissing && blank && !q.optional && <span className="text-[12px] text-[#ff9f0a]">Needed</span>}
                    {filled.includes(q.key) && !blank && <span className="text-[12px] text-[#64d2ff]">filled in for you</span>}
                  </div>
                  <div className="w-full shrink-0 sm:w-[46%]">
                    {q.kind === 'yesno' ? <YesNo value={v} onChange={x => setP(setv(p, q.key, x))} />
                      : q.kind === 'select' ? (
                        <select value={v || ''} onChange={e => setP(setv(p, q.key, e.target.value))}
                          className={'h-9 w-full rounded-[10px] bg-white/[.06] px-3 text-[14px] outline-none focus:ring-2 focus:ring-signal ' + (v ? 'text-white' : 'text-faint')}>
                          <option value="" disabled>Choose…</option>
                          {(v && !q.options.includes(v) ? [v, ...q.options] : q.options).map(o => <option key={o} value={o} className="text-black">{o}</option>)}
                        </select>)
                      : <input value={v || ''} placeholder={q.hint || ''} onChange={e => setP(setv(p, q.key, e.target.value))}
                          className="h-9 w-full rounded-[10px] bg-white/[.06] px-3 text-[14px] text-white outline-none placeholder:text-faint focus:ring-2 focus:ring-signal" />}
                  </div>
                </div>)
            })}
          </div>
        </section>))}
    </div>
  )
}

function YesNo({ value, onChange }) {
  return (
    <div className="inline-flex rounded-[10px] bg-white/[.06] p-[2px]">
      {[[true, 'Yes'], [false, 'No']].map(([v, l]) => (
        <button key={l} type="button" onClick={() => onChange(v)}
          className={'h-8 rounded-[8px] px-5 text-[13.5px] transition ' + (value === v ? 'bg-white font-semibold text-[#1d1d1f]' : 'text-white/75 hover:text-white')}>{l}</button>))}
    </div>
  )
}
