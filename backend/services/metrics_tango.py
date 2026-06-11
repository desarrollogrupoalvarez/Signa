"""Registros: métricas desde Tango (rango de fechas, sin filtro por usuario)."""

from __future__ import annotations

import calendar
import logging
from datetime import date
from typing import Any, Sequence

from config import Config
from services import tango_queries
from services.apartado_paths import parse_depositos
from services.tango_comprobante_mapper import (
    group_ingresos,
    group_transferencias,
    map_ingreso_group,
    map_transferencia_group,
)

logger = logging.getLogger("remitos")


def parse_year_month(year: str, month: str) -> tuple[int, int | None]:
    y = int(year)
    if month:
        m = int(month)
        if not (1 <= m <= 12):
            raise ValueError("Mes inválido")
        return y, m
    return y, None


def fecha_rango(year: int, month: int | None) -> tuple[date, date]:
    if month is not None:
        last = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last)
    return date(year, 1, 1), date(year, 12, 31)


def _cantidad(val: Any) -> float | int | None:
    if val is None:
        return None
    try:
        if isinstance(val, bool):
            return None
        if isinstance(val, int):
            return val
        return float(val)
    except (TypeError, ValueError):
        return None


def _filter_ingreso_doc(doc: dict[str, Any], q_terms: list[str]) -> dict[str, Any] | None:
    if not q_terms:
        return doc
    prov = (doc.get("proveedor") or "").lower()
    terms_in_prov = {t for t in q_terms if prov and t in prov}
    remaining = [t for t in q_terms if t not in terms_in_prov]
    items = list(doc.get("items") or [])
    matched_items = items
    if remaining:
        filtered: list[dict[str, Any]] = []
        for it in items:
            blob = ((it.get("codigo") or "") + " " + (it.get("descripcion") or "")).lower().strip()
            if blob and all(t in blob for t in remaining):
                filtered.append(it)
        if not filtered:
            meta_blob = " ".join(
                [
                    doc.get("proveedor") or "",
                    doc.get("fecha") or "",
                    doc.get("orden") or "",
                    doc.get("comprobante") or "",
                    str(doc.get("remito_interno") or ""),
                    str(doc.get("remito_proveedor") or ""),
                ]
            ).lower()
            if all(t in meta_blob for t in remaining):
                filtered = items
        matched_items = filtered
        if not matched_items:
            return None
    elif terms_in_prov:
        matched_items = items
    out = dict(doc)
    out["items"] = matched_items
    out["items_match"] = len(matched_items)
    out["items_total"] = len(items)
    return out


def _filter_transfer_doc(doc: dict[str, Any], q_terms: list[str]) -> dict[str, Any] | None:
    if not q_terms:
        return doc
    header_blob = " ".join(
        [
            doc.get("comprobante") or "",
            doc.get("origen") or "",
            doc.get("destino") or "",
        ]
    ).lower()
    terms_in_header = {t for t in q_terms if header_blob and t in header_blob}
    remaining = [t for t in q_terms if t not in terms_in_header]
    items = list(doc.get("items") or [])
    matched_items = items
    if remaining:
        filtered: list[dict[str, Any]] = []
        for it in items:
            blob = ((it.get("codigo") or "") + " " + (it.get("descripcion") or "")).lower().strip()
            if blob and all(t in blob for t in remaining):
                filtered.append(it)
        matched_items = filtered
        if not matched_items:
            return None
    elif terms_in_header:
        matched_items = items
    out = dict(doc)
    out["items"] = matched_items
    out["items_match"] = len(matched_items)
    out["items_total"] = len(items)
    return out


def _ingreso_doc_from_group(apartado_codigo: str, rows: list[dict[str, Any]], mapped: dict[str, Any]) -> dict[str, Any]:
    h = rows[0]
    fuente = str(h.get("tango_fuente") or "").strip()
    items = []
    for ln in mapped.get("lineas") or []:
        items.append(
            {
                "codigo": ln.get("codigo_articulo") or "",
                "descripcion": ln.get("descripcion") or "",
                "cantidad": _cantidad(ln.get("cantidad")),
                "um": ln.get("unidad_medida") or "",
            }
        )
    num_rem = mapped.get("numero_informe") or ""
    comprobante = f"REM {num_rem}".strip() if num_rem else "REM"
    return {
        "apartado": apartado_codigo,
        "origen_datos": "tango",
        "tango_fuente": fuente,
        "comprobante": comprobante,
        "fecha": mapped.get("fecha") or "",
        "proveedor": mapped.get("proveedor") or "",
        "remito_interno": num_rem,
        "remito_proveedor": mapped.get("numero_remito") or "",
        "deposito": mapped.get("deposito_general") or "",
        "usuario": mapped.get("usuario") or "",
        "items_total": len(items),
        "items_match": len(items),
        "items": items,
    }


