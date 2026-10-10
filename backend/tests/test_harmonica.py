"""Vérification de la conversion notes → tablature d'harmonica."""
import pytest

from app.instruments.harmonica_chromatic import ChromaticHarmonica, chroma_table
from app.instruments.harmonica_diatonic import (
    DiatonicHarmonica, KEY_OFFSETS, harp_layout, positions_by_pitch,
)
from app.music import Event, name_to_midi

# Table de référence écrite à la main pour un harmonica diatonique en Do
# (accordage Richter) : note -> notation la plus simple attendue.
C_HARP_REFERENCE = {
    "C4": "1", "C#4": "-1'", "D4": "-1", "D#4": "1o", "E4": "2", "F4": "-2''", "F#4": "-2'",
    "G4": "-2", "G#4": "-3'''", "A4": "-3''", "A#4": "-3'", "B4": "-3",
    "C5": "4", "C#5": "-4'", "D5": "-4", "D#5": "4o", "E5": "5", "F5": "-5", "F#5": "5o",
    "G5": "6", "G#5": "-6'", "A5": "-6", "A#5": "6o", "B5": "-7",
    "C6": "7", "C#6": "-7o", "D6": "-8", "D#6": "8'", "E6": "8", "F6": "-9", "F#6": "9'",
    "G6": "9", "G#6": "-9o", "A6": "-10", "A#6": "10''", "B6": "10'", "C7": "10", "C#7": "-10o",
}


def ev(pitches, beat=0.0):
    return [Event(start=i * 0.5, end=i * 0.5 + 0.4, beat=i, beats=1, pitches=[p], velocities=[0.8])
            for i, p in enumerate(pitches)]


def test_c_harp_has_every_chromatic_note_from_c4_to_c7():
    table = positions_by_pitch("C")
    for name, label in C_HARP_REFERENCE.items():
        midi = name_to_midi(name)
        assert midi in table, name
        assert table[midi][0].label == label, (name, table[midi][0].label, label)
    # Seule la note C#7 (overdraw 10) dépasse C7 ; rien sous C4.
    assert min(table) == name_to_midi("C4")
    assert max(table) == name_to_midi("C#7")


def test_bend_counts_per_hole():
    bends = {}
    for p in harp_layout("C"):
        if p.bend:
            bends[(p.hole, p.action)] = max(bends.get((p.hole, p.action), 0), p.bend)
    assert bends == {(1, "draw"): 1, (2, "draw"): 2, (3, "draw"): 3, (4, "draw"): 1, (6, "draw"): 1,
                     (8, "blow"): 1, (9, "blow"): 1, (10, "blow"): 2}


@pytest.mark.parametrize("key,hole1_blow", [("C", "C4"), ("G", "G3"), ("A", "A3"), ("D", "D4"), ("F#", "F#4")])
def test_other_keys_are_transposed(key, hole1_blow):
    layout = harp_layout(key)
    first = next(p for p in layout if p.hole == 1 and p.action == "blow" and not p.bend and not p.over)
    assert first.pitch == name_to_midi(hole1_blow)
    # La disposition est identique à celle en Do, décalée.
    c = {(p.hole, p.action, p.bend, p.over): p.pitch for p in harp_layout("C")}
    for p in layout:
        assert p.pitch == c[(p.hole, p.action, p.bend, p.over)] + KEY_OFFSETS[key]


def notes_of(names):
    return [name_to_midi(n) for n in names]


def labels(result):
    return [e["notes"][0]["label"] for e in result.events]


def test_simple_melody_on_c_harp_all_levels():
    melody = notes_of(["C5", "C5", "C5", "D5", "E5", "D5", "C5", "E5", "D5", "D5", "C5"])
    for level in ("debutant", "intermediaire", "avance", "expert"):
        r = DiatonicHarmonica().tablature(ev(melody), level, {"harp_key": "C"})
        assert labels(r) == ["4", "4", "4", "-4", "5", "-4", "4", "5", "-4", "-4", "4"]
        assert all(e["notes"][0]["playable"] for e in r.events)
        assert r.summary["octave_shift"] == 0


