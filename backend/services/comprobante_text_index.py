"""Indexación de texto extraído de PDFs en comprobante_tango."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pdf_extractor import extraer_texto_pdf
from services.apartado_paths import SIN_FIRMAR, bandeja_sin_firmar, parse_depositos
from services.path_settings import resolve_storage_path

if TYPE_CHECKING:
    from models.apartado import Apartado
    from models.comprobante_tango import ComprobanteTango
    from sqlalchemy.orm import Session

logger = logging.getLogger("remitos")

_SKIP_DIR_NAMES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})


def _is_unc_path(path: Path | str) -> bool:
    s = str(path).replace("/", "\\")
    return s.startswith("\\\\")


def normalizar_ruta(path: str | Path) -> str:
    raw = str(path).strip()
    if _is_unc_path(raw):
        return os.path.normpath(raw)
    try:
        return os.path.normpath(str(Path(path).expanduser().resolve()))
    except OSError:
        return os.path.normpath(raw)


def _escanear_pdfs_en_arbol(
    root: Path,
    *,
    incluir: str = "todos",
) -> dict[str, str]:
    """
    Un solo recorrido del árbol. Retorna mapa nombre_archivo -> ruta absoluta normalizada.
    incluir: 'firmados' (fuera de Sin Firmar), 'pendientes' (solo bajo Sin Firmar), 'todos'
    """
    out: dict[str, str] = {}
    try:
        if not root.is_dir():
            return out
    except OSError:
        return out

    sin_firmar = SIN_FIRMAR.upper()
    if _is_unc_path(root):
        root_res = Path(os.path.normpath(str(root)))
    else:
        try:
            root_res = root.resolve()
        except OSError:
            return out

    def _aceptar(rel_parts: tuple[str, ...]) -> bool:
        en_sin_firmar = any(p.upper() == sin_firmar for p in rel_parts)
        if incluir == "firmados":
            return not en_sin_firmar
        if incluir == "pendientes":
            return en_sin_firmar
        return True

    def _walk(base: Path, rel_parts: tuple[str, ...]) -> None:
        try:
            with os.scandir(base) as it:
                for entry in it:
                    name = entry.name
                    if name.startswith("~$") or name.lower() in _SKIP_DIR_NAMES:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if name.upper() == sin_firmar and incluir == "firmados":
                            continue
                        _walk(Path(entry.path), rel_parts + (name,))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if not name.lower().endswith(".pdf"):
                        continue
                    if not _aceptar(rel_parts):
                        continue
                    if name not in out:
                        try:
                            out[name] = normalizar_ruta(entry.path)
                        except OSError:
                            pass
        except OSError as ex:
            logger.warning("ESCANEAR_PDFS | root=%s | %s", base, ex)

    _walk(root_res, ())
    return out


@dataclass
class IndiceRutasApartado:
    """Índice nombre PDF -> ruta absoluta (un escaneo por carpeta, sin rglob por fila)."""

    firmados: dict[str, str] = field(default_factory=dict)
    pendientes: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        apartado: "Apartado",
        *,
        solo_pendientes: bool = False,
    ) -> "IndiceRutasApartado":
        destino = resolve_storage_path(getattr(apartado, "destino_path", None))
        bandeja = resolve_storage_path(getattr(apartado, "bandeja_path", None))
        firmados: dict[str, str] = {}
        if not solo_pendientes and destino:
            firmados = _escanear_pdfs_en_arbol(destino, incluir="firmados")

        pendientes: dict[str, str] = {}
        try:
            bandeja_ok = bandeja.is_dir()
        except OSError:
            bandeja_ok = False
        if bandeja_ok:
            if bandeja.name.upper() == SIN_FIRMAR.upper():
                pendientes = _escanear_pdfs_en_arbol(bandeja, incluir="todos")
            else:
                pendientes = _escanear_pdfs_en_arbol(bandeja, incluir="pendientes")
                deps = parse_depositos(apartado)
                for dep in deps:
                    inbox = bandeja_sin_firmar(bandeja, dep.carpeta)
                    if inbox.is_dir():
                        try:
                            with os.scandir(inbox) as it:
                                for entry in it:
                                    if not entry.is_file(follow_symlinks=False):
                                        continue
                                    if not entry.name.lower().endswith(".pdf"):
                                        continue
                                    if entry.name not in pendientes:
                                        try:
                                            pendientes[entry.name] = normalizar_ruta(entry.path)
                                        except OSError:
                                            pass
                        except OSError:
                            pass

        return cls(firmados=firmados, pendientes=pendientes)

    def lookup(self, pdf_filename: str, estado: str) -> str | None:
        name = (pdf_filename or "").strip()
        if not name:
            return None
        if (estado or "").strip().lower() == "firmado":
            return self.firmados.get(name)
        return self.pendientes.get(name)


def nombre_ui_firmado(apartado: "Apartado", ruta_abs: str | Path) -> str:
    """Nombre prefijo/relativo para UI sin .resolve() en rutas UNC."""
    prefijo = (getattr(apartado, "prefijo", None) or "x").strip()[:8]
    dest_norm = os.path.normpath((getattr(apartado, "destino_path", None) or "").strip()).lower()
    stored_norm = os.path.normpath(str(ruta_abs))
    if dest_norm and stored_norm.lower().startswith(dest_norm):
        rel = stored_norm[len(dest_norm) :].lstrip("\\/")
        if rel:
            return f"{prefijo}/" + rel.replace("\\", "/")
    return f"{prefijo}/{Path(ruta_abs).name}"


def ruta_firmado_desde_bd(
    db: "Session",
    apartado_id: int,
    pdf_filename: str,
) -> Path | None:
    """Ruta absoluta del PDF firmado si está guardada en comprobante_tango."""
    from models.comprobante_tango import ComprobanteTango

    name = (pdf_filename or "").strip()
    if not name:
        return None
    row = (
        db.query(ComprobanteTango)
        .filter(
            ComprobanteTango.apartado_id == apartado_id,
            ComprobanteTango.pdf_filename == name,
            ComprobanteTango.estado == "firmado",
        )
        .order_by(ComprobanteTango.updated_at.desc())
        .first()
    )
    if not row or not (row.ruta or "").strip():
        return None
    p = Path(row.ruta.strip())
    try:
        return p if p.is_file() else None
    except OSError:
        return None


def resolver_ruta_comprobante(
    apartado: "Apartado",
    pdf_filename: str,
    estado: str,
    *,
    ruta_guardada: str | None = None,
    indice: IndiceRutasApartado | None = None,
) -> Path | None:
    """Resuelve la ruta absoluta del PDF según apartado, nombre y estado."""
    estado_norm = (estado or "").strip().lower()
    stored = (ruta_guardada or "").strip()
    if stored and estado_norm == "firmado":
        p = Path(stored)
        try:
            if p.is_file():
                return p
        except OSError:
            pass

    name = (pdf_filename or "").strip()
    if not name:
        return None

    if indice is not None:
        hit = indice.lookup(name, estado)
        if hit:
            return Path(hit)

    if (estado or "").strip().lower() == "firmado":
        destino = resolve_storage_path(getattr(apartado, "destino_path", None))
        if not destino.is_dir():
            return None
        try:
            for p in destino.rglob(name):
                if not p.is_file():
                    continue
                try:
                    rel = p.relative_to(destino.resolve())
                except (ValueError, OSError):
                    continue
                if any(part.upper() == SIN_FIRMAR.upper() for part in rel.parts):
                    continue
                return p
        except OSError as ex:
            logger.warning("RESOLVER_RUTA_FIRMADO | apartado=%s | %s", apartado.codigo, ex)
        return None

    bandeja = resolve_storage_path(getattr(apartado, "bandeja_path", None))
    if not bandeja.is_dir():
        return None

    candidatos: list[Path] = []
    if bandeja.name.upper() == SIN_FIRMAR.upper():
        p = bandeja / name
        if p.is_file():
            return p
        return None

    deps = parse_depositos(apartado)
    if deps:
        for dep in deps:
            inbox = bandeja_sin_firmar(bandeja, dep.carpeta)
            p = inbox / name
            if p.is_file():
                candidatos.append(p)
    else:
        p = bandeja / SIN_FIRMAR / name
        if p.is_file():
            candidatos.append(p)

    if candidatos:
        return candidatos[0]

    try:
        for p in bandeja.rglob(name):
            if p.is_file() and SIN_FIRMAR.upper() in {
                part.upper() for part in p.relative_to(bandeja).parts
            }:
                return p
    except OSError:
        pass
    return None


def guardar_indexacion(
    db: "Session",
    comprobante_id: int,
    *,
    texto: str | None = None,
    ruta: str | Path | None = None,
    apartado_id: int | None = None,
) -> bool:
    from models.comprobante_tango import ComprobanteTango

    q = db.query(ComprobanteTango).filter(ComprobanteTango.id == comprobante_id)
    if apartado_id is not None:
        q = q.filter(ComprobanteTango.apartado_id == apartado_id)
    row = q.first()
    if not row:
        return False
    if texto is not None:
        row.texto_contenido = texto or None
    estado = (row.estado or "").strip().lower()
    if estado == "pendiente":
        row.ruta = None
    elif ruta is not None:
        row.ruta = normalizar_ruta(ruta)
    db.flush()
    return True


def update_texto_contenido(
    db: "Session",
    comprobante_id: int,
    texto: str,
    *,
    apartado_id: int | None = None,
    ruta: str | Path | None = None,
) -> bool:
    return guardar_indexacion(
        db,
        comprobante_id,
        texto=texto,
        ruta=ruta,
        apartado_id=apartado_id,
    )


def persistir_texto_comprobante(
    ruta: str | Path,
    comprobante_id: int | None = None,
    *,
    apartado_id: int | None = None,
) -> bool:
    """
    Extrae texto del PDF y lo guarda en comprobante_tango (solo texto en pendiente).
    La ruta absoluta se persiste únicamente al firmar (estado firmado).
    No lanza excepción; retorna False si no pudo persistir.
    """
    path = Path(ruta)
    texto = extraer_texto_pdf(str(path))
    if not texto.strip():
        logger.debug("INDEX_TEXTO_VACIO | ruta=%s | id=%s", path, comprobante_id)
        return False
    try:
        from core.database import db_session
        from models.comprobante_tango import ComprobanteTango

        with db_session() as db:
            if comprobante_id is not None:
                existing = db.get(ComprobanteTango, int(comprobante_id))
                if existing and (existing.texto_contenido or "").strip():
                    return True
                ok = guardar_indexacion(
                    db,
                    comprobante_id,
                    texto=texto,
                    apartado_id=apartado_id,
                )
                if ok:
                    logger.info(
                        "INDEX_TEXTO_OK | id=%s | chars=%d",
                        comprobante_id,
                        len(texto),
                    )
                return ok

            q = db.query(ComprobanteTango).filter(
                ComprobanteTango.pdf_filename == path.name,
                ComprobanteTango.estado == "pendiente",
            )
            if apartado_id is not None:
                q = q.filter(ComprobanteTango.apartado_id == apartado_id)
            row = q.first()
            if not row:
                logger.debug("INDEX_TEXTO_SIN_FILA | ruta=%s", path.name)
                return False
            row.texto_contenido = texto
            row.ruta = None
            db.flush()
            logger.info(
                "INDEX_TEXTO_OK | id=%s | chars=%d",
                row.id,
                len(texto),
            )
            return True
    except Exception as ex:
        logger.warning("INDEX_TEXTO_ERROR | ruta=%s | id=%s | %s", path, comprobante_id, ex)
        return False


_INDEX_PENDIENTES_BATCH = 35


def fila_sin_texto_indexado(row: "ComprobanteTango") -> bool:
    return not (getattr(row, "texto_contenido", None) or "").strip()


def indexar_pendientes_sin_texto(
    db: "Session",
    apartados: list,
    *,
    indices: dict[int, IndiceRutasApartado] | None = None,
    filter_fecha: str | None = None,
    limit: int = _INDEX_PENDIENTES_BATCH,
) -> int:
    """
    Indexa texto solo en filas pendientes sin texto_contenido (p. ej. al refrescar lista).
    Procesa como máximo `limit` filas por llamada para no bloquear el request.
    """
    from datetime import date as date_cls

    from models.comprobante_tango import ComprobanteTango
    from sqlalchemy import func, or_

    if not apartados:
        return 0

    apartado_ids = [int(a.id) for a in apartados]
    apartado_map = {int(a.id): a for a in apartados}
    want_fecha = (filter_fecha or "").strip()[:10] or None

    q = (
        db.query(ComprobanteTango)
        .filter(
            ComprobanteTango.estado == "pendiente",
            ComprobanteTango.apartado_id.in_(apartado_ids),
            or_(
                ComprobanteTango.texto_contenido.is_(None),
                func.trim(ComprobanteTango.texto_contenido) == "",
            ),
        )
        .order_by(ComprobanteTango.updated_at.desc().nulls_last(), ComprobanteTango.id.desc())
    )
    if want_fecha:
        try:
            d = date_cls.fromisoformat(want_fecha)
            q = q.filter(ComprobanteTango.tango_fecha == d)
        except ValueError:
            pass

    rows = q.limit(max(1, int(limit))).all()
    n = 0
    for row in rows:
        if not fila_sin_texto_indexado(row):
            continue
        apartado = apartado_map.get(int(row.apartado_id))
        if not apartado:
            continue
        idx = indices.get(int(apartado.id)) if indices else None
        if indexar_comprobante_por_fila(db, row, apartado, indice=idx):
            n += 1
    return n


def indexar_comprobante_por_fila(
    db: "Session",
    row: "ComprobanteTango",
    apartado: "Apartado",
    *,
    solo_ruta: bool = False,
    indice: IndiceRutasApartado | None = None,
) -> bool:
    """Extrae y persiste texto (pendiente) o ruta+texto (firmado) para una fila."""
    estado = (row.estado or "").strip().lower()
    if estado == "pendiente" and not solo_ruta and not fila_sin_texto_indexado(row):
        return True
    ruta_guardada = row.ruta if estado == "firmado" else None
    ruta = resolver_ruta_comprobante(
        apartado,
        row.pdf_filename,
        row.estado,
        ruta_guardada=ruta_guardada,
        indice=indice,
    )
    if not ruta or not ruta.is_file():
        logger.warning(
            "INDEX_SIN_ARCHIVO | id=%s | archivo=%s | estado=%s",
            row.id,
            row.pdf_filename,
            row.estado,
        )
        return False

    if estado == "pendiente":
        row.ruta = None
        if solo_ruta:
            return False
        texto = extraer_texto_pdf(str(ruta))
        if not texto.strip():
            return False
        row.texto_contenido = texto
        db.flush()
        return True

    ruta_norm = normalizar_ruta(ruta)
    row.ruta = ruta_norm
    if solo_ruta:
        db.flush()
        return True

    texto = extraer_texto_pdf(str(ruta))
    if texto.strip():
        row.texto_contenido = texto
    db.flush()
    return True


def reindexar_comprobante_firmado(
    db: "Session",
    apartado_id: int,
    clave: str,
    *,
    ruta_firmado: str | Path | None = None,
) -> None:
    """Re-indexa el PDF firmado tras marcar estado firmado."""
    from models.apartado import Apartado
    from models.comprobante_tango import ComprobanteTango

    row = (
        db.query(ComprobanteTango)
        .filter(
            ComprobanteTango.apartado_id == apartado_id,
            ComprobanteTango.clave == clave,
        )
        .first()
    )
    if not row:
        return
    apartado = db.query(Apartado).filter(Apartado.id == apartado_id).first()
    if not apartado:
        return

    if ruta_firmado:
        row.ruta = normalizar_ruta(ruta_firmado)
        db.flush()

    try:
        if indexar_comprobante_por_fila(db, row, apartado):
            logger.info(
                "REINDEX_FIRMADO_OK | id=%s | clave=%s | ruta=%s",
                row.id,
                clave,
                row.ruta,
            )
    except Exception as ex:
        logger.warning("REINDEX_FIRMADO_ERROR | clave=%s | %s", clave, ex)
