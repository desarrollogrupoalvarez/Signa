"""Sincroniza comprobantes Tango del dia hacia la bandeja del apartado."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

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


def _resolve_pdf_bandeja(
    bandeja_dir: Path, fname: str, fname_previo: str | None
) -> Path | None:
    """PDF existente: nombre canónico, filename en BD o variantes _2, _3."""
    if not fname:
        return None
    canon = bandeja_dir / fname
    if canon.is_file():
        return canon
    if fname_previo:
        prev = bandeja_dir / fname_previo
        if prev.is_file():
            return prev
    stem = Path(fname).stem
    if not bandeja_dir.is_dir():
        return None
    try:
        for f in sorted(bandeja_dir.glob(f"{stem}*.pdf")):
            if f.is_file():
                return f
    except OSError:
        pass
    return None


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


def _registrar_y_contar(
    path_pdf: Path,
    result: dict[str, Any],
    *,
    apartado: "Apartado",
    clave: str,
    tango_fecha: date | None,
    tango_usr: str | None,
    fuente: str,
) -> bool:
    ok = documents.register(
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
    name = path_pdf.name
    if ok:
        result["registrados"].append(name)
    else:
        result["omitidos_sin_registro"].append(name)
        logger.info(
            "SYNC_SIN_REGISTRO | archivo=%s | clave=%s | ap=%s",
            name,
            clave,
            apartado.codigo,
        )
    return ok


def _procesar_grupo(
    db: "Session",
    apartado: "Apartado",
    clave: str,
    grp: list[dict[str, Any]],
    bandeja_dir: Path,
    bandeja_root: Path,
    fuente: str,
    result: dict[str, Any],
    *,
    filename_fn: Callable[[dict], str],
    map_fn: Callable[[list[dict[str, Any]]], dict[str, Any]],
    generar_fn: Callable[[dict, Path, dict], Path],
) -> None:
    h = grp[0]
    estado, fname_previo = comprobante_tango_store.get_estado_y_filename(
        db, apartado.id, clave
    )
    if estado == "firmado":
        result["omitidos_ya_firmados"].append(clave)
        return

    fname = filename_fn(h)
    datos = map_fn(grp)
    tango_usr = str(h.get("USUARIO") or "").strip().upper() or None
    tango_fecha = _parse_fecha_row(h)

    if fname_previo and fname_previo != fname:
        _eliminar_pdf_previo(bandeja_dir, fname_previo)

    viejos = mapper.purge_old_format_files(bandeja_dir, fname, h)
    for v in viejos:
        documents.remove_by_path(bandeja_dir / v)
        logger.info("PURGE_VIEJO | %s | %s", fuente, v)

    existing = _resolve_pdf_bandeja(bandeja_dir, fname, fname_previo)
    if existing:
        result["omitidos_en_bandeja"].append(existing.name)
        comprobante_tango_store.upsert_pendiente(
            db, apartado.id, clave, existing.name, tango_fecha
        )
        _registrar_y_contar(
            existing,
            result,
            apartado=apartado,
            clave=clave,
            tango_fecha=tango_fecha,
            tango_usr=tango_usr,
            fuente=fuente,
        )
        return

    documents.remove_pending_by_tango_clave(clave, bandeja_root, delete_file=False)

    try:
        out = generar_fn(datos, bandeja_dir, h)
        comprobante_tango_store.upsert_pendiente(
            db, apartado.id, clave, out.name, tango_fecha
        )
        result["generados"].append(out.name)
        result["generados_por_fuente"].setdefault(fuente, []).append(out.name)
        _registrar_y_contar(
            out,
            result,
            apartado=apartado,
            clave=clave,
            tango_fecha=tango_fecha,
            tango_usr=tango_usr,
            fuente=fuente,
        )
    except Exception as ex:
        logger.exception("sync_apartado gen %s [%s]: %s", clave, fuente, ex)
        result["errores"].append(f"{fuente}/{clave}: {ex}")


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
        _procesar_grupo(
            db,
            apartado,
            clave,
            grp,
            bandeja_dir,
            bandeja_root,
            fuente,
            result,
            filename_fn=mapper.filename_transferencia,
            map_fn=mapper.map_transferencia_group,
            generar_fn=mapper.generar_pdf_transferencia,
        )


def _procesar_grupos_ingreso(
    db: "Session",
    apartado: "Apartado",
    groups: dict[str, list[dict[str, Any]]],
    bandeja_dir: Path,
    bandeja_root: Path,
    fuente: str,
    result: dict[str, Any],
) -> None:
    for clave, grp in groups.items():
        _procesar_grupo(
            db,
            apartado,
            clave,
            grp,
            bandeja_dir,
            bandeja_root,
            fuente,
            result,
            filename_fn=mapper.filename_ingreso,
            map_fn=mapper.map_ingreso_group,
            generar_fn=mapper.generar_pdf_ingreso,
        )


def _log_sync_resumen(apartado: "Apartado", fecha: date, result: dict[str, Any]) -> None:
    """Resumen estructurado para diagnosticar desvíos toast vs lista (p. ej. 9 vs 7)."""
    logger.info(
        "sync_tango_resumen | apartado=%s | fecha=%s | usuarios=%s | "
        "comprobantes_detectados=%d | generados=%d | registrados=%d | "
        "omitidos_bandeja=%d | omitidos_sin_registro=%d | omitidos_firmados=%d | errores=%d",
        apartado.codigo,
        fecha.isoformat(),
        ",".join(result.get("usuarios_consultados") or []),
        result.get("comprobantes_detectados", 0),
        len(result.get("generados") or []),
        len(result.get("registrados") or []),
        len(result.get("omitidos_en_bandeja") or []),
        len(result.get("omitidos_sin_registro") or []),
        len(result.get("omitidos_ya_firmados") or []),
        len(result.get("errores") or []),
    )
    sin_reg = result.get("omitidos_sin_registro") or []
    if sin_reg:
        logger.warning(
            "sync_tango_sin_registro | apartado=%s | archivos=%s",
            apartado.codigo,
            ",".join(sin_reg[:20]),
        )


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
        "registrados": [],
        "omitidos_en_bandeja": [],
        "omitidos_sin_registro": [],
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

    _log_sync_resumen(apartado, fecha, result)
    return result
