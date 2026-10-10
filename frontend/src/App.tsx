import { useCallback, useEffect, useRef, useState } from 'react'
import {
  downloadPdf, getHealth, makeTablature, transcribe,
  type Corrections, type Health, type Level, type Tablature, type TabParams, type Transcription,
} from './api'
import { NoteEditor } from './components/NoteEditor'
import { TabView } from './components/TabView'
import { TabSynth } from './synth'

const INSTRUMENTS = [
  { id: 'harmonica_diatonique', name: 'Harmonica diatonique', hint: '10 trous, le plus courant', icon: '🎵' },
  { id: 'harmonica_chromatique', name: 'Harmonica chromatique', hint: '12 trous en Do, avec bouton', icon: '🎶' },
  { id: 'guitare', name: 'Guitare', hint: 'Accordage standard', icon: '🎸' },
  { id: 'piano', name: 'Piano', hint: 'Noms des notes, MD / MG', icon: '🎹' },
]

const LEVELS: { id: Level; name: string; hint: string }[] = [
  { id: 'debutant', name: 'Débutant', hint: 'Mélodie simplifiée, sans technique' },
  { id: 'intermediaire', name: 'Intermédiaire', hint: 'Plus de notes, bends d’½ ton' },
  { id: 'avance', name: 'Avancé', hint: 'Mélodie détaillée, tous les bends' },
  { id: 'expert', name: 'Expert', hint: 'Au plus près de l’original' },
]

const HARP_KEYS = ['auto', 'C', 'G', 'A', 'D', 'F', 'Bb', 'E', 'Eb', 'Ab', 'Db', 'B', 'F#']

type Source = 'youtube' | 'file'

