"""Non-régression sur les enregistrements RÉELS annotés (partie « test »).

Ignoré si les données ne sont pas téléchargées : `python -m evaluation.fetch_data`.
Les seuils sont les résultats mesurés (evaluation/RESULTS.md) moins une petite
marge ; les références ne sont jamais modifiées.
"""
import pytest

from evaluation import engines as E
from evaluation.datasets import HARMONICA_DIR, harmonica_clips, harmonica_mix_clips
from evaluation.metrics import Counts, note_counts

pytestmark = pytest.mark.skipif(not HARMONICA_DIR.exists(), reason="données d'évaluation absentes")


def agg(clips, fn, tol=0.05):
    a = Counts()
    for c in clips:
        a.add(note_counts(c.notes, fn(c), tol))
    return a.summary()


@pytest.fixture(scope="module")
def test_clips():
    return [c for c in harmonica_clips() if c.split == "test"]


def test_reference_notes_exist_on_the_harmonica_used():
    """Les tables Richter couvrent les notes réellement jouées par des harmonicistes."""
    from app.instruments.harmonica_diatonic import positions_by_pitch
    clips = harmonica_clips()
    total = sum(len(c.notes) for c in clips)
    found = sum(r.pitch in positions_by_pitch(c.harp_key) for c in clips for r in c.notes)
    assert found / total >= 0.995


def test_v2_beats_v1_on_real_harmonica(test_clips):
    v1 = agg(test_clips, E.v1_raw)
    v2 = agg(test_clips, E.v2_prepared)
    assert v2["f1"] >= 0.56 and v2["f1"] >= v1["f1"] + 0.10, (v1, v2)
    assert v2["octave_errors"] <= v1["octave_errors"] / 2


def test_v2_with_accompaniment():
    clips = [c for c in harmonica_mix_clips() if c.split == "test"]
    assert agg(clips, E.v2_prepared)["f1"] >= 0.50


def test_tablature_end_to_end():
    from evaluation.tab_eval import evaluate_clip, reference_notes_fn, summarize
    clips = [c for c in harmonica_clips() if c.split == "test"]
    for level, min_precision in [("debutant", 0.86), ("expert", 0.75)]:
        st: dict = {}
        for c in clips:
            for k, v in evaluate_clip(c, level, E.v2_raw).items():
                st[k] = st.get(k, 0) + v
        s = summarize(st)
        assert s["precision_notes_tab"] >= min_precision, (level, s)
        assert s["conversion_coherente"] == 1.0
    # conversion seule, à partir des notes humaines : toujours cohérente et jouable en expert
    st = {}
    for c in clips:
        for k, v in evaluate_clip(c, "expert", reference_notes_fn).items():
            st[k] = st.get(k, 0) + v
    s = summarize(st)
    assert s["conversion_coherente"] == 1.0 and s["jouables"] == 1.0
