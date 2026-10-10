"""Outils musicaux indépendants de l'instrument.

Ce module ne fait PAS de transcription : il reçoit des notes déjà détectées
(sortie du modèle) et les prépare pour la conversion en tablature
(extraction de mélodie, quantification rythmique, simplification par niveau).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Iterable

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FRENCH_NAMES = ["Do", "Do#", "Ré", "Ré#", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "La#", "Si"]

LEVELS = ("debutant", "intermediaire", "avance", "expert")


def midi_to_name(midi: int) -> str:
    """60 -> 'C4' (notation scientifique)."""
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def midi_to_french(midi: int) -> str:
    """60 -> 'Do4'."""
    return f"{FRENCH_NAMES[midi % 12]}{midi // 12 - 1}"


def name_to_midi(name: str) -> int:
    """'C4' -> 60, 'F#5' -> 78, 'Bb3' -> 58."""
    name = name.strip()
    letter = name[0].upper()
    rest = name[1:]
    acc = 0
    while rest and rest[0] in "#b":
        acc += 1 if rest[0] == "#" else -1
        rest = rest[1:]
    octave = int(rest)
    return (octave + 1) * 12 + NOTE_NAMES.index(letter) + acc


@dataclass
class Note:
    """Note détectée : temps en secondes, hauteur MIDI, amplitude 0..1."""

    start: float
    end: float
    pitch: int
    velocity: float = 0.8

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Event:
    """Un instant de la partition : une note (mélodie) ou plusieurs (accord)."""

    start: float
    end: float
    beat: float  # position en temps depuis le début
    beats: float  # durée en temps
    pitches: list[int]
    velocities: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LevelSettings:
    grid: float  # pas de quantification en temps (None = pas d'arrondi)
    min_duration: float  # durée minimale d'une note conservée (s)
    min_rel_velocity: float  # amplitude minimale relative au max du morceau
    max_polyphony: int  # 1 = mélodie seule
    quantize: bool


LEVEL_SETTINGS: dict[str, LevelSettings] = {
    "debutant": LevelSettings(grid=0.5, min_duration=0.12, min_rel_velocity=0.35, max_polyphony=1, quantize=True),
    "intermediaire": LevelSettings(grid=0.25, min_duration=0.08, min_rel_velocity=0.25, max_polyphony=1, quantize=True),
    "avance": LevelSettings(grid=0.25, min_duration=0.06, min_rel_velocity=0.18, max_polyphony=3, quantize=True),
    "expert": LevelSettings(grid=0.125, min_duration=0.04, min_rel_velocity=0.10, max_polyphony=6, quantize=False),
}

# Intervalles (demi-tons) des premiers harmoniques au-dessus d'une fondamentale :
# octave, quinte+octave, 2 octaves, tierce+2 oct., quinte+2 oct., 7e+2 oct., 3 octaves.
HARMONIC_INTERVALS = {12, 19, 24, 28, 31, 34, 36}


def _overlap(a: Note, b: Note) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def remove_harmonic_ghosts(notes: list[Note], ratio: float = 0.8) -> list[Note]:
    """Supprime les notes qui ne sont qu'un harmonique d'une note plus forte.

    Un modèle de transcription détecte parfois l'octave ou la douzième d'une
    note riche en harmoniques (harmonica, voix…). On retire une note si une
    note plus grave, sonnant en même temps, est à un intervalle harmonique et
    nettement plus forte.
    """
    kept = []
    for n in notes:
        ghost = False
        for m in notes:
            if m is n or m.pitch >= n.pitch:
                continue
            if (n.pitch - m.pitch) not in HARMONIC_INTERVALS:
                continue
            if _overlap(n, m) >= 0.5 * n.duration and n.velocity <= ratio * m.velocity:
                ghost = True
                break
        if not ghost:
            kept.append(n)
    return kept


def filter_notes(notes: Iterable[Note], min_duration: float, min_rel_velocity: float) -> list[Note]:
    notes = list(notes)
    if not notes:
        return []
    vmax = max(n.velocity for n in notes)
    return [n for n in notes if n.duration >= min_duration and n.velocity >= min_rel_velocity * vmax]


def extract_melody(notes: list[Note], onset_window: float = 0.05) -> list[Note]:
    """Réduit des notes polyphoniques à une ligne mélodique monophonique.

    Méthode « skyline » pondérée : parmi les notes qui démarrent ensemble, on
    garde la plus aiguë suffisamment forte ; une note est coupée quand la
    suivante commence.
    """
    if not notes:
        return []
    notes = sorted(notes, key=lambda n: (n.start, -n.pitch))
    groups: list[list[Note]] = []
    for n in notes:
        if groups and n.start - groups[-1][0].start <= onset_window:
            groups[-1].append(n)
        else:
            groups.append([n])

    melody: list[Note] = []
    for g in groups:
        vmax = max(n.velocity for n in g)
        candidates = [n for n in g if n.velocity >= 0.6 * vmax]
        chosen = max(candidates, key=lambda n: n.pitch)
        if melody:
            prev = melody[-1]
            if chosen.start < prev.end:
                # Une note faible qui démarre pendant une note forte et plus
                # aiguë est probablement de l'accompagnement : on l'ignore.
                if chosen.pitch < prev.pitch and chosen.velocity < 0.5 * prev.velocity:
                    continue
                prev.end = chosen.start
        melody.append(Note(chosen.start, chosen.end, chosen.pitch, chosen.velocity))
    return [n for n in melody if n.duration > 0]


def group_chords(notes: list[Note], max_polyphony: int, onset_window: float = 0.05) -> list[list[Note]]:
    """Regroupe les notes qui commencent ensemble (accords)."""
    notes = sorted(notes, key=lambda n: (n.start, n.pitch))
    groups: list[list[Note]] = []
    for n in notes:
        if groups and n.start - groups[-1][0].start <= onset_window:
            groups[-1].append(n)
        else:
            groups.append([n])
    result = []
    for g in groups:
        # Une seule note par hauteur, on garde les plus fortes si trop de notes.
        by_pitch: dict[int, Note] = {}
        for n in g:
            if n.pitch not in by_pitch or n.velocity > by_pitch[n.pitch].velocity:
                by_pitch[n.pitch] = n
        g = sorted(by_pitch.values(), key=lambda n: -n.velocity)[:max_polyphony]
        result.append(sorted(g, key=lambda n: n.pitch))
    return result


def build_events(notes: list[Note], tempo: float, level: str, polyphonic_instrument: bool) -> list[Event]:
    """Pipeline complet : filtrage → mélodie/accords → quantification."""
    settings = LEVEL_SETTINGS[level]
    notes = [Note(n.start, n.end, n.pitch, n.velocity) for n in notes]
    notes = remove_harmonic_ghosts(notes)
    notes = filter_notes(notes, settings.min_duration, settings.min_rel_velocity)
    if not notes:
        return []

    max_poly = settings.max_polyphony if polyphonic_instrument else 1
    if max_poly == 1:
        groups = [[n] for n in extract_melody(notes)]
    else:
        groups = group_chords(notes, max_poly)

    beat_s = 60.0 / tempo
    origin = groups[0][0].start
    events: list[Event] = []
    for i, g in enumerate(groups):
        start = min(n.start for n in g)
        end = max(n.end for n in g)
        if i + 1 < len(groups):
            end = min(end, min(n.start for n in groups[i + 1])) if max_poly == 1 else end
        beat = (start - origin) / beat_s
        beats = max((end - start) / beat_s, 0.0)
        if settings.quantize:
            q = settings.grid
            beat = round(beat / q) * q
            beats = max(q, round(beats / q) * q)
        else:
            beat = round(beat, 3)
            beats = round(max(beats, 0.05), 3)
        events.append(Event(
            start=round(start, 3), end=round(end, 3), beat=beat, beats=beats,
            pitches=[n.pitch for n in g], velocities=[round(n.velocity, 3) for n in g],
        ))

    if settings.quantize:
        # Deux événements arrondis sur la même position : on garde le premier.
        dedup: list[Event] = []
        for e in events:
            if dedup and abs(e.beat - dedup[-1].beat) < 1e-6:
                continue
            dedup.append(e)
        events = dedup
        # Une note ne déborde pas sur la suivante en notation monophonique.
        if max_poly == 1:
            for a, b in zip(events, events[1:]):
                a.beats = min(a.beats, b.beat - a.beat)
    return events


def apply_shift(events: list[Event], shift: int) -> list[Event]:
    return [Event(e.start, e.end, e.beat, e.beats, [p + shift for p in e.pitches], list(e.velocities)) for e in events]
