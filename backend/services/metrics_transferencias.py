"""
Métricas por lectura de PDFs (Transferencias).

Se calcula al vuelo: parsea texto extraído (PyMuPDF/fitz) de PDFs ya procesados.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class TransferItem:
    codigo: str
    descripcion: str
    cantidad: float | None
    um: str | None


@dataclass
class TransferMetric:
    comprobante: str | None
    fecha: str | None
    origen: str | None
    destino: str | None
    items: list[TransferItem]


_RE_COMP_FECHA = re.compile(
    r"^\s*Comprobante\s*:?\s*(.+?)\s+Fecha\s*:?\s*([0-9]{2}/[0-9]{2}/[0-9]{4})\s*$",
    re.IGNORECASE,
)
_RE_ORIGEN = re.compile(r"^\s*Origen\s*:?\s*(.+?)(?:\s+Usuario\s*:.*)?\s*$", re.IGNORECASE)
_RE_DESTINO = re.compile(r"^\s*Destino\s*:?\s*(.+?)(?:\s+Hora\s*:.*)?\s*$", re.IGNORECASE)
_RE_TOTAL_UNIDADES = re.compile(r"^\s*(?:Total\s+de\s+Unidades|TOTAL)\b", re.IGNORECASE)
_RE_TABLE_HEADER = re.compile(r"art[ií]culo|descripci[oó]n|cantidad|u/m", re.IGNORECASE)
_RE_CANT_UM = re.compile(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s+([A-Z]{1,6})\s*$")
_RE_QTY = re.compile(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*$")
# U/M suele ser corto (UNI, KG, L, etc.). Evitamos confundir descripciones como "LENTES".
_RE_UM = re.compile(r"^[A-Z]{1,4}$")
# Código típico de artículo en transferencias: AGRO01 / 01AGRO12, etc. Evitar confundir descripciones.
_RE_CODE = re.compile(r"^(?=.*\d)[A-Z0-9]{3,}$")
_RE_ROW_ALT = re.compile(
    r"^\s*([A-Z0-9]{6,})\s+(.+?)\s+([0-9]+(?:[.,][0-9]+)?)\s+([A-Z]{1,4})\s*$"
)
_RE_ROW_3COL = re.compile(
    r"^\s*([A-Z0-9]{6,})\s+(.+?)\s+([0-9]+(?:[.,][0-9]+)?)\s*$"
)


def extract_pdf_text(path: Path, max_pages: int = 2) -> str:
    out: list[str] = []
    doc = None
    try:
        doc = fitz.open(str(path))
        for i in range(min(len(doc), max_pages)):
            out.append(doc[i].get_text() or "")
    except Exception:
        return ""
    finally:
        try:
            if doc:
                doc.close()
        except Exception:
            pass
    return "\n".join(out)


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace(".", "").replace(",", ".")) if s.count(",") == 1 and s.count(".") > 1 else float(s.replace(",", "."))
    except Exception:
        try:
            return float(s.replace(",", "."))
        except Exception:
            return None


def parse_transfer_text(text: str) -> TransferMetric:
    comprobante = None
    fecha = None
    origen = None
    destino = None
    items: list[TransferItem] = []
    total_unidades: float | None = None

    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]

    in_table = False
    qty_queue: list[float] = []
    um_current: str | None = None

    def _assign_from_queue():
        nonlocal qty_queue
        if not qty_queue:
            return
        for it in items:
            if not qty_queue:
                break
            if it.cantidad is None:
                it.cantidad = qty_queue.pop(0)

    def _assign_um_to_missing(um: str):
        for it in items:
            if it.um is None:
                it.um = um

    for idx, ln in enumerate(lines):
        m = _RE_COMP_FECHA.match(ln)
        if m:
            comprobante = m.group(1).strip()
            fecha = m.group(2).strip()
            continue

        m = _RE_ORIGEN.match(ln)
        if m:
            origen = m.group(1).strip()
            continue

        m = _RE_DESTINO.match(ln)
        if m:
            destino = m.group(1).strip()
            continue

        if not in_table:
            # La tabla suele arrancar con "Artículo"
            low = ln.lower()
            # En algunos PDFs el texto viene con caracteres corruptos (Art�culo, Descripci�n).
            # Detectamos por substrings más tolerantes.
            if ("art" in low and "descrip" in low and "cant" in low) or ("artículo" in low) or ("articulo" in low):
                in_table = True
            continue

        if _RE_TOTAL_UNIDADES.search(ln):
            mnum = re.search(r"([0-9]+(?:[.,][0-9]+)?)", ln)
            if mnum:
                total_unidades = _to_float(mnum.group(1))
            else:
                if idx + 1 < len(lines):
                    mnext = _RE_QTY.match(lines[idx + 1].strip())
                    if mnext:
                        total_unidades = _to_float(mnext.group(1))
            break

        if _RE_TABLE_HEADER.search(ln):
            continue

        mrow3 = _RE_ROW_3COL.match(ln)
        if mrow3:
            codigo = mrow3.group(1).strip()
            desc = mrow3.group(2).strip()
            cant = _to_float(mrow3.group(3).strip())
            items.append(TransferItem(codigo=codigo, descripcion=desc, cantidad=cant, um=um_current))
            continue

        # Fila alternativa en una línea (código + desc + cantidad + um)
        mrow = _RE_ROW_ALT.match(ln)
        if mrow:
            codigo = mrow.group(1).strip()
            desc = mrow.group(2).strip()
            cant = _to_float(mrow.group(3).strip())
            um = mrow.group(4).strip()
            items.append(TransferItem(codigo=codigo, descripcion=desc, cantidad=cant, um=um))
            um_current = um_current or um
            continue

        if _RE_CODE.match(ln):
            items.append(TransferItem(codigo=ln.strip(), descripcion="", cantidad=None, um=None))
            if um_current:
                items[-1].um = um_current
            _assign_from_queue()
            continue

        mqu = _RE_CANT_UM.match(ln)
        if mqu:
            qv = _to_float(mqu.group(1))
            if qv is not None:
                qty_queue.append(qv)
                _assign_from_queue()
            um_current = mqu.group(2).strip()
            _assign_um_to_missing(um_current)
            continue

        mq = _RE_QTY.match(ln)
        if mq:
            qv = _to_float(mq.group(1))
            if qv is not None:
                qty_queue.append(qv)
                _assign_from_queue()
            continue

        if _RE_UM.match(ln):
            um_current = ln.strip()
            _assign_um_to_missing(um_current)
            continue

        # Descripción: asignar al primer item sin descripción, o anexar al último si ya tiene
        if items:
            for it in items:
                if not it.descripcion:
                    it.descripcion = ln.strip()
                    break
            else:
                items[-1].descripcion = (items[-1].descripcion + " " + ln.strip()).strip()
            _assign_from_queue()

    items = [it for it in items if it.codigo and it.descripcion]
    if total_unidades is not None and items:
        missing_idx = [i for i, it in enumerate(items) if it.cantidad is None]
        if len(missing_idx) == 1:
            known_sum = sum((it.cantidad or 0.0) for it in items)
            diff = total_unidades - known_sum
            if diff >= 0 and diff <= max(total_unidades, 0.0) + 1e-6:
                items[missing_idx[0]].cantidad = round(diff, 3)
    return TransferMetric(
        comprobante=comprobante,
        fecha=fecha,
        origen=origen,
        destino=destino,
        items=items,
    )


def parse_transfer_pdf(path: Path) -> TransferMetric:
    return parse_transfer_text(extract_pdf_text(path))

