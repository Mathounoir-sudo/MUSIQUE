import type { TabEvent, TabNote } from '../api'
import { frenchName } from '../notes'

interface Props {
  event: TabEvent
  note: TabNote
  instrument: string
  octaveShift: number
  onPlay: (start: number, end: number) => void
  onCorrect: (noteId: number, pitch: number | null) => void
  onReset: (noteId: number) => void
  onClose: () => void
}

/** Détail d'une note : confiance, raisons d'incertitude, correction manuelle. */
export function NoteEditor({ event, note, instrument, octaveShift, onPlay, onCorrect, onReset, onClose }: Props) {
  const id = note.note_id ?? -1
  // Les corrections portent sur la hauteur ENREGISTRÉE ; la tablature peut être
  // transposée d'une octave (octaveShift) pour tenir sur l'instrument.
  const recorded = note.pitch - octaveShift
  const suggestions = Array.from(new Set([...(note.alternatives ?? []), recorded - 1, recorded + 1, recorded - 12, recorded + 12]))
    .filter((p) => p !== recorded && p > 20 && p < 109)
  const conf = Math.round((note.confidence ?? 1) * 100)

  return (
    <div className="space-y-3 rounded-2xl border border-indigo-200 bg-indigo-50/60 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm text-slate-500">Note sélectionnée · {event.start.toFixed(2)} s</div>
          <div className="text-lg font-semibold">
            <span className="font-mono">{note.label}</span> — {note.french} ({note.name})
            {octaveShift !== 0 && <span className="text-sm font-normal text-slate-500"> · entendue {frenchName(recorded)}</span>}
          </div>
          {note.corrected_from != null ? (
            <div className="text-sm text-emerald-700">
              Corrigée par vous : détectée {frenchName(note.corrected_from)} → corrigée {frenchName(recorded)}
            </div>
          ) : (
            <div className="text-sm text-slate-600">
              Confiance de la détection : <b>{conf} %</b>
              {note.cents ? ` · écart ${note.cents > 0 ? '+' : ''}${Math.round(note.cents)} cents` : ''}
            </div>
          )}
          {note.uncertain_reasons?.map((r) => <div key={r} className="text-sm text-orange-700">⚠ {r}</div>)}
          {note.issue && <div className="text-sm text-orange-700">⚠ {note.issue}</div>}
        </div>
        <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600" aria-label="Fermer">✕</button>
      </div>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => onPlay(event.start, event.end)}
          className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700">
          ▶ Écouter ce passage (original)
        </button>
        {id >= 0 && note.corrected_from != null && (
          <button type="button" onClick={() => onReset(id)} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm">
            Revenir à la note détectée
          </button>
        )}
      </div>

      {id >= 0 ? (
        <div className="space-y-1">
          <div className="text-sm text-slate-600">
            La note entendue est différente ? Choisissez la bonne hauteur (telle qu'enregistrée)
            {instrument.startsWith('harmonica') ? ' (la tablature sera recalculée)' : ''} :
          </div>
          <div className="flex flex-wrap gap-1">
            {suggestions.map((p) => (
              <button key={p} type="button" onClick={() => onCorrect(id, p)}
                className={`rounded-lg border px-2 py-1 text-sm ${note.alternatives?.includes(p) ? 'border-amber-400 bg-amber-50' : 'border-slate-300 bg-white'} hover:border-indigo-500`}>
                {frenchName(p)}
              </button>
            ))}
            <select className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm" value=""
              onChange={(e) => e.target.value && onCorrect(id, Number(e.target.value))}>
              <option value="">Autre note…</option>
              {Array.from({ length: 61 }, (_, i) => i + 43).map((p) => <option key={p} value={p}>{frenchName(p)}</option>)}
            </select>
            <button type="button" onClick={() => onCorrect(id, null)}
              className="rounded-lg border border-red-200 bg-white px-2 py-1 text-sm text-red-700">
              Supprimer (note parasite)
            </button>
          </div>
          {(note.alternatives?.length ?? 0) > 0 && (
            <div className="text-xs text-slate-500">Encadrées en jaune : autres hauteurs détectées au même instant.</div>
          )}
        </div>
      ) : (
        <div className="text-sm text-slate-500">Cette note ne peut pas être corrigée individuellement.</div>
      )}
    </div>
  )
}
