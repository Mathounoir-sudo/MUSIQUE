"""Harmonica diatonique 10 trous, accordage Richter.

Disposition d'un harmonica en Do (C) — hauteurs MIDI :

    trou      1   2   3   4   5   6   7   8   9   10
    souffle   C4  E4  G4  C5  E5  G5  C6  E6  G6  C7
    aspiré    D4  G4  B4  D5  F5  A5  B5  D6  F6  A6

Bends : sur les trous 1 à 6 la note aspirée peut être abaissée jusqu'à un
demi-ton au-dessus de la note soufflée ; sur les trous 7 à 10 c'est la note
soufflée qui s'abaisse jusqu'à un demi-ton au-dessus de la note aspirée.
Overblows (1, 4, 5, 6) et overdraws (7, 9, 10) donnent la note manquante
un demi-ton au-dessus de la plus haute note naturelle du trou.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..music import Event, apply_shift, midi_to_french, midi_to_name
from itertools import product

from .base import Instrument, TabNote, TabResult, base_event, measures_text, viterbi

C_BLOW = [60, 64, 67, 72, 76, 79, 84, 88, 91, 96]
C_DRAW = [62, 67, 71, 74, 77, 81, 83, 86, 89, 93]
OVERBLOW_HOLES = {1, 4, 5, 6}
OVERDRAW_HOLES = {7, 9, 10}

# Décalage (demi-tons) de chaque tonalité par rapport à l'harmonica en Do.
# Les tonalités G à B sont accordées plus grave que C, Db à F# plus aiguës.
KEY_OFFSETS = {
    "G": -5, "Ab": -4, "A": -3, "Bb": -2, "B": -1, "C": 0,
    "Db": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "F#": 6,
}
# Ordre de préférence en cas d'égalité (harmonicas les plus répandus d'abord).
KEY_PREFERENCE = ["C", "G", "A", "D", "F", "Bb", "E", "Eb", "Ab", "Db", "B", "F#"]

# Niveau de technique : 0 naturel, 1 bend d'un demi-ton, 2 bend plus profond, 3 overblow/overdraw.
TIER_NAMES = {0: "note naturelle", 1: "bend d'un demi-ton", 2: "bend profond", 3: "overblow / overdraw"}
LEVEL_MAX_TIER = {"debutant": 0, "intermediaire": 1, "avance": 2, "expert": 3}
TIER_LEVEL = {0: "débutant", 1: "intermédiaire", 2: "avancé", 3: "expert"}


@dataclass(frozen=True)
class HarpPosition:
    hole: int
    action: str  # "blow" | "draw"
    bend: int  # demi-tons de bend (0 = aucun)
    over: bool  # overblow / overdraw
    pitch: int

    @property
    def tier(self) -> int:
        if self.over:
            return 3
        if self.bend == 0:
            return 0
        return 1 if self.bend == 1 else 2

    @property
    def label(self) -> str:
        sign = "-" if self.action == "draw" else ""
        if self.over:
            return f"{sign}{self.hole}o"
        return f"{sign}{self.hole}" + "'" * self.bend

    @property
    def detail(self) -> str:
        verb = "aspirer" if self.action == "draw" else "souffler"
        text = f"Trou {self.hole} · {verb}"
        if self.over:
            text += " · overblow" if self.action == "blow" else " · overdraw"
        elif self.bend:
            text += f" · bend {'½ ton' if self.bend == 1 else f'{self.bend} demi-tons'}"
        return text


def harp_layout(key: str = "C") -> list[HarpPosition]:
    """Toutes les notes jouables (avec techniques) sur un harmonica dans `key`."""
    k = KEY_OFFSETS[key]
    positions: list[HarpPosition] = []
    for i in range(10):
        hole = i + 1
        blow, draw = C_BLOW[i] + k, C_DRAW[i] + k
        positions.append(HarpPosition(hole, "blow", 0, False, blow))
        positions.append(HarpPosition(hole, "draw", 0, False, draw))
        if draw > blow:  # trous 1-6 : bends aspirés
            for b in range(1, draw - blow):
                positions.append(HarpPosition(hole, "draw", b, False, draw - b))
            if hole in OVERBLOW_HOLES:
                positions.append(HarpPosition(hole, "blow", 0, True, draw + 1))
        else:  # trous 7-10 : bends soufflés
            for b in range(1, blow - draw):
                positions.append(HarpPosition(hole, "blow", b, False, blow - b))
            if hole in OVERDRAW_HOLES:
                positions.append(HarpPosition(hole, "draw", 0, True, blow + 1))
    return positions


def positions_by_pitch(key: str) -> dict[int, list[HarpPosition]]:
    table: dict[int, list[HarpPosition]] = {}
    for p in harp_layout(key):
        table.setdefault(p.pitch, []).append(p)
    for v in table.values():
        v.sort(key=lambda p: (p.tier, p.hole))
    return table


TIER_SCORE = {0: 1.0, 1: 0.8, 2: 0.6, 3: 0.15}  # overblow = technique la plus difficile


def score_fit(pitches: list[int], key: str, max_tier: int) -> tuple[int, float]:
    """(nombre de notes jouables au niveau donné, facilité moyenne cumulée)."""
    table = positions_by_pitch(key)
    playable, ease = 0, 0.0
    for p in pitches:
        opts = table.get(p)
        if not opts:
            continue
        best = min(o.tier for o in opts)
        if best <= max_tier:
            playable += 1
            ease += TIER_SCORE[best]
        else:
            ease += 0.1
    return playable, ease


def choose_key_and_shift(pitches: list[int], max_tier: int, key: str | None,
                         allow_octave_shift: bool) -> tuple[str, int]:
    """Choisit la tonalité d'harmonica et l'éventuelle transposition d'octave.

    Critères, dans l'ordre : nombre de notes jouables au niveau choisi, pas de
    transposition (fidélité à l'original), facilité des techniques, puis
    tonalités d'harmonica les plus courantes.
    """
    keys = [key] if key else KEY_PREFERENCE
    shifts = [0, 12, -12, 24, -24] if allow_octave_shift else [0]
    best, best_score = (keys[0], 0), None
    for s in shifts:
        shifted = [p + s for p in pitches]
        for k in keys:
            playable, ease = score_fit(shifted, k, max_tier)
            score = (playable, -abs(s), round(ease, 6))
            if best_score is None or score > best_score:
                best, best_score = (k, s), score
    return best


def chord_positions(pitches: list[int], table: dict[int, list[HarpPosition]]) -> list[tuple[HarpPosition, ...]]:
    """Accords jouables : trous adjacents, même sens de souffle, notes naturelles.

    C'est la façon réelle de jouer plusieurs notes à l'harmonica (bouche sur
    2-3 trous voisins). Les accords avec bends ou trous non adjacents
    (octaves en blocage de langue) ne sont pas proposés.
    """
    options = [[p for p in table.get(x, []) if p.tier == 0] for x in pitches]
    out = []
    for combo in product(*options):
        holes = sorted(p.hole for p in combo)
        if len({p.action for p in combo}) == 1 and len(set(holes)) == len(holes) and \
                holes[-1] - holes[0] == len(holes) - 1:
            out.append(tuple(sorted(combo, key=lambda p: p.hole)))
    return out


class DiatonicHarmonica(Instrument):
    id = "harmonica_diatonique"
    name = "Harmonica diatonique"
    description = "10 trous, accordage Richter. Chiffre = trou ; « - » = aspirer ; « ' » = bend."
    polyphonic = True
    max_polyphony = 3  # 3 trous adjacents au plus (niveaux avancé et expert)
    options = [
        {"id": "harp_key", "label": "Tonalité de l'harmonica",
         "choices": ["auto"] + KEY_PREFERENCE, "default": "auto"},
    ]

    def pitch_range(self, options: dict):
        if not options.get("recording_is_instrument"):
            return (None, None)
        key = options.get("harp_key")
        keys = [key] if key in KEY_OFFSETS else list(KEY_OFFSETS)
        ps = [p.pitch for k in keys for p in harp_layout(k)]
        return (min(ps), max(ps))

    def tablature(self, events: list[Event], level: str, options: dict) -> TabResult:
        max_tier = LEVEL_MAX_TIER[level]
        requested = options.get("harp_key") or "auto"
        key_opt = None if requested == "auto" else requested
        if key_opt is not None and key_opt not in KEY_OFFSETS:
            raise ValueError(f"Tonalité d'harmonica inconnue : {key_opt}")
        allow_shift = options.get("allow_octave_shift", True)

        # La tonalité est choisie sur la ligne mélodique (note la plus haute).
        melody = [max(e.pitches) for e in events]
        key, shift = choose_key_and_shift(melody, max_tier, key_opt, allow_shift)
        events = apply_shift(events, shift)
        table = positions_by_pitch(key)

        # Candidats par événement : un tuple de positions (une par note jouée).
        cands: list[list[tuple]] = []
        dropped: list[list[int]] = []
        for e in events:
            top = max(e.pitches)
            if len(e.pitches) > 1:
                chords = chord_positions(sorted(e.pitches), table)
                if chords:
                    cands.append(chords)
                    dropped.append([])
                    continue
            cands.append([(p,) for p in table.get(top, [])] or [(None,)])
            dropped.append([p for p in e.pitches if p != top])

        def unary(c: tuple) -> float:
            if c[0] is None:
                return 0.0
            return sum(p.tier * 1.0 + (25.0 if p.tier > max_tier else 0.0) for p in c)

        def transition(a: tuple, b: tuple) -> float:
            if a[0] is None or b[0] is None:
                return 0.0
            return 0.35 * abs(a[-1].hole - b[-1].hole)

        path = viterbi(cands, unary, transition)

        out_events, warnings = [], []
        stats = {"total": 0, "playable": 0, "needs_higher_level": 0, "out_of_range": 0, "bends": 0,
                 "overblows": 0, "chords": 0, "chord_notes_dropped": 0}
        for e, combo, drop in zip(events, path, dropped):
            notes: list[TabNote] = []
            stats["chord_notes_dropped"] += len(drop)
            if len(combo) > 1:
                stats["chords"] += 1
            for pos in combo:
                stats["total"] += 1
                if pos is None:
                    pitch = max(e.pitches)
                    stats["out_of_range"] += 1
                    notes.append(TabNote(pitch, "?", f"{midi_to_french(pitch)} : hors tessiture", playable=False,
                                         issue=f"{midi_to_name(pitch)} n'existe pas sur un harmonica en {key}."))
                    continue
                ok = pos.tier <= max_tier
                issue = None
                if not ok:
                    stats["needs_higher_level"] += 1
                    issue = f"Nécessite un {TIER_NAMES[pos.tier]} (niveau {TIER_LEVEL[pos.tier]})."
                else:
                    stats["playable"] += 1
                if pos.over:
                    stats["overblows"] += 1
                elif pos.bend:
                    stats["bends"] += 1
                notes.append(TabNote(pos.pitch, pos.label, pos.detail, playable=ok, issue=issue,
                                     extra={"hole": pos.hole, "action": pos.action, "bend": pos.bend,
                                            "overblow": pos.over, "technique": TIER_NAMES[pos.tier]}))
            ev = base_event(e, sorted(notes, key=lambda n: -n.pitch))
            if drop:
                ev["dropped"] = [midi_to_name(p) for p in drop]
            out_events.append(ev)

        if shift:
            direction = "vers l'aigu" if shift > 0 else "vers le grave"
            warnings.append(f"Mélodie transposée de {abs(shift) // 12} octave(s) {direction} pour tenir sur "
                            "l'harmonica (les notes ne sont plus à la hauteur de l'enregistrement).")
        if key_opt is None:
            warnings.append(f"Harmonica en {key} recommandé : c'est celui qui joue ces notes avec le moins de "
                            "techniques difficiles. Choisissez votre propre harmonica dans la liste si besoin.")
        if stats["out_of_range"]:
            warnings.append(f"{stats['out_of_range']} note(s) hors tessiture, marquées « ? ».")
        if stats["needs_higher_level"]:
            warnings.append(f"{stats['needs_higher_level']} note(s) demandent une technique au-delà du niveau choisi "
                            "(affichées en orange).")
        if stats["chord_notes_dropped"]:
            warnings.append(f"{stats['chord_notes_dropped']} note(s) d'accord retirée(s) : impossibles à jouer "
                            "ensemble sur des trous voisins ; la note la plus aiguë est gardée.")

        def cell(ev):
            labels = [n["label"] for n in ev["notes"]]
            return labels[0] if len(labels) == 1 else "(" + " ".join(reversed(labels)) + ")"

        text = [f"Harmonica diatonique en {key} — chiffre = souffler, -chiffre = aspirer, ' = bend d'½ ton"]
        text += measures_text(out_events, cell, width=7)
        legend = [
            {"symbol": "4", "meaning": "Souffler dans le trou 4"},
            {"symbol": "-4", "meaning": "Aspirer dans le trou 4"},
            {"symbol": "-3'", "meaning": "Aspirer trou 3 en bend d'½ ton (une apostrophe = ½ ton)"},
            {"symbol": "-3''", "meaning": "Aspirer trou 3 en bend d'un ton"},
            {"symbol": "8'", "meaning": "Souffler trou 8 en bend (trous 7 à 10)"},
            {"symbol": "4o / -7o", "meaning": "Overblow (souffle) / overdraw (aspiré) — expert"},
            {"symbol": "(4 5)", "meaning": "Accord : trous voisins joués ensemble (avancé/expert)"},
            {"symbol": "?", "meaning": "Note absente de l'harmonica choisi"},
        ]
        summary = {
            "instrument": self.name,
            "harp_key": key,
            "harp_key_auto": key_opt is None,
            "octave_shift": shift,
            **stats,
        }
        return TabResult(out_events, text, legend, summary, warnings)
