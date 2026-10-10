"""Conversion de notes en tablature, un module par instrument.

Pour ajouter un instrument : créer une sous-classe de `Instrument` et
l'enregistrer dans `INSTRUMENTS`.
"""
from .base import Instrument, TabResult
from .guitar import Guitar
from .harmonica_chromatic import ChromaticHarmonica
from .harmonica_diatonic import DiatonicHarmonica
from .piano import Piano

INSTRUMENTS: dict[str, Instrument] = {
    i.id: i for i in (DiatonicHarmonica(), ChromaticHarmonica(), Guitar(), Piano())
}

__all__ = ["INSTRUMENTS", "Instrument", "TabResult"]
