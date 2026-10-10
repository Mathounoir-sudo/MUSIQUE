"""Moteurs comparés. Chaque moteur : audio → liste de notes (start, end, pitch, velocity).

Les sorties brutes du réseau Basic Pitch sont mises en cache (evaluation/data/cache)
pour pouvoir comparer de nombreux réglages sans relancer le modèle.
"""
from __future__ import annotations

import hashlib
import pathlib

import numpy as np

from . import legacy_v1
from .datasets import DATA_DIR, Clip

SR = 22050
CACHE = DATA_DIR / "cache"


def _key(clip: Clip) -> str:
    return hashlib.sha1(clip.id.encode()).hexdigest()[:16]


def clip_wav(clip: Clip) -> pathlib.Path:
    """Fichier WAV mono 22 050 Hz de l'extrait (mélange calculé si besoin)."""
    import soundfile as sf
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{_key(clip)}.wav"
    if not p.exists():
        sf.write(str(p), clip.load(SR), SR, subtype="PCM_16")
    return p


def bp_output(clip: Clip) -> dict:
    p = CACHE / f"{_key(clip)}.bp.npz"
    if p.exists():
        return dict(np.load(p))
    from basic_pitch.inference import run_inference
    from app.transcription import _get_model
    out = run_inference(str(clip_wav(clip)), _get_model())
    np.savez_compressed(p, **out)
    return out


def bp_notes(output: dict, onset=0.5, frame=0.3, min_ms=80, melodia=True, fmin=None, fmax=None):
    from basic_pitch.note_creation import model_output_to_notes
    min_len = int(np.round(min_ms / 1000 * (22050 / 256)))
    _, events = model_output_to_notes(output, onset_thresh=onset, frame_thresh=frame, min_note_len=min_len,
                                      min_freq=fmin, max_freq=fmax, multiple_pitch_bends=False,
                                      melodia_trick=melodia)
    return [legacy_v1.Note(float(s), float(e), int(p), float(a)) for s, e, p, a, *_ in events]


# --- Moteur v1 (avant modification), reproduit à l'identique -----------------

def v1_raw(clip: Clip):
    """Notes produites par l'application v1 (paramètres de app/transcription.py v1)."""
    return bp_notes(bp_output(clip), 0.5, 0.3, 80, True)


def v1_melody(clip: Clip, level: str = "expert"):
    """Mélodie que v1 transmettait au module harmonica (avant quantification)."""
    s = legacy_v1.LEVEL_SETTINGS[level]
    notes = legacy_v1.remove_harmonic_ghosts(v1_raw(clip))
    notes = legacy_v1.filter_notes(notes, s.min_duration, s.min_rel_velocity)
    return legacy_v1.extract_melody(notes)


# --- Alternative monophonique : pYIN + segmentation --------------------------

def pyin_track(clip: Clip, fmin=150.0, fmax=2100.0, frame=1024, hop=128):
    p = CACHE / f"{_key(clip)}.pyin{fmin:.0f}-{fmax:.0f}-{frame}-{hop}.npz"
    if p.exists():
        d = np.load(p)
        return d["f0"], d["vprob"], d["rms"], hop / SR
    import librosa
    y = clip.load(SR)
    f0, voiced, vprob = librosa.pyin(y, fmin=fmin, fmax=fmax, sr=SR, frame_length=frame, hop_length=hop)
    rms = librosa.feature.rms(y=y, frame_length=frame, hop_length=hop)[0][: len(f0)]
    np.savez_compressed(p, f0=f0, vprob=vprob, rms=rms)
    return f0, vprob, rms, hop / SR