def _transfer_doc_from_group(apartado_codigo: str, rows: list[dict[str, Any]], mapped: dict[str, Any]) -> dict[str, Any]:
    h = rows[0]
    fuente = str(h.get("tango_fuente") or "").strip()
    items = []
    for ln in mapped.get("lineas") or []:
        items.append(
            {
                "codigo": ln.get("codigo") or "",
                "descripcion": ln.get("descripcion") or "",
                "cantidad": _cantidad(ln.get("cantidad")),
                "um": "",
            }
        )
    return {
        "apartado": apartado_codigo,
        "origen_datos": "tango",
        "tango_fuente": fuente,
        "comprobante": mapped.get("numero_comprobante") or "",
        "fecha": mapped.get("fecha") or "",
        "origen": mapped.get("origen_deposito") or mapped.get("origen_codigo") or "",
        "destino": mapped.get("destino_deposito") or mapped.get("destino_codigo") or "",
        "usuario": mapped.get("usuario") or "",
        "items_total": len(items),
        "items_match": len(items),
        "items": items,
    }


def query_ingresos(
    apartados: Sequence[Any],
    *,
    year: int,
    month: int | None,
    q: str = "",
) -> dict[str, Any]:
    if not Config.tango_configured():
        raise RuntimeError("Tango no configurado en el servidor")

    fecha_desde, fecha_hasta = fecha_rango(year, month)
    q_terms = [t for t in (q or "").strip().lower().split() if t]

    documentos: list[dict[str, Any]] = []
    filas_tango = 0
    comprobantes_tango = 0
    fuentes: dict[str, int] = {}

    for ap in apartados:
        for dep in parse_depositos(ap):
            src = Config.tango_source_by_id(dep.tango_fuente)
            if not src:
                continue
            deps_cods = list(dep.cod_depositos)
            try:
                rows = tango_queries.fetch_ingresos_rango(
                    deps_cods,
                    fecha_desde,
                    fecha_hasta,
                    database=src.database,
                    tango_fuente=src.id,
                )
            except Exception as ex:
                logger.exception(
                    "metrics_ingresos [%s] apartado=%s dep=%s: %s",
                    src.id,
                    ap.codigo,
                    dep.carpeta,
                    ex,
                )
                continue
            filas_tango += len(rows)
            fuentes[src.id] = fuentes.get(src.id, 0) + len(rows)
            groups = group_ingresos(rows)
            comprobantes_tango += len(groups)
            for grp_rows in groups.values():
                mapped = map_ingreso_group(grp_rows)
                doc = _ingreso_doc_from_group(ap.codigo, grp_rows, mapped)
                filtered = _filter_ingreso_doc(doc, q_terms)
                if filtered is not None:
                    documentos.append(filtered)

    return {
        "documentos": documentos,
        "total": len(documentos),
        "filas_tango": filas_tango,
        "comprobantes_tango": comprobantes_tango,
        "fuentes": fuentes,
    }


def query_transferencias(
    apartados: Sequence[Any],
    *,
    year: int,
    month: int | None,
    q: str = "",
) -> dict[str, Any]:
    if not Config.tango_configured():
        raise RuntimeError("Tango no configurado en el servidor")

    fecha_desde, fecha_hasta = fecha_rango(year, month)
    q_terms = [t for t in (q or "").strip().lower().split() if t]

    documentos: list[dict[str, Any]] = []
    filas_tango = 0
    comprobantes_tango = 0
    fuentes: dict[str, int] = {}

    for ap in apartados:
        for dep in parse_depositos(ap):
            src = Config.tango_source_by_id(dep.tango_fuente)
            if not src:
                continue
            deps_cods = list(dep.cod_depositos)
            try:
                rows = tango_queries.fetch_transferencias_rango(
                    deps_cods,
                    fecha_desde,
                    fecha_hasta,
                    database=src.database,
                    tango_fuente=src.id,
                )
            except Exception as ex:
                logger.exception(
                    "metrics_transferencias [%s] apartado=%s dep=%s: %s",
                    src.id,
                    ap.codigo,
                    dep.carpeta,
                    ex,
                )
                continue
            filas_tango += len(rows)
            fuentes[src.id] = fuentes.get(src.id, 0) + len(rows)
            groups = group_transferencias(rows)
            comprobantes_tango += len(groups)
            for grp_rows in groups.values():
                mapped = map_transferencia_group(grp_rows)
                doc = _transfer_doc_from_group(ap.codigo, grp_rows, mapped)
                filtered = _filter_transfer_doc(doc, q_terms)
                if filtered is not None:
                    documentos.append(filtered)

    return {
        "documentos": documentos,
        "total": len(documentos),
        "filas_tango": filas_tango,
        "comprobantes_tango": comprobantes_tango,
        "fuentes": fuentes,
    }
