"""Búsqueda fulltext en comprobante_tango (optimizada: solo SQL, sin disco)."""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from pathlib import Path

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_SEARCH_LIMIT = 300


def _query_terms(q: str) -> list[str]:
    return [p for p in re.split(r"\s+", (q or "").strip()) if p]


def _escape_tsquery_term(term: str) -> str:
    return term.replace("\\", "\\\\").replace("'", "''")


def _build_tsquery(q: str) -> str | None:
    """
    Construye tsquery con prefijo por término (roda:* encuentra «rodamiento»).
    """
    terms: list[str] = []
    for part in _query_terms(q):
        cleaned = re.sub(r"[^\w]", "", part, flags=re.UNICODE)
        if cleaned:
            terms.append(f"{_escape_tsquery_term(cleaned)}:*")
    if not terms:
        return None
    return " & ".join(terms)


def _fecha_iso(val: date | datetime | str | None) -> str | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()
    s = str(val).strip()
    return s[:10] if s else None


def _buscar_sql(
    *,
    estado: str,
    apartado_ids: list[int] | None,
    tsq: str,
) -> str:
    sql = """
        SELECT ct.id, ct.apartado_id, ct.clave, ct.pdf_filename, ct.ruta, ct.estado, ct.tango_fecha,
               ct.updated_at,
               a.codigo AS apartado_codigo, a.prefijo, a.modo_flujo, a.destino_path,
               ts_headline(
                   'spanish',
                   coalesce(ct.texto_contenido, ''),
                   to_tsquery('spanish', :tsq),
                   'MaxFragments=1, MinWords=8, MaxWords=25'
               ) AS fragmento
        FROM comprobante_tango ct
        JOIN apartados a ON a.id = ct.apartado_id
        WHERE ct.estado = :estado
          AND ct.texto_contenido IS NOT NULL
          AND ct.texto_search @@ to_tsquery('spanish', :tsq)
    """
    if apartado_ids:
        sql += " AND ct.apartado_id = ANY(:apartado_ids)"
    sql += " ORDER BY ct.tango_fecha DESC NULLS LAST, ct.id DESC LIMIT :lim"
    return sql


def _row_to_item(row: Any) -> dict[str, Any]:
    prefijo = (row["prefijo"] or "x").strip()[:8]
    pdf_fn = (row["pdf_filename"] or "").strip()
    estado = row["estado"]
    ruta_bd = (row.get("ruta") or "").strip()
    if estado == "firmado":
        nombre = _nombre_listado_firmado(
            prefijo, ruta_bd, row.get("destino_path"), pdf_fn
        )
    else:
        nombre = pdf_fn

    updated = row.get("updated_at")
    modificado_en = updated.isoformat() if isinstance(updated, datetime) else None
    modo_flujo = row["modo_flujo"] or "transferencia"
    categoria_ui = "ingresos" if modo_flujo == "ingreso" else "tra"

    item: dict[str, Any] = {
        "id": row["id"],
        "fecha": _fecha_iso(row["tango_fecha"]),
        "estado": estado,
        "fragmento": (row.get("fragmento") or "").strip(),
        "nombre": nombre,
        "origen": row["apartado_codigo"],
        "apartado_codigo": row["apartado_codigo"],
        "modificado_en": modificado_en,
        "modo_flujo": modo_flujo,
        "extension": ".pdf",
        "clave": (row.get("clave") or "").strip(),
        "pdf_filename": pdf_fn,
    }
    if estado == "firmado":
        item["ruta"] = ruta_bd
        item["categoria"] = "pdf"
    else:
        item["categoria"] = categoria_ui
    return item


