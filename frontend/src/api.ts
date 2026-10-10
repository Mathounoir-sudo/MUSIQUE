// Types et appels à l'API Python (voir backend/app/main.py).

export type Level = 'debutant' | 'intermediaire' | 'avance' | 'expert'

export interface DetectedNote {
  start: number
  end: number
  pitch: number
  velocity: number
  name: string
}

export interface Transcription {
  id: string
  title: string
  source: 'file' | 'youtube'
  audio_url: string
  duration: number
  tempo: number
  engine: string
  notes: DetectedNote[]
}

export interface TabNote {
  pitch: number
  name: string
  french: string
  label: string
  detail: string
  playable: boolean
  issue: string | null
  action?: 'blow' | 'draw'
  bend?: number
  overblow?: boolean
  slide?: boolean
  string?: number
  fret?: number
  hand?: 'MD' | 'MG'
}

export interface TabEvent {
  start: number
  end: number
  beat: number
  beats: number
  measure: number
  notes: TabNote[]
}

export interface Tablature {
  instrument: string
  level: Level
  tempo: number
  beats_per_measure: number
  events: TabEvent[]
  text: string[]
  legend: { symbol: string; meaning: string }[]
  summary: Record<string, string | number | boolean>
  warnings: string[]
}

export interface Health {
  transcription: { available: boolean; engine?: string; error?: string }
  youtube: { available: boolean; yt_dlp: boolean; ffmpeg: boolean }
}

async function errorMessage(r: Response): Promise<string> {
  try {
    const data = await r.json()
    if (typeof data.detail === 'string') return data.detail
    if (Array.isArray(data.detail)) return data.detail.map((d: { msg: string }) => d.msg).join(' ; ')
  } catch {
    /* réponse non JSON */
  }
  return `Erreur du serveur (${r.status}).`
}

async function call<T>(url: string, init: RequestInit): Promise<T> {
  let r: Response
  try {
    r = await fetch(url, init)
  } catch {
    throw new Error("Impossible de joindre le serveur d'analyse. Vérifiez qu'il est lancé (voir README).")
  }
  if (!r.ok) throw new Error(await errorMessage(r))
  return r.json() as Promise<T>
}

export function getHealth(): Promise<Health> {
  return call('/api/health', {})
}

export function transcribe(input: { file?: File; youtubeUrl?: string; rightsConfirmed: boolean }): Promise<Transcription> {
  const form = new FormData()
  if (input.file) form.append('file', input.file)
  else form.append('youtube_url', input.youtubeUrl ?? '')
  form.append('rights_confirmed', String(input.rightsConfirmed))
  return call('/api/transcribe', { method: 'POST', body: form })
}

export interface TabParams {
  instrument: string
  level: Level
  options: Record<string, string>
  tempo?: number
}

function tabBody(t: Transcription, p: TabParams) {
  return JSON.stringify({
    notes: t.notes.map(({ start, end, pitch, velocity }) => ({ start, end, pitch, velocity })),
    tempo: p.tempo ?? t.tempo,
    instrument: p.instrument,
    level: p.level,
    options: p.options,
    title: t.title,
    engine: t.engine,
  })
}

export function makeTablature(t: Transcription, p: TabParams): Promise<Tablature> {
  return call('/api/tablature', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: tabBody(t, p) })
}

export async function downloadPdf(t: Transcription, p: TabParams): Promise<void> {
  const r = await fetch('/api/pdf', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: tabBody(t, p) })
  if (!r.ok) throw new Error(await errorMessage(r))
  const blob = await r.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${t.title || 'tablature'} - ${p.instrument} - ${p.level}.pdf`
  a.click()
  URL.revokeObjectURL(a.href)
}
