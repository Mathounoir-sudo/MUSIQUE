"""Outils musicaux indépendants de l'instrument.

Ce module ne fait PAS de transcription : il reçoit des notes déjà détectées
(sortie du modèle) et les prépare pour la conversion en tablature
(extraction de mélodie, quantification rythmique, simplification par niveau).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

from .note_cleanup import CleanupParams, DetectedNote, clean_notes

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


# Une note détectée (voir note_cleanup.DetectedNote) ; alias conservé pour la compatibilité.
Note = DetectedNote


@dataclass
class Event:
    """Un instant de la partition : une note (mélodie) ou plusieurs (accord)."""

    start: float
    end: float
    beat: float  # position en temps depuis le début
    beats: float  # durée en temps
    pitches: list[int]
    velocities: list[float] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)
    cents: list[float] = field(default_factory=list)
    note_ids: list[int] = field(default_factory=list)
    original_pitches: list[int | None] = field(default_factory=list)
    alternatives: list[list[int]] = field(default_factory=list)  # hauteurs concurrentes détectées

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LevelSettings:
    grid: float  # pas de quantification en temps
    min_duration: float  # durée minimale d'une note conservée (s)
    min_confidence: float  # confiance minimale (note_cleanup.confidence)
    max_polyphony: int  # 1 = mélodie seule
    quantize: bool


# Les niveaux SIMPLIFIENT (moins de notes, rythme arrondi) mais ne corrigent rien :
# le nettoyage des erreurs de détection est le même pour tous (note_cleanup).
# Seuils vérifiés sur les références réelles (evaluation/README.md) : au niveau
# débutant, les notes gardées sont plus souvent justes (précision plus haute).
LEVEL_SETTINGS: dict[str, LevelSettings] = {
    "debutant": LevelSettings(grid=0.5, min_duration=0.1, min_confidence=0.55, max_polyphony=1, quantize=True),
    "intermediaire": LevelSettings(grid=0.25, min_duration=0.06, min_confidence=0.35, max_polyphony=1, quantize=True),
    "avance": LevelSettings(grid=0.25, min_duration=0.04, min_confidence=0.2, max_polyphony=3, quantize=True),
    "expert": LevelSettings(grid=0.125, min_duration=0.0, min_confidence=0.0, max_polyphony=6, quantize=False),
}


def extract_melody(notes: list[DetectedNote], onset_window: float = 0.05) -> list[DetectedNote]:
    """Réduit des notes polyphoniques à une ligne mélodique monophonique.

    Méthode « skyline » pondérée : parmi les notes qui démarrent ensemble, on
    garde la plus aiguë parmi celles d'amplitude ≥ 60 % de la plus forte ; une
    note est coupée quand la suivante commence. Comparée sur les références
    réelles à « la plus forte » et « la plus aiguë » : c'est la meilleure.
    """
    if not notes:
        return []
    notes = sorted(notes, key=lambda n: (n.start, -n.pitch))
    groups: list[list[DetectedNote]] = []
    for n in notes:
        if groups and n.start - groups[-1][0].start <= onset_window:
            groups[-1].append(n)
        else:
            groups.append([n])

    melody: list[DetectedNote] = []
    for g in groups:
        vmax = max(n.amplitude for n in g)
        candidates = [n for n in g if n.amplitude >= 0.6 * vmax]
        chosen = max(candidates, key=lambda n: n.pitch)
        if melody:
            prev = melody[-1]
            if chosen.start < prev.end:
                # Une note faible qui démarre pendant une note forte et plus
                # aiguë est probablement de l'accompagnement : on l'ignore.
                if chosen.pitch < prev.pitch and chosen.amplitude < 0.5 * prev.amplitude:
                    continue
                prev.end = chosen.start
        melody.append(replace(chosen, alternatives=sorted({n.pitch for n in g if n is not chosen} | set(chosen.alternatives))))
    return [n for n in melody if n.duration > 0]


def group_chords(notes: list[DetectedNote], max_polyphony: int, onset_window: float = 0.05) -> list[list[DetectedNote]]:
    """Regroupe les notes qui commencent ensemble (accords)."""
    notes = sorted(notes, key=lambda n: (n.start, n.pitch))
    groups: list[list[DetectedNote]] = []
    for n in notes:
        if groups and n.start - groups[-1][0].start <= onset_window:
            groups[-1].append(n)
        else:
            groups.append([n])
    result = []
    for g in groups:
        by_pitch: dict[int, DetectedNote] = {}
        for n in g:
            if n.pitch not in by_pitch or n.amplitude > by_pitch[n.pitch].amplitude:
                by_pitch[n.pitch] = n
        g = sorted(by_pitch.values(), key=lambda n: -n.amplitude)[:max_polyphony]
        result.append(sorted(g, key=lambda n: n.pitch))
    return result


def prepare_notes(notes: list[DetectedNote], level: str, pitch_range=(None, None)):
    """Nettoyage commun + filtre de simplification du niveau. Renvoie (notes, rapport)."""
    settings = LEVEL_SETTINGS[level]
    # La latence du modèle est déjà corrigée à la transcription.
    cleaned, report = clean_notes(notes, CleanupParams(latency=0.0), pitch_range)
    kept = [n for n in cleaned if n.original_pitch is not None
            or (n.duration >= settings.min_duration and n.confidence >= settings.min_confidence)]
    report["simplified_away"] = len(cleaned) - len(kept)
    return kept, report


def build_events(notes: list[DetectedNote], tempo: float, level: str, max_polyphony: int = 1,
                 pitch_range=(None, None)) -> tuple[list[Event], dict]:
    """Pipeline complet : nettoyage → simplification → mélodie/accords → quantification."""
    settings = LEVEL_SETTINGS[level]
    notes, report = prepare_notes(notes, level, pitch_range)
    if not notes:
        return [], report

    max_poly = min(settings.max_polyphony, max_polyphony)
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
        if max_poly == 1 and i + 1 < len(groups):
            end = min(end, min(n.start for n in groups[i + 1]))
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
            pitches=[n.pitch for n in g], velocities=[round(n.amplitude, 3) for n in g],
            confidences=[n.confidence for n in g], cents=[round(n.cents, 1) for n in g],
            note_ids=[n.id for n in g], original_pitches=[n.original_pitch for n in g],
            alternatives=[[a for a in n.alternatives if a not in [m.pitch for m in g]] for n in g],
        ))

    if settings.quantize:
        # Deux événements arrondis sur la même position : on garde le premier,
        # SAUF s'il n'est que le glissement d'attaque d'un bend (fragment
        # < 100 ms à 1-2 demi-tons d'une note plus longue) : on garde alors la
        # note tenue visée. (Garder « le plus long » dans tous les cas a été
        # mesuré moins juste sur les enregistrements réels.)
        def is_glide(first: Event, second: Event) -> bool:
            return (len(first.pitches) == 1 and len(second.pitches) == 1
                    and first.end - first.start < 0.1 and second.end - second.start > first.end - first.start
                    and 1 <= abs(first.pitches[0] - second.pitches[0]) <= 2)

        dedup: list[Event] = []
        for e in events:
            if dedup and abs(e.beat - dedup[-1].beat) < 1e-6:
                report["quantize_collisions"] = report.get("quantize_collisions", 0) + 1
                if is_glide(dedup[-1], e):
                    e.start = dedup[-1].start
                    dedup[-1] = e
                continue
            dedup.append(e)
        events = dedup
        if max_poly == 1:
            for a, b in zip(events, events[1:]):
                a.beats = min(a.beats, b.beat - a.beat)
    return events, report


def apply_shift(events: list[Event], shift: int) -> list[Event]:
    return [replace(e, pitches=[p + shift for p in e.pitches]) for e in events]
