"""Régressions ciblées de la détection (modèle réel, sons construits) et du nettoyage.

Ces sons sont synthétiques : ils ne prouvent pas la qualité sur de vrais
enregistrements (voir test_real_recordings.py), mais verrouillent des
comportements précis : notes répétées, silences, harmoniques, bends, accords.
"""
import os
import tempfile

import numpy as np
import pytest
import soundfile as sf

from app.instruments.harmonica_diatonic import DiatonicHarmonica
from app.music import build_events, prepare_notes
from app.note_cleanup import CleanupParams, DetectedNote, clean_notes, merge_fragments
from app.transcription import transcribe
from scripts.make_reference_audio import SR, tone

HARP = DiatonicHarmonica()


def silence(s):
    return np.zeros(int(SR * s), np.float32)


def detect(y):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.wav")
        sf.write(p, y, SR)
        return transcribe(p, y, SR).notes


def tab_labels(notes, level, key="C"):
    opts = {"harp_key": key, "recording_is_instrument": True}
    events, _ = build_events(notes, 100, level, HARP.max_polyphony, HARP.pitch_range(opts))
    return [[n["label"] for n in e["notes"]] for e in HARP.tablature(events, level, opts).events]


def test_repeated_notes_and_silences():
    y = 0.3 * np.concatenate([silence(.3), tone(72, .35), silence(.06), tone(72, .35), silence(.06),
                              tone(72, .35), silence(.8), tone(72, .5), silence(.4)])
    notes, _ = prepare_notes(detect(y), "expert", HARP.pitch_range({"recording_is_instrument": True}))
    c5 = [n for n in notes if n.pitch == 72]
    assert len(c5) == 4, [(n.start, n.pitch) for n in notes]  # répétitions non fusionnées
    assert all(abs(a.start - b) < 0.05 for a, b in zip(c5, [0.3, 0.71, 1.12, 2.27]))
    # rien pendant le silence de 0,8 s
    assert not [n for n in notes if 1.5 < n.start < 2.2]


def test_strong_second_harmonic_is_not_an_octave_error():
    """Son d'anche dont l'harmonique 2 est plus forte que la fondamentale."""
    def reed(m, sec):
        f0 = 440 * 2 ** ((m - 69) / 12)
        t = np.arange(int(SR * sec)) / SR
        y = sum(a * np.sin(2 * np.pi * f0 * (k + 1) * t) for k, a in enumerate([0.5, 1, 0.6, 0.3, 0.2]))
        return (y * np.minimum(1, np.minimum(t / .02, (sec - t) / .04))).astype(np.float32)
    y = 0.3 * np.concatenate([silence(.3), reed(67, .6), silence(.1), reed(71, .6), silence(.3)])
    assert tab_labels(detect(y), "expert") in ([["-2"], ["-3"]], [["3"], ["-3"]])


def test_bend_glide_gives_target_note():
    """Aspiré trou 3 qui descend de B4 à A4 (bend d'un ton) puis tient A4."""
    t = np.arange(int(SR * 0.9)) / SR
    midi = np.where(t < 0.12, 71 - 2 * t / 0.12, 69.0)
    ph = 2 * np.pi * np.cumsum(440 * 2 ** ((midi - 69) / 12)) / SR
    y = sum(a * np.sin((k + 1) * ph) for k, a in enumerate([1, .55, .35, .2]))
    y = 0.3 * np.concatenate([silence(.3), (y * np.minimum(1, np.minimum(t / .02, (0.9 - t) / .04))).astype(np.float32),
                              silence(.3)])
    labels = tab_labels(detect(y), "avance")
    assert ["-3''"] in labels
    # Débutant sans transposition : le bend d'un ton est signalé non jouable, pas remplacé.
    opts = {"harp_key": "C", "recording_is_instrument": True, "allow_octave_shift": False}
    events, _ = build_events(detect(y), 100, "debutant", 1, HARP.pitch_range(opts))
    held = [n for e in HARP.tablature(events, "debutant", opts).events for n in e["notes"] if n["label"] == "-3''"]
    assert held and not held[0]["playable"]
    # Par défaut, la transposition d'octave proposée est annoncée explicitement.
    opts.pop("allow_octave_shift")
    r = HARP.tablature(events, "debutant", opts)
    assert r.summary["octave_shift"] == 12 and any("transposée" in w for w in r.warnings)


def test_chord_on_adjacent_holes():
    y = 0.5 * np.concatenate([silence(.3), (tone(72, .8) + tone(76, .8) + tone(79, .8)) / 3, silence(.3)])
    notes = detect(y)
    assert tab_labels(notes, "expert") == [["6", "5", "4"]]  # accord 4-5-6 soufflé
    assert tab_labels(notes, "debutant") == [["6"]]  # mélodie seule


# --- Nettoyage (sans audio) ----------------------------------------------------

def test_latency_and_fragment_merge():
    frag = DetectedNote(1.000, 1.050, 72, 0.8)
    main = DetectedNote(1.060, 1.600, 72, 0.8)
    out, rep = clean_notes([frag, main], CleanupParams(latency=0.025))
    assert len(out) == 1 and rep["fragments_merged"] == 1
    assert abs(out[0].start - 0.975) < 1e-6 and "fragments fusionnés" in out[0].corrections


def test_real_repeated_note_is_not_merged():
    a = DetectedNote(0.0, 0.30, 72, 0.8)
    b = DetectedNote(0.36, 0.70, 72, 0.8)  # coup de langue de 60 ms
    assert len(merge_fragments([a, b], 0.03, 0.1)) == 2


def test_range_filter_only_when_recording_is_the_instrument():
    low = DetectedNote(0, 0.5, 50, 0.9)  # D3 : sous tous les harmonicas diatoniques
    ok = DetectedNote(0.5, 1, 72, 0.9)
    with_range, rep = prepare_notes([low, ok], "expert", HARP.pitch_range({"recording_is_instrument": True}))
    assert [n.pitch for n in with_range] == [72] and rep["out_of_range"] == 1
    without, _ = prepare_notes([low, ok], "expert", HARP.pitch_range({}))
    assert len(without) == 2


def test_user_correction_is_kept_and_certain():
    weak = DetectedNote(0, 0.04, 61, 0.2, id=3, original_pitch=60)
    notes, _ = prepare_notes([weak], "debutant", HARP.pitch_range({"recording_is_instrument": True, "harp_key": "C"}))
    assert notes and notes[0].confidence == 1.0


def test_levels_simplify_without_inventing():
    notes = [DetectedNote(i * 0.25, i * 0.25 + 0.2, 72 + (i % 3), 0.3 + 0.1 * (i % 6)) for i in range(24)]
    counts = {lvl: len(prepare_notes(notes, lvl)[0]) for lvl in ("debutant", "intermediaire", "avance", "expert")}
    assert counts["debutant"] <= counts["intermediaire"] <= counts["avance"] <= counts["expert"] == len(notes)


@pytest.mark.parametrize("chord,expected_drop", [([60, 72], 1), ([72, 76], 0)])
def test_non_adjacent_chord_keeps_melody(chord, expected_drop):
    from app.music import Event
    ev = [Event(0, 1, 0, 1, chord, [0.8] * len(chord), [1.0] * len(chord), [0.0] * len(chord),
                list(range(len(chord))), [None] * len(chord))]
    r = HARP.tablature(ev, "expert", {"harp_key": "C", "allow_octave_shift": False})
    assert r.summary["chord_notes_dropped"] == expected_drop
    assert max(n["pitch"] for n in r.events[0]["notes"]) == max(chord)
