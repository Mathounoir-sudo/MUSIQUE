"""Évalue un ou plusieurs moteurs sur les références réelles.

    python -m evaluation.run --engines v1_raw v1_melody --split test
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

from . import engines as E
from .datasets import all_clips
from .metrics import Counts, melody_reference, note_counts


def evaluate(engine_fns: dict, clips, verbose=False) -> dict:
    """engine_fns : nom -> (fonction clip -> notes, mode) ; mode = 'multi' ou 'melody'."""
    results = {}
    for name, (fn, mode) in engine_fns.items():
        agg: dict[str, Counts] = defaultdict(Counts)
        per_clip = {}
        for clip in clips:
            est = fn(clip)
            ref = clip.notes if mode == "multi" else melody_reference(clip.notes)
            c = note_counts(ref, est)
            agg[clip.dataset].add(c)
            per_clip[clip.id] = c.summary()["f1"]
            if verbose:
                print(f"  {name:20s} {clip.id:70s} F1={per_clip[clip.id]:.3f}")
        results[name] = {"mode": mode, "by_dataset": {k: v.summary() for k, v in agg.items()}, "per_clip": per_clip}
    return results


ENGINES = {
    "v1_raw": (E.v1_raw, "multi"),
    "v1_melody": (E.v1_melody, "melody"),
    "v2_multi": (E.v2_prepared, "multi"),
    "v2_multi_autokey": (lambda c: E.v2_prepared(c, keyed=False), "multi"),
    "v2_melody": (E.v2_melody, "melody"),
}


def table(results: dict) -> str:
    lines = ["| moteur | mode | jeu | P | R | F1 | F1+fin | err. octave | err. ½ton/ton | parasites | fragm. | fusions | n réf |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        for ds, s in sorted(r["by_dataset"].items()):
            lines.append(f"| {name} | {r['mode']} | {ds} | {s['precision']:.3f} | {s['recall']:.3f} | **{s['f1']:.3f}** | "
                         f"{s['f1_with_offset']:.3f} | {s['octave_errors']} | {s['semitone_errors']} | "
                         f"{s['fp_spurious_rate']:.2f} | {s['fragmented_ref_notes']} | {s['merged_est_notes']} | {s['n_ref']} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", nargs="+", default=list(ENGINES))
    ap.add_argument("--split", default="test", choices=["dev", "test", "all"])
    ap.add_argument("--datasets", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    clips = [c for c in all_clips() if a.split == "all" or c.split == a.split]
    if a.datasets:
        clips = [c for c in clips if c.dataset in a.datasets]
    res = evaluate({k: ENGINES[k] for k in a.engines}, clips, a.v)
    print(table(res))
    if a.out:
        with open(a.out, "w") as f:
            json.dump(res, f, indent=1)


if __name__ == "__main__":
    main()