def segment_f0(f0, vprob, rms, dt, vthr=0.5, min_dur=0.05, change_frames=4, rms_dip=0.5):
    """Découpe une courbe de f0 en notes : changement de demi-ton stable, silence,
    ou chute d'énergie (re-attaque d'une note répétée)."""
    from app.music import Note
    midi = np.where(np.isfinite(f0) & (vprob >= vthr), 69 + 12 * np.log2(np.where(np.isfinite(f0), f0, 1) / 440), np.nan)
    notes, cur, start = [], None, 0
    frames: list[float] = []

    def close(i):
        if cur is not None and (i - start) * dt >= min_dur:
            notes.append(Note(start * dt, i * dt, int(round(float(np.median(frames)))),
                              float(np.mean(vprob[start:i]))))

    i = 0
    n = len(midi)
    while i < n:
        m = midi[i]
        if np.isnan(m):
            close(i); cur, frames = None, []
            i += 1
            continue
        r = int(round(m))
        if cur is None:
            cur, start, frames = r, i, [m]
        elif r != cur:
            # changement confirmé seulement s'il dure change_frames trames
            seg = midi[i:i + change_frames]
            if np.all(np.isfinite(seg)) and np.all(np.round(seg) == r):
                close(i); cur, start, frames = r, i, [m]
            else:
                frames.append(m)
        else:
            # re-attaque : creux d'énergie marqué puis remontée
            lo = rms[max(start, i - 6):i + 1].min() if i > start + 6 else None
            if lo is not None and rms[i] > 0 and lo < rms_dip * rms[start:i].max() and rms[i] > 1.5 * lo and \
                    rms[i - 1] <= rms[i] and (i - start) * dt > min_dur and rms[i - 3: i].min() == lo:
                close(i - 1); start, frames = i - 1, [m]
            else:
                frames.append(m)
        i += 1
    close(n)
    return notes


def pyin_notes(clip: Clip, **kw):
    f0, vprob, rms, dt = pyin_track(clip)
    return segment_f0(f0, vprob, rms, dt, **kw)


# --- Moteur v2 : Basic Pitch réglé + nettoyage (app/note_cleanup.py) ----------

def bp_detected(output: dict, onset=0.6, frame=0.3, min_ms=35, melodia=True):
    from basic_pitch.note_creation import model_output_to_notes
    from app.note_cleanup import DetectedNote
    min_len = int(np.round(min_ms / 1000 * (22050 / 256)))
    _, events = model_output_to_notes(output, onset_thresh=onset, frame_thresh=frame, min_note_len=min_len,
                                      include_pitch_bends=True, multiple_pitch_bends=False, melodia_trick=melodia)
    out = []
    for s, e, p, a, bends in events:
        cents = float(np.median(bends)) * 100 / 3 if bends else 0.0
        out.append(DetectedNote(float(s), float(e), int(p), float(a), cents))
    return out


def harp_range(key: str | None):
    from app.instruments.harmonica_diatonic import KEY_OFFSETS, harp_layout
    keys = [key] if key else list(KEY_OFFSETS)
    ps = [p.pitch for k in keys for p in harp_layout(k)]
    return min(ps), max(ps)


def v2_raw(clip: Clip):
    """Notes renvoyées par /api/transcribe en v2 (avant nettoyage instrumental)."""
    from app.transcription import notes_from_model_output
    return notes_from_model_output(bp_output(clip))


def v2_prepared(clip: Clip, level: str = "expert", keyed: bool = True):
    """Notes nettoyées telles que /api/tablature les utilise (harmonica, enregistrement d'harmonica)."""
    from app.instruments import INSTRUMENTS
    from app.music import prepare_notes
    inst = INSTRUMENTS["harmonica_diatonique"]
    opts = {"recording_is_instrument": True, "harp_key": clip.harp_key if keyed else "auto"}
    rng = inst.pitch_range(opts) if clip.dataset.startswith("harmonica") else (None, None)
    notes, _ = prepare_notes(v2_raw(clip), level, rng)
    return notes


def v2_melody(clip: Clip, level: str = "expert", keyed: bool = True):
    from app.music import extract_melody
    return extract_melody(v2_prepared(clip, level, keyed))
