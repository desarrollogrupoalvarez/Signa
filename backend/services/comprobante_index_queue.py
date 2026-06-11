"""Cola única de indexación de texto en comprobante_tango (un worker, commit por trabajo)."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger("remitos")

_BATCH_ENCOLAR = 35
_INDICE_TTL = 45.0

_pending_ids: set[int] = set()
_pending_lock = threading.Lock()
_job_queue: queue.Queue = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()
_stop = threading.Event()
_indice_cache: dict[int, tuple[float, object]] = {}
_indice_cache_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class _IndexJob:
    kind: str
    comprobante_id: int | None = None
    apartado_id: int | None = None
    path: str | None = None
    apartado_codigo: str | None = None
    tango_clave: str | None = None
    tango_fecha: str | None = None


def start_index_worker() -> None:
    """Arranca el worker de indexación (idempotente)."""
    _ensure_worker()


def stop_index_worker() -> None:
    _stop.set()


def enqueue_comprobante(comprobante_id: int, *, apartado_id: int | None = None) -> bool:
    cid = int(comprobante_id)
    with _pending_lock:
        if cid in _pending_ids:
            return False
        _pending_ids.add(cid)
    _ensure_worker()
    _job_queue.put(
        _IndexJob(
            kind="comprobante_id",
            comprobante_id=cid,
            apartado_id=apartado_id,
        )
    )
    return True


def enqueue_pdf_bandeja(
    path: Path | str,
    apartado_codigo: str,
    *,
    tango_clave: str | None = None,
    tango_fecha: str | None = None,
) -> None:
    _ensure_worker()
    _job_queue.put(
        _IndexJob(
            kind="pdf",
            path=str(path),
            apartado_codigo=(apartado_codigo or "").strip(),
            tango_clave=(tango_clave or "").strip() or None,
            tango_fecha=(tango_fecha or "").strip()[:10] or None,
        )
    )


def encolar_pendientes_sin_texto(
    db: "Session",
    apartados: list,
    *,
    filter_fecha: str | None = None,
    limit: int = _BATCH_ENCOLAR,
) -> int:
    """Encola filas pendientes sin texto (no indexa en el request HTTP)."""
    from datetime import date as date_cls

    from models.comprobante_tango import ComprobanteTango
    from sqlalchemy import func, or_

    if not apartados:
        return 0

    apartado_ids = [int(a.id) for a in apartados]
    want_fecha = (filter_fecha or "").strip()[:10] or None

    q = (
        db.query(ComprobanteTango.id, ComprobanteTango.apartado_id)
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
    for row_id, apartado_id in rows:
        if enqueue_comprobante(int(row_id), apartado_id=int(apartado_id)):
            n += 1
    if n:
        logger.debug("INDEX_QUEUE_ENCOLADOS | n=%d", n)
    return n


def encolar_pendientes_apartado(
    apartado_id: int,
    *,
    filter_fecha: str | None = None,
    limit: int = _BATCH_ENCOLAR,
) -> int:
    from core.database import db_session
    from models.apartado import Apartado

    with db_session() as db:
        apartado = db.get(Apartado, int(apartado_id))
        if not apartado:
            return 0
        return encolar_pendientes_sin_texto(
            db,
            [apartado],
            filter_fecha=filter_fecha,
            limit=limit,
        )


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        th = threading.Thread(target=_worker_loop, name="index-comprobante-queue", daemon=True)
        th.start()
        logger.info("Worker de indexación de comprobantes iniciado")


def _indice_pendientes(apartado) -> object:
    from services.comprobante_text_index import IndiceRutasApartado

    aid = int(apartado.id)
    now = time.monotonic()
    with _indice_cache_lock:
        hit = _indice_cache.get(aid)
        if hit and (now - hit[0]) < _INDICE_TTL:
            return hit[1]
    idx = IndiceRutasApartado.build(apartado, solo_pendientes=True)
    with _indice_cache_lock:
        _indice_cache[aid] = (now, idx)
    return idx


def invalidate_indice_cache(apartado_id: int | None = None) -> None:
    with _indice_cache_lock:
        if apartado_id is None:
            _indice_cache.clear()
        else:
            _indice_cache.pop(int(apartado_id), None)


def _worker_loop() -> None:
    while not _stop.is_set():
        try:
            job = _job_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            _process_job(job)
        except Exception as ex:
            logger.warning("INDEX_QUEUE_ERROR | kind=%s | %s", job.kind, ex)
        finally:
            if job.kind == "comprobante_id" and job.comprobante_id is not None:
                with _pending_lock:
                    _pending_ids.discard(int(job.comprobante_id))
            _job_queue.task_done()


def _process_job(job: _IndexJob) -> None:
    from core.database import db_session
    from models.apartado import Apartado
    from models.comprobante_tango import ComprobanteTango
    from services.comprobante_text_index import fila_sin_texto_indexado, indexar_comprobante_por_fila

    with db_session() as db:
        if job.kind == "comprobante_id":
            row = db.get(ComprobanteTango, int(job.comprobante_id))
            if not row or row.estado != "pendiente" or not fila_sin_texto_indexado(row):
                return
            apartado = db.get(Apartado, int(row.apartado_id))
            if not apartado:
                return
            idx = _indice_pendientes(apartado)
            if indexar_comprobante_por_fila(db, row, apartado, indice=idx):
                logger.info("INDEX_QUEUE_OK | id=%s | archivo=%s", row.id, row.pdf_filename)
            return

        if job.kind != "pdf" or not job.path or not job.apartado_codigo:
            return

        from services import apartados as apartados_svc

        path = Path(job.path)
        apartado = apartados_svc.get_by_codigo(db, job.apartado_codigo, active_only=False)
        if not apartado:
            return

        row = (
            db.query(ComprobanteTango)
            .filter(
                ComprobanteTango.apartado_id == apartado.id,
                ComprobanteTango.pdf_filename == path.name,
                ComprobanteTango.estado == "pendiente",
            )
            .first()
        )
        if not row and job.tango_clave:
            row = (
                db.query(ComprobanteTango)
                .filter(
                    ComprobanteTango.apartado_id == apartado.id,
                    ComprobanteTango.clave == job.tango_clave,
                )
                .first()
            )
        if row and not fila_sin_texto_indexado(row):
            return
        if not row:
            from datetime import date as date_cls

            from services import comprobante_tango_store

            fecha = None
            if job.tango_fecha:
                try:
                    fecha = date_cls.fromisoformat(job.tango_fecha)
                except ValueError:
                    fecha = None
            row = comprobante_tango_store.upsert_pendiente_bandeja(
                db,
                apartado.id,
                path.name,
                tango_clave=job.tango_clave,
                tango_fecha=fecha,
            )
        if not fila_sin_texto_indexado(row):
            return
        idx = _indice_pendientes(apartado)
        if indexar_comprobante_por_fila(db, row, apartado, indice=idx):
            logger.info("INDEX_QUEUE_OK | id=%s | archivo=%s", row.id, path.name)
