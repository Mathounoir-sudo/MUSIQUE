import type { TabEvent, TabNote, Tablature } from '../api'

function noteStyle(n: TabNote, instrument: string): string {
  if (!n.playable) return 'border-orange-400 bg-orange-50 text-orange-800'
  if (instrument.startsWith('harmonica')) {
    if (n.overblow || (n.bend ?? 0) > 0) return 'border-amber-400 bg-amber-50 text-amber-900'
    return n.action === 'draw' ? 'border-rose-300 bg-rose-50 text-rose-800' : 'border-sky-300 bg-sky-50 text-sky-800'
  }
  if (instrument === 'piano') return n.hand === 'MG' ? 'border-violet-300 bg-violet-50 text-violet-800' : 'border-emerald-300 bg-emerald-50 text-emerald-800'
  return 'border-slate-300 bg-white text-slate-800'
}

function subtitle(n: TabNote, instrument: string): string {
  if (instrument.startsWith('harmonica')) {
    if (n.label === '?') return n.french
    const verb = n.action === 'draw' ? 'aspirer' : 'souffler'
    const extra = n.overblow ? ' · OB' : n.bend ? ` · bend ${n.bend === 1 ? '½ ton' : `${n.bend}×½`}` : n.slide ? ' · bouton' : ''
    return `${verb}${extra}`
  }
  if (instrument === 'guitare') return n.label === '?' ? n.name : `corde ${n.string} · case ${n.fret}`
  return n.hand ?? ''
}

function EventCard({ ev, instrument, active }: { ev: TabEvent; instrument: string; active: boolean }) {
  return (
    <div
      className={`flex flex-col gap-1 rounded-xl p-1 transition ${active ? 'bg-indigo-100 ring-2 ring-indigo-500' : ''}`}
      style={{ minWidth: `${Math.max(3.4, Math.min(ev.beats, 4) * 2.6)}rem` }}
    >
      {ev.notes.map((n, i) => {
        const display = instrument === 'guitare' && n.label !== '?' ? `${n.fret}` : n.label
        return (
          <div
            key={i}
            title={[n.detail, `${n.french} (${n.name})`, n.issue].filter(Boolean).join('\n')}
            className={`rounded-lg border-2 px-2 py-1 text-center ${noteStyle(n, instrument)}`}
          >
            <div className="font-mono text-xl font-bold leading-tight">{display}</div>
            <div className="text-[10px] leading-tight opacity-80">{subtitle(n, instrument)}</div>
            <div className="text-[10px] leading-tight opacity-60">{n.french}</div>
          </div>
        )
      })}
    </div>
  )
}

export function TabView({ tab, activeIndex }: { tab: Tablature; activeIndex: number }) {
  const measures = new Map<number, { ev: TabEvent; idx: number }[]>()
  tab.events.forEach((ev, idx) => {
    const list = measures.get(ev.measure) ?? []
    list.push({ ev, idx })
    measures.set(ev.measure, list)
  })
  const last = Math.max(...tab.events.map((e) => e.measure))
  const all = Array.from({ length: last }, (_, i) => i + 1)

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {all.map((m) => (
        <div key={m} className="rounded-2xl border border-slate-200 bg-white p-2 shadow-sm">
          <div className="mb-1 px-1 text-xs font-medium text-slate-400">Mesure {m}</div>
          <div className="flex flex-wrap items-start gap-1">
            {(measures.get(m) ?? []).map(({ ev, idx }) => (
              <EventCard key={idx} ev={ev} instrument={tab.instrument} active={idx === activeIndex} />
            ))}
            {!measures.get(m) && <div className="px-2 py-4 text-sm text-slate-400">silence</div>}
          </div>
        </div>
      ))}
    </div>
  )
}
