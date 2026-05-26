"""Sincroniza comprobantes Tango del dia hacia la bandeja del apartado."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import Config
from services import comprobante_tango_store, documents, tango_comprobante_mapper as mapper
from services import tango_queries
from services.apartado_paths import bandeja_sin_firmar, parse_depositos
from services.apartados import tango_usernames_for_apartado

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from models.apartado import Apartado

logger = logging.getLogger("remitos")


def _parse_fecha_row(row: dict) -> date | None:
    v = row.get("Fecha")
    if isinstance(v, date):
        return v
    try:
        from datetime import datetime

        if isinstance(v, datetime):
            return v.date()
        s = str(v).strip()[:10]
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _pdf_en_bandeja(bandeja_dir: Path, filename: str) -> bool:
    if not filename:
        return False
    return (bandeja_dir / filename).is_file()


def _eliminar_pdf_previo(bandeja_dir: Path, pdf_filename_previo: str | None) -> None:
    if not pdf_filename_previo:
        return
    old_path = bandeja_dir / pdf_filename_previo
    try:
        if old_path.is_file():
            old_path.unlink()
            logger.info("PDF_VIEJO_ELIMINADO | archivo=%s", pdf_filename_previo)
    except OSError as ex:
        logger.warning("No se pudo eliminar PDF previo %s: %s", pdf_filename_previo, ex)
    documents.remove_by_path(old_path)


def _procesar_grupos_transferencia(
    db: "Session",
    apartado: "Apartado",
    groups: dict[str, list[dict[str, Any]]],
    bandeja_dir: Path,
    bandeja_root: Path,
    fuente: str,
    result: dict[str, Any],
) -> None:

    for clave, grp in groups.items():
        h = grp[0]
        estado, fname_previo = comprobante_tango_store.get_estado_y_filename(
            db, apartado.id, clave
        )
        if estado == "firmado":
            result["omitidos_ya_firmados"].append(clave)
            continue

        fname = mapper.filename_transferencia(h)
        datos = mapper.map_transferencia_group(grp)
        tango_usr = str(h.get("USUARIO") or "").strip().upper() or None

        if fname_previo and fname_previo != fname:
            _eliminar_pdf_previo(bandeja_dir, fname_previo)

        documents.remove_pending_by_tango_clave(clave, bandeja_root)

        viejos = mapper.purge_old_format_files(bandeja_dir, fname, h)
        for v in viejos:
            documents.remove_by_path(bandeja_dir / v)
            logger.info("PURGE_VIEJO | %s | %s", fuente, v)

        if _pdf_en_bandeja(bandeja_dir, fname):
            result["omitidos_en_bandeja"].append(fname)
            tango_fecha = _parse_fecha_row(h)
            comprobante_tango_store.upsert_pendiente(db, apartado.id, clave, fname, tango_fecha)
            path_pdf = bandeja_dir / fname
            documents.register(
                path_pdf,
                silent=True,
                apartado_codigo=apartado.codigo,
                modo_flujo=apartado.modo_flujo,
                prefijo=apartado.prefijo,
                tango_clave=clave,
                tango_fecha=tango_fecha.isoformat() if tango_fecha else None,
                tango_usuario=tango_usr,
                tango_fuente=fuente,
                origen="tango",
            )
            continue

        try:
            out = mapper.generar_pdf_transferencia(datos, bandeja_dir, h)
            tango_fecha = _parse_fecha_row(h)
            comprobante_tango_store.upsert_pendiente(
                db, apartado.id, clave, out.name, tango_fecha
            )
            documents.register(
                out,
                silent=True,
                apartado_codigo=apartado.codigo,
                modo_flujo=apartado.modo_flujo,
                prefijo=apartado.prefijo,
                tango_clave=clave,
                tango_fecha=tango_fecha.isoformat() if tango_fecha else None,
                tango_usuario=tango_usr,
                tango_fuente=fuente,
                origen="tango",
            )
            result["generados"].append(out.name)
            result["generados_por_fuente"].setdefault(fuente, []).append(out.name)
        except Exception as ex:
            logger.exception("sync_apartado gen %s [%s]: %s", clave, fuente, ex)
            result["errores"].append(f"{fuente}/{clave}: {ex}")


def _procesar_grupos_ingreso(
    db: "Session",
    apartado: "Apartado",
    groups: dict[str, list[dict[str, Any]]],
    bandeja_dir: Path,
    bandeja_root: Path,
    fuente: str,
    result: dict[str, Any],
) -> None:
    bandeja = bandeja_dir

    for clave, grp in groups.items():
        h = grp[0]
        estado, fname_previo = comprobante_tango_store.get_estado_y_filename(
            db, apartado.id, clave
        )
        if estado == "firmado":
            result["omitidos_ya_firmados"].append(clave)
            continue

        fname = mapper.filename_ingreso(h)
        datos = mapper.map_ingreso_group(grp)
        tango_usr = str(h.get("USUARIO") or "").strip().upper() or None

        if fname_previo and fname_previo != fname:
            _eliminar_pdf_previo(bandeja, fname_previo)

        documents.remove_pending_by_tango_clave(clave, bandeja_root)

        viejos = mapper.purge_old_format_files(bandeja, fname, h)
        for v in viejos:
            documents.remove_by_path(bandeja / v)
            logger.info("PURGE_VIEJO | %s | %s", fuente, v)

        if _pdf_en_bandeja(bandeja, fname):
            result["omitidos_en_bandeja"].append(fname)
            tango_fecha = _parse_fecha_row(h)
            comprobante_tango_store.upsert_pendiente(db, apartado.id, clave, fname, tango_fecha)
            documents.register(
                bandeja / fname,
                silent=True,
                apartado_codigo=apartado.codigo,
                modo_flujo=apartado.modo_flujo,
                prefijo=apartado.prefijo,
                tango_clave=clave,
                tango_fecha=tango_fecha.isoformat() if tango_fecha else None,
                tango_usuario=tango_usr,
                tango_fuente=fuente,
                origen="tango",
            )
            continue

        try:
            out = mapper.generar_pdf_ingreso(datos, bandeja, h)
            tango_fecha = _parse_fecha_row(h)
            comprobante_tango_store.upsert_pendiente(db, apartado.id, clave, out.name, tango_fecha)
            documents.register(
                out,
                silent=True,
                apartado_codigo=apartado.codigo,
                modo_flujo=apartado.modo_flujo,
                prefijo=apartado.prefijo,
                tango_clave=clave,
                tango_fecha=tango_fecha.isoformat() if tango_fecha else None,
                tango_usuario=tango_usr,
                tango_fuente=fuente,
                origen="tango",
            )
            result["generados"].append(out.name)
            result["generados_por_fuente"].setdefault(fuente, []).append(out.name)
        except Exception as ex:
            logger.exception("sync_apartado gen %s [%s]: %s", clave, fuente, ex)
            result["errores"].append(f"{fuente}/{clave}: {ex}")


def sync_apartado(
    db: "Session",
    apartado: "Apartado",
    fecha: date,
    *,
    solicitante_username: str | None = None,
    solicitante_es_superadmin: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "generados": [],
        "omitidos_en_bandeja": [],
        "omitidos_ya_firmados": [],
        "errores": [],
        "usuarios_consultados": [],
        "filas_tango": 0,
        "comprobantes_detectados": 0,
        "generados_por_fuente": {},
        "filas_tango_por_fuente": {},
        "comprobantes_por_fuente": {},
    }
    if not Config.tango_configured():
        result["errores"].append("Tango no configurado en el servidor")
        return result

    depositos = parse_depositos(apartado)
    if not depositos:
        result["errores"].append("Apartado sin depósitos configurados")
        return result

    if solicitante_es_superadmin:
        usuarios = tango_usernames_for_apartado(db, apartado)
    else:
        un = (solicitante_username or "").strip().upper()
        if not un:
            result["errores"].append("Usuario solicitante sin nombre de usuario Tango")
            return result
        usuarios = [un]
    result["usuarios_consultados"] = usuarios
    if not usuarios:
        result["errores"].append("Sin usuarios activos asignados al apartado")
        return result

    bandeja = Path(apartado.bandeja_path)
    bandeja.mkdir(parents=True, exist_ok=True)
    modo = apartado.modo_flujo

    if modo == "transferencia":
        total_filas = 0
        total_comps = 0
        for dep in depositos:
            src = Config.tango_source_by_id(dep.tango_fuente)
            if not src:
                result["errores"].append(
                    f"{dep.carpeta}: base Tango no configurada ({dep.tango_fuente})"
                )
                continue
            deps_cods = list(dep.cod_depositos)
            try:
                rows = tango_queries.fetch_transferencias(
                    deps_cods,
                    usuarios,
                    fecha,
                    database=src.database,
                    tango_fuente=src.id,
                )
            except Exception as ex:
                logger.exception("sync_apartado query [%s]: %s", src.id, ex)
                result["errores"].append(f"{src.id}: {ex}")
                continue

            groups = mapper.group_transferencias(rows)
            result["filas_tango_por_fuente"][src.id] = len(rows)
            result["comprobantes_por_fuente"][src.id] = len(groups)
            total_filas += len(rows)
            total_comps += len(groups)

            logger.info(
                "sync_tango | apartado=%s | deposito=%s | fuente=%s | fecha=%s | filas=%d | comprobantes=%d",
                apartado.codigo,
                dep.carpeta,
                src.id,
                fecha.isoformat(),
                len(rows),
                len(groups),
            )
            bandeja_dir = bandeja_sin_firmar(bandeja, dep.carpeta)
            _procesar_grupos_transferencia(
                db, apartado, groups, bandeja_dir, bandeja, src.id, result
            )

        result["filas_tango"] = total_filas
        result["comprobantes_detectados"] = total_comps

    elif modo == "ingreso":
        total_filas = 0
        total_comps = 0
        for dep in depositos:
            src = Config.tango_source_by_id(dep.tango_fuente)
            if not src:
                result["errores"].append(
                    f"{dep.carpeta}: base Tango no configurada ({dep.tango_fuente})"
                )
                continue
            deps_cods = list(dep.cod_depositos)
            try:
                rows = tango_queries.fetch_ingresos(
                    deps_cods,
                    usuarios,
                    fecha,
                    database=src.database,
                    tango_fuente=src.id,
                )
            except Exception as ex:
                logger.exception("sync_apartado ingreso query [%s]: %s", src.id, ex)
                result["errores"].append(f"{src.id}: {ex}")
                continue

            groups = mapper.group_ingresos(rows)
            result["filas_tango_por_fuente"][src.id] = len(rows)
            result["comprobantes_por_fuente"][src.id] = len(groups)
            total_filas += len(rows)
            total_comps += len(groups)

            logger.info(
                "sync_tango ingreso | apartado=%s | deposito=%s | fuente=%s | fecha=%s | filas=%d | comprobantes=%d",
                apartado.codigo,
                dep.carpeta,
                src.id,
                fecha.isoformat(),
                len(rows),
                len(groups),
            )
            bandeja_dir = bandeja_sin_firmar(bandeja, dep.carpeta)
            _procesar_grupos_ingreso(db, apartado, groups, bandeja_dir, bandeja, src.id, result)

        result["filas_tango"] = total_filas
        result["comprobantes_detectados"] = total_comps
    else:
        result["errores"].append(f"modo_flujo no soportado: {modo}")
        return result

    try:
        db.commit()
    except Exception as ex:
        db.rollback()
        result["errores"].append(f"commit: {ex}")
    return result
