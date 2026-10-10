"""Piano : notation par nom de note (Do4 = do central) et main conseillée."""
from __future__ import annotations

from ..music import Event, apply_shift, midi_to_french, midi_to_name
from .base import Instrument, TabNote, TabResult, base_event, measures_text

LOW, HIGH = 21, 108  # A0 – C8
SPLIT = 60  # Do central : main droite à partir de Do4


class Piano(Instrument):
    id = "piano"
    name = "Piano"
    description = "Nom des notes avec leur octave (Do4 = do central). MD = main droite, MG = main gauche."
    polyphonic = True
    options: list[dict] = []

    def tablature(self, events: list[Event], level: str, options: dict) -> TabResult:
        shift = 0
        all_p = [p for e in events for p in e.pitches]
        if all_p and (min(all_p) < LOW or max(all_p) > HIGH):
            shift = 12 if min(all_p) < LOW else -12
        events = apply_shift(events, shift)
        melody_only = level in ("debutant", "intermediaire")
        out_events = []
        stats = {"total": 0, "playable": 0, "out_of_range": 0}
        for e in events:
            notes = []
            for p in sorted(e.pitches, reverse=True):
                stats["total"] += 1
                hand = "MD" if (melody_only or p >= SPLIT) else "MG"
                if LOW <= p <= HIGH:
                    stats["playable"] += 1
                    notes.append(TabNote(p, midi_to_french(p), f"{midi_to_french(p)} ({midi_to_name(p)}) · {hand}",
                                         extra={"hand": hand}))
                else:
                    stats["out_of_range"] += 1
                    notes.append(TabNote(p, "?", "Hors clavier", False, "Note hors du clavier 88 touches.",
                                         {"hand": hand}))
            out_events.append(base_event(e, notes))

        def cell(hand):
            return lambda ev: "+".join(n["label"] for n in ev["notes"] if n["hand"] == hand) or "."

        text = ["Piano — MD = main droite, MG = main gauche, + = notes jouées ensemble"]
        md = measures_text(out_events, cell("MD"), width=5)
        mg = measures_text(out_events, cell("MG"), width=5)
        for a, b in zip(md, mg):
            text += ["MD " + a, "MG " + b, ""]
        legend = [
            {"symbol": "Do4", "meaning": "Do central (C4). Ré4, Mi4… montent ; Si3 est juste en dessous"},
            {"symbol": "Fa#4", "meaning": "« # » = touche noire juste à droite (dièse)"},
            {"symbol": "MD / MG", "meaning": "Main droite / main gauche conseillée"},
            {"symbol": "Do4+Mi4", "meaning": "Notes à jouer ensemble"},
        ]
        warnings = [f"Transposé d'une octave ({'+' if shift > 0 else '-'}12) pour tenir sur le clavier."] if shift else []
        summary = {"instrument": self.name, "octave_shift": shift, **stats}
        return TabResult(out_events, text, legend, summary, warnings)
