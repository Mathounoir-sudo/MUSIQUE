"""Guitare 6 cordes, accordage standard (Mi La Ré Sol Si Mi)."""
from __future__ import annotations

from itertools import product

from ..music import Event, apply_shift, midi_to_name
from .base import BEATS_PER_MEASURE, Instrument, TabNote, TabResult, base_event, viterbi

TUNING = [40, 45, 50, 55, 59, 64]  # E2 A2 D3 G3 B3 E4 (corde 6 → corde 1)
STRING_NAMES = ["E", "A", "D", "G", "B", "e"]
LEVEL_MAX_FRET = {"debutant": 7, "intermediaire": 12, "avance": 15, "expert": 20}
LEVEL_FRET_WEIGHT = {"debutant": 0.6, "intermediaire": 0.15, "avance": 0.08, "expert": 0.05}
MAX_SPAN = 4  # écart maximal entre cases d'un même accord


def positions(pitch: int, max_fret: int) -> list[tuple[int, int]]:
    """(index de corde 0=Mi grave, case) pour une hauteur donnée."""
    return [(s, pitch - open_p) for s, open_p in enumerate(TUNING) if 0 <= pitch - open_p <= max_fret]


def chord_shapes(pitches: list[int], max_fret: int, fret_w: float, limit: int = 40):
    """Toutes les façons de jouer un accord sur des cordes distinctes."""
    options = [positions(p, max_fret) for p in pitches]
    if any(not o for o in options):
        return []
    shapes = []
    for combo in product(*options):
        strings = [s for s, _ in combo]
        if len(set(strings)) != len(strings):
            continue
        fretted = [f for _, f in combo if f > 0]
        span = (max(fretted) - min(fretted)) if fretted else 0
        if span > MAX_SPAN - 1 + (1 if len(combo) == 1 else 0):
            continue
        cost = sum(f for _, f in combo) * fret_w / len(combo) + span * 0.4
        shapes.append((cost, tuple(zip(pitches, combo))))
    shapes.sort(key=lambda x: x[0])
    return shapes[:limit]


def hand_pos(shape) -> float | None:
    frets = [f for _, (_, f) in shape if f > 0]
    return sum(frets) / len(frets) if frets else None


