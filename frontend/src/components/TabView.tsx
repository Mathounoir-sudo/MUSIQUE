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

interface CardProps {
  ev: TabEvent
  instrument: string
  active: boolean
  selectedNote: number | null
  onSelect: (note: number) => void
}

function EventCard({ ev, instrument, active, selectedNote, onSelect }: CardProps) {
  return (
    <div
      className={`flex flex-col gap-1 rounded-xl p-1 transition ${active ? 'bg-indigo-100 ring-2 ring-indigo-500' : ''}`}
      style={{ minWidth: `${Math.max(3.4, Math.min(ev.beats, 4) * 2.6)}rem` }}
    >
      {ev.notes.map((n, i) => {
        const display = instrument === 'guitare' && n.label !== '?' ? `${n.fret}` : n.label
        const conf = n.confidence ?? 1
        const corrected = n.corrected_from != null
        const border = corrected ? '!border-emerald-500 ring-1 ring-emerald-300' : n.uncertain ? 'border-dashed' : ''
        return (
          <button
            type="button"
            key={i}
            onClick={() => onSelect(i)}
            title={[n.detail, `${n.french} (${n.name})`, n.issue, ...(n.uncertain_reasons ?? []),
              corrected ? 'Corrigée par vous' : `Confiance ${Math.round(conf * 100)} %`].filter(Boolean).join('\n')}
            className={`relative rounded-lg border-2 px-2 py-1 text-center transition hover:shadow ${noteStyle(n, instrument)} ${border} ${selectedNote === i ? 'outline outline-2 outline-indigo-600' : ''}`}
          >
            {n.uncertain && !corrected && (
              <span className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-orange-500 text-[10px] font-bold text-white">?</span>
            )}
            {corrected && (
              <span className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-emerald-600 text-[10px] font-bold text-white">✓</span>
            )}
            <div className={`font-mono text-xl font-bold leading-tight ${n.uncertain && !corrected ? 'opacity-70' : ''}`}>{display}</div>
            <div className="text-[10px] leading-tight opacity-80">{subtitle(n, instrument)}</div>
            <div className="text-[10px] leading-tight opacity-60">{n.french}</div>
            {!corrected && (
              <div className="mx-auto mt-0.5 h-1 w-full overflow-hidden rounded bg-black/10" aria-label={`Confiance ${Math.round(conf * 100)} %`}>
                <div className={`h-full ${conf >= 0.5 ? 'bg-current opacity-50' : 'bg-orange-500'}`} style={{ width: `${Math.max(8, conf * 100)}%` }} />
              </div>
            )}
          </button>
        )
      })}
    </div>
  )
}

interface Props {
  tab: Tablature
  activeIndex: number
  selected: { ev: number; note: number } | null
  onSelect: (ev: number, note: number) => void
}

export function TabView({ tab, activeIndex, selected, onSelect }: Props) {
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
              <EventCard key={idx} ev={ev} instrument={tab.instrument} active={idx === activeIndex}
                selectedNote={selected?.ev === idx ? selected.note : null} onSelect={(note) => onSelect(idx, note)} />
            ))}
            {!measures.get(m) && <div className="px-2 py-4 text-sm text-slate-400">silence</div>}
          </div>
        </div>
      ))}
    </div>
  )
}
