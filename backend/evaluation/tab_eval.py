"""Évaluation de bout en bout jusqu'à la tablature d'harmonica, par niveau.

Sépare deux sources d'erreur :
* conversion : pour chaque note de tablature, le trou/souffle/bend indiqué
  produit-il la hauteur annoncée sur l'harmonica choisi ? (table Richter)
  — mesuré aussi en donnant les notes de RÉFÉRENCE (sans transcription) ;
* transcription : la hauteur annoncée correspond-elle à une note réellement
  jouée (annotation humaine) au même moment ?

    python -m evaluation.tab_eval --split test
"""
from __future__ import annotations

import argparse
import json

from app.instruments import INSTRUMENTS
from app.instruments.harmonica_diatonic import harp_layout
from app.music import LEVELS, Event, build_events

from . import engines as E
from .datasets import harmonica_clips, harmonica_mix_clips
from .metrics import melody_reference

TOL = 0.1


def label_pitch_table(key: str) -> dict[str, int]:
    return {p.label: p.pitch for p in harp_layout(key)}


def tab_notes(events_dicts):
    for ev in events_dicts:
        for n in ev["notes"]:
            yield ev, n


def evaluate_clip(clip, level, notes_fn, keyed=True):
    inst = INSTRUMENTS["harmonica_diatonique"]
    opts = {"recording_is_instrument": True, "harp_key": clip.harp_key if keyed else "auto"}
    events, _ = build_events(notes_fn(clip), 100.0, level, inst.max_polyphony, inst.pitch_range(opts))
    tab = inst.tablature(events, level, opts)
    key = tab.summary["harp_key"]
    table = label_pitch_table(key)
    ref = clip.notes
    mel = melody_reference(ref)
    st = dict(notes=0, correct=0, playable=0, uncertain=0, uncertain_correct=0, certain=0, certain_correct=0,
              conversion_ok=0, labeled=0, mel_ref=len(mel), mel_found=0, key_match=int(key == clip.harp_key))
    shift = tab.summary.get("octave_shift", 0)
    for ev, n in tab_notes(tab.events):
        st["notes"] += 1
        sounding = n["pitch"] - shift  # hauteur à comparer à l'enregistrement
        ok = any(r.pitch == sounding and abs(r.start - ev["start"]) <= TOL for r in ref)
        st["correct"] += ok
        st["playable"] += n["playable"]
        if n.get("uncertain"):
            st["uncertain"] += 1
            st["uncertain_correct"] += ok
        else:
            st["certain"] += 1
            st["certain_correct"] += ok
        if n["label"] != "?":
            st["labeled"] += 1
            st["conversion_ok"] += table.get(n["label"]) == n["pitch"]
    for r in mel:
        st["mel_found"] += any(n["pitch"] - shift == r.pitch and abs(ev["start"] - r.start) <= TOL
                               for ev, n in tab_notes(tab.events))
    return st


def summarize(st):
    p = st["correct"] / max(1, st["notes"])
    r = st["mel_found"] / max(1, st["mel_ref"])
    return {
        "precision_notes_tab": round(p, 3),
        "rappel_melodie": round(r, 3),
        "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
        "jouables": round(st["playable"] / max(1, st["notes"]), 3),
        "incertaines": round(st["uncertain"] / max(1, st["notes"]), 3),
        "precision_si_incertaine": round(st["uncertain_correct"] / max(1, st["uncertain"]), 3),
        "precision_si_sure": round(st["certain_correct"] / max(1, st["certain"]), 3),
        "conversion_coherente": round(st["conversion_ok"] / max(1, st["labeled"]), 4),
        "notes": st["notes"],
    }


def reference_notes_fn(clip):
    """Notes de référence humaines → teste la conversion seule, sans transcription."""
    from app.note_cleanup import DetectedNote
    return [DetectedNote(r.start, r.end, r.pitch, 0.9, id=i) for i, r in enumerate(clip.notes)]


def legacy_events(clip, level):
    """Événements tels que v1 les produisait (pour l'avant/après de bout en bout)."""
    from . import legacy_v1 as L
    evs = L.build_events(E.v1_raw(clip), 100.0, level, False)
    return [Event(e.start, e.end, e.beat, e.beats, e.pitches, e.velocities, [1.0] * len(e.pitches),
                  [0.0] * len(e.pitches), [-1] * len(e.pitches), [None] * len(e.pitches)) for e in evs]


def evaluate_v1_clip(clip, level):
    """Tablature v1 : harmonica en tonalité automatique (seul mode qui existait), pas de tessiture."""
    inst = INSTRUMENTS["harmonica_diatonique"]
    events = legacy_events(clip, level)
    tab = inst.tablature(events, level, {"harp_key": clip.harp_key})
    ref = clip.notes
    mel = melody_reference(ref)
    shift = tab.summary.get("octave_shift", 0)
    st = dict(notes=0, correct=0, playable=0, uncertain=0, uncertain_correct=0, certain=0, certain_correct=0,
              conversion_ok=0, labeled=0, mel_ref=len(mel), mel_found=0, key_match=1)
    table = label_pitch_table(clip.harp_key)
    for ev, n in tab_notes(tab.events):
        st["notes"] += 1
        ok = any(r.pitch == n["pitch"] - shift and abs(r.start - ev["start"]) <= TOL for r in ref)
        st["correct"] += ok
        st["certain"] += 1
        st["certain_correct"] += ok
        st["playable"] += n["playable"]
        if n["label"] != "?":
            st["labeled"] += 1
            st["conversion_ok"] += table.get(n["label"]) == n["pitch"]
    for r in mel:
        st["mel_found"] += any(n["pitch"] - shift == r.pitch and abs(ev["start"] - r.start) <= TOL
                               for ev, n in tab_notes(tab.events))
    return st


def run(split: str):
    out = {}
    sets = {"harmonica": [c for c in harmonica_clips() if split == "all" or c.split == split],
            "harmonica_mix": [c for c in harmonica_mix_clips() if split == "all" or c.split == split]}
    for ds, clips in sets.items():
        for level in LEVELS:
            for name, fn in [("v1", lambda c, l=level: evaluate_v1_clip(c, l)),
                             ("v2", lambda c, l=level: evaluate_clip(c, l, E.v2_raw)),
                             ("reference->tab", lambda c, l=level: evaluate_clip(c, l, reference_notes_fn))]:
                if ds == "harmonica_mix" and name == "reference->tab":
                    continue
                agg: dict = {}
                for c in clips:
                    for k, v in fn(c).items():
                        agg[k] = agg.get(k, 0) + v
                out[f"{ds}|{level}|{name}"] = summarize(agg)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["dev", "test", "all"])
    ap.add_argument("--out")
    a = ap.parse_args()
    res = run(a.split)
    keys = list(next(iter(res.values())).keys())
    print("| jeu | niveau | moteur | " + " | ".join(keys) + " |")
    print("|" + "---|" * (len(keys) + 3))
    for k, v in res.items():
        print("| " + " | ".join(k.split("|")) + " | " + " | ".join(str(v[x]) for x in keys) + " |")
    if a.out:
        json.dump(res, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