def buscar_comprobantes(
    db: "Session",
    q: str,
    *,
    estado: str = "firmado",
    apartado_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """
    Busca comprobantes por contenido indexado en BD.
    Una sola query SQL con GIN + ts_headline; no lee PDFs ni recorre carpetas.
    """
    q_norm = (q or "").strip()
    if not q_norm:
        return []

    estado_norm = (estado or "firmado").strip().lower()
    if estado_norm not in ("pendiente", "firmado"):
        estado_norm = "firmado"

    tsq = _build_tsquery(q_norm)
    if not tsq:
        return []

    params: dict[str, Any] = {
        "estado": estado_norm,
        "tsq": tsq,
        "lim": _SEARCH_LIMIT,
    }
    if apartado_ids:
        params["apartado_ids"] = apartado_ids

    sql = _buscar_sql(estado=estado_norm, apartado_ids=apartado_ids, tsq=tsq)
    rows = db.execute(text(sql), params).mappings().all()
    return [_row_to_item(row) for row in rows]


def _nombre_listado_firmado(
    prefijo: str,
    ruta_bd: str,
    destino_path: str | None,
    pdf_fn: str,
) -> str:
    """Nombre para UI sin acceder al disco (evita cuelgues en rutas UNC)."""
    pfx = (prefijo or "x").strip()[:8]
    stored = (ruta_bd or "").strip()
    if stored:
        dest_norm = os.path.normpath((destino_path or "").strip()).lower()
        stored_norm = os.path.normpath(stored)
        if dest_norm and stored_norm.lower().startswith(dest_norm):
            rel = stored_norm[len(dest_norm) :].lstrip("\\/")
            if rel:
                return f"{pfx}/" + rel.replace("\\", "/")
        return f"{pfx}/{Path(stored).name}"
    if pdf_fn:
        return f"{pfx}/{pdf_fn}"
    return pfx


def _listado_firmado_item(
    row: Any,
    *,
    ruta_efectiva: str,
) -> dict[str, Any]:
    prefijo = (row["prefijo"] or "x").strip()[:8]
    pdf_fn = (row["pdf_filename"] or "").strip()
    nombre = _nombre_listado_firmado(
        prefijo,
        ruta_efectiva,
        row.get("destino_path"),
        pdf_fn,
    )
    updated = row.get("updated_at")
    modificado_en = updated.isoformat() if isinstance(updated, datetime) else None
    modo_flujo = row["modo_flujo"] or "transferencia"
    return {
        "id": row["id"],
        "nombre": nombre,
        "origen": row["apartado_codigo"],
        "apartado_codigo": row["apartado_codigo"],
        "modificado_en": modificado_en,
        "categoria": "pdf",
        "modo_flujo": modo_flujo,
        "extension": ".pdf",
        "ruta": ruta_efectiva,
        "fecha": _fecha_iso(row["tango_fecha"]),
        "estado": "firmado",
    }


def listar_firmados_comprobantes(
    db: "Session",
    aps: list,
    *,
    origen_f: str = "",
    tipo_f: str = "",
) -> list[dict[str, Any]]:
    """
    Lista firmados desde comprobante_tango (solo PostgreSQL, sin escanear carpetas UNC).
    Si falta ruta en BD, arma nombre como prefijo/pdf_filename; abrir el archivo
    resuelve la ruta en disco (_safe_signed_path).
    """
    if not aps:
        return []

    apartado_ids = [int(a.id) for a in aps]

    sql = """
        SELECT ct.id, ct.apartado_id, ct.clave, ct.pdf_filename, ct.ruta, ct.tango_fecha,
               ct.updated_at,
               a.codigo AS apartado_codigo, a.prefijo, a.modo_flujo, a.destino_path
        FROM comprobante_tango ct
        JOIN apartados a ON a.id = ct.apartado_id
        WHERE ct.estado = 'firmado'
          AND ct.apartado_id = ANY(:apartado_ids)
        ORDER BY ct.tango_fecha DESC NULLS LAST, ct.updated_at DESC NULLS LAST, ct.id DESC
    """
    rows = db.execute(text(sql), {"apartado_ids": apartado_ids}).mappings().all()

    origen_norm = (origen_f or "").strip().lower()
    tipo_norm = (tipo_f or "").strip().lower()
    items: list[dict[str, Any]] = []

    for row in rows:
        if origen_norm and origen_norm not in ("todos", "all"):
            if (row["apartado_codigo"] or "") != origen_norm:
                continue
        if tipo_norm and tipo_norm not in ("todos", "all", ""):
            if tipo_norm != "pdf":
                continue

        ruta_bd = (row.get("ruta") or "").strip()
        items.append(_listado_firmado_item(row, ruta_efectiva=ruta_bd))

    return items


def listar_pendientes_comprobantes(
    db: "Session",
    aps: list,
    *,
    filter_fecha: str | None = None,
) -> list[dict[str, Any]]:
    """Lista comprobantes con estado pendiente en BD (sin escanear destino firmados)."""
    if not aps:
        return []

    apartado_ids = [int(a.id) for a in aps]
    sql = """
        SELECT ct.id, ct.apartado_id, ct.clave, ct.pdf_filename, ct.tango_fecha,
               ct.updated_at,
               a.codigo AS apartado_codigo, a.prefijo, a.modo_flujo
        FROM comprobante_tango ct
        JOIN apartados a ON a.id = ct.apartado_id
        WHERE ct.estado = 'pendiente'
          AND ct.apartado_id = ANY(:apartado_ids)
        ORDER BY ct.tango_fecha DESC NULLS LAST, ct.updated_at DESC NULLS LAST, ct.id DESC
    """
    rows = db.execute(text(sql), {"apartado_ids": apartado_ids}).mappings().all()
    want_fecha = (filter_fecha or "").strip()[:10] or None
    items: list[dict[str, Any]] = []
    for row in rows:
        fecha = _fecha_iso(row["tango_fecha"])
        if want_fecha and fecha and fecha != want_fecha:
            continue
        pdf_fn = (row["pdf_filename"] or "").strip()
        modo_flujo = row["modo_flujo"] or "transferencia"
        items.append(
            {
                "comprobante_id": row["id"],
                "clave": (row["clave"] or "").strip(),
                "pdf_filename": pdf_fn,
                "nombre": pdf_fn,
                "apartado_codigo": row["apartado_codigo"],
                "prefijo": (row["prefijo"] or "x").strip()[:8],
                "modo_flujo": modo_flujo,
                "categoria": "ingresos" if modo_flujo == "ingreso" else "tra",
                "tango_fecha": fecha,
                "recibido_en": (
                    row["updated_at"].isoformat()
                    if isinstance(row.get("updated_at"), datetime)
                    else None
                ),
            }
        )
    return items


def _fecha_en_periodo(fecha_iso: str | None, year: int | None, month: int | None) -> bool:
    if not year:
        return True
    s = (fecha_iso or "").strip()
    if len(s) < 4 or not s[:4].isdigit():
        return False
    if int(s[:4]) != year:
        return False
    if month is None:
        return True
    if len(s) < 7 or s[4] != "-":
        return False
    try:
        return int(s[5:7]) == month
    except ValueError:
        return False


def buscar_firmados_para_metricas(
    db: "Session",
    aps: list,
    q: str,
    *,
    year: int | None = None,
    month: int | None = None,
) -> list[dict[str, Any]]:
    """
    Resultados de búsqueda fulltext en firmados, formato compatible con métricas.
    Evita escanear carpetas UNC cuando hay texto indexado en BD.
    """
    if not aps or not (q or "").strip():
        return []
    apartado_ids = [int(a.id) for a in aps]
    items = buscar_comprobantes(db, q, estado="firmado", apartado_ids=apartado_ids)
    out: list[dict[str, Any]] = []
    for it in items:
        if not _fecha_en_periodo(it.get("fecha"), year, month):
            continue
        nombre = (it.get("nombre") or "").strip()
        ruta_abs = (it.get("ruta") or "").strip()
        out.append(
            {
                "apartado": it.get("origen") or "",
                "origen_datos": "pdf",
                "archivo": Path(nombre).name if "/" in nombre else nombre,
                "carpeta": str(Path(ruta_abs).parent) if ruta_abs else "",
                "ruta": ruta_abs,
                "nombre_firmado": nombre,
                "proveedor": "",
                "fecha": it.get("fecha") or "",
                "comprobante": "",
                "origen": "",
                "destino": "",
                "items_total": 0,
                "items_match": 0,
                "items": [],
                "fragmento": it.get("fragmento") or "",
            }
        )
    return out


def nombres_pendientes_coincidentes(
    db: "Session",
    q: str,
    apartado_ids: list[int] | None = None,
) -> dict[str, str]:
    """Mapa pdf_filename -> fragmento (query liviana, sin post-proceso en disco)."""
    q_norm = (q or "").strip()
    if not q_norm:
        return {}

    tsq = _build_tsquery(q_norm)
    if not tsq:
        return {}

    params: dict[str, Any] = {
        "estado": "pendiente",
        "tsq": tsq,
        "lim": _SEARCH_LIMIT,
    }
    if apartado_ids:
        params["apartado_ids"] = apartado_ids

    sql = _buscar_sql(estado="pendiente", apartado_ids=apartado_ids, tsq=tsq)
    rows = db.execute(text(sql), params).mappings().all()
    out: dict[str, str] = {}
    for row in rows:
        name = (row["pdf_filename"] or "").strip()
        if name:
            out[name] = (row["fragmento"] or "").strip()
    return out