class Guitar(Instrument):
    id = "guitare"
    name = "Guitare"
    description = "Accordage standard. Tablature 6 lignes : ligne du haut = corde de Mi aigu, chiffre = case."
    polyphonic = True
    options: list[dict] = []

    def tablature(self, events: list[Event], level: str, options: dict) -> TabResult:
        max_fret = LEVEL_MAX_FRET[level]
        fret_w = LEVEL_FRET_WEIGHT[level]
        lo, hi = TUNING[0], TUNING[-1] + max_fret
        all_p = [p for e in events for p in e.pitches]
        best_shift, best = 0, -1
        for s in (0, -12, 12, -24, 24):
            n = sum(lo <= p + s <= hi for p in all_p)
            if n > best:
                best_shift, best = s, n
        events = apply_shift(events, best_shift)

        warnings: list[str] = []
        dropped_total = 0
        cands, kept_pitches, missing = [], [], []
        for e in events:
            playable = [p for p in e.pitches if positions(p, max_fret)]
            out = [p for p in e.pitches if p not in playable]
            # Si l'accord est impossible à plaquer, on retire les notes les plus
            # faibles (en gardant la note la plus aiguë = mélodie).
            vel = dict(zip(e.pitches, e.velocities or [1.0] * len(e.pitches)))
            shapes = chord_shapes(playable, max_fret, fret_w) if playable else []
            while playable and not shapes:
                top = max(playable)
                removable = [p for p in playable if p != top]
                if not removable:
                    break
                victim = min(removable, key=lambda p: vel.get(p, 0))
                playable.remove(victim)
                out.append(victim)
                dropped_total += 1
                shapes = chord_shapes(playable, max_fret, fret_w)
            kept_pitches.append(playable if shapes else [])
            missing.append(out if shapes else e.pitches)
            cands.append(shapes or [(0.0, None)])

        def unary(c):
            return c[0]

        def transition(a, b):
            if a[1] is None or b[1] is None:
                return 0.0
            pa, pb = hand_pos(a[1]), hand_pos(b[1])
            if pa is None or pb is None:
                pa = pb = 0.0
            strings_a = {s for _, (s, _) in a[1]}
            strings_b = {s for _, (s, _) in b[1]}
            return 0.3 * abs(pa - pb) + (0.0 if strings_a & strings_b else 0.2)

        path = viterbi(cands, unary, transition)
        out_events = []
        stats = {"total": 0, "playable": 0, "out_of_range": 0, "dropped_chord_notes": dropped_total}
        for e, (_, shape), miss in zip(events, path, missing):
            notes = []
            for pitch, (s, f) in (shape or ()):
                stats["total"] += 1
                stats["playable"] += 1
                notes.append(TabNote(pitch, f"{6 - s}:{f}",
                                     f"Corde {6 - s} ({STRING_NAMES[s]}) · case {f}" + (" (à vide)" if f == 0 else ""),
                                     extra={"string": 6 - s, "fret": f}))
            for pitch in miss:
                stats["total"] += 1
                stats["out_of_range"] += 1
                notes.append(TabNote(pitch, "?", f"{midi_to_name(pitch)} non jouable", False,
                                     f"{midi_to_name(pitch)} hors des cases 0–{max_fret} ou impossible dans l'accord."))
            notes.sort(key=lambda n: -n.pitch)
            out_events.append(base_event(e, notes))

        if best_shift:
            warnings.append(f"Transposé de {abs(best_shift) // 12} octave(s) "
                            f"{'vers l’aigu' if best_shift > 0 else 'vers le grave'} pour la tessiture de la guitare.")
        if stats["out_of_range"]:
            warnings.append(f"{stats['out_of_range']} note(s) non placées sur le manche (cases 0–{max_fret}).")

        legend = [
            {"symbol": "e|--3--", "meaning": "Corde de Mi aigu (1re corde), case 3"},
            {"symbol": "0", "meaning": "Corde à vide"},
            {"symbol": "Chiffres alignés", "meaning": "Notes jouées ensemble (accord)"},
            {"symbol": "1:3", "meaning": "Dans les cartes : corde 1, case 3"},
        ]
        text = ["Guitare, accordage standard — chaque ligne = une corde, chiffre = case"] + ascii_tab(out_events)
        summary = {"instrument": self.name, "tuning": "E A D G B E", "octave_shift": best_shift,
                   "max_fret": max_fret, **stats}
        return TabResult(out_events, text, legend, summary, warnings)


def ascii_tab(events: list[dict], measures_per_line: int = 2) -> list[str]:
    if not events:
        return []
    by_measure: dict[int, list[dict]] = {}
    for e in events:
        by_measure.setdefault(int(e["beat"] // BEATS_PER_MEASURE), []).append(e)
    lines: list[str] = []
    last = max(by_measure)
    for start in range(0, last + 1, measures_per_line):
        rows = [STRING_NAMES[s] + "|" for s in range(5, -1, -1)]
        for m in range(start, min(start + measures_per_line, last + 1)):
            for e in by_measure.get(m, []):
                cells = {n["string"]: str(n["fret"]) for n in e["notes"] if "string" in n}
                w = max([len(c) for c in cells.values()] + [1])
                for i, s in enumerate(range(1, 7)):  # ligne du haut = corde 1 (Mi aigu)
                    rows[i] += "-" + cells.get(s, "-" * w).ljust(w, "-") + "-"
            rows = [r + "-|" for r in rows]
        lines.append(f"Mesures {start + 1}-{min(start + measures_per_line, last + 1)}")
        lines.extend(rows)
        lines.append("")
    return lines
