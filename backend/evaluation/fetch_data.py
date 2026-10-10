"""Télécharge les enregistrements de référence (hors dépôt) avec git.

    python -m evaluation.fetch_data

Nécessite git. Environ 1,9 Go pour le jeu harmonica (le dépôt source contient
aussi le code MATLAB des auteurs), 80 Mo pour les extraits mirdata.
"""
from __future__ import annotations

import subprocess
import sys

from .datasets import DATA_DIR

SOURCES = [
    ("harmonica", "https://github.com/filipemlins/Automatic-Music-Transcription-Harmonica", ["Annotaded"]),
    ("mirdata", "https://github.com/mir-dataset-loaders/mirdata",
     ["tests/resources/mir_datasets/vocadito", "tests/resources/mir_datasets/filosax"]),
]


def run(*args: str) -> None:
    print("$", " ".join(args))
    subprocess.run(args, check=True)


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, url, paths in SOURCES:
        dest = DATA_DIR / name
        if dest.exists():
            print(f"{dest} existe déjà, ignoré.")
            continue
        run("git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", url, str(dest))
        run("git", "-C", str(dest), "sparse-checkout", "set", *paths)
    print("Données prêtes dans", DATA_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
