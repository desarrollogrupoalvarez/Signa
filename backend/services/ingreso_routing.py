"""
Destino de PDF firmados con prefijo IN_ (Tango / ingresos), bajo path_destino_ingresos.
Estructura: Año {yyyy} / {mm:02d}
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import fitz

_IN_NAME = re.compile(r"^(IN|ING)[_\s]?(\d{8})", re.IGNORECASE)
_DATE8 = re.compile(r"(\d{8})")
_DATE_DMY = re.compile(r"(\d{2})[-_/](\d{2})[-_/](\d{4})")


def parse_in_date(name: str) -> tuple[int, int, int] | None:
    base = Path(name).name
    m = _IN_NAME.match(base)
    d = m.group(2) if m else None
    if not d:
        # Fallback: si hay fecha en el nombre (YYYYMMDD) en cualquier lugar, usarla.
        m2 = _DATE8.search(base)
        d = m2.group(1) if m2 else None
    if not d:
        # Fallback: formatos tipo DD-MM-YYYY (o con _ /)
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
    out: list[str] = []
    try:
        doc = fitz.open(str(path))
        for i in range(min(len(doc), max_pages)):
            out.append(doc[i].get_text() or "")
        doc.close()
    except Exception:
        return ""
    return "\n".join(out)


def destination_dir_ingresos(root: Path, filename: str, text: str) -> Path:
    """Raíz = carpeta de destino ingresos; debajo: Año aaaa / mm o Otros / …"""
    inn = parse_in_date(filename)
    if inn:
        y, mo, _ = inn
        p = root / f"Año {y}" / f"{mo:02d}"
        return p
    today = date.today()
    return root / "Otros" / f"Año {today.year}" / f"{today.month:02d}"
