"""Nettoyage des notes brutes du modèle, AVANT toute conversion en tablature.

Chaque règle corrige un type d'erreur mesuré sur des enregistrements réels
d'harmonica (voir evaluation/README.md) et ses seuils ont été choisis sur la
partie « dev » des références, puis vérifiés sur la partie « test » :

1. latence : Basic Pitch place les attaques en moyenne ~25 ms trop tard
   (mesuré sur harmonica, voix et saxophone) → décalage constant ;
2. tessiture : une note hors de la tessiture physique de l'instrument choisi
   ne peut pas avoir été jouée par lui → retirée (comptée dans le rapport) ;
3. fragments d'attaque : le modèle coupe souvent l'attaque d'une note en un
   fragment très court suivi de la même hauteur → fusion ;
4. harmoniques fantômes : octave/douzième d'une note plus forte qui sonne en
   même temps → retirées, avec trace de la note concurrente ;
5. confiance : combinaison de l'amplitude du modèle et de la durée. Les notes
   peu sûres sont signalées « incertaines » (et non inventées ni cachées).

Rien ici ne dépend d'un instrument de tablature particulier, sauf la
tessiture qui est fournie par l'appelant.
"""
from __future__ import annotations

from dataclasses import dataclass, field

HARMONIC_INTERVALS = (12, 19, 24, 28, 31)


@dataclass
class DetectedNote:
    """Représentation intermédiaire d'une note détectée."""

    start: float
    end: float
    pitch: int  # demi-ton MIDI estimé
    amplitude: float  # activation du modèle (0..1)
    cents: float = 0.0  # écart moyen au demi-ton tempéré (bends, justesse)
    confidence: float = 1.0  # 0..1, voir confidence()
    source: str = "basic-pitch"
    corrections: list[str] = field(default_factory=list)
    alternatives: list[int] = field(default_factory=list)  # hauteurs concurrentes au même instant
    id: int = -1  # index dans la transcription d'origine
    original_pitch: int | None = None  # renseigné si l'utilisateur a corrigé la hauteur

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def hz(self) -> float:
        return 440.0 * 2 ** ((self.pitch + self.cents / 100 - 69) / 12)

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3), "end": round(self.end, 3), "pitch": self.pitch,
            "hz": round(self.hz, 1), "cents": round(self.cents, 1), "velocity": round(self.amplitude, 3),
            "confidence": round(self.confidence, 3), "source": self.source,
            "corrections": self.corrections, "alternatives": self.alternatives,
            "id": self.id, "original_pitch": self.original_pitch,
        }


@dataclass(frozen=True)
class CleanupParams:
    latency: float = 0.025  # s, soustrait aux débuts/fins (calibré sur dev)
    merge_gap: float = 0.03  # s, écart maximal entre fragment et suite
    merge_max_fragment: float = 0.09  # s, durée maximale d'un fragment d'attaque
    ghost_ratio: float = 0.8  # amplitude max d'un harmonique fantôme / note grave
    min_confidence: float = 0.0  # en dessous : retirée
    uncertain_below: float = 0.5  # en dessous : signalée incertaine


def confidence(n: DetectedNote) -> float:
    """Score 0..1 : amplitude du modèle pondérée par la durée.

    Sur les références « dev », les vraies notes ont une amplitude médiane de
    0,63 et une durée médiane de 0,27 s, les fausses 0,43 et 0,12 s.
    """
    dur_factor = min(1.0, n.duration / 0.12)
    amp = min(1.0, max(0.0, (n.amplitude - 0.3) / 0.4))
    return round(0.7 * amp + 0.3 * dur_factor, 3)


def shift_latency(notes: list[DetectedNote], latency: float) -> None:
    for n in notes:
        n.start = max(0.0, n.start - latency)
        n.end = max(n.start + 0.01, n.end - latency)


def filter_range(notes: list[DetectedNote], lo: int | None, hi: int | None) -> tuple[list[DetectedNote], int]:
    if lo is None and hi is None:
        return notes, 0
    kept = [n for n in notes if n.original_pitch is not None
            or ((lo is None or n.pitch >= lo) and (hi is None or n.pitch <= hi))]
    return kept, len(notes) - len(kept)


def merge_fragments(notes: list[DetectedNote], gap: float, max_fragment: float) -> list[DetectedNote]:
    """Fusionne « fragment court + même hauteur juste après (ou chevauchant) »."""
    by_pitch: dict[int, list[DetectedNote]] = {}
    for n in sorted(notes, key=lambda n: n.start):
        by_pitch.setdefault(n.pitch, []).append(n)
    out = []
    for seq in by_pitch.values():
        merged = [seq[0]]
        for n in seq[1:]:
            prev = merged[-1]
            touching = n.start - prev.end <= gap
            if touching and (prev.duration <= max_fragment or n.start < prev.end):
                prev.end = max(prev.end, n.end)
                prev.amplitude = max(prev.amplitude, n.amplitude)
                if "fragments fusionnés" not in prev.corrections:
                    prev.corrections.append("fragments fusionnés")
            else:
                merged.append(n)
        out.extend(merged)
    return sorted(out, key=lambda n: (n.start, n.pitch))


def _overlap(a: DetectedNote, b: DetectedNote) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def remove_ghosts(notes: list[DetectedNote], ratio: float) -> list[DetectedNote]:
    kept = []
    for n in notes:
        ghost_of = None
        for m in notes:
            if m is n or m.pitch >= n.pitch or (n.pitch - m.pitch) not in HARMONIC_INTERVALS:
                continue
            if _overlap(n, m) >= 0.5 * n.duration and n.amplitude <= ratio * m.amplitude:
                ghost_of = m
                break
        if ghost_of is None or n.original_pitch is not None:
            kept.append(n)
        elif n.pitch not in ghost_of.alternatives:
            ghost_of.alternatives.append(n.pitch)
    return kept


def note_alternatives(notes: list[DetectedNote], window: float = 0.05) -> None:
    """Renseigne les hauteurs concurrentes qui démarrent au même moment."""
    for n in notes:
        for m in notes:
            if m is not n and abs(m.start - n.start) <= window and m.pitch not in n.alternatives:
                n.alternatives.append(m.pitch)


def clean_notes(notes: list[DetectedNote], params: CleanupParams = CleanupParams(),
                pitch_range: tuple[int | None, int | None] = (None, None)) -> tuple[list[DetectedNote], dict]:
    notes = [DetectedNote(n.start, n.end, n.pitch, n.amplitude, n.cents, n.confidence, n.source,
                          list(n.corrections), list(n.alternatives), n.id, n.original_pitch) for n in notes]
    report = {"raw": len(notes)}
    shift_latency(notes, params.latency)
    notes, report["out_of_range"] = filter_range(notes, *pitch_range)
    before = len(notes)
    notes = merge_fragments(notes, params.merge_gap, params.merge_max_fragment)
    report["fragments_merged"] = before - len(notes)
    before = len(notes)
    notes = remove_ghosts(notes, params.ghost_ratio)
    report["harmonics_removed"] = before - len(notes)
    for n in notes:
        n.confidence = 1.0 if n.original_pitch is not None else confidence(n)
    before = len(notes)
    notes = [n for n in notes if n.confidence >= params.min_confidence]
    report["low_confidence_removed"] = before - len(notes)
    note_alternatives(notes)
    report["uncertain"] = sum(n.confidence < params.uncertain_below for n in notes)
    report["kept"] = len(notes)
    return notes, report
