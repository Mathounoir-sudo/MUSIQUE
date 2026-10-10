"""Métriques de transcription (note par note) et de tablature.

Transcription — conventions MIREX / mir_eval :
* une note détectée est correcte si sa hauteur MIDI est la bonne (±50 cents)
  et que son début est à ±50 ms du début de référence (« onset F1 ») ;
* la variante « avec fin » exige aussi une fin à ±20 % de la durée (min. 50 ms).
Erreurs analysées sur les notes détectées non appariées (faux positifs) :
octave (±12/±24 demi-tons d'une note de référence commençant au même moment),
demi-ton/ton (±1/±2 : souvent un bend), autres, ou « parasite » (aucune note
de référence à ce moment).
Segmentation : « fragmentation » = une note de référence recouverte par
plusieurs notes détectées de même hauteur ; « fusion » = une note détectée de
même hauteur recouvrant plusieurs notes de référence (notes répétées perdues).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import mir_eval
import numpy as np

ONSET_TOL = 0.05


def _arrays(notes):
    if not notes:
        return np.zeros((0, 2)), np.zeros(0)
    iv = np.array([[n.start, max(n.end, n.start + 0.01)] for n in notes])
    hz = np.array([440.0 * 2 ** ((n.pitch - 69) / 12) for n in notes])
    return iv, hz


def melody_reference(notes, window: float = ONSET_TOL):
    """Ligne mélodique de référence : la note la plus aiguë de chaque attaque."""
    notes = sorted(notes, key=lambda n: (n.start, -n.pitch))
    out = []
    for n in notes:
        if out and n.start - out[-1].start <= window:
            continue
        out.append(n)
    return out


@dataclass
class Counts:
    tp: int = 0
    n_est: int = 0
    n_ref: int = 0
    tp_off: int = 0
    octave: int = 0
    semitone: int = 0
    other_pitch: int = 0
    spurious: int = 0
    fragmented: int = 0
    merged: int = 0

    def add(self, o: "Counts"):
        for k in self.__dataclass_fields__:
            setattr(self, k, getattr(self, k) + getattr(o, k))

    def summary(self) -> dict:
        p = self.tp / self.n_est if self.n_est else 0.0
        r = self.tp / self.n_ref if self.n_ref else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        po = self.tp_off / self.n_est if self.n_est else 0.0
        ro = self.tp_off / self.n_ref if self.n_ref else 0.0
        fo = 2 * po * ro / (po + ro) if po + ro else 0.0
        fp = max(1, self.n_est - self.tp)
        return {
            "precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4), "f1_with_offset": round(fo, 4),
            "n_ref": self.n_ref, "n_est": self.n_est, "tp": self.tp,
            "fp_octave_rate": round(self.octave / fp, 4), "fp_semitone_rate": round(self.semitone / fp, 4),
            "fp_other_pitch_rate": round(self.other_pitch / fp, 4), "fp_spurious_rate": round(self.spurious / fp, 4),
            "octave_errors": self.octave, "semitone_errors": self.semitone,
            "fragmented_ref_notes": self.fragmented, "merged_est_notes": self.merged,
        }


def note_counts(ref, est, tol: float = ONSET_TOL) -> Counts:
    c = Counts(n_est=len(est), n_ref=len(ref))
    if not ref or not est:
        return c
    riv, rhz = _arrays(ref)
    eiv, ehz = _arrays(est)
    match = mir_eval.transcription.match_notes(riv, rhz, eiv, ehz, onset_tolerance=tol, offset_ratio=None)
    c.tp = len(match)
    c.tp_off = len(mir_eval.transcription.match_notes(riv, rhz, eiv, ehz, onset_tolerance=tol,
                                                       offset_ratio=0.2, offset_min_tolerance=0.05))
    matched_est = {j for _, j in match}
    for j, e in enumerate(est):
        if j in matched_est:
            continue
        near = [r for r in ref if abs(r.start - e.start) <= tol]
        if not near:
            # Pas d'attaque de référence ici : la note est-elle pendant une note tenue ?
            during = [r for r in ref if r.start - tol < e.start < r.end]
            if any(r.pitch == e.pitch for r in during):
                continue  # compté comme fragmentation ci-dessous
            diffs = [abs(r.pitch - e.pitch) for r in during]
            if diffs and min(diffs) in (12, 24):
                c.octave += 1
            elif diffs and min(diffs) in (1, 2):
                c.semitone += 1
            else:
                c.spurious += 1
            continue
        d = min(abs(r.pitch - e.pitch) for r in near)
        if d in (12, 24, 19):
            c.octave += 1
        elif d in (1, 2):
            c.semitone += 1
        else:
            c.other_pitch += 1
    for r in ref:
        pieces = [e for e in est if e.pitch == r.pitch and e.start < r.end - 0.03 and e.end > r.start + 0.03]
        if len(pieces) > 1:
            c.fragmented += 1
    for e in est:
        covered = [r for r in ref if r.pitch == e.pitch and e.start - tol <= r.start < e.end - 0.03]
        if len(covered) > 1:
            c.merged += 1
    return c


def pitch_class_confusions(ref, est) -> Counter:
    """Pour les attaques communes : (réf, détectée) → nombre, pour diagnostiquer."""
    out = Counter()
    for e in est:
        near = [r for r in ref if abs(r.start - e.start) <= ONSET_TOL]
        if near:
            r = min(near, key=lambda r: abs(r.pitch - e.pitch))
            out[e.pitch - r.pitch] += 1
    return out


def note_counts_pitch_class(ref, est, tol: float = ONSET_TOL) -> Counts:
    """Comme note_counts mais en ignorant l'octave (diagnostic des références douteuses)."""
    from copy import copy

    def pc(ns):
        out = []
        for n in ns:
            m = copy(n)
            m.pitch = 60 + n.pitch % 12
            out.append(m)
        return out
    return note_counts(pc(ref), pc(est), tol)
