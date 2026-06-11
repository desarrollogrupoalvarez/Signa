"""Búsqueda por palabras en nombre y contenido de archivos."""

from __future__ import annotations

from pathlib import Path

import fitz

_PDF_TEXT_CACHE: dict[tuple[str, float], str] = {}
_PDF_TEXT_CACHE_MAX = 4000
_PDF_SEARCH_MAX_PAGES = 8


def _cache_key(ruta: Path) -> tuple[str, float] | None:
    try:
        st = ruta.stat()
        return (str(ruta.resolve()), st.st_mtime)
    except OSError:
        return None


def _store_pdf_text(key: tuple[str, float], text: str) -> None:
    while len(_PDF_TEXT_CACHE) >= _PDF_TEXT_CACHE_MAX:
        try:
            del _PDF_TEXT_CACHE[next(iter(_PDF_TEXT_CACHE))]
        except StopIteration:
            break
    _PDF_TEXT_CACHE[key] = text


def pdf_text(ruta: Path, *, max_pages: int = _PDF_SEARCH_MAX_PAGES) -> str:
    """Texto del PDF (cacheado por ruta + mtime)."""
    key = _cache_key(ruta)
    if key is None:
        return ""
    cached = _PDF_TEXT_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        doc = fitz.open(str(ruta))
        n = min(len(doc), max(1, max_pages))
        texto = "\n".join(doc[i].get_text() or "" for i in range(n))
        doc.close()
    except Exception:
        texto = ""
    _store_pdf_text(key, texto)
    return texto


def query_terms(q: str) -> list[str]:
    return [p.lower() for p in (q or "").split() if p]


def name_matches(ruta: Path, q: str) -> bool:
    palabras = query_terms(q)
    if not palabras:
        return True
    name = ruta.name.lower()
    return all(p in name for p in palabras)


def pdf_matches(ruta: Path, q: str) -> bool:
    palabras = query_terms(q)
    if not palabras:
        return True
    texto = pdf_text(ruta).lower()
    return all(p in texto for p in palabras)


def file_search_matches(ruta: Path, q: str) -> bool:
    palabras = query_terms(q)
    if not palabras:
        return True
    if name_matches(ruta, q):
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
