"""Test de bout en bout : fichier audio de référence → modèle → tablature.

Les WAV de référence sont générés par scripts/make_reference_audio.py, avec
des notes connues. On vérifie que le modèle les retrouve et que la tablature
d'harmonica obtenue est exactement celle attendue.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from scripts.make_reference_audio import main as make_audio

FIXTURES = Path(__file__).parent / "fixtures"
client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def reference_audio():
    if not (FIXTURES / "au_clair_de_la_lune.wav").exists():
        make_audio(FIXTURES)


@pytest.fixture(scope="module")
def transcriptions():
    cache = {}

    def get(name):
        if name not in cache:
            with open(FIXTURES / f"{name}.wav", "rb") as f:
                r = client.post("/api/transcribe", files={"file": (f"{name}.wav", f, "audio/wav")})
            assert r.status_code == 200, r.text
            cache[name] = r.json()
        return cache[name]
    return get


def tab(data, instrument, level, **options):
    r = client.post("/api/tablature", json={"notes": data["notes"], "tempo": data["tempo"],
                                            "instrument": instrument, "level": level, "options": options})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("name", ["au_clair_de_la_lune", "gamme_do_majeur", "phrase_blues_bends"])
def test_model_finds_reference_notes(transcriptions, name):
    data = transcriptions(name)
    truth = json.loads((FIXTURES / f"{name}.json").read_text())
    assert abs(data["tempo"] - truth["tempo"]) < 5
    # Mélodie extraite (niveau expert = sans simplification) vs vérité terrain.
    t = tab(data, "piano", "expert")
    detected = [(e["start"], e["notes"][0]["pitch"]) for e in t["events"] if len(e["notes"]) == 1]
    hits = 0
    for n in truth["notes"]:
        if any(abs(s - n["start"]) < 0.08 and p == n["pitch"] for s, p in detected):
            hits += 1
    assert hits / len(truth["notes"]) >= 0.95
    assert len(t["events"]) <= len(truth["notes"]) + 1


def test_harmonica_tab_from_audio(transcriptions):
    data = transcriptions("au_clair_de_la_lune")
    for level in ("debutant", "intermediaire", "avance", "expert"):
        t = tab(data, "harmonica_diatonique", level, harp_key="auto")
        assert t["summary"]["harp_key"] == "C"
        assert [e["notes"][0]["label"] for e in t["events"]] == \
            ["4", "4", "4", "-4", "5", "-4", "4", "5", "-4", "-4", "4"]
        assert t["summary"]["playable"] == t["summary"]["total"] == 11


def test_harmonica_bends_from_audio(transcriptions):
    data = transcriptions("phrase_blues_bends")
    t = tab(data, "harmonica_diatonique", "expert", harp_key="C")
    assert [e["notes"][0]["label"] for e in t["events"]] == ["3", "-3'", "-3''", "-2", "-2''", "-1"]
    assert t["summary"]["octave_shift"] == 0
    t = tab(data, "harmonica_diatonique", "debutant", harp_key="auto")
    assert t["summary"]["playable"] == t["summary"]["total"]


def test_pdf_export(transcriptions):
    data = transcriptions("au_clair_de_la_lune")
    r = client.post("/api/pdf", json={"notes": data["notes"], "tempo": data["tempo"],
                                      "instrument": "harmonica_diatonique", "level": "debutant",
                                      "title": "Test"})
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")


def test_audio_is_served(transcriptions):
    data = transcriptions("au_clair_de_la_lune")
    r = client.get(data["audio_url"])
    assert r.status_code == 200 and r.content[:4] == b"RIFF"


def test_input_validation():
    r = client.post("/api/transcribe", data={})
    assert r.status_code == 400
    r = client.post("/api/transcribe", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400 and "mp3" in r.json()["detail"]
    r = client.post("/api/transcribe", files={"file": ("broken.mp3", b"not audio", "audio/mpeg")})
    assert r.status_code == 400
    r = client.post("/api/transcribe", data={"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert r.status_code == 400 and "droit" in r.json()["detail"]
    r = client.post("/api/transcribe", data={"youtube_url": "https://example.com/video", "rights_confirmed": "true"})
    assert r.status_code == 400 and "YouTube" in r.json()["detail"]
    r = client.post("/api/tablature", json={"notes": [], "tempo": 100, "instrument": "banjo", "level": "debutant"})
    assert r.status_code == 400
