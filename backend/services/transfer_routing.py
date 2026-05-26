"""
Clasificación TRA y ruta bajo la raíz configurada.
La raíz (path_transferencias) ya apunta a la carpeta «Transferencias»; no se añade un nivel extra.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import fitz

if TYPE_CHECKING:
    from services.apartado_paths import CategoriaConfig

_TRA_NAME = re.compile(r"^TRA[_\s]?(\d{8})", re.IGNORECASE)
_DATE8_ANY = re.compile(r"(\d{8})")
_DATE_DMY = re.compile(r"(\d{2})[-_/](\d{2})[-_/](\d{4})")

# Palabras clave en descripción → Importante (búsqueda en texto completo, normalizado)
_DEFAULT_KEY_IMPORTANTE = (
    "fibra",
    "bateria",
    "batería",
)


@dataclass
class RoutingResult:
    rel_dir_parts: list[str]  # bajo transferencias_root, p.ej. ["Importante", "Año 2026", "04"]
    display_kind: str  # "tra" | "otros"


def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def extract_pdf_text(path: Path, max_pages: int = 8) -> str:
    out: list[str] = []
    try:
        doc = fitz.open(str(path))
        for i in range(min(len(doc), max_pages)):
            out.append(doc[i].get_text() or "")
        doc.close()
    except Exception:
        return ""
    return "\n".join(out)


def is_important_by_description(text: str, keywords: tuple[str, ...] | None = None) -> bool:
    n = _norm_text(text)
    keys = keywords or _DEFAULT_KEY_IMPORTANTE
    return any(_norm_text(k) in n for k in keys if k)


def parse_keywords_csv(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    s = str(raw)
    # soporta coma, punto y coma y newline
    for ch in ("\n", ";"):
        s = s.replace(ch, ",")
    parts = [p.strip() for p in s.split(",")]
    # dedupe manteniendo orden (normalizado)
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        if not p:
            continue
        n = _norm_text(p)
        if n in seen:
            continue
        seen.add(n)
        out.append(p)
    return tuple(out)


def parse_tra_date(name: str) -> tuple[int, int, int] | None:
    m = _TRA_NAME.match(Path(name).name)
    if not m:
        # Fallback: soportar fecha en cualquier lugar (YYYYMMDD) o DD-MM-YYYY.
        base = Path(name).name
        m2 = _DATE8_ANY.search(base)
        if m2:
            d = m2.group(1)
            try:
                y, mo, day = int(d[0:4]), int(d[4:6]), int(d[6:8])
                datetime(y, mo, day)
                return y, mo, day
            except (ValueError, OSError):
                return None
        m3 = _DATE_DMY.search(base)
        if m3:
            try:
                day = int(m3.group(1))
                mo = int(m3.group(2))
                y = int(m3.group(3))
                datetime(y, mo, day)
                return y, mo, day
            except (ValueError, OSError):
                return None
        return None
    d = m.group(1)
    try:
        y, mo, day = int(d[0:4]), int(d[4:6]), int(d[6:8])
        datetime(y, mo, day)
    except (ValueError, OSError):
        return None
    return y, mo, day


def _categoria_para_texto(
    text: str,
    categorias: list["CategoriaConfig"],
    *,
    keywords_importante: tuple[str, ...] | None = None,
) -> str:
    if categorias:
        for cat in categorias:
            if not cat.keywords:
                continue
            keys = parse_keywords_csv(cat.keywords)
            if keys and is_important_by_description(text, keys):
                return cat.nombre
        for cat in categorias:
            if not cat.keywords:
                return cat.nombre
        return categorias[0].nombre

    important = is_important_by_description(text, keywords_importante)
    return "Importante" if important else "Regulares"


def classify_routing(
    filename: str,
    text: str,
    *,
    keywords_importante: tuple[str, ...] | None = None,
    categorias: list["CategoriaConfig"] | None = None,
) -> RoutingResult:
    """
    Determina subcarpeta relativa (sin raíz de depósito) y tipo.
    """
    tra = parse_tra_date(filename)
    tier = _categoria_para_texto(text, categorias or [], keywords_importante=keywords_importante)

    if tra:
        y, mo, _ = tra
        return RoutingResult(
            rel_dir_parts=[tier, f"Año {y}", f"{mo:02d}"],
            display_kind="tra",
        )

    today = date.today()
    return RoutingResult(
        rel_dir_parts=["Otros", f"Año {today.year}", f"{today.month:02d}"],
        display_kind="otros",
    )


def destination_dir(
    deposito_root: Path,
    filename: str,
    text: str,
    *,
    keywords_importante: tuple[str, ...] | None = None,
    categorias: list["CategoriaConfig"] | None = None,
) -> Path:
    r = classify_routing(
        filename,
        text,
        keywords_importante=keywords_importante,
        categorias=categorias,
    )
    p = deposito_root
    for part in r.rel_dir_parts:
        p = p / part
    return p
