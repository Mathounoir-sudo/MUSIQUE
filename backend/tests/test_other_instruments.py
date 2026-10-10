from app.instruments.guitar import TUNING, Guitar
from app.instruments.piano import Piano
from app.music import Event, Note, build_events, extract_melody, name_to_midi, remove_harmonic_ghosts


def test_guitar_positions_are_correct():
    pitches = [name_to_midi(n) for n in ["E2", "A2", "C3", "G3", "B3", "E4", "C5"]]
    events = [Event(i, i + 0.5, i, 1, [p], [0.8]) for i, p in enumerate(pitches)]
    r = Guitar().tablature(events, "intermediaire", {})
    for e, p in zip(r.events, pitches):
        n = e["notes"][0]
        assert n["playable"]
        assert TUNING[6 - n["string"]] + n["fret"] == p
    assert r.events[0]["notes"][0]["label"] == "6:0"


def test_guitar_chord_uses_distinct_strings():
    chord = [name_to_midi(n) for n in ["C3", "E3", "G3", "C4", "E4"]]
    r = Guitar().tablature([Event(0, 1, 0, 4, chord, [0.8] * 5)], "expert", {})
    notes = r.events[0]["notes"]
    assert len({n["string"] for n in notes}) == 5
    for n in notes:
        assert TUNING[6 - n["string"]] + n["fret"] == n["pitch"]
    assert any(line.startswith("e|") for line in r.text)


def test_piano_hands():
    r = Piano().tablature([Event(0, 1, 0, 1, [48, 64], [0.8, 0.8])], "expert", {})
    hands = {n["label"]: n["hand"] for n in r.events[0]["notes"]}
    assert hands == {"Do3": "MG", "Mi4": "MD"}


def test_harmonic_ghost_removed_but_real_octave_kept():
    fund = Note(0, 1, 60, 0.9)
    ghost = Note(0, 1, 72, 0.3)
    assert remove_harmonic_ghosts([fund, ghost]) == [fund]
    real = Note(0, 1, 72, 0.9)
    assert len(remove_harmonic_ghosts([fund, real])) == 2


def test_melody_extraction_keeps_top_voice():
    notes = [Note(0, 1, 48, 0.8), Note(0, 0.5, 67, 0.8), Note(0.5, 1, 69, 0.8)]
    assert [n.pitch for n in extract_melody(notes)] == [67, 69]


def test_quantization_by_level():
    notes = [Note(0.0, 0.48, 60, 0.8), Note(0.52, 0.98, 62, 0.8), Note(1.03, 1.2, 64, 0.8)]
    ev = build_events(notes, 120, "debutant", False)
    assert [e.beat for e in ev] == [0.0, 1.0, 2.0]
    # Une note très courte et faible disparaît en débutant, reste en expert.
    notes.append(Note(1.5, 1.55, 65, 0.2))
    assert len(build_events(notes, 120, "debutant", False)) == 3
    assert len(build_events(notes, 120, "expert", False)) == 4


def test_guitar_ascii_rows_match_strings():
    # E4 = 1re corde à vide (ligne « e »), C3 = 5e corde case 3 (ligne « A »).
    events = [Event(0, 0.5, 0, 1, [name_to_midi("E4")], [0.8]), Event(0.5, 1, 1, 1, [name_to_midi("C3")], [0.8])]
    r = Guitar().tablature(events, "intermediaire", {})
    rows = {line[0]: line for line in r.text if len(line) > 1 and line[1] == "|"}
    assert rows["e"].startswith("e|-0-")
    assert "-3-" in rows["A"] and "0" not in rows["A"]
