"""Harmonica chromatique 12 trous en Do, accordage « solo ».

Chaque groupe de 4 trous couvre une octave :
    souffle  C  E  G  C
    aspiré   D  F  A  B
Le bouton (tiroir, « slide ») enfoncé monte la note d'un demi-ton.
Tessiture : C4 (trou 1 soufflé) à C7 (trou 12 soufflé), C#7 avec le bouton.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..music import Event, apply_shift, midi_to_french, midi_to_name
from .base import Instrument, TabNote, TabResult, base_event, measures_text, viterbi

BLOW_STEPS = [0, 4, 7, 12]
DRAW_STEPS = [2, 5, 9, 11]
LOW = 60  # C4


@dataclass(frozen=True)
class ChromaPosition:
    hole: int
    action: str
    slide: bool
    pitch: int

    @property
    def label(self) -> str:
        return ("-" if self.action == "draw" else "") + str(self.hole) + ("<" if self.slide else "")

    @property
    def detail(self) -> str:
        verb = "aspirer" if self.action == "draw" else "souffler"
        return f"Trou {self.hole} · {verb}" + (" · bouton enfoncé" if self.slide else "")


def chromatic_layout(holes: int = 12) -> list[ChromaPosition]:
    out = []
    for h in range(1, holes + 1):
        g, i = divmod(h - 1, 4)
        base = LOW + 12 * g
        for action, steps in (("blow", BLOW_STEPS), ("draw", DRAW_STEPS)):
            p = base + steps[i]
            out.append(ChromaPosition(h, action, False, p))
            out.append(ChromaPosition(h, action, True, p + 1))
    return out


def chroma_table() -> dict[int, list[ChromaPosition]]:
    t: dict[int, list[ChromaPosition]] = {}
    for p in chromatic_layout():
        t.setdefault(p.pitch, []).append(p)
    return t


class ChromaticHarmonica(Instrument):
    id = "harmonica_chromatique"
    name = "Harmonica chromatique"
    description = "12 trous en Do. Chiffre = trou ; « - » = aspirer ; « < » = bouton enfoncé."
    polyphonic = False
    options: list[dict] = []

    def tablature(self, events: list[Event], level: str, options: dict) -> TabResult:
        table = chroma_table()
        lo, hi = min(table), max(table)
        pitches = [e.pitches[0] for e in events]
        # Transposition par octave pour faire tenir le plus de notes possible.
        best_shift, best = 0, -1
        for s in (0, 12, -12, 24, -24):
            n = sum(lo <= p + s <= hi for p in pitches)
            if n > best:
                best_shift, best = s, n
        events = apply_shift(events, best_shift)
        slide_allowed = level != "debutant"

        cands = [list(table.get(e.pitches[0], [])) or [None] for e in events]

        def unary(p):
            if p is None:
                return 0.0
            return (0.6 if p.slide else 0.0) + (25.0 if p.slide and not slide_allowed else 0.0)

        def transition(a, b):
            if a is None or b is None:
                return 0.0
            return 0.35 * abs(a.hole - b.hole)

        path = viterbi(cands, unary, transition)
        out_events, warnings = [], []
        stats = {"total": 0, "playable": 0, "needs_higher_level": 0, "out_of_range": 0, "slides": 0}
        for e, pos in zip(events, path):
            pitch = e.pitches[0]
            stats["total"] += 1
            if pos is None:
                stats["out_of_range"] += 1
                note = TabNote(pitch, "?", f"{midi_to_french(pitch)} : hors tessiture", False,
                               f"{midi_to_name(pitch)} est hors de la tessiture C4–C#7.")
            else:
                ok = slide_allowed or not pos.slide
                stats["playable" if ok else "needs_higher_level"] += 1
                stats["slides"] += int(pos.slide)
                note = TabNote(pitch, pos.label, pos.detail, ok,
                               None if ok else "Nécessite le bouton (niveau intermédiaire).",
                               {"hole": pos.hole, "action": pos.action, "slide": pos.slide})
            out_events.append(base_event(e, [note]))

        if best_shift:
            warnings.append(f"Mélodie transposée de {abs(best_shift) // 12} octave(s) "
                            f"{'vers l’aigu' if best_shift > 0 else 'vers le grave'}.")
        if stats["out_of_range"]:
            warnings.append(f"{stats['out_of_range']} note(s) hors tessiture, marquées « ? ».")
        if stats["needs_higher_level"]:
            warnings.append(f"{stats['needs_higher_level']} note(s) demandent le bouton (altérations).")
        text = ["Harmonica chromatique en Do (12 trous) — chiffre = souffler, -chiffre = aspirer, < = bouton"]
        text += measures_text(out_events, lambda ev: ev["notes"][0]["label"])
        legend = [
            {"symbol": "5", "meaning": "Souffler dans le trou 5"},
            {"symbol": "-5", "meaning": "Aspirer dans le trou 5"},
            {"symbol": "5< / -5<", "meaning": "Même chose avec le bouton enfoncé (+½ ton)"},
            {"symbol": "?", "meaning": "Note hors tessiture"},
        ]
        summary = {"instrument": self.name, "harp_key": "C", "octave_shift": best_shift, **stats}
        return TabResult(out_events, text, legend, summary, warnings)