def test_bends_flagged_by_level():
    melody = notes_of(["G4", "A#4", "A4", "G4", "F4", "D4"])
    expected = ["3", "-3'", "-3''", "-2", "-2''", "-1"]
    expert = DiatonicHarmonica().tablature(ev(melody), "expert", {"harp_key": "C", "allow_octave_shift": False})
    assert labels(expert) == expected
    assert all(e["notes"][0]["playable"] for e in expert.events)

    inter = DiatonicHarmonica().tablature(ev(melody), "intermediaire", {"harp_key": "C", "allow_octave_shift": False})
    assert labels(inter) == expected
    flags = [e["notes"][0]["playable"] for e in inter.events]
    # Bend d'½ ton autorisé en intermédiaire, bends d'un ton non.
    assert flags == [True, True, False, True, False, True]

    beginner = DiatonicHarmonica().tablature(ev(melody), "debutant", {"harp_key": "C", "allow_octave_shift": False})
    assert [e["notes"][0]["playable"] for e in beginner.events] == [True, False, False, True, False, True]


def test_auto_key_avoids_bends_for_beginners():
    melody = notes_of(["G4", "A#4", "A4", "G4", "F4", "D4"])
    r = DiatonicHarmonica().tablature(ev(melody), "debutant", {"harp_key": "auto"})
    assert all(e["notes"][0]["playable"] for e in r.events)
    # Vérifie que chaque trou indiqué produit bien la note voulue.
    table = {p.label: p.pitch for p in harp_layout(r.summary["harp_key"])}
    for e in r.events:
        n = e["notes"][0]
        assert table[n["label"]] == n["pitch"]


def test_every_label_produces_the_written_pitch_in_all_keys():
    """Pour toute note et toute tonalité, la case proposée sonne juste."""
    for key in KEY_OFFSETS:
        table = {p.label: p.pitch for p in harp_layout(key)}
        pitches = sorted(positions_by_pitch(key))
        r = DiatonicHarmonica().tablature(ev(pitches), "expert", {"harp_key": key, "allow_octave_shift": False})
        for e in r.events:
            n = e["notes"][0]
            assert n["playable"]
            assert table[n["label"]] == n["pitch"]


def test_out_of_range_note_is_marked_not_invented():
    r = DiatonicHarmonica().tablature(ev([name_to_midi("C4"), name_to_midi("C2")]), "expert",
                                      {"harp_key": "C", "allow_octave_shift": False})
    assert labels(r) == ["1", "?"]
    assert r.events[1]["notes"][0]["playable"] is False
    assert r.summary["out_of_range"] == 1


def test_g4_prefers_nearest_hole():
    # Après le trou 1, G4 se joue -2 ; après le trou 4, plutôt 3 soufflé.
    r1 = DiatonicHarmonica().tablature(ev(notes_of(["C4", "G4"])), "expert", {"harp_key": "C", "allow_octave_shift": False})
    assert labels(r1) == ["1", "-2"]
    r2 = DiatonicHarmonica().tablature(ev(notes_of(["C5", "G4"])), "expert", {"harp_key": "C", "allow_octave_shift": False})
    assert labels(r2) == ["4", "3"]


def test_chromatic_harmonica():
    table = chroma_table()
    assert min(table) == name_to_midi("C4") and max(table) == name_to_midi("C#7")
    melody = notes_of(["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "C#5", "F#5"])
    r = ChromaticHarmonica().tablature(ev(melody), "intermediaire", {})
    assert labels(r) == ["1", "-1", "2", "-2", "3", "-3", "-4", "4", "4<", "-6<"]
    beginner = ChromaticHarmonica().tablature(ev(melody), "debutant", {})
    assert [e["notes"][0]["playable"] for e in beginner.events][-2:] == [False, False]


def test_auto_key_prefers_bends_over_overblows():
    melody = notes_of(["G4", "A#4", "A4", "G4", "F4", "D4"])
    r = DiatonicHarmonica().tablature(ev(melody), "expert", {"harp_key": "auto"})
    assert not any(e["notes"][0].get("overblow") for e in r.events)
