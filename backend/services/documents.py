"""
In-memory document store + watchers por bandeja de apartados.
"""

import os
import time
import hashlib
import threading
import logging
from datetime import datetime
from pathlib import Path

from services.file_ops import safe_unlink
from services.pending_guard import (
    destino_paths_for_codigos,
    doc_is_firmado_in_db,
    firmado_claves_by_apartado_codigo,
    should_skip_pending_registration,
)
from services.file_search import file_search_matches
from services.tango_comprobante_mapper import parse_meta_from_filename
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

logger = logging.getLogger("remitos")

_store: dict[str, dict] = {}
_lock = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm_path_key(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _doc_id(path: Path) -> str:
    s = _norm_path_key(path)
    return hashlib.md5(s.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _legacy_categoria_to_apart(categoria: str) -> tuple[str, str, str]:
    if categoria == "ingresos":
        return "ingresos", "ingreso", "i"
    return "transferencias", "transferencia", "t"


def _categoria_ui(modo_flujo: str) -> str:
    return "ingresos" if modo_flujo == "ingreso" else "tra"


def _norm_tango_usuario(val: str | None) -> str | None:
    u = (val or "").strip().upper()
    return u or None


def _resolve_tango_meta(
    nombre: str,
    *,
    tango_fecha: str | None = None,
    tango_usuario: str | None = None,
) -> tuple[str | None, str | None]:
    parsed_fecha, parsed_user = parse_meta_from_filename(nombre)
    fecha = (tango_fecha or "").strip()[:10] or parsed_fecha
    usuario = _norm_tango_usuario(tango_usuario) or parsed_user
    return fecha or None, usuario


def enrich_tango_meta(doc: dict) -> None:
    """Completa tango_fecha / tango_usuario en el dict (mutación in-place)."""
    fecha, usuario = _resolve_tango_meta(
        doc.get("nombre") or "",
        tango_fecha=doc.get("tango_fecha"),
        tango_usuario=doc.get("tango_usuario"),
    )
    if fecha:
        doc["tango_fecha"] = fecha
    if usuario:
        doc["tango_usuario"] = usuario


def effective_tango_usuario(doc: dict) -> str | None:
    enrich_tango_meta(doc)
    return doc.get("tango_usuario")


def _patch_pending_tango_fields(
    doc: dict,
    *,
    tango_clave: str | None = None,
    tango_fecha: str | None = None,
    tango_usuario: str | None = None,
    tango_fuente: str | None = None,
    origen: str | None = None,
) -> None:
    fecha, usuario = _resolve_tango_meta(
        doc.get("nombre") or "",
        tango_fecha=tango_fecha or doc.get("tango_fecha"),
        tango_usuario=tango_usuario or doc.get("tango_usuario"),
    )
    if tango_clave:
        doc["tango_clave"] = tango_clave
    if fecha:
        doc["tango_fecha"] = fecha
    if usuario:
        doc["tango_usuario"] = usuario
    if tango_fuente:
        doc["tango_fuente"] = tango_fuente
    if origen:
        doc["origen"] = origen


# ── Public API ────────────────────────────────────────────────────────────────

def register(
    path: Path,
    *,
    silent: bool = False,
    apartado_codigo: str | None = None,
    modo_flujo: str | None = None,
    prefijo: str | None = None,
    categoria: str | None = None,
    tango_clave: str | None = None,
    tango_fecha: str | None = None,
    tango_usuario: str | None = None,
    tango_fuente: str | None = None,
    origen: str | None = None,
) -> bool:
    """
    Registra un PDF. Preferir (apartado_codigo, modo_flujo, prefijo).
    Compat: categoria "tra" | "ingresos" se mapea a apartados predefinidos.
    """
    if path.suffix.lower() != ".pdf":
        return False
    try:
        if not path.is_file():
            return False
    except OSError:
        return False

    if apartado_codigo and modo_flujo is not None and prefijo is not None:
        ac, mf, pr = apartado_codigo.strip(), modo_flujo, (prefijo or "x").strip()
    elif categoria in ("tra", "ingresos", None):
        c = categoria or "tra"
        if c not in ("tra", "ingresos"):
            c = "tra"
        ac, mf, pr = _legacy_categoria_to_apart(c)
    else:
        ac, mf, pr = _legacy_categoria_to_apart("tra")

    if mf not in ("transferencia", "ingreso"):
        ac, mf, pr = _legacy_categoria_to_apart("tra")

    if should_skip_pending_registration(path, ac, tango_clave=tango_clave):
        return False

    fecha_res, usuario_res = _resolve_tango_meta(
        path.name, tango_fecha=tango_fecha, tango_usuario=tango_usuario
    )
    doc_id = _doc_id(path)
    with _lock:
        existing = _store.get(doc_id)
        if existing:
            if existing.get("estado") != "pendiente":
                return False
            _patch_pending_tango_fields(
                existing,
                tango_clave=tango_clave,
                tango_fecha=fecha_res,
                tango_usuario=usuario_res,
                tango_fuente=tango_fuente,
                origen=origen,
            )
            if not silent:
                logger.debug(
                    "DOCUMENTO_ACTUALIZADO | id=%s | archivo=%s | usuario=%s",
                    doc_id,
                    path.name,
                    existing.get("tango_usuario"),
                )
            return True
        try:
            file_hash = _sha256(path)
        except OSError:
            return False
        _store[doc_id] = {
            "id": doc_id,
            "nombre": path.name,
            "ruta": os.path.normpath(str(path)),
            "estado": "pendiente",
            "apartado_codigo": ac,
            "modo_flujo": mf,
            "prefijo": pr,
            "categoria": _categoria_ui(mf),
            "recibido_en": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            "firmado_en": None,
            "dispositivo": None,
            "hash_original": file_hash,
            "tango_clave": (tango_clave or None),
            "tango_fecha": fecha_res,
            "tango_usuario": usuario_res,
            "tango_fuente": (tango_fuente or None),
            "origen": (origen or None),
        }
    cat_log = categoria or ac
    if not silent:
        logger.info("NUEVO_DOCUMENTO | id=%s | archivo=%s | apartado=%s", doc_id, path.name, cat_log)
    return True


def refresh_file_hash(doc_id: str) -> bool:
    with _lock:
        doc = _store.get(doc_id)
        if not doc or doc.get("estado") != "pendiente":
            return False
        r = doc["ruta"]
    try:
        p = Path(r)
        h = _sha256(p)
    except OSError:
        return False
    with _lock:
        d = _store.get(doc_id)
        if d and d.get("estado") == "pendiente":
            d["hash_original"] = h
    return True


def get(doc_id: str) -> dict | None:
    with _lock:
        return _store.get(doc_id)


def mark_signed(
    doc_id: str,
    dispositivo: str,
    ruta_firmado: Path,
    hash_firmado: str,
    archivo_firmado_relativo: str | None = None,
) -> None:
    with _lock:
        doc = _store.get(doc_id)
        if doc:
            doc["estado"] = "firmado"
            doc["firmado_en"] = datetime.now().isoformat()
            doc["dispositivo"] = dispositivo
            doc["hash_firmado"] = hash_firmado
            doc["archivo_firmado"] = ruta_firmado.name
            if archivo_firmado_relativo:
                doc["archivo_firmado_relativo"] = archivo_firmado_relativo


# ── Watchers ─────────────────────────────────────────────────────────────────

_inbox_observers: list = []
_observer_lock = threading.Lock()


def get_bandeja_tuples_for_rescan() -> list[tuple[Path, str, str, str]]:
    from core.database import SessionLocal
    from services import apartados

    db = SessionLocal()
    try:
        from services.path_settings import resolve_storage_path

        rows = apartados.list_active_apartados(db)
        return [
            (resolve_storage_path(a.bandeja_path), a.codigo, a.modo_flujo, a.prefijo)
            for a in rows
        ]
    finally:
        db.close()


def restart_inbox_watcher() -> None:
    b_list = get_bandeja_tuples_for_rescan()
    with _observer_lock:
        for o in _inbox_observers:
            try:
                o.stop()
                o.join(timeout=5)
            except Exception as e:
                logger.warning("Al detener observer: %s", e)
        _inbox_observers.clear()
        if b_list:
            _prune_pendientes_multibandeja(b_list)
        for path_b, ac, mf, pr in b_list:
            if path_b and str(path_b).strip():
                scan_inbox(path_b, apartado_codigo=ac, modo_flujo=mf, prefijo=pr)
            obs = _create_watcher(path_b, apartado_codigo=ac, modo_flujo=mf, prefijo=pr)
            _inbox_observers.append(obs)
    if b_list:
        logger.info("Watchers de bandeja reiniciados (%d apartado(s))", len(b_list))
    else:
        logger.warning("Watchers: no hay apartados activos con bandeja en BD")


def _prune_pendientes_multibandeja(blist: list[tuple[Path, str, str, str]]) -> None:
    with _lock:
        to_remove: list[str] = []
        for did, d in _store.items():
            if d.get("estado") != "pendiente":
                continue
            r = d.get("ruta", "")
            ok = any(
                r and _pendiente_misma_bandeja(r, Path(b0))
                for b0, _, _, _ in blist
            )
            if not ok:
                to_remove.append(did)
        for did in to_remove:
            _store.pop(did, None)
            logger.info("PENDIENTE_EXCLUIDO | id=%s | fuera de bandejas vigentes", did)


def _pendiente_bajo_bandeja(ruta: str, bandeja: Path) -> bool:
    """True si el PDF está bajo bandeja_path (p. ej. {deposito}/Sin Firmar)."""
    if not ruta or not str(bandeja).strip():
        return False
    try:
        root = bandeja.resolve()
        p = Path(ruta).resolve()
        p.relative_to(root)
        return True
    except (ValueError, OSError, TypeError):
        return False


def _pendiente_misma_bandeja(ruta: str, bandeja: Path) -> bool:
    return _pendiente_bajo_bandeja(ruta, bandeja)


def is_path_under_ingresos_bandeja(ruta: str, bandeja_ingresos: str) -> bool:
    return is_path_same_bandeja(ruta, bandeja_ingresos)


def is_path_same_bandeja(ruta: str, bandeja: str) -> bool:
    return _pendiente_misma_bandeja(ruta, Path(bandeja))


def list_pending(
    allowed_apartado_codes: set[str] | None = None,
    *,
    filter_username: str | None = None,
    filter_fecha: str | None = None,
    filter_q: str | None = None,
) -> list[dict]:
    want_user = _norm_tango_usuario(filter_username)
    want_fecha = (filter_fecha or "").strip()[:10] or None
    want_q = (filter_q or "").strip() or None
    codes = allowed_apartado_codes or set()
    firmado_map = firmado_claves_by_apartado_codigo(codes) if codes else {}
    destino_map = destino_paths_for_codigos(codes) if codes else {}

    with _lock:
        ids_to_remove = [
            doc_id
            for doc_id, doc in _store.items()
            if doc["estado"] == "pendiente" and not _path_exists(doc["ruta"])
        ]
        for doc_id in ids_to_remove:
            _store.pop(doc_id, None)

        def include(doc: dict) -> bool:
            if doc.get("estado") != "pendiente":
                return False
            if allowed_apartado_codes is not None and doc.get("apartado_codigo") not in allowed_apartado_codes:
                return False
            if doc_is_firmado_in_db(doc, firmado_map, destino_map):
                return False
            enrich_tango_meta(doc)
            owner = _norm_tango_usuario(doc.get("tango_usuario"))
            if want_user:
                if not owner or owner != want_user:
                    return False
            doc_fecha = doc.get("tango_fecha")
            if want_fecha and doc_fecha and doc_fecha != want_fecha:
                return False
            if want_q:
                ruta = doc.get("ruta", "")
                try:
                    if not file_search_matches(Path(ruta), want_q):
                        return False
                except OSError:
                    return False
            return True

        return sorted(
            [
                {k: v for k, v in doc.items() if k != "ruta"}
                for doc in _store.values()
                if include(doc)
            ],
            key=lambda d: d["recibido_en"],
            reverse=True,
        )


def remove(doc_id: str) -> None:
    with _lock:
        _store.pop(doc_id, None)


def remove_by_path(path: Path) -> None:
    """Quita del store (pendiente) el documento cuya ruta coincide con path."""
    key = _norm_path_key(path)
    doc_id = hashlib.md5(key.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
    with _lock:
        doc = _store.get(doc_id)
        if doc and doc.get("estado") == "pendiente":
            _store.pop(doc_id, None)
            logger.info("PENDIENTE_QUITADO | id=%s | archivo=%s", doc_id, path.name)


def remove_pending_by_tango_clave(
    tango_clave: str, bandeja: Path, *, delete_file: bool = False
) -> None:
    """
    Quita del store pendientes que compartan la tango_clave dada y
    estén bajo la bandeja indicada.

    Por defecto no borra el PDF en disco (sync Tango reutiliza archivos existentes).
    Pasar delete_file=True solo al reemplazar por un nombre distinto.
    """
    if not tango_clave:
        return
    with _lock:
        to_remove = [
            did
            for did, doc in _store.items()
            if doc.get("estado") == "pendiente"
            and doc.get("tango_clave") == tango_clave
            and _pendiente_bajo_bandeja(doc.get("ruta", ""), bandeja)
        ]
        for did in to_remove:
            doc = _store.pop(did, None)
            if doc:
                ruta = doc.get("ruta", "")
                logger.info("PENDIENTE_REEMPLAZADO | id=%s | archivo=%s", did, Path(ruta).name)
                if delete_file:
                    p = Path(ruta)
                    if p.is_file():
                        if safe_unlink(p):
                            logger.info("PDF_VIEJO_ELIMINADO_STORE | archivo=%s", p.name)


def _path_exists(ruta: str) -> bool:
    try:
        return Path(ruta).exists()
    except OSError:
        return False


def scan_inbox(
    bandeja: Path,
    apartado_codigo: str = "transferencias",
    *,
    modo_flujo: str = "transferencia",
    prefijo: str = "t",
) -> None:
    bandeja.mkdir(parents=True, exist_ok=True)
    from core.database import SessionLocal
    from services import apartados as apartados_svc
    from services.apartado_paths import infer_tango_fuente_from_path, iter_bandeja_inbox_pdfs

    db = SessionLocal()
    try:
        a = apartados_svc.get_by_codigo(db, apartado_codigo, active_only=False)
        pdfs = iter_bandeja_inbox_pdfs(a) if a else [
            p for p in bandeja.rglob("*.pdf") if p.is_file()
        ]
    finally:
        db.close()

    for pdf in pdfs:
        fecha_p, usuario_p = _resolve_tango_meta(pdf.name)
        register(
            pdf,
            silent=True,
            apartado_codigo=apartado_codigo,
            modo_flujo=modo_flujo,
            prefijo=prefijo,
            tango_fecha=fecha_p,
            tango_usuario=usuario_p,
            tango_fuente=infer_tango_fuente_from_path(pdf),
            origen="bandeja",
        )
    with _lock:
        total = sum(1 for d in _store.values() if d["estado"] == "pendiente")
    logger.info("Bandeja %s escaneada (pendientes en memoria: %s)", apartado_codigo, total)


# ── Watchdog ──────────────────────────────────────────────────────────────────


class _BandejaHandler(FileSystemEventHandler):
    def __init__(self, apartado_codigo: str, modo_flujo: str, prefijo: str):
        super().__init__()
        self.apartado_codigo = apartado_codigo
        self.modo_flujo = modo_flujo
        self.prefijo = prefijo

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".pdf":
            return
        time.sleep(0.75)
        register(
            path,
            apartado_codigo=self.apartado_codigo,
            modo_flujo=self.modo_flujo,
            prefijo=self.prefijo,
        )

    def on_moved(self, event):
        if event.is_directory:
            return
        old = Path(event.src_path)
        if old.suffix.lower() == ".pdf":
            old_id = _doc_id(old)
            with _lock:
                if old_id in _store and _store[old_id].get("estado") == "pendiente":
                    del _store[old_id]
        new = Path(event.dest_path)
        if new.suffix.lower() == ".pdf":
            time.sleep(0.3)
            register(
                new,
                apartado_codigo=self.apartado_codigo,
                modo_flujo=self.modo_flujo,
                prefijo=self.prefijo,
            )

    def on_deleted(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        doc_id = _doc_id(path)
        with _lock:
            if doc_id in _store and _store[doc_id]["estado"] == "pendiente":
                del _store[doc_id]
        logger.info("DOCUMENTO_ELIMINADO | archivo=%s", path.name)


def stop_inbox_watcher() -> None:
    with _observer_lock:
        obs_list = list(_inbox_observers)
    for o in obs_list:
        try:
            o.stop()
            o.join(timeout=5)
        except Exception as e:
            logger.warning("Al detener observer: %s", e)


def _use_polling_observer(bandeja: Path) -> bool:
    from config import Config

    if os.name == "nt":
        return True
    if Config.WATCHDOG_USE_POLLING:
        return True
    s = str(bandeja).replace("\\", "/")
    return s.startswith("/mnt/") or s.startswith("/media/")


def _create_watcher(bandeja: Path, apartado_codigo: str, modo_flujo: str, prefijo: str):
    from config import Config

    bandeja.mkdir(parents=True, exist_ok=True)
    handler = _BandejaHandler(apartado_codigo, modo_flujo, prefijo)
    if _use_polling_observer(bandeja):
        observer = PollingObserver(timeout=Config.WATCHDOG_POLLING_TIMEOUT)
    else:
        observer = Observer()
    observer.schedule(handler, str(bandeja), recursive=True)
    observer.start()
    logger.info("Watcher %s en: %s", apartado_codigo, bandeja)
    return observer


def start_watcher(bandeja: Path, apartado_codigo: str, modo_flujo: str, prefijo: str) -> PollingObserver:
    obs = _create_watcher(bandeja, apartado_codigo, modo_flujo, prefijo)
    with _observer_lock:
        _inbox_observers.append(obs)
    return obs


def start_rescan_loop(get_bandeja_tuples, interval: float = 60.0):
    stop = threading.Event()

    def _loop():
        while not stop.wait(interval):
            try:
                row = get_bandeja_tuples()
                from core.database import SessionLocal
                from services import apartados as apartados_svc
                from services.apartado_paths import infer_tango_fuente_from_path, iter_bandeja_inbox_pdfs

                db = SessionLocal()
                try:
                    for bandeja, ac, mf, pr in row:
                        if not bandeja.is_dir():
                            continue
                        a = apartados_svc.get_by_codigo(db, ac, active_only=False)
                        pdfs = iter_bandeja_inbox_pdfs(a) if a else []
                        for pdf in pdfs:
                            if register(
                                pdf,
                                silent=True,
                                apartado_codigo=ac,
                                modo_flujo=mf,
                                prefijo=pr,
                                tango_fuente=infer_tango_fuente_from_path(pdf),
                            ):
                                logger.info(
                                    "NUEVO_DOCUMENTO | id=%s | archivo=%s | origen=rescaneo | ap=%s",
                                    _doc_id(pdf),
                                    pdf.name,
                                    ac,
                                )
                finally:
                    db.close()
            except Exception as ex:
                logger.warning("Rescaneo: %s", ex)

    th = threading.Thread(target=_loop, name="rescaneo-bandeja", daemon=True)
    th.start()
    logger.info("Rescaneo periódico cada %gs (N bandejas)", interval)
    return stop, th
