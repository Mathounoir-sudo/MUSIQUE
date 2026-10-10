"""Export PDF d'une tablature générée (police à chasse fixe)."""
from __future__ import annotations

import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

from .instruments import TabResult

LEVEL_LABELS = {"debutant": "Débutant", "intermediaire": "Intermédiaire", "avance": "Avancé", "expert": "Expert"}


def render_pdf(tab: TabResult, title: str, level: str, tempo: float, engine: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 1.8 * cm
    y = height - margin

    def line(text: str, font: str = "Courier", size: float = 9.5, gap: float = 1.35):
        nonlocal y
        if y < margin + size:
            c.showPage()
            y = height - margin
        c.setFont(font, size)
        c.drawString(margin, y, text)
        y -= size * gap

    line(title or "Tablature", "Helvetica-Bold", 16, 1.6)
    s = tab.summary
    meta = f"{s.get('instrument', '')} · niveau {LEVEL_LABELS.get(level, level)} · tempo estimé {tempo:g} BPM"
    if s.get("harp_key"):
        meta += f" · harmonica en {s['harp_key']}"
    line(meta, "Helvetica", 10)
    line(f"Transcription automatique : {engine}. Vérifiez à l'oreille, des erreurs restent possibles.",
         "Helvetica-Oblique", 8.5, 2)
    for w in tab.warnings:
        line("! " + w, "Helvetica", 9)
    y -= 6
    for t in tab.text:
        line(t)
    y -= 8
    line("Légende", "Helvetica-Bold", 11, 1.5)
    for item in tab.legend:
        line(f"{item['symbol']:<14} {item['meaning']}", "Courier", 8.5)
    c.save()
    return buf.getvalue()
