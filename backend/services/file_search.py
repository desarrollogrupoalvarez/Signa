"""Búsqueda por palabras en nombre y contenido de archivos."""

from __future__ import annotations

from pathlib import Path

import fitz


def pdf_matches(ruta: Path, q: str) -> bool:
    palabras = [p.lower() for p in q.split() if p]
    if not palabras:
        return True
    try:
        doc = fitz.open(str(ruta))
        texto = "\n".join(doc[i].get_text() or "" for i in range(len(doc))).lower()
        doc.close()
        return all(p in texto for p in palabras)
    except Exception:
        return False


def file_search_matches(ruta: Path, q: str) -> bool:
    palabras = [p.lower() for p in q.split() if p]
    if not palabras:
        return True
    name = ruta.name.lower()
    if all(p in name for p in palabras):
        return True
    e = ruta.suffix.lower()
    if e == ".pdf":
        return pdf_matches(ruta, q)
    if e in (
        ".txt",
        ".csv",
        ".log",
        ".md",
        ".json",
        ".xml",
        ".html",
        ".htm",
        ".yml",
        ".yaml",
        ".ini",
        ".conf",
        ".rc",
    ):
        try:
            text = ruta.read_text(encoding="utf-8", errors="ignore")[:400_000].lower()
            return all(p in text for p in palabras)
        except OSError:
            return False
    return False
