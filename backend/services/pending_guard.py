"""Evita registrar como pendientes PDFs ya firmados (BD o destino)."""

from __future__ import annotations

import logging
from pathlib import Path

from services.apartado_paths import SIN_FIRMAR
from services.file_ops import safe_unlink

logger = logging.getLogger("remitos")


def _skip_sin_firmar_in_parts(parts: tuple[str, ...]) -> bool:
    return any(p.upper() == SIN_FIRMAR.upper() for p in parts)


def pdf_exists_in_destino(destino_root: Path, filename: str) -> bool:
    """True si existe un PDF con el mismo nombre bajo destino (fuera de Sin Firmar)."""
    if not destino_root.is_dir() or not filename:
        return False
    try:
        for p in destino_root.rglob(filename):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(destino_root.resolve())
            except (ValueError, OSError):
                continue
            if _skip_sin_firmar_in_parts(rel.parts):
                continue
            return True
    except OSError as ex:
        logger.warning("pdf_exists_in_destino | root=%s | %s", destino_root, ex)
    return False


def path_is_pending_inbox(path: Path, apartado) -> bool:
    """True si el PDF está bajo la bandeja de pendientes (carpeta Sin Firmar), no en destino archivado."""
    from services.apartado_paths import SIN_FIRMAR
    from services.path_settings import resolve_storage_path

    band = resolve_storage_path(getattr(apartado, "bandeja_path", None))
    if not band:
        return False
    try:
        path.resolve().relative_to(band.resolve())
    except (ValueError, OSError):
        return False
    if band.name.upper() == SIN_FIRMAR.upper():
        return True
    try:
        rel = path.resolve().relative_to(band.resolve())
        return any(p.upper() == SIN_FIRMAR.upper() for p in rel.parts)
    except (ValueError, OSError):
        return False


def _resolve_clave(db, apartado_id: int, tango_clave: str | None, filename: str) -> str | None:
    from services import comprobante_tango_store

    clave = (tango_clave or "").strip()
    if clave:
        return clave
    return comprobante_tango_store.clave_by_pdf_filename(db, apartado_id, filename)


def should_skip_pending_registration(
    path: Path,
    apartado_codigo: str,
    *,
    tango_clave: str | None = None,
    cleanup_orphan: bool = True,
) -> bool:
    """
    True si el PDF no debe registrarse como pendiente (ya firmado en BD o copia en destino).
    Si cleanup_orphan, intenta borrar el PDF huérfano de la bandeja.
    """
    from core.database import SessionLocal
    from services import apartados as apartados_svc
    from services import comprobante_tango_store

    ac = (apartado_codigo or "").strip()
    if not ac:
        return False

    db = SessionLocal()
    try:
        a = apartados_svc.get_by_codigo(db, ac, active_only=False)
        if not a:
            return False

        clave = _resolve_clave(db, a.id, tango_clave, path.name)
        if clave:
            estado = comprobante_tango_store.get_estado(db, a.id, clave)
            if estado == "firmado":
                logger.info(
                    "PENDIENTE_OMITIDO_FIRMADO_BD | archivo=%s | clave=%s | ap=%s",
                    path.name,
                    clave,
                    ac,
                )
                if cleanup_orphan and path_is_pending_inbox(path, a):
                    safe_unlink(path)
                return True

        from services.path_settings import resolve_storage_path

        destino = resolve_storage_path(a.destino_path) if a.destino_path else None
        if destino and pdf_exists_in_destino(destino, path.name):
            logger.info(
                "PENDIENTE_OMITIDO_EN_DESTINO | archivo=%s | ap=%s",
                path.name,
                ac,
            )
            # Solo borrar copia huérfana en bandeja; nunca el PDF archivado en destino.
            if cleanup_orphan and path_is_pending_inbox(path, a):
                safe_unlink(path)
            return True
    finally:
        db.close()
    return False


def firmado_claves_by_apartado_codigo(apartado_codigos: set[str]) -> dict[str, set[str]]:
    """Mapa apartado_codigo -> claves con estado firmado en BD."""
    if not apartado_codigos:
        return {}
    from core.database import SessionLocal
    from services import apartados as apartados_svc
    from services import comprobante_tango_store

    db = SessionLocal()
    try:
        codigo_to_id: dict[str, int] = {}
        for cod in apartado_codigos:
            a = apartados_svc.get_by_codigo(db, cod, active_only=False)
            if a:
                codigo_to_id[cod] = a.id
        if not codigo_to_id:
            return {}
        raw = comprobante_tango_store.firmado_claves_by_apartado_ids(
            db, set(codigo_to_id.values())
        )
        out: dict[str, set[str]] = {}
        id_to_cod = {v: k for k, v in codigo_to_id.items()}
        for aid, claves in raw.items():
            cod = id_to_cod.get(aid)
            if cod and claves:
                out[cod] = claves
        return out
    finally:
        db.close()


def doc_is_firmado_in_db(
    doc: dict,
    firmado_map: dict[str, set[str]],
    destino_by_codigo: dict[str, Path] | None = None,
) -> bool:
    """
    Excluir de pendientes solo si está firmado en BD y la copia existe en destino.
    Si está firmado en BD pero no hay copia en destino, sigue en pendientes para reintentar.
    """
    clave = (doc.get("tango_clave") or "").strip()
    if not clave:
        return False
    ac = (doc.get("apartado_codigo") or "").strip()
    if clave not in firmado_map.get(ac, set()):
        return False
    destino = (destino_by_codigo or {}).get(ac)
    if destino is None:
        from core.database import SessionLocal
        from services import apartados as apartados_svc
        from services.path_settings import resolve_storage_path

        db = SessionLocal()
        try:
            a = apartados_svc.get_by_codigo(db, ac, active_only=False)
            if not a or not a.destino_path:
                return True
            destino = resolve_storage_path(a.destino_path)
        finally:
            db.close()
    nombre = (doc.get("nombre") or Path(doc.get("ruta", "")).name or "").strip()
    if nombre and destino and pdf_exists_in_destino(destino, nombre):
        return True
    return False


def destino_paths_for_codigos(apartado_codigos: set[str]) -> dict[str, Path]:
    """Mapa apartado_codigo -> destino_path resuelto."""
    if not apartado_codigos:
        return {}
    from core.database import SessionLocal
    from services import apartados as apartados_svc
    from services.path_settings import resolve_storage_path

    db = SessionLocal()
    try:
        out: dict[str, Path] = {}
        for cod in apartado_codigos:
            a = apartados_svc.get_by_codigo(db, cod, active_only=False)
            if a and a.destino_path:
                out[cod] = resolve_storage_path(a.destino_path)
        return out
    finally:
        db.close()
