"""Registros: listado y búsqueda en PDFs archivados (firmados)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from services.apartado_paths import SIN_FIRMAR
from services.file_search import file_search_matches
from services.metrics_ingresos import parse_ingreso_pdf
from services.metrics_transferencias import parse_transfer_pdf


def _skip_sin_firmar_path(p: Path, root: Path) -> bool:
    """Excluye PDFs en carpeta Sin Firmar (pendientes en bandeja, no firmados)."""
    try:
        rel = p.relative_to(root)
    except ValueError:
        return True
    return any(part.upper() == SIN_FIRMAR.upper() for part in rel.parts)


def _year_month_filters(year: str, month: str) -> tuple[int | None, str | None]:
    year_i = None
    month_i = None
    try:
        if year:
            year_i = int(year)
    except (TypeError, ValueError):
        year_i = None
    try:
        if month:
            month_i = int(month)
    except (TypeError, ValueError):
        month_i = None
    month_s = f"{month_i:02d}" if month_i and 1 <= month_i <= 12 else None
    return year_i, month_s


def _path_matches_period(p: Path, root: Path, year_i: int | None, month_s: str | None) -> bool:
    if not year_i and not month_s:
        return True
    try:
        rel_parts = [str(x) for x in p.relative_to(root).parts]
    except Exception:
        rel_parts = [str(x) for x in p.parts]
    if year_i and not any(str(year_i) in pt for pt in rel_parts):
        return False
    if month_s and month_s not in rel_parts:
        return False
    return True


def _iter_pdfs_for_period(root: Path, year_i: int | None, month_s: str | None):
    """Recorre PDFs del período evitando un rglob completo del árbol cuando hay año/mes."""
    if year_i and month_s:
        yield from root.glob(f"**/Año {year_i}/{month_s}/*.pdf")
        return
    if year_i:
        yield from root.glob(f"**/Año {year_i}/**/*.pdf")
        return
    yield from root.rglob("*.pdf")


def _resolve_dest_root(apartado) -> Path | None:
    from services.path_settings import resolve_storage_path

    raw = getattr(apartado, "destino_path", None)
    if not raw:
        return None
    return resolve_storage_path(raw)


def _filter_ingreso_items(m, q_terms: list[str], p: Path) -> list | None:
    """None = descartar PDF; lista = ítems a incluir."""
    matched_items = list(m.items or [])
    if not q_terms:
        return matched_items
    prov = (m.proveedor or "").lower()
    terms_in_prov = {t for t in q_terms if prov and t in prov}
    remaining = [t for t in q_terms if t not in terms_in_prov]

    if remaining:
        filtered_items: list = []
        for it in (m.items or []):
            codigo = (it.codigo or "").lower()
            desc = (it.descripcion or "").lower()
            blob = (codigo + " " + desc).strip()
            if blob and all(t in blob for t in remaining):
                filtered_items.append(it)
        if not filtered_items:
            meta_blob = " ".join(
                [
                    (m.proveedor or ""),
                    (m.fecha or ""),
                    (m.orden or ""),
                    str(p.name or ""),
                    str(m.remito_interno or ""),
                    str(m.remito_proveedor or ""),
                ]
            ).lower()
            if all(t in meta_blob for t in remaining):
                filtered_items = list(m.items or [])
        matched_by_proveedor = len(terms_in_prov) > 0
        if not remaining and matched_by_proveedor:
            matched_items = list(m.items or [])
        else:
            matched_items = filtered_items
        if remaining and not matched_items:
            return None
    elif terms_in_prov:
        matched_items = list(m.items or [])
    return matched_items


def _filter_transfer_items(m, q_terms: list[str]) -> list | None:
    matched_items = list(m.items or [])
    if not q_terms:
        return matched_items
    header_blob = " ".join(
        [
            (m.comprobante or ""),
            (m.origen or ""),
            (m.destino or ""),
        ]
    ).lower()
    terms_in_header = {t for t in q_terms if header_blob and t in header_blob}
    remaining = [t for t in q_terms if t not in terms_in_header]
    if remaining:
        filtered = []
        for it in (m.items or []):
            blob = ((it.codigo or "") + " " + (it.descripcion or "")).lower().strip()
            if blob and all(t in blob for t in remaining):
                filtered.append(it)
        matched_items = filtered
    elif terms_in_header:
        matched_items = list(m.items or [])
    if remaining and not matched_items:
        return None
    return matched_items


def _lightweight_ingreso_entry(a, p: Path, root: Path) -> dict[str, Any]:
    rel = str(p.relative_to(root)).replace("\\", "/")
    return {
        "apartado": a.codigo,
        "origen_datos": "pdf",
        "archivo": p.name,
        "carpeta": str(p.parent),
        "ruta": str(p),
        "nombre_firmado": f"{(a.prefijo or 'x').strip()[:8]}/{rel}",
        "proveedor": "",
        "fecha": "",
        "remito_interno": "",
        "remito_proveedor": "",
        "deposito": "",
        "orden": "",
        "items_total": 0,
        "items_match": 0,
        "items": [],
    }


def _lightweight_transfer_entry(a, p: Path, root: Path) -> dict[str, Any]:
    pfx = (a.prefijo or "x").strip()[:8]
    try:
        rel = f"{pfx}/" + str(p.relative_to(root)).replace("\\", "/")
    except Exception:
        rel = f"{pfx}/" + p.name
    return {
        "apartado": a.codigo,
        "origen_datos": "pdf",
        "archivo": p.name,
        "carpeta": str(p.parent),
        "ruta": str(p),
        "nombre_firmado": rel,
        "comprobante": "",
        "fecha": "",
        "origen": "",
        "destino": "",
        "items_total": 0,
        "items_match": 0,
        "items": [],
    }


def list_ingresos_pdfs(
    apartados: Sequence[Any],
    *,
    year: str,
    month: str,
    q: str = "",
    limit: int = 2500,
    parse_content: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """PDFs del período; con q filtra por proveedor/ítems. Sin q evita leer el contenido del PDF."""
    q_terms = [t for t in (q or "").strip().lower().split() if t]
    q_raw = (q or "").strip()
    year_i, month_s = _year_month_filters(year, month)
    limit = max(1, min(2500, limit))
    out: list[dict[str, Any]] = []
    scanned = 0

    for a in apartados:
        root = _resolve_dest_root(a)
        if not root or not root.is_dir():
            continue
        try:
            for p in _iter_pdfs_for_period(root, year_i, month_s):
                if scanned >= limit:
                    break
                if not p.is_file():
                    continue
                if _skip_sin_firmar_path(p, root):
                    continue
                if not _path_matches_period(p, root, year_i, month_s):
                    continue
                if parse_content and q_terms and not file_search_matches(p, q_raw):
                    continue
                if not parse_content:
                    out.append(_lightweight_ingreso_entry(a, p, root))
                    scanned += 1
                    continue
                m = parse_ingreso_pdf(p)
                matched_items = _filter_ingreso_items(m, q_terms, p)
                if matched_items is None:
                    continue
                out.append(
                    {
                        "apartado": a.codigo,
                        "origen_datos": "pdf",
                        "archivo": p.name,
                        "carpeta": str(p.parent),
                        "ruta": str(p),
                        "nombre_firmado": f"{(a.prefijo or 'x').strip()[:8]}/"
                        + str(p.relative_to(root)).replace("\\", "/"),
                        "proveedor": m.proveedor,
                        "fecha": m.fecha,
                        "remito_interno": m.remito_interno,
                        "remito_proveedor": m.remito_proveedor,
                        "deposito": m.deposito,
                        "orden": m.orden,
                        "items_total": len(m.items or []),
                        "items_match": len(matched_items or []),
                        "items": [
                            {
                                "codigo": it.codigo,
                                "descripcion": it.descripcion,
                                "cantidad": it.cantidad,
                                "um": it.um,
                            }
                            for it in (matched_items or [])
                        ],
                    }
                )
                scanned += 1
        except OSError:
            continue

    return out, scanned


def list_transferencias_pdfs(
    apartados: Sequence[Any],
    *,
    year: str,
    month: str,
    q: str = "",
    limit: int = 2000,
    parse_content: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """PDFs del período; con q filtra por encabezado/ítems. Sin q evita leer el contenido del PDF."""
    q_terms = [t for t in (q or "").strip().lower().split() if t]
    q_raw = (q or "").strip()
    year_i, month_s = _year_month_filters(year, month)
    limit = max(1, min(2000, limit))
    out: list[dict[str, Any]] = []
    scanned = 0

    for a in apartados:
        root = _resolve_dest_root(a)
        if not root or not root.is_dir():
            continue
        try:
            for p in _iter_pdfs_for_period(root, year_i, month_s):
                if scanned >= limit:
                    break
                if not p.is_file():
                    continue
                if _skip_sin_firmar_path(p, root):
                    continue
                if not _path_matches_period(p, root, year_i, month_s):
                    continue
                if parse_content and q_terms and not file_search_matches(p, q_raw):
                    continue
                if not parse_content:
                    out.append(_lightweight_transfer_entry(a, p, root))
                    scanned += 1
                    continue
                m = parse_transfer_pdf(p)
                matched_items = _filter_transfer_items(m, q_terms)
                if matched_items is None:
                    continue
                rel = None
                try:
                    rel = f"{(a.prefijo or 'x').strip()[:8]}/" + str(p.relative_to(root)).replace("\\", "/")
                except Exception:
                    rel = f"{(a.prefijo or 'x').strip()[:8]}/" + p.name
                out.append(
                    {
                        "apartado": a.codigo,
                        "origen_datos": "pdf",
                        "archivo": p.name,
                        "carpeta": str(p.parent),
                        "ruta": str(p),
                        "nombre_firmado": rel,
                        "comprobante": m.comprobante,
                        "fecha": m.fecha,
                        "origen": m.origen,
                        "destino": m.destino,
                        "items_total": len(m.items or []),
                        "items_match": len(matched_items or []),
                        "items": [
                            {
                                "codigo": it.codigo,
                                "descripcion": it.descripcion,
                                "cantidad": it.cantidad,
                                "um": it.um,
                            }
                            for it in (matched_items or [])
                        ],
                    }
                )
                scanned += 1
        except OSError:
            continue

    return out, scanned


# Alias para compatibilidad
search_ingresos_pdfs = list_ingresos_pdfs
search_transferencias_pdfs = list_transferencias_pdfs
