"""
Destino de PDF firmados IN_ (ingresos).
Misma jerarquía que transferencias/digitalizados:
  {destino}/{deposito}/{categoria}/{Año yyyy}/{mm}/archivo.pdf
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import fitz

from services import transfer_routing
from services.apartado_paths import CategoriaConfig, parse_categorias_for_deposito
from services.metrics_ingresos import parse_ingreso_pdf

_IN_NAME = re.compile(r"^(IN|ING)[_\s]?(\d{8})", re.IGNORECASE)
_DATE8 = re.compile(r"(\d{8})")
_DATE_DMY = re.compile(r"(\d{2})[-_/](\d{2})[-_/](\d{4})")


def parse_in_date(name: str) -> tuple[int, int, int] | None:
    base = Path(name).name
    m = _IN_NAME.match(base)
    d = m.group(2) if m else None
    if not d:
        m2 = _DATE8.search(base)
        d = m2.group(1) if m2 else None
    if not d:
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
    if not d:
        return None
    try:
        y, mo, day = int(d[0:4]), int(d[4:6]), int(d[6:8])
        datetime(y, mo, day)
    except (ValueError, OSError):
        return None
    return y, mo, day


def extract_pdf_text(path: Path, max_pages: int = 8) -> str:
    return transfer_routing.extract_pdf_text(path, max_pages=max_pages)


def destination_dir_ingresos(
    deposito_root: Path,
    filename: str,
    text: str,
    *,
    codigos_articulo: set[str] | None = None,
    categorias: list[CategoriaConfig] | None = None,
    keywords_importante: tuple[str, ...] | None = None,
    source: Path | None = None,
) -> Path:
    """
    Clasifica bajo la raíz del depósito (p. ej. AGROINDUSTRIAS) con categorías y fecha IN.
    Si se pasa `source`, extrae códigos de artículo del PDF.
    """
    codigos = codigos_articulo
    if codigos is None and source is not None:
        parsed = parse_ingreso_pdf(source)
        codigos = {
            (it.codigo or "").strip().upper()
            for it in (parsed.items or [])
            if (it.codigo or "").strip()
        }
    return transfer_routing.destination_dir(
        deposito_root,
        filename,
        codigos,
        keywords_importante=keywords_importante,
        categorias=categorias,
        text_fallback=text or "",
    )
