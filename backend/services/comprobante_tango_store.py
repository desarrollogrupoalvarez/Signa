"""Persistencia de estado comprobante_tango."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from models.comprobante_tango import ComprobanteTango

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def get_estado(db: "Session", apartado_id: int, clave: str) -> str | None:
    row = (
        db.query(ComprobanteTango)
        .filter(ComprobanteTango.apartado_id == apartado_id, ComprobanteTango.clave == clave)
        .first()
    )
    return row.estado if row else None


def get_estado_y_filename(db: "Session", apartado_id: int, clave: str) -> tuple[str | None, str | None]:
    row = (
        db.query(ComprobanteTango)
        .filter(ComprobanteTango.apartado_id == apartado_id, ComprobanteTango.clave == clave)
        .first()
    )
    if not row:
        return None, None
    return row.estado, (row.pdf_filename or "").strip() or None


def upsert_pendiente(
    db: "Session",
    apartado_id: int,
    clave: str,
    pdf_filename: str,
    tango_fecha: date | None,
) -> ComprobanteTango:
    row = (
        db.query(ComprobanteTango)
        .filter(ComprobanteTango.apartado_id == apartado_id, ComprobanteTango.clave == clave)
        .first()
    )
    if not row:
        row = ComprobanteTango(apartado_id=apartado_id, clave=clave)
        db.add(row)
    row.estado = "pendiente"
    row.pdf_filename = (pdf_filename or "").strip()
    row.tango_fecha = (
        tango_fecha.isoformat()[:10]
        if hasattr(tango_fecha, "isoformat")
        else (str(tango_fecha)[:10] if tango_fecha else None)
    )
    db.flush()
    return row


def mark_firmado(db: "Session", apartado_id: int, clave: str) -> None:
    row = (
        db.query(ComprobanteTango)
        .filter(ComprobanteTango.apartado_id == apartado_id, ComprobanteTango.clave == clave)
        .first()
    )
    if row:
        row.estado = "firmado"
        db.flush()
