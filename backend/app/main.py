"""API HTTP : import audio → transcription → tablature."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import audio_input
from .audio_input import InputError
from .instruments import INSTRUMENTS
from .music import LEVELS, build_events, midi_to_name
from .note_cleanup import DetectedNote
from .pdf_export import render_pdf
from .transcription import TranscriptionUnavailable, engine_status, transcribe

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tablatures")

app = FastAPI(title="Générateur de tablatures", version="1.0.0")

Level = Literal["debutant", "intermediaire", "avance", "expert"]


class NoteIn(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    pitch: int = Field(ge=0, le=127)
    velocity: float = Field(default=0.8, ge=0, le=1.5)
    cents: float = Field(default=0.0, ge=-100, le=100)
    id: int = -1
    # Hauteur détectée à l'origine, si l'utilisateur a corrigé la note.
    original_pitch: int | None = Field(default=None, ge=0, le=127)


class TabRequest(BaseModel):
    notes: list[NoteIn] = Field(max_length=20000)
    tempo: float = Field(default=100, gt=20, lt=400)
    instrument: str
    level: Level = "debutant"
    options: dict = Field(default_factory=dict)
    title: str = ""
    engine: str = ""


@app.get("/api/health")
def health():
    return {"status": "ok", "transcription": engine_status(), "youtube": audio_input.youtube_status()}


@app.get("/api/instruments")
def instruments():
    return {"instruments": [i.info() for i in INSTRUMENTS.values()], "levels": list(LEVELS)}


@app.post("/api/transcribe")
def transcribe_endpoint(
    file: UploadFile | None = File(default=None),
    youtube_url: str = Form(default=""),
    rights_confirmed: bool = Form(default=False),
):
    """Étape 1 : récupère l'audio et le transcrit en notes (indépendant de l'instrument)."""
    if file is None and not youtube_url.strip():
        raise HTTPException(400, "Collez un lien YouTube ou importez un fichier MP3/WAV.")
    job_id, job_dir = audio_input.new_job()
    try:
        if file is not None and file.filename:
            title = Path(file.filename).stem
            y = audio_input.save_upload(file.filename, file.file.read(), job_dir)
            source = "file"
        else:
            if not rights_confirmed:
                raise InputError("Confirmez que vous avez le droit d'utiliser l'audio de cette vidéo "
                                 "(votre propre contenu, licence libre ou autorisation de l'auteur).")
            y, title = audio_input.download_youtube(youtube_url, job_dir)
            source = "youtube"
        result = transcribe(job_dir / "audio.wav", y, audio_input.SAMPLE_RATE)
    except InputError as exc:
        raise HTTPException(400, str(exc))
    except TranscriptionUnavailable as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:  # pragma: no cover - erreur inattendue
        log.exception("Échec de la transcription")
        raise HTTPException(500, f"Erreur pendant l'analyse audio : {exc}")

    if not result.notes:
        raise HTTPException(422, "Aucune note n'a été détectée dans cet audio. "
                                 "Essayez un enregistrement plus net, avec une mélodie bien audible.")
    log.info("Transcription %s : %d notes, %.1f BPM", job_id, len(result.notes), result.tempo)
    return {
        "id": job_id,
        "title": title,
        "source": source,
        "audio_url": f"/api/audio/{job_id}",
        "duration": result.duration,
        "tempo": result.tempo,
        "engine": result.engine,
        "notes": [{**n.to_dict(), "id": i, "name": midi_to_name(n.pitch)} for i, n in enumerate(result.notes)],
    }


@app.get("/api/audio/{job_id}")
def audio(job_id: str):
    path = audio_input.job_audio(job_id)
    if path is None:
        raise HTTPException(404, "Audio expiré ou introuvable. Relancez l'import.")
    return FileResponse(path, media_type="audio/wav")


def _make_tab(req: TabRequest):
    inst = INSTRUMENTS.get(req.instrument)
    if inst is None:
        raise HTTPException(400, f"Instrument inconnu : {req.instrument}")
    notes = [DetectedNote(n.start, n.end, n.pitch, n.velocity, n.cents, id=n.id, original_pitch=n.original_pitch,
                          source="correction utilisateur" if n.original_pitch is not None else "basic-pitch")
             for n in req.notes if n.end > n.start]
    events, report = build_events(notes, req.tempo, req.level, inst.max_polyphony, inst.pitch_range(req.options))
    if not events:
        raise HTTPException(422, "Aucune note exploitable à ce niveau. Essayez le niveau Expert.")
    try:
        tab = inst.tablature(events, req.level, req.options)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    tab.summary["cleanup"] = report
    uncertain = sum(n.get("uncertain", False) for e in tab.events for n in e["notes"])
    tab.summary["uncertain"] = uncertain
    total = max(1, tab.summary.get("total", 1))
    if uncertain / total > 0.35:
        tab.warnings.insert(0, f"{uncertain} note(s) sur {total} sont incertaines : l'enregistrement est difficile "
                               "à analyser (plusieurs instruments, bruit, notes très rapides). Vérifiez-les à l'oreille "
                               "et corrigez-les si besoin.")
    return tab


@app.post("/api/tablature")
def tablature(req: TabRequest):
    """Étape 2 : conversion des notes en tablature (rapide, sans réanalyse audio)."""
    tab = _make_tab(req)
    return {
        "instrument": req.instrument,
        "level": req.level,
        "tempo": req.tempo,
        "beats_per_measure": 4,
        "events": tab.events,
        "text": tab.text,
        "legend": tab.legend,
        "summary": tab.summary,
        "warnings": tab.warnings,
    }


@app.post("/api/pdf")
def pdf(req: TabRequest):
    tab = _make_tab(req)
    data = render_pdf(tab, req.title, req.level, req.tempo, req.engine or "Basic Pitch")
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="tablature.pdf"'})


# En production, le frontend compilé (frontend/dist) est servi par la même application.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
