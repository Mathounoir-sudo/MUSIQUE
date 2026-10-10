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

from .music import Note

log = logging.getLogger(__name__)

SAMPLE_RATE = 22050
_model = None
_model_lock = threading.Lock()


class TranscriptionUnavailable(RuntimeError):
    pass


@dataclass
class Transcription:
    notes: list[Note]
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


def transcribe(wav_path: str | pathlib.Path, y: np.ndarray, sr: int) -> Transcription:
    """Transcrit un fichier WAV (mono) déjà validé."""
    from basic_pitch.inference import predict

    model = _get_model()
    _, _, note_events = predict(
        str(wav_path),
        model,
        onset_threshold=0.5,
        frame_threshold=0.3,
        minimum_note_length=80,  # ms
        minimum_frequency=None,
        maximum_frequency=None,
        multiple_pitch_bends=False,
        melodia_trick=True,
    )
    notes = [
        Note(start=float(s), end=float(e), pitch=int(p), velocity=float(a))
        for s, e, p, a, *_ in note_events
    ]
    notes.sort(key=lambda n: (n.start, n.pitch))
    return Transcription(
        notes=notes,
        tempo=estimate_tempo(y, sr),
        duration=round(len(y) / sr, 2),
        engine=engine_name(),
    )