function Section({ step, title, children }: { step: number; title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-600 text-xs text-white">{step}</span>
        {title}
      </h2>
      {children}
    </section>
  )
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [source, setSource] = useState<Source>('file')
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [rights, setRights] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [instrument, setInstrument] = useState('harmonica_diatonique')
  const [level, setLevel] = useState<Level>('debutant')
  const [harpKey, setHarpKey] = useState('auto')
  const [tempo, setTempo] = useState<number | undefined>(undefined)
  const [recordingIsInstrument, setRecordingIsInstrument] = useState(true)
  const [corrections, setCorrections] = useState<Corrections>({})
  const [selected, setSelected] = useState<{ ev: number; note: number } | null>(null)

  const [transcription, setTranscription] = useState<Transcription | null>(null)
  const [transcribedFrom, setTranscribedFrom] = useState('')
  const [tab, setTab] = useState<Tablature | null>(null)
  const [busy, setBusy] = useState<'' | 'transcribe' | 'tab' | 'pdf'>('')
  const [error, setError] = useState('')
  const [view, setView] = useState<'cards' | 'text'>('cards')

  const [speed, setSpeed] = useState(1)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [synthPlaying, setSynthPlaying] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)
  const synth = useRef(new TabSynth())

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null))
  }, [])

  const params: TabParams = {
    instrument,
    level,
    options: {
      recording_is_instrument: recordingIsInstrument,
      ...(instrument === 'harmonica_diatonique' ? { harp_key: harpKey } : {}),
    },
    tempo,
    corrections,
  }
  const paramsKey = JSON.stringify(params)
  const sourceKey = source === 'file' ? `file:${file?.name}:${file?.size}:${file?.lastModified}` : `yt:${youtubeUrl.trim()}`

  const validate = (): string => {
    if (source === 'file') {
      if (!file) return 'Choisissez un fichier MP3 ou WAV.'
      if (!/\.(mp3|wav)$/i.test(file.name)) return 'Format non pris en charge : seuls les fichiers .mp3 et .wav sont acceptés.'
      if (file.size > 40 * 1024 * 1024) return 'Fichier trop volumineux (40 Mo maximum).'
    } else {
      if (!youtubeUrl.trim()) return 'Collez un lien YouTube.'
      if (!/^(https?:\/\/)?(www\.|m\.|music\.)?(youtube\.com\/(watch\?.*v=|shorts\/|embed\/)|youtu\.be\/)[\w-]{11}/i.test(youtubeUrl.trim()))
        return 'Ce lien ne ressemble pas à une vidéo YouTube (ex. https://www.youtube.com/watch?v=…).'
      if (!rights) return "Cochez la case confirmant que vous avez le droit d'utiliser l'audio de cette vidéo."
    }
    return ''
  }

  const stopAll = () => {
    synth.current.stop()
    setSynthPlaying(false)
    setActiveIndex(-1)
  }

  const refreshTab = useCallback(async (t: Transcription, p: TabParams) => {
    setBusy('tab')
    setError('')
    try {
      setTab(await makeTablature(t, p))
    } catch (e) {
      setTab(null)
      setError((e as Error).message)
    } finally {
      setBusy('')
    }
  }, [])

  const generate = async () => {
    const msg = validate()
    if (msg) {
      setError(msg)
      return
    }
    stopAll()
    setError('')
    let t = transcription
    if (!t || transcribedFrom !== sourceKey) {
      setBusy('transcribe')
      setTab(null)
      try {
        t = await transcribe(source === 'file' ? { file: file!, rightsConfirmed: false } : { youtubeUrl, rightsConfirmed: rights })
        setTranscription(t)
        setTranscribedFrom(sourceKey)
        setTempo(undefined)
        setCorrections({})
        setSelected(null)
      } catch (e) {
        setBusy('')
        setError((e as Error).message)
        return
      }
    }
    await refreshTab(t, t === transcription ? params : { ...params, tempo: undefined, corrections: {} })
  }

  // Changer d'instrument, de niveau ou de tonalité recalcule la tablature
  // sans réanalyser l'audio.
  const lastParams = useRef(paramsKey)
  useEffect(() => {
    if (lastParams.current === paramsKey) return
    lastParams.current = paramsKey
    if (transcription && tab) {
      stopAll()
      void refreshTab(transcription, JSON.parse(paramsKey))
    }
  }, [paramsKey])

  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = speed
  }, [speed, transcription])

  const onAudioTime = () => {
    const a = audioRef.current
    if (!a || !tab || synthPlaying) return
    const t = a.currentTime
    let idx = -1
    tab.events.forEach((e, i) => {
      if (e.start <= t + 0.03) idx = i
    })
    const ev = tab.events[idx]
    setActiveIndex(ev && t <= Math.max(ev.end, ev.start + 0.3) + 0.15 ? idx : -1)
  }

  const toggleSynth = () => {
    if (!tab) return
    if (synthPlaying) {
      stopAll()
      return
    }
    audioRef.current?.pause()
    setSynthPlaying(true)
    synth.current.play(tab.events, tab.tempo, speed, setActiveIndex, () => setSynthPlaying(false))
  }

  const playPassage = (start: number, end: number) => {
    const a = audioRef.current
    if (!a) return
    stopAll()
    a.currentTime = Math.max(0, start - 0.3)
    a.playbackRate = speed
    void a.play()
    const stopAt = end + 0.3
    const check = () => {
      if (a.currentTime >= stopAt || a.paused) a.pause()
      else requestAnimationFrame(check)
    }
    requestAnimationFrame(check)
  }

  const exportPdf = async () => {
    if (!transcription) return
    setBusy('pdf')
    try {
      await downloadPdf(transcription, params)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  const s = tab?.summary
  const ytUnavailable = health && !health.youtube.available

  return (
    <div className="min-h-screen">
      <header className="bg-gradient-to-br from-indigo-600 via-indigo-600 to-violet-600 text-white">
        <div className="mx-auto max-w-5xl px-4 py-10 sm:py-14">
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">TabMaker</h1>
          <p className="mt-3 max-w-2xl text-indigo-100">
            Importez un morceau, choisissez votre instrument et votre niveau : l'application détecte les notes avec un
            modèle de transcription audio, puis les convertit en tablature jouable. Priorité à l'harmonica.
          </p>
        </div>
      </header>

      <main className="mx-auto -mt-6 max-w-5xl space-y-6 px-4 pb-16">
        <div className="space-y-8 rounded-3xl bg-white p-5 shadow-xl shadow-slate-200/60 ring-1 ring-slate-100 sm:p-8">
          {health && !health.transcription.available && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              Le moteur de transcription n'est pas installé sur le serveur : {health.transcription.error}. Voir le README.
            </div>
          )}

          <Section step={1} title="Le morceau">
            <div className="inline-flex rounded-xl bg-slate-100 p-1 text-sm font-medium">
              {(['file', 'youtube'] as Source[]).map((src) => (
                <button
                  key={src}
                  type="button"
                  onClick={() => setSource(src)}
                  className={`rounded-lg px-4 py-2 transition ${source === src ? 'bg-white text-indigo-700 shadow' : 'text-slate-500 hover:text-slate-700'}`}
                >
                  {src === 'file' ? 'Fichier audio' : 'Lien YouTube'}
                </button>
              ))}
            </div>

            {source === 'file' ? (
              <label
                className="flex cursor-pointer flex-col items-center justify-center gap-1 rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center transition hover:border-indigo-400 hover:bg-indigo-50/40"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault()
                  const f = e.dataTransfer.files[0]
                  if (f) setFile(f)
                }}
              >
                <input type="file" accept=".mp3,.wav,audio/mpeg,audio/wav" className="hidden"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                <span className="text-3xl">🎧</span>
                {file ? (
                  <span className="font-medium text-slate-700">{file.name} <span className="text-slate-400">({(file.size / 1024 / 1024).toFixed(1)} Mo)</span></span>
                ) : (
                  <span className="font-medium text-slate-700">Glissez un fichier ici ou cliquez pour choisir</span>
                )}
                <span className="text-xs text-slate-500">MP3 ou WAV · 10 minutes et 40 Mo maximum · une mélodie bien audible donne les meilleurs résultats</span>
              </label>
            ) : (
              <div className="space-y-3">
                <input
                  type="url"
                  value={youtubeUrl}
                  onChange={(e) => setYoutubeUrl(e.target.value)}
                  placeholder="https://www.youtube.com/watch?v=…"
                  className="w-full rounded-xl border border-slate-300 px-4 py-3 outline-none ring-indigo-500 focus:ring-2"
                />
                <label className="flex items-start gap-2 text-sm text-slate-600">
                  <input type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)} className="mt-1" />
                  Je confirme avoir le droit d'utiliser l'audio de cette vidéo (ma propre vidéo, licence libre/Creative
                  Commons, ou autorisation de l'auteur).
                </label>
                <p className="text-xs text-slate-500">
                  Si l'audio ne peut pas être récupéré (vidéo protégée, restrictions de YouTube), importez plutôt un fichier MP3 ou WAV.
                  {ytUnavailable && (
                    <span className="mt-1 block font-medium text-orange-600">
                      Sur ce serveur, {!health.youtube.ffmpeg ? 'FFmpeg' : 'yt-dlp'} n'est pas installé : l'import YouTube ne fonctionnera pas (voir README).
                    </span>
                  )}
                </p>
              </div>
            )}
          </Section>

          <Section step={2} title="Votre instrument">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {INSTRUMENTS.map((i) => (
                <button
                  key={i.id}
                  type="button"
                  onClick={() => setInstrument(i.id)}
                  className={`rounded-2xl border-2 p-3 text-left transition ${instrument === i.id ? 'border-indigo-600 bg-indigo-50' : 'border-slate-200 hover:border-slate-300'}`}
                >
                  <div className="text-2xl">{i.icon}</div>
                  <div className="mt-1 font-semibold">{i.name}</div>
                  <div className="text-xs text-slate-500">{i.hint}</div>
                </button>
              ))}
            </div>
            {instrument === 'harmonica_diatonique' && (
              <label className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
                Tonalité de l'harmonica :
                <select value={harpKey} onChange={(e) => setHarpKey(e.target.value)}
                  className="rounded-lg border border-slate-300 bg-white px-2 py-1">
                  {HARP_KEYS.map((k) => (
                    <option key={k} value={k}>{k === 'auto' ? 'Automatique (harmonica recommandé)' : k}</option>
                  ))}
                </select>
                <span className="text-xs text-slate-400">gravée sur le côté de l'harmonica (C = Do)</span>
              </label>
            )}
            <label className="flex items-start gap-2 text-sm text-slate-600">
              <input type="checkbox" checked={recordingIsInstrument} onChange={(e) => setRecordingIsInstrument(e.target.checked)} className="mt-1" />
              <span>
                L'enregistrement est joué avec cet instrument
                <span className="block text-xs text-slate-400">
                  Les notes impossibles sur cet instrument (hors tessiture) sont alors écartées comme erreurs de détection.
                  Décochez pour transcrire un autre instrument ou une voix.
                </span>
              </span>
            </label>
            <p className="text-xs text-slate-400">D'autres instruments pourront être ajoutés (ukulélé, flûte, basse…).</p>
          </Section>

          <Section step={3} title="Votre niveau">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {LEVELS.map((l) => (
                <button
                  key={l.id}
                  type="button"
                  onClick={() => setLevel(l.id)}
                  className={`rounded-2xl border-2 p-3 text-left transition ${level === l.id ? 'border-indigo-600 bg-indigo-50' : 'border-slate-200 hover:border-slate-300'}`}
                >
                  <div className="font-semibold">{l.name}</div>
                  <div className="text-xs text-slate-500">{l.hint}</div>
                </button>
              ))}
            </div>
          </Section>

          <div className="space-y-3">
            <button
              type="button"
              onClick={generate}
              disabled={busy !== ''}
              className="w-full rounded-2xl bg-indigo-600 px-6 py-4 text-lg font-semibold text-white shadow-lg shadow-indigo-200 transition hover:bg-indigo-700 disabled:cursor-wait disabled:opacity-70"
            >
              {busy === 'transcribe' ? 'Analyse de l’audio en cours…' : busy === 'tab' ? 'Création de la tablature…' : 'Générer ma tablature'}
            </button>
            {busy === 'transcribe' && (
              <p className="text-center text-sm text-slate-500">
                Le modèle détecte les notes (environ 5 à 30 s selon la durée du morceau).
              </p>
            )}
            {error && (
              <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
            )}
          </div>
        </div>

        {transcription && tab && s && (
          <div className="space-y-5 rounded-3xl bg-white p-5 shadow-xl shadow-slate-200/60 ring-1 ring-slate-100 sm:p-8">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-2xl font-bold">{transcription.title}</h2>
                <p className="text-sm text-slate-500">
                  {String(s.instrument)}
                  {s.harp_key ? ` en ${s.harp_key}` : ''} · {LEVELS.find((l) => l.id === tab.level)?.name} · tempo {tab.tempo} BPM ·{' '}
                  {s.playable}/{s.total} notes jouables · {Number(s.uncertain ?? 0)} incertaine(s)
                </p>
              </div>
              <button type="button" onClick={exportPdf} disabled={busy !== ''}
                className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-60">
                {busy === 'pdf' ? 'Export…' : 'Exporter en PDF'}
              </button>
            </div>

            <p className="rounded-xl bg-slate-50 p-3 text-xs text-slate-500">
              Transcription automatique réelle par {transcription.engine} : {transcription.notes.length} notes détectées dans l'audio
              ({transcription.duration.toFixed(0)} s). Un modèle peut se tromper (notes manquantes, harmoniques,
              accompagnement) : vérifiez à l'oreille en comparant l'original et la tablature.
            </p>

            {tab.warnings.length > 0 && (
              <ul className="space-y-1 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                {tab.warnings.map((w) => <li key={w}>⚠️ {w}</li>)}
              </ul>
            )}

            <div className="grid gap-3 rounded-2xl bg-slate-50 p-4 sm:grid-cols-[1fr_auto] sm:items-center">
              <div className="space-y-2">
                <div className="text-xs font-medium text-slate-500">Audio original</div>
                <audio ref={audioRef} src={transcription.audio_url} controls className="w-full"
                  onPlay={() => { synth.current.stop(); setSynthPlaying(false) }}
                  onTimeUpdate={onAudioTime} onLoadedMetadata={() => { if (audioRef.current) audioRef.current.playbackRate = speed }} />
              </div>
              <div className="flex flex-col gap-2 sm:w-56">
                <button type="button" onClick={toggleSynth}
                  className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700">
                  {synthPlaying ? '■ Arrêter' : '▶ Écouter la tablature'}
                </button>
                <label className="flex items-center justify-between gap-2 text-xs text-slate-600">
                  Tempo (BPM)
                  <input type="number" min={30} max={300} value={tempo ?? transcription.tempo}
                    title="Tempo estimé automatiquement : corrigez-le s'il est faux, la tablature est recalculée."
                    onChange={(e) => { const v = Number(e.target.value); if (v >= 30 && v <= 300) setTempo(v) }}
                    className="w-20 rounded-md border border-slate-300 bg-white px-2 py-1" />
                </label>
                <label className="text-xs text-slate-600">
                  Vitesse : <b>{Math.round(speed * 100)} %</b>
                  <input type="range" min={0.5} max={1.25} step={0.05} value={speed}
                    onChange={(e) => setSpeed(Number(e.target.value))} className="w-full accent-indigo-600" />
                </label>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap gap-1">
                {LEVELS.map((l) => (
                  <button key={l.id} type="button" onClick={() => setLevel(l.id)}
                    className={`rounded-full px-3 py-1 text-sm ${level === l.id ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>
                    {l.name}
                  </button>
                ))}
              </div>
              <div className="inline-flex rounded-lg bg-slate-100 p-1 text-sm">
                {(['cards', 'text'] as const).map((v) => (
                  <button key={v} type="button" onClick={() => setView(v)}
                    className={`rounded-md px-3 py-1 ${view === v ? 'bg-white shadow' : 'text-slate-500'}`}>
                    {v === 'cards' ? 'Cartes' : 'Texte'}
                  </button>
                ))}
              </div>
            </div>

            <div className={busy === 'tab' ? 'opacity-50 transition' : 'transition'}>
              {view === 'cards' ? (
                <TabView tab={tab} activeIndex={activeIndex}
                  selected={selected} onSelect={(ev, note) => setSelected({ ev, note })} />
              ) : (
                <pre className="overflow-x-auto rounded-2xl bg-slate-900 p-4 text-sm leading-relaxed text-slate-100">{tab.text.join('\n')}</pre>
              )}
            </div>

            {selected && tab.events[selected.ev]?.notes[selected.note] && (
              <NoteEditor
                event={tab.events[selected.ev]}
                note={tab.events[selected.ev].notes[selected.note]}
                instrument={tab.instrument}
                octaveShift={Number(tab.summary.octave_shift ?? 0)}
                onPlay={playPassage}
                onClose={() => setSelected(null)}
                onCorrect={(id, pitch) => {
                  setCorrections((c) => ({ ...c, [id]: pitch }))
                  setSelected(null)
                }}
                onReset={(id) => {
                  setCorrections((c) => {
                    const next = { ...c }
                    delete next[id]
                    return next
                  })
                  setSelected(null)
                }}
              />
            )}
            {Object.keys(corrections).length > 0 && (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">
                <span>{Object.keys(corrections).length} correction(s) appliquée(s) par vous (cadre vert dans la tablature).</span>
                <button type="button" className="underline" onClick={() => setCorrections({})}>Annuler toutes les corrections</button>
              </div>
            )}

            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-600">Comment lire cette tablature</h3>
              <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                {tab.legend.map((l) => (
                  <div key={l.symbol} className="flex gap-3">
                    <dt className="w-24 shrink-0 font-mono font-bold text-indigo-700">{l.symbol}</dt>
                    <dd className="text-slate-600">{l.meaning}</dd>
                  </div>
                ))}
              </dl>
              {instrument.startsWith('harmonica') && (
                <p className="mt-2 text-xs text-slate-500">
                  Couleurs : <span className="text-sky-700">bleu = souffler</span>, <span className="text-rose-700">rouge = aspirer</span>,{' '}
                  <span className="text-amber-700">jaune = bend/overblow</span>, <span className="text-orange-700">orange = au-delà de votre niveau ou hors tessiture</span>.
                </p>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
