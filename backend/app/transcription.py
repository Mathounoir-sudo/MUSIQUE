"""Transcription audio → notes, avec le modèle Basic Pitch (Spotify).

Basic Pitch est un réseau de neurones entraîné pour la transcription
automatique (audio → MIDI, polyphonique, tous instruments). On utilise sa
version ONNX, qui ne nécessite pas TensorFlow.

Ce module ne connaît rien des instruments ni des tablatures.
"""
from __future__ import annotations

import logging
import pathlib
import threading
from dataclasses import dataclass

import numpy as np

from .note_cleanup import DetectedNote, shift_latency

log = logging.getLogger(__name__)

SAMPLE_RATE = 22050
_model = None
_model_lock = threading.Lock()


class TranscriptionUnavailable(RuntimeError):
    pass


# Réglages choisis par mesure sur les enregistrements réels « dev »
# (evaluation/README.md) : v1 utilisait onset=0.5, frame=0.3, 80 ms.
BASIC_PITCH_PARAMS = {"onset_thresh": 0.5, "frame_thresh": 0.25, "min_note_ms": 35, "melodia_trick": True}
# Retard moyen des attaques de Basic Pitch mesuré sur harmonica (+30 ms),
# voix (+24 ms) et saxophone (+14 ms) ; valeur retenue sur « dev ».
MODEL_LATENCY_S = 0.025
# Les « pitch bends » de Basic Pitch (tiers de demi-ton) sont décalés d'un pas :
# un son parfaitement accordé donne +1. Mesuré sur sons de synthèse ET sur les
# notes réelles d'harmonica (médiane +33 cents contre 0 dans les annotations).
BEND_BIN_OFFSET = 1


@dataclass
class Transcription:
    notes: list[DetectedNote]
    tempo: float
    duration: float
    engine: str


def engine_status() -> dict:
    try:
        import basic_pitch  # noqa: F401
        import onnxruntime  # noqa: F401
    except Exception as exc:  # pragma: no cover - dépend de l'installation
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"available": True, "engine": engine_name()}


def engine_name() -> str:
    try:
        from importlib.metadata import version
        return f"Basic Pitch {version('basic-pitch')} (Spotify, ONNX)"
    except Exception:  # pragma: no cover
        return "Basic Pitch (Spotify, ONNX)"


def _get_model():
    global _model
    with _model_lock:
        if _model is None:
            try:
                import basic_pitch
                from basic_pitch.inference import Model
            except ImportError as exc:
                raise TranscriptionUnavailable(
                    "Le moteur de transcription Basic Pitch n'est pas installé. "
                    "Voir README : pip install --no-deps basic-pitch==0.4.0"
                ) from exc
            path = pathlib.Path(basic_pitch.__file__).parent / "saved_models" / "icassp_2022" / "nmp.onnx"
            _model = Model(path)
        return _model


def estimate_tempo(y: np.ndarray, sr: int) -> float:
    import librosa

    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0]) if np.size(tempo) else 0.0
    if not bpm or not np.isfinite(bpm):
        return 100.0
    while bpm < 60:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    return round(bpm, 1)


def notes_from_model_output(output: dict) -> list[DetectedNote]:
    """Sortie brute du réseau Basic Pitch → notes structurées (latence corrigée)."""
    from basic_pitch.note_creation import model_output_to_notes

    p = BASIC_PITCH_PARAMS
    _, note_events = model_output_to_notes(
        output,
        onset_thresh=p["onset_thresh"],
        frame_thresh=p["frame_thresh"],
        min_note_len=int(round(p["min_note_ms"] / 1000 * (22050 / 256))),
        include_pitch_bends=True,
        multiple_pitch_bends=False,
        melodia_trick=p["melodia_trick"],
    )
    notes = []
    for s, e, pitch, amp, bends in note_events:
        # Les « pitch bends » de Basic Pitch sont en tiers de demi-ton.
        cents = (float(np.median(bends)) - BEND_BIN_OFFSET) * 100 / 3 if bends else 0.0
        notes.append(DetectedNote(float(s), float(e), int(pitch), float(amp), round(cents, 1)))
    shift_latency(notes, MODEL_LATENCY_S)
    notes.sort(key=lambda n: (n.start, n.pitch))
    for i, n in enumerate(notes):
        n.id = i
    return notes


def transcribe(wav_path: str | pathlib.Path, y: np.ndarray, sr: int) -> Transcription:
    """Transcrit un fichier WAV (mono) déjà validé en notes brutes structurées.

    Aucune décision liée à l'instrument n'est prise ici : le nettoyage
    (tessiture, harmoniques, fragments) se fait à la création de la tablature.
    """
    from basic_pitch.inference import run_inference

    output = run_inference(str(wav_path), _get_model())
    return Transcription(
        notes=notes_from_model_output(output),
        tempo=estimate_tempo(y, sr),
        duration=round(len(y) / sr, 2),
        engine=engine_name(),
    )
