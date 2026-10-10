"""Interface commune des instruments et utilitaires de doigté."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence, TypeVar

from ..music import Event, midi_to_french, midi_to_name

T = TypeVar("T")

BEATS_PER_MEASURE = 4


@dataclass
class TabNote:
    pitch: int  # hauteur jouée (après transposition éventuelle)
    label: str  # notation compacte, ex. "-3'" ou "5:3"
    detail: str  # explication en clair
    playable: bool = True
    issue: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "pitch": self.pitch,
            "name": midi_to_name(self.pitch),
            "french": midi_to_french(self.pitch),
            "label": self.label,
            "detail": self.detail,
            "playable": self.playable,
            "issue": self.issue,
            **self.extra,
        }


@dataclass
class TabResult:
    events: list[dict]
    text: list[str]  # tablature texte (affichage brut + PDF)
    legend: list[dict]  # [{"symbol": ..., "meaning": ...}]
    summary: dict[str, Any]
    warnings: list[str]


def viterbi(candidates: Sequence[Sequence[T]], unary: Callable[[T], float],
            transition: Callable[[T, T], float]) -> list[T]:
    """Chemin de coût minimal à travers une suite d'ensembles de candidats.

    Utilisé pour choisir le doigté (trou, corde/case…) le plus confortable
    sur l'ensemble du morceau plutôt que note par note.
    """
    if not candidates:
        return []
    costs = [unary(c) for c in candidates[0]]
    back: list[list[int]] = []
    for step in candidates[1:]:
        new_costs, ptrs = [], []
        prev_layer = candidates[len(back)]
        for c in step:
            u = unary(c)
            best_i, best = 0, float("inf")
            for i, p in enumerate(prev_layer):
                v = costs[i] + transition(p, c)
                if v < best:
                    best_i, best = i, v
            new_costs.append(best + u)
            ptrs.append(best_i)
        costs = new_costs
        back.append(ptrs)
    idx = min(range(len(costs)), key=costs.__getitem__)
    path = [idx]
    for ptrs in reversed(back):
        idx = ptrs[idx]
        path.append(idx)
    path.reverse()
    return [candidates[i][j] for i, j in enumerate(path)]


def measures_text(events: list[dict], cell: Callable[[dict], str], width: int = 6,
                  per_line: int = 4) -> list[str]:
    """Met en forme des événements en mesures de 4 temps : « | a  b  c | d … »."""
    if not events:
        return []
    measures: dict[int, list[str]] = {}
    for e in events:
        m = int(e["beat"] // BEATS_PER_MEASURE)
        measures.setdefault(m, []).append(cell(e).ljust(width))
    last = max(measures)
    blocks = [" ".join(measures.get(m, ["-".ljust(width)])).rstrip() for m in range(last + 1)]
    lines = []
    for i in range(0, len(blocks), per_line):
        chunk = blocks[i:i + per_line]
        lines.append(f"M{i + 1:<3} | " + " | ".join(chunk) + " |")
    return lines


UNCERTAIN_CONFIDENCE = 0.5  # voir note_cleanup.confidence
UNCERTAIN_CENTS = 35  # hauteur à mi-chemin entre deux demi-tons


def annotate_detection(e: Event, notes: list[TabNote]) -> None:
    """Recopie dans chaque note de tablature les informations de détection
    (confiance, écart en cents, note d'origine) pour signaler les incertitudes."""
    for n in notes:
        if n.pitch not in e.pitches:
            continue
        i = e.pitches.index(n.pitch)
        conf = e.confidences[i] if i < len(e.confidences) else 1.0
        cents = e.cents[i] if i < len(e.cents) else 0.0
        orig = e.original_pitches[i] if i < len(e.original_pitches) else None
        reasons = []
        if orig is None and conf < UNCERTAIN_CONFIDENCE:
            reasons.append("détection peu sûre (son faible ou très court)")
        if orig is None and abs(cents) > UNCERTAIN_CENTS:
            reasons.append(f"hauteur entre deux notes ({cents:+.0f} cents) : bend partiel ou note voisine")
        n.extra.update({
            "confidence": conf, "cents": cents,
            "note_id": e.note_ids[i] if i < len(e.note_ids) else -1,
            "corrected_from": orig, "uncertain": bool(reasons), "uncertain_reasons": reasons,
            "alternatives": e.alternatives[i] if i < len(e.alternatives) else [],
        })


def base_event(e: Event, notes: list[TabNote]) -> dict:
    annotate_detection(e, notes)
    return {
        "start": e.start,
        "end": e.end,
        "beat": e.beat,
        "beats": e.beats,
        "measure": int(e.beat // BEATS_PER_MEASURE) + 1,
        "notes": [n.to_dict() for n in notes],
    }


class Instrument:
    id: str = ""
    name: str = ""
    description: str = ""
    polyphonic: bool = False
    max_polyphony: int = 1  # notes simultanées possibles (aux niveaux avancé/expert)
    range: tuple[int, int] | None = None  # tessiture physique (MIDI)
    options: list[dict] = []

    def pitch_range(self, options: dict) -> tuple[int | None, int | None]:
        """Tessiture utilisée pour écarter les notes qui ne peuvent pas venir de
        cet instrument — seulement si l'enregistrement est joué avec lui."""
        if not options.get("recording_is_instrument") or self.range is None:
            return (None, None)
        return self.range

    def tablature(self, events: list[Event], level: str, options: dict) -> TabResult:  # pragma: no cover
        raise NotImplementedError

    def info(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "polyphonic": self.polyphonic,
            "max_polyphony": self.max_polyphony,
            "options": self.options,
        }
