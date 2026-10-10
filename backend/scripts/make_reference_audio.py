"""Génère des fichiers audio de référence dont les notes sont connues.

Usage :  python scripts/make_reference_audio.py [dossier_sortie]

Chaque fichier WAV est accompagné d'un JSON contenant les notes réellement
jouées (vérité terrain) pour tester la chaîne complète.
Les sons sont synthétisés (timbre proche d'une anche : harmoniques
décroissantes + léger vibrato) ; aucune œuvre protégée n'est utilisée.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 22050

# (nom, tempo, [(note MIDI, durée en temps), ...])
MELODIES = {
    # « Au clair de la lune » (air traditionnel, domaine public), en Do à l'octave 5 :
    # sur un harmonica en Do : 4 4 4 -4 5 -4 | 4 5 -4 -4 4
    "au_clair_de_la_lune": (100, [
        (72, 1), (72, 1), (72, 1), (74, 1), (76, 2), (74, 2),
        (72, 1), (76, 1), (74, 1), (74, 1), (72, 4),
    ]),
    # Gamme de Do majeur sur 2 octaves basses : exige -2 / 3 et les trous 1-7.
    "gamme_do_majeur": (110, [(p, 1) for p in [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83, 84]]),
    # Phrase blues demandant des bends sur un harmonica en Do :
    # G4 (-2) Bb4 (-3') A4 (-3'') G4 (-2) F4 (-2'') D4 (-1)
    "phrase_blues_bends": (90, [(67, 1), (70, 1), (69, 1), (67, 1), (65, 1), (62, 2)]),
}


def tone(midi: int, seconds: float) -> np.ndarray:
    f0 = 440.0 * 2 ** ((midi - 69) / 12)
    t = np.arange(int(SR * seconds)) / SR
    vib = 1 + 0.003 * np.sin(2 * np.pi * 5.5 * t)
    phase = 2 * np.pi * f0 * np.cumsum(vib) / SR
    amps = [1.0, 0.55, 0.35, 0.22, 0.12, 0.08, 0.05]
    y = sum(a * np.sin((k + 1) * phase) for k, a in enumerate(amps))
    env = np.minimum(1.0, np.minimum(t / 0.02, (seconds - t) / 0.04))
    return (y * np.clip(env, 0, 1)).astype(np.float32)


def render(tempo: float, notes: list[tuple[int, float]]):
    beat = 60.0 / tempo
    gap = 0.04
    lead = 0.3
    parts = [np.zeros(int(SR * lead), np.float32)]
    truth, t = [], lead
    for midi, beats in notes:
        dur = beats * beat
        parts.append(tone(midi, dur - gap))
        parts.append(np.zeros(int(SR * gap), np.float32))
        truth.append({"pitch": midi, "start": round(t, 3), "end": round(t + dur - gap, 3)})
        t += dur
    parts.append(np.zeros(int(SR * 0.5), np.float32))
    y = np.concatenate(parts)
    return 0.3 * y / np.max(np.abs(y)), truth


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, (tempo, notes) in MELODIES.items():
        y, truth = render(tempo, notes)
        sf.write(out_dir / f"{name}.wav", y, SR, subtype="PCM_16")
        (out_dir / f"{name}.json").write_text(json.dumps({"tempo": tempo, "notes": truth}, indent=1))
        print(f"{name}.wav  ({len(truth)} notes, {len(y) / SR:.1f} s)")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "tests" / "fixtures")
