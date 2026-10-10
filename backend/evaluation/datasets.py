"""Jeux de référence : enregistrements RÉELS avec annotations humaines.

Aucun fichier audio n'est stocké dans le dépôt. `python -m evaluation.fetch_data`
télécharge les sources (GitHub) dans `evaluation/data/` (ignoré par git).

Sources (voir evaluation/README.md pour le détail et les licences) :

* harmonica — Lins, Johann, Benetos & Schramm, « Automatic transcription of
  diatonic harmonica recordings », ICASSP 2019. 44 extraits d'harmonica
  diatonique solo (tonalités C, G, Bb) annotés à la main (début, fin,
  fréquence). Pas de licence explicite : usage d'évaluation locale uniquement.
* vocadito — voix solo a cappella, notes annotées par 2 annotateurs (CC BY 4.0).
* filosax — saxophone ténor réel (anche) + pistes d'accompagnement réelles
  séparées (piano/basse/batterie) ; notes annotées.
* harmonica+accompagnement — mélange de deux enregistrements réels :
  un extrait du jeu harmonica et une piste d'accompagnement Filosax. La
  référence reste celle de l'harmonica (annotation humaine).
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

DATA_DIR = Path(os.environ.get("MUSIQUE_EVAL_DATA", Path(__file__).parent / "data"))
HARMONICA_DIR = DATA_DIR / "harmonica" / "Annotaded"
MIRDATA_DIR = DATA_DIR / "mirdata" / "tests" / "resources" / "mir_datasets"

# Annotations inexploitables (hauteurs négatives : fichier corrompu dans la source).
EXCLUDED = {"Harmonica_em_C/OhSusana2/OhSusanapart2GaitaC.wav"}

# Séparation développement / test PAR MORCEAU (pas d'extrait d'un même morceau
# des deux côtés). Les seuils sont réglés sur « dev » ; les résultats annoncés
# sont ceux de « test », jamais vus pendant le réglage.
DEV_SONGS = {
    "HelpMe", "Hucklebuckintro1", "Hucklebuckintro2", "SugarSweet", "ittakesthree1", "ittakesthreepart2",
    "ittakesthreepart3", "Heyjude1", "Heyjude2", "Heyjude3", "Heyjude4", "Heyjude5", "byebyebirdpart1",
    "byebyebirdpart3", "Intervalos", "route66", "Garysblues1stchorus1", "garysblues1stchorus2",
    "garysblues2ndchorus1", "Odetojoypart1HarmonicaG", "Odetojoypart3HarmonicaG", "honestido", "honestido2",
}


@dataclass
class RefNote:
    start: float
    end: float
    pitch: int  # MIDI arrondi
    hz: float | None = None


@dataclass
class Clip:
    id: str
    dataset: str
    audio: Path | None  # None si mélange calculé à la volée
    notes: list[RefNote]
    split: str = "test"
    harp_key: str | None = None  # tonalité de l'harmonica réellement utilisé
    kind: str = "solo"  # solo | mix
    mix_with: Path | None = None
    mix_gain_db: float = 0.0
    tags: list[str] = field(default_factory=list)

    def load(self, sr: int = 22050) -> np.ndarray:
        import librosa
        y, _ = librosa.load(str(self.audio), sr=sr, mono=True)
        if self.mix_with is not None:
            b, _ = librosa.load(str(self.mix_with), sr=sr, mono=True)
            b = np.resize(b, y.shape)  # boucle l'accompagnement sur la durée de l'extrait
            ry = np.sqrt(np.mean(y ** 2)) + 1e-9
            rb = np.sqrt(np.mean(b ** 2)) + 1e-9
            b = b * (ry / rb) * 10 ** (self.mix_gain_db / 20)
            y = y + b
            y = y / (np.max(np.abs(y)) + 1e-9) * 0.9
        return y


def hz_to_midi(hz: float) -> int:
    return int(round(69 + 12 * np.log2(hz / 440.0)))


def harmonica_clips() -> list[Clip]:
    clips = []
    for wav in sorted(HARMONICA_DIR.glob("*/*/*.wav")):
        rel = wav.relative_to(HARMONICA_DIR).as_posix()
        if rel in EXCLUDED:
            continue
        ann = wav.with_name(wav.stem + "Hz.txt")
        if not ann.exists():
            continue
        a = np.loadtxt(ann, delimiter=",", ndmin=2)
        notes = [RefNote(float(s), float(e), hz_to_midi(f), float(f)) for s, e, f in a if e > s and f > 0]
        key = rel.split("/")[0].replace("Harmonica_em_", "")
        song = rel.split("/")[1]
        clips.append(Clip(id=f"harmonica/{song}/{wav.stem}", dataset="harmonica", audio=wav, notes=notes,
                          split="dev" if song in DEV_SONGS else "test", harp_key=key))
    return clips


def vocadito_clips() -> list[Clip]:
    root = MIRDATA_DIR / "vocadito"
    out = []
    for wav in sorted((root / "Audio").glob("*.wav")):
        ann = root / "Annotations" / "Notes" / f"{wav.stem}_notesA1.csv"
        if not ann.exists():
            continue
        notes = []
        with open(ann) as f:
            for row in csv.reader(f):
                s, hz, d = map(float, row[:3])
                notes.append(RefNote(s, s + d, hz_to_midi(hz), hz))
        out.append(Clip(id=f"vocadito/{wav.stem}", dataset="vocadito", audio=wav, notes=notes, split="test",
                        tags=["voix", "vibrato"]))
    return out


def filosax_clips() -> list[Clip]:
    root = MIRDATA_DIR / "filosax"
    out = []
    for part in sorted(root.glob("Participant */*")):
        wav = part / "Sax.wav"
        ann = part / "annotations.json"
        if not (wav.exists() and ann.exists()):
            continue
        import soundfile as sf
        dur = sf.info(str(wav)).duration
        data = json.loads(ann.read_text())
        notes = [RefNote(n["a_start_time"], n["a_end_time"], int(n["midi_pitch"]))
                 for n in data["notes"] if n["a_start_time"] < dur - 0.05]
        base = f"filosax/{part.parent.name.replace(' ', '')}_{part.name}"
        out.append(Clip(id=base, dataset="filosax", audio=wav, notes=notes, split="test", tags=["anche"]))
        backing = root / "Backing" / part.name / "Piano_Drums.wav"
        if backing.exists():
            out.append(Clip(id=base + "+piano_batterie", dataset="filosax_mix", audio=wav, notes=notes,
                            split="test", kind="mix", mix_with=backing, mix_gain_db=-3.0, tags=["anche", "accompagnement"]))
    return out


def harmonica_mix_clips() -> list[Clip]:
    """Harmonica réel + accompagnement réel (piano/batterie, basse/batterie)."""
    backings = sorted((MIRDATA_DIR / "filosax" / "Backing").glob("*/*_Drums.wav"))
    if not backings:
        return []
    out = []
    for i, c in enumerate(harmonica_clips()):
        b = backings[i % len(backings)]
        out.append(Clip(id=c.id + f"+{b.stem}", dataset="harmonica_mix", audio=c.audio, notes=c.notes, split=c.split,
                        harp_key=c.harp_key, kind="mix", mix_with=b, mix_gain_db=-6.0, tags=["accompagnement"]))
    return out


def all_clips() -> list[Clip]:
    return harmonica_clips() + harmonica_mix_clips() + vocadito_clips() + filosax_clips()
