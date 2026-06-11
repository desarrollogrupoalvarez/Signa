"""
Flask application — routes only. Business logic lives in services/.
"""

import hashlib
import ipaddress
import logging
import mimetypes
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, abort, g, jsonify, request, send_file
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from core.apartado_access import apartado_codes_for_user
from core.apartado_admin import can_reveal_file_location, permissions_from_payload, user_puede_ver_todos_pendientes
from core.database import SessionLocal
from models.user import User
from services import apartados as apartados_svc
from services import audit, documents, path_settings, transfer_routing
from services import ingreso_merge, ingreso_routing
from services.pdf_service import sign_pdf
from services import metrics_pdf, metrics_tango
from sqlalchemy.orm import joinedload


# ── Logger ────────────────────────────────────────────────────────────────────

def _setup_logger() -> logging.Logger:
    log_dir = Path(Config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("remitos")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(log_dir / "audit.log", maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


logger = _setup_logger()


# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=None)
app.wsgi_app = ProxyFix(app.wsgi_app)
CORS(app, origins=Config.CORS_ORIGINS)

# ── DB session per request ────────────────────────────────────────────────────

@app.before_request
def _open_db():
    g.db = SessionLocal()


@app.teardown_appcontext
def _close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.rollback()
        db.close()


@app.after_request
def _no_cache_sensitive_lists(response):
    if request.method == "GET" and request.path in ("/api/documentos", "/api/firmados"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Vary"] = "Authorization"
    return response


# ── Blueprints ────────────────────────────────────────────────────────────────

from auth.controller import bp as auth_bp                # noqa: E402
from users.controller import bp as users_bp                # noqa: E402
from configuracion.controller import bp as configuracion_bp  # noqa: E402
from apartados.controller import bp as apartados_bp  # noqa: E402
from areas.controller import bp as areas_bp  # noqa: E402

app.register_blueprint(auth_bp)
app.register_blueprint(users_bp)
app.register_blueprint(configuracion_bp)
app.register_blueprint(apartados_bp)
app.register_blueprint(areas_bp)


# ── IP allowlist ──────────────────────────────────────────────────────────────

def _parse_allowed_ips(raw: str):
    raw = (raw or "").strip()
    if not raw or raw == "*":
        return None
    items = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            items.append(ipaddress.ip_network(part, strict=False) if "/" in part else ipaddress.ip_address(part))
        except ValueError:
            logger.warning(f"ALLOWED_IPS inválido: '{part}'")
    return items or None


_ALLOWED_IPS = _parse_allowed_ips(Config.ALLOWED_IPS)


def _ip_allowed(ip_str: str) -> bool:
    if _ALLOWED_IPS is None:
        return True
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in item if isinstance(item, (ipaddress.IPv4Network, ipaddress.IPv6Network)) else ip == item for item in _ALLOWED_IPS)


@app.before_request
def _check_ip():
    ip = (request.remote_addr or "").strip()
    if not _ip_allowed(ip):
        logger.warning(f"ACCESO_IP_DENEGADO | ip={ip} | path={request.path}")
        if not request.path.startswith("/api/"):
            return ("Sin permiso", 403, {"Content-Type": "text/plain; charset=utf-8"})
        abort(403, "Sin permiso")


from core.middleware import require_auth  # noqa: E402


def _current_db_user():
    try:
        uid = int(g.current_user["sub"])
    except (TypeError, ValueError, KeyError):
        abort(401, "Token malformado")
    u = g.db.query(User).options(joinedload(User.role), joinedload(User.apartados)).get(uid)
    if not u:
        abort(404, "Usuario no encontrado")
    return u


def _effective_apartado_codes() -> set[str]:
    u = _current_db_user()
    rname = u.role.name if u.role else None
    return apartado_codes_for_user(g.db, u, rname)


def _require_apartado_doc(doc: dict | None) -> None:
    if not doc:
        return
    if doc.get("apartado_codigo") not in _effective_apartado_codes():
        abort(403, "Sin acceso a este apartado")


def _current_permissions() -> set[str]:
    return permissions_from_payload(g.current_user)


def _require_firmado_carpeta_access(nombre: str, apartado_codigo: str | None = None) -> None:
    u = _current_db_user()
    if not u.role:
        abort(403, "Sin permiso para este archivo")
    from services.digitalizado_access import nombre_firmado_permitido

    if not nombre_firmado_permitido(
        nombre,
        role_id=u.role.id,
        db=g.db,
        perms=_current_permissions(),
        apartado_codigo=apartado_codigo,
    ):
        abort(403, "Sin permiso para esta carpeta")


# ── Static frontend ───────────────────────────────────────────────────────────

_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"




def _mark_tango_firmado_si_aplica(db, doc, *, ruta_firmado=None):
    if not doc:
        return
    clave = doc.get("tango_clave")
    if not clave:
        return
    ac = (doc.get("apartado_codigo") or "").strip()
    if not ac:
        return
    from services import apartados as apartados_svc
    from services import comprobante_tango_store
    from services.comprobante_text_index import normalizar_ruta

    a = apartados_svc.get_by_codigo(db, ac, active_only=False)
    if not a:
        return
    ruta_str = normalizar_ruta(ruta_firmado) if ruta_firmado else None
    comprobante_tango_store.mark_firmado(db, a.id, clave, ruta_firmado=ruta_str)
    try:
        db.commit()
    except Exception:
        db.rollback()

@app.route("/")
def index():
    dist = _FRONTEND_DIST / "index.html"
    if dist.exists():
        return send_file(str(dist))
    return "<h2>Frontend not built. Run <code>npm run build</code> inside frontend/.</h2>", 200


@app.route("/assets/<path:filename>")
def assets(filename):
    assets_dir = _FRONTEND_DIST / "assets"
    return send_file(str(assets_dir / filename))


# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/documentos")
@require_auth("pendientes:ver")
def list_documents():
    ap = _effective_apartado_codes()
    if not ap:
        return jsonify({"documentos": []})
    u = _current_db_user()
    jwt_user = (g.current_user.get("username") or "").strip().upper() or None
    db_user = (u.username or "").strip().upper() or None
    if jwt_user and db_user and jwt_user != db_user:
        logger.warning(
            "LIST_DOCUMENTOS_USER_MISMATCH | jwt=%s | db=%s | sub=%s",
            jwt_user,
            db_user,
            g.current_user.get("sub"),
        )
    perms = _current_permissions()
    filter_user = None if user_puede_ver_todos_pendientes(perms) else (db_user or jwt_user)
    fecha_q = (request.args.get("fecha") or "").strip()[:10] or None
    q = (request.args.get("q") or "").strip() or None
    from models.apartado import Apartado

    try:
        aps = (
            g.db.query(Apartado)
            .filter(Apartado.activo.is_(True), Apartado.codigo.in_(ap))
            .all()
        )
        docs = documents.list_pending_from_bd(
            g.db,
            aps,
            ap,
            filter_username=filter_user,
            filter_fecha=fecha_q,
            filter_q=q,
        )
    except Exception as e:
        logger.warning("LIST_PENDIENTES_BD | %s", e)
        docs = documents.list_pending(
            ap,
            filter_username=filter_user,
            filter_fecha=fecha_q,
            filter_q=q,
        )
    return jsonify({"documentos": docs})


@app.route("/api/documentos/<doc_id>/pdf")
@require_auth("pendientes:ver")
def get_pdf(doc_id):
    doc = documents.get(doc_id)
    if not doc:
        abort(404, "Documento no encontrado")
    _require_apartado_doc(doc)
    if doc["estado"] != "pendiente":
        abort(410, "Documento ya procesado")
    ruta = Path(doc["ruta"])
    if not ruta.exists():
        documents.remove(doc_id)
        abort(404, "Archivo no encontrado en disco")
    logger.info(f"VISUALIZACION | id={doc_id} | archivo={doc['nombre']} | ip={request.remote_addr}")
    return send_file(str(ruta), mimetype="application/pdf")


def _ingreso_copiar_a_destino_y_marcar(doc: dict, db, dispositivo: str) -> dict:
    """
    Tras anexar escaneos al PDF en la bandeja, copia el PDF al destino,
    marca firmado, auditoría y elimina el archivo de la bandeja.
    """
    doc_id = doc["id"]
    a = apartados_svc.get_by_codigo(db, doc.get("apartado_codigo") or "", active_only=False)
    if not a or a.modo_flujo != "ingreso":
        abort(400, "Solo aplica a apartados con flujo de ingreso")
    if not documents.is_path_same_bandeja(doc["ruta"], a.bandeja_path):
        abort(400, "Ruta de documento no coincide con la bandeja del apartado")
    source = Path(doc["ruta"])
    if not source.is_file():
        documents.remove(doc_id)
        abort(404, "Archivo no encontrado")
    try:
        from services.path_settings import resolve_storage_path

        dest_root = resolve_storage_path(a.destino_path)
        dest_dir = _resolve_dest_dir_for_doc(doc, a, source)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / source.name
        from services.file_ops import safe_copy2, safe_unlink

        if not safe_copy2(source, dest):
            abort(500, "No se pudo copiar el archivo al destino")
        hash_firmado = _sha256(dest)
        try:
            dr = dest_root.resolve()
            d_res = dest.resolve()
            rel = f"{a.prefijo}/" + str(d_res.relative_to(dr)).replace("\\", "/")
        except (ValueError, OSError):
            rel = f"{a.prefijo}/" + dest.name
        documents.mark_signed(doc_id, dispositivo, dest, hash_firmado, rel)
        _mark_tango_firmado_si_aplica(g.db, doc, ruta_firmado=dest)
        audit.record_ingreso_completado(doc, dispositivo, request.remote_addr, dest, hash_firmado, rel)
        if not safe_unlink(source):
            logger.warning("BANDEJA_NO_BORRADA_TRAS_INGRESO | archivo=%s", source.name)
        logger.info("INGRESO_COMPLETADO | id=%s | archivo=%s", doc_id, doc["nombre"])
        user_id = int((g.current_user or {}).get("sub") or 0) or None
        _invalidate_firmados_cache(user_id)
        return {
            "ok": True,
            "archivo_firmado": rel,
            "hash_firmado": hash_firmado,
        }
    except OSError as e:
        logger.error("ERROR_COMPLETAR_INGRESO | id=%s | %s", doc_id, e)
        abort(500, f"Error al completar: {e}")


@app.route("/api/documentos/<doc_id>/adjuntar_escaneos", methods=["POST"])
@require_auth("pendientes:firmar")
def adjuntar_escaneos(doc_id):
    doc = documents.get(doc_id)
    if not doc or doc.get("estado") != "pendiente":
        abort(404, "Documento no encontrado o ya procesado")
    _require_apartado_doc(doc)
    a = apartados_svc.get_by_codigo(g.db, doc.get("apartado_codigo") or "", active_only=False)
    if not a or a.modo_flujo != "ingreso":
        abort(400, "Solo aplica a apartados con flujo de ingreso (p. ej. Ingresos)")

    if not documents.is_path_same_bandeja(doc["ruta"], a.bandeja_path):
        abort(400, "Ruta de documento no coincide con la bandeja del apartado")

    import tempfile

    files = request.files.getlist("imagenes")
    if not files:
        files = request.files.getlist("files")
    if not files:
        abort(400, "Enviá al menos una imagen (imagenes[] o files[])")
    paths_tmp: list[Path] = []
    for fs in files:
        if len(paths_tmp) >= ingreso_merge.MAX_IMAGES:
            break
        if not fs or not getattr(fs, "filename", None):
            continue
        suf = (Path(fs.filename).suffix or ".jpg").lower()
        if suf not in ingreso_merge.ALLOWED_EXT:
            continue
        fd, tmp = tempfile.mkstemp(suffix=suf)
        try:
            os.close(fd)
            fs.save(tmp)
            paths_tmp.append(Path(tmp))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            abort(500, "No se pudo guardar imagen temporal")
    if not paths_tmp:
        abort(400, "Ninguna imagen válida (use PNG, JPG o WebP)")

    pdf_path = Path(doc["ruta"])
    if not pdf_path.is_file():
        documents.remove(doc_id)
        abort(404, "Archivo no encontrado")

    max_b = int(getattr(Config, "MAX_FIRMA_SIZE", 5 * 1024 * 1024)) * 3
    for p in paths_tmp:
        if p.stat().st_size > max_b:
            for x in paths_tmp:
                x.unlink(missing_ok=True)
            abort(400, "Imagen demasiado grande")

    try:
        n = ingreso_merge.append_images_to_pdf_in_place(pdf_path, paths_tmp)
    except Exception as e:
        logger.error("ERROR_ADJUNTAR | id=%s | %s", doc_id, e)
        for x in paths_tmp:
            x.unlink(missing_ok=True)
        abort(500, f"No se pudo anexar imágenes: {e}")
    for x in paths_tmp:
        x.unlink(missing_ok=True)

    documents.refresh_file_hash(doc_id)
    doc2 = documents.get(doc_id)
    if not doc2:
        abort(500, "Error interno al refrescar documento")
    dispositivo = (request.form.get("dispositivo") or request.remote_addr)[:100]
    out = _ingreso_copiar_a_destino_y_marcar(doc2, g.db, dispositivo)
    out["paginas_anadidas"] = n
    return jsonify(out)


@app.route("/api/documentos/<doc_id>/completar_ingreso", methods=["POST"])
@require_auth("pendientes:firmar")
def completar_ingreso(doc_id):
    """Archiva un IN sin escaneo nuevo (o tras merge externo). PDF actual copiado al destino de ingresos."""
    doc = documents.get(doc_id)
    if not doc or doc.get("estado") != "pendiente":
        abort(404, "Documento no encontrado o ya procesado")
    _require_apartado_doc(doc)
    a = apartados_svc.get_by_codigo(g.db, doc.get("apartado_codigo") or "", active_only=False)
    if not a or a.modo_flujo != "ingreso":
        abort(400, "Solo aplica a apartados con flujo de ingreso (p. ej. Ingresos)")

    data = request.get_json(force=True, silent=True) or {}
    dispositivo = (data.get("dispositivo") or request.remote_addr)[:100]
    return jsonify(_ingreso_copiar_a_destino_y_marcar(doc, g.db, dispositivo))


def _resolve_dest_dir_for_doc(doc: dict, a, source: Path) -> Path:
    """Directorio de destino según apartado y modo de flujo."""
    from services.apartado_paths import parse_categorias_for_deposito, resolve_deposito_carpeta
    from services.tango_paths import transferencias_segment_root

    carpeta = resolve_deposito_carpeta(
        a,
        ruta=doc.get("ruta"),
        tango_fuente=doc.get("tango_fuente"),
    )
    from services.path_settings import resolve_storage_path

    deposito_root = transferencias_segment_root(
        resolve_storage_path(a.destino_path),
        a,
        doc.get("tango_fuente"),
        ruta_pendiente=doc.get("ruta"),
    )
    keys = transfer_routing.parse_keywords_csv(getattr(a, "keywords_importante", "") or "")
    cats = parse_categorias_for_deposito(
        a, carpeta=carpeta, tango_fuente=doc.get("tango_fuente")
    )
    if a.modo_flujo == "ingreso":
        from services.metrics_ingresos import parse_ingreso_pdf

        texto = ingreso_routing.extract_pdf_text(source)
        parsed = parse_ingreso_pdf(source)
        codigos = {
            (it.codigo or "").strip().upper()
            for it in (parsed.items or [])
            if (it.codigo or "").strip()
        }
    else:
        from services.metrics_transferencias import parse_transfer_pdf

        texto = transfer_routing.extract_pdf_text(source)
        parsed = parse_transfer_pdf(source)
        codigos = {
            (it.codigo or "").strip().upper()
            for it in (parsed.items or [])
            if (it.codigo or "").strip()
        }
    return transfer_routing.destination_dir(
        deposito_root,
        source.name,
        codigos,
        keywords_importante=keys or None,
        categorias=cats or None,
        text_fallback=texto,
    )


def _finalize_archivo_pendiente(
    doc_id: str,
    doc: dict,
    a,
    source: Path,
    dest: Path,
    dispositivo: str,
    *,
    audit_fn,
) -> dict:
    """Marca firmado, auditoría, Tango y elimina el PDF de bandeja."""
    from services.path_settings import resolve_storage_path

    hash_firmado = _sha256(dest)
    root_dest = resolve_storage_path(a.destino_path)
    try:
        d_res = dest.resolve()
        rel = f"{a.prefijo}/" + str(d_res.relative_to(root_dest.resolve())).replace("\\", "/")
    except (ValueError, OSError):
        rel = f"{a.prefijo}/" + dest.name
    documents.mark_signed(doc_id, dispositivo, dest, hash_firmado, rel)
    _mark_tango_firmado_si_aplica(g.db, doc, ruta_firmado=dest)
    audit_fn(doc, dispositivo, request.remote_addr, dest, hash_firmado, rel)
    from services.file_ops import safe_unlink

    if not safe_unlink(source):
        logger.warning(
            "BANDEJA_NO_BORRADA_TRAS_FIRMA | archivo=%s | se omitirá en próximo registro",
            source.name,
        )
    user_id = int((g.current_user or {}).get("sub") or 0) or None
    _invalidate_firmados_cache(user_id)
    return {"ok": True, "archivo_firmado": rel, "hash_firmado": hash_firmado}


@app.route("/api/documentos/<doc_id>/firmar", methods=["POST"])
@require_auth("pendientes:firmar")
def sign_document(doc_id):
    doc = documents.get(doc_id)
    if not doc:
        abort(404, "Documento no encontrado")
    _require_apartado_doc(doc)
    if doc["estado"] != "pendiente":
        abort(409, "Documento ya fue procesado")

    data = request.get_json(force=True) or {}
    firma_b64 = data.get("firma")
    dispositivo = (data.get("dispositivo") or request.remote_addr)[:100]
    page_num = data.get("page")
    placement = data.get("placement")

    if not firma_b64:
        abort(400, "Firma requerida")
    try:
        page_num = int(page_num)
    except (TypeError, ValueError):
        abort(400, "Página inválida")
    if not isinstance(placement, dict):
        abort(400, "placement requerido (x, y, w, h en 0–1)")

    source = Path(doc["ruta"])
    if not source.exists():
        documents.remove(doc_id)
        abort(404, "Archivo original no encontrado")

    try:
        a = apartados_svc.get_by_codigo(g.db, doc.get("apartado_codigo") or "", active_only=False)
        if not a:
            abort(500, "Apartado no encontrado en base de datos")
        dest_dir = _resolve_dest_dir_for_doc(doc, a, source)
        dest = sign_pdf(source, firma_b64, page_num, placement, dest_dir)

        def _audit(doc_, disp, ip, dest_path, h, rel):
            audit.record(doc_, disp, ip, page_num, placement, dest_path, h, rel)

        out = _finalize_archivo_pendiente(
            doc_id, doc, a, source, dest, dispositivo, audit_fn=_audit
        )
        logger.info(
            f"DOCUMENTO_FIRMADO | id={doc_id} | archivo={doc['nombre']} | pagina={page_num} | dispositivo={dispositivo}"
        )
        return jsonify(out)
    except Exception as e:
        logger.error(f"ERROR_FIRMA | id={doc_id} | error={e}")
        abort(500, f"Error al procesar firma: {e}")


@app.route("/api/documentos/<doc_id>/archivar_sin_firma", methods=["POST"])
@require_auth("pendientes:firmar")
def archivar_sin_firma(doc_id):
    doc = documents.get(doc_id)
    if not doc:
        abort(404, "Documento no encontrado")
    _require_apartado_doc(doc)
    if doc["estado"] != "pendiente":
        abort(409, "Documento ya fue procesado")

    data = request.get_json(force=True, silent=True) or {}
    dispositivo = (data.get("dispositivo") or request.remote_addr)[:100]

    source = Path(doc["ruta"])
    if not source.exists():
        documents.remove(doc_id)
        abort(404, "Archivo original no encontrado")

    try:
        a = apartados_svc.get_by_codigo(g.db, doc.get("apartado_codigo") or "", active_only=False)
        if not a:
            abort(500, "Apartado no encontrado en base de datos")
        if a.modo_flujo != "transferencia":
            abort(400, "Solo aplica a apartados con flujo de transferencia")

        dest_dir = _resolve_dest_dir_for_doc(doc, a, source)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / source.name
        from services.file_ops import safe_copy2

        if not safe_copy2(source, dest):
            abort(500, "No se pudo copiar el archivo al destino")

        out = _finalize_archivo_pendiente(
            doc_id,
            doc,
            a,
            source,
            dest,
            dispositivo,
            audit_fn=audit.record_transferencia_sin_firma,
        )
        logger.info(
            "DOCUMENTO_ARCHIVADO_SIN_FIRMA | id=%s | archivo=%s | dispositivo=%s",
            doc_id,
            doc["nombre"],
            dispositivo,
        )
        return jsonify(out)
    except OSError as e:
        logger.error("ERROR_ARCHIVAR_SIN_FIRMA | id=%s | %s", doc_id, e)
        abort(500, f"Error al archivar: {e}")
    except Exception as e:
        logger.error("ERROR_ARCHIVAR_SIN_FIRMA | id=%s | error=%s", doc_id, e)
        abort(500, f"Error al archivar: {e}")


# Archivos firmados: listar todos los tipos (no solo PDF). Ver _SIGNED_BLOCK_EXT.
_SIGNED_BLOCK_EXT = frozenset(
    {
        ".exe",
        ".bat",
        ".cmd",
        ".com",
        ".msi",
        ".scr",
        ".pif",
        ".vbs",
        ".js",
        ".jse",
        ".wsf",
        ".wsh",
        ".ps1",
        ".psm1",
        ".hta",
        ".dll",
        ".cpl",
        ".application",
    }
)


def _signed_skip_relpath(rel: Path) -> bool:
    from services.apartado_paths import SIN_FIRMAR

    for part in rel.parts:
        if part.startswith("~$"):
            return True
        if part.upper() == SIN_FIRMAR.upper():
            return True
    name = rel.name.lower()
    if name in (".ds_store", "thumbs.db", "desktop.ini"):
        return True
    return False


def _categoria_archivo(p: Path) -> str:
    e = p.suffix.lower()
    if e == ".pdf":
        return "pdf"
    if e in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"):
        return "imagen"
    if e in (".heic", ".heif"):
        return "otro"
    if e in (
        ".txt",
        ".csv",
        ".log",
        ".md",
        ".json",
        ".xml",
        ".html",
        ".htm",
        ".yml",
        ".yaml",
        ".ini",
        ".conf",
        ".rc",
    ):
        return "texto"
    if e in (".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf"):
        return "oficina"
    if e in (".mp4", ".webm", ".ogv", ".mov", ".mkv", ".m4v"):
        return "media"
    if e in (".mp3", ".ogg", ".oga", ".wav", ".m4a", ".aac", ".flac", ".opus"):
        return "media"
    return "otro"


def _tipo_filtro_coincide(categoria: str, tipo: str) -> bool:
    t = (tipo or "").strip().lower()
    if t in ("", "todos", "all"):
        return True
    return categoria == t


def _collect_firmados_from_root(
    root: Path, origen: str, prefix: str
) -> list[tuple[Path, str, float, str, str, str]]:
    """Lista archivos bajo destino_path; omite carpetas Sin Firmar (bandeja de pendientes)."""
    from services.apartado_paths import SIN_FIRMAR

    out: list[tuple[Path, str, float, str, str, str]] = []
    if not root.is_dir():
        return out
    pfx = (prefix or "x").strip()[:8]
    sin_firmar = SIN_FIRMAR.upper()
    skip_names = frozenset({".ds_store", "thumbs.db", "desktop.ini"})

    def _walk(base: Path, rel_base: Path) -> None:
        try:
            with os.scandir(base) as it:
                for entry in it:
                    name = entry.name
                    if name.startswith("~$") or name.lower() in skip_names:
                        continue
                    rel = rel_base / name
                    if entry.is_dir(follow_symlinks=False):
                        if name.upper() == sin_firmar:
                            continue
                        _walk(Path(entry.path), rel)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if ".." in rel.parts or _signed_skip_relpath(rel):
                        continue
                    suf = Path(name).suffix.lower()
                    if suf in _SIGNED_BLOCK_EXT:
                        continue
                    try:
                        mtime = entry.stat(follow_symlinks=False).st_mtime
                    except OSError:
                        continue
                    rel_key = f"{pfx}/" + str(rel).replace("\\", "/")
                    cat = _categoria_archivo(Path(name))
                    out.append((Path(entry.path), rel_key, mtime, origen, cat, suf or ""))
        except OSError as e:
            logger.warning("LISTA_FIRMADOS_SCAN | root=%s | %s", base, e)

    _walk(root, Path("."))
    return out


def _file_search_matches(ruta: Path, q: str) -> bool:
    from services.file_search import file_search_matches

    return file_search_matches(ruta, q)


def _require_reveal_location() -> None:
    u = _current_db_user()
    role = u.role.name if u and u.role else None
    if not can_reveal_file_location(role):
        abort(403, "Sin permiso para abrir ubicación de archivos")


_FirmadosEntry = tuple[Path, str, float, str, str, str]

_FIRMADOS_INDEX_CACHE: dict[tuple, tuple[float, list[_FirmadosEntry]]] = {}
_FIRMADOS_INDEX_TTL_SEC = 120.0
_FIRMADOS_SCAN_LOCK = threading.Lock()
_FIRMADOS_SCAN_WAITERS: dict[tuple, threading.Event] = {}


def _invalidate_firmados_cache(user_id: int | None = None) -> None:
    """Borra índice en memoria tras firmar/archivar (evita listas obsoletas)."""
    _FIRMADOS_INDEX_CACHE.clear()


def _firmados_index_key(allowed: list[str]) -> tuple:
    return tuple(sorted(allowed))


def _firmados_entries_cached(aps, allowed: list[str], *, fresh: bool) -> list[_FirmadosEntry]:
    index_key = _firmados_index_key(allowed)
    now = time.time()
    cached = _FIRMADOS_INDEX_CACHE.get(index_key)
    if not fresh and cached and now - cached[0] < _FIRMADOS_INDEX_TTL_SEC:
        return cached[1]

    wait_event: threading.Event | None = None
    is_leader = False
    with _FIRMADOS_SCAN_LOCK:
        cached = _FIRMADOS_INDEX_CACHE.get(index_key)
        if not fresh and cached and now - cached[0] < _FIRMADOS_INDEX_TTL_SEC:
            return cached[1]
        wait_event = _FIRMADOS_SCAN_WAITERS.get(index_key)
        if wait_event is None:
            wait_event = threading.Event()
            _FIRMADOS_SCAN_WAITERS[index_key] = wait_event
            is_leader = True

    if not is_leader:
        wait_event.wait(timeout=180)
        cached = _FIRMADOS_INDEX_CACHE.get(index_key)
        if cached:
            return cached[1]

    try:
        entries = _scan_firmados_entries(aps)
        _FIRMADOS_INDEX_CACHE[index_key] = (time.time(), entries)
        return entries
    except OSError as e:
        logger.warning("LISTA_FIRMADOS_ERROR | %s", e)
        raise
    finally:
        with _FIRMADOS_SCAN_LOCK:
            evt = _FIRMADOS_SCAN_WAITERS.pop(index_key, None)
            if evt:
                evt.set()


def _scan_firmados_entries(aps) -> list[_FirmadosEntry]:
    from services.path_settings import resolve_storage_path, scan_roots_for_apartado

    entries: list[_FirmadosEntry] = []
    seen_files: set[str] = set()
    for a in aps:
        scan_roots = scan_roots_for_apartado(a)
        if not scan_roots:
            logger.warning(
                "LISTA_FIRMADOS_SIN_RUTAS | apartado=%s | destino=%s | bandeja=%s",
                a.codigo,
                a.destino_path,
                a.bandeja_path,
            )
            continue
        for root in scan_roots:
            if not root.is_dir():
                logger.debug(
                    "LISTA_FIRMADOS_ROOT_OMITIDO | apartado=%s | path=%s",
                    a.codigo,
                    root,
                )
                continue
            for row in _collect_firmados_from_root(root, a.codigo, a.prefijo):
                try:
                    fkey = str(row[0].resolve())
                except OSError:
                    fkey = str(row[0])
                if fkey in seen_files:
                    continue
                seen_files.add(fkey)
                entries.append(row)
    legacy = resolve_storage_path(Config.REMITOS_FIRMADOS)
    if legacy.is_dir() and any(a.codigo == "transferencias" for a in aps):
        for row in _collect_firmados_from_root(legacy, "transferencias", "t"):
            try:
                fkey = str(row[0].resolve())
            except OSError:
                fkey = str(row[0])
            if fkey not in seen_files:
                seen_files.add(fkey)
                entries.append(row)
    entries.sort(key=lambda x: x[2], reverse=True)
    return entries


def _filter_firmados_entries(
    entries: list[_FirmadosEntry],
    *,
    origen_f: str,
    tipo_f: str,
    q: str,
) -> list[dict]:
    from services.file_search import name_matches, pdf_matches

    q_norm = (q or "").strip()
    items: list[dict] = []

    for ruta, rel, mt, orig, cat, ext in entries:
        if origen_f and origen_f not in ("todos", "all") and orig != origen_f:
            continue
        if not _tipo_filtro_coincide(cat, tipo_f):
            continue
        if q_norm:
            if not name_matches(ruta, q_norm):
                if ruta.suffix.lower() != ".pdf" or not pdf_matches(ruta, q_norm):
                    continue
        items.append(
            {
                "nombre": rel,
                "origen": orig,
                "modificado_en": datetime.fromtimestamp(mt).isoformat(),
                "categoria": cat,
                "extension": ext,
            }
        )
    return items


def _filter_firmados_for_user(items: list[dict]) -> list[dict]:
    u = _current_db_user()
    if not u.role:
        return []
    from services.digitalizado_access import filtrar_firmados_por_carpeta

    return filtrar_firmados_por_carpeta(
        items,
        role_id=u.role.id,
        db=g.db,
        perms=_current_permissions(),
    )


@app.route("/api/firmados")
@require_auth("digitalizados:ver")
def list_signed():
    q = request.args.get("q", "").strip()
    origen_f = (request.args.get("origen", "") or "").strip().lower()
    tipo_f = (request.args.get("tipo", "") or "").strip().lower()
    estado_f = (request.args.get("estado", "") or "firmado").strip().lower()
    if estado_f not in ("pendiente", "firmado"):
        estado_f = "firmado"
    allowed = _effective_apartado_codes()
    if not allowed:
        return jsonify({"documentos": [], "total": 0})
    try:
        from models.apartado import Apartado

        aps = (
            g.db.query(Apartado)
            .filter(Apartado.activo.is_(True), Apartado.codigo.in_(allowed))
            .order_by(Apartado.orden, Apartado.codigo)
            .all()
        )
    except Exception as e:
        logger.warning("LISTA_FIRMADOS_RUTA | %s", e)
        abort(500, "Configuración de apartados no disponible")

    if q:
        from services.comprobante_search import buscar_comprobantes

        try:
            items = buscar_comprobantes(
                g.db,
                q,
                estado=estado_f,
                apartado_ids=[a.id for a in aps],
            )
            if origen_f and origen_f not in ("todos", "all"):
                items = [it for it in items if it.get("origen") == origen_f]
            if tipo_f and tipo_f not in ("todos", "all", ""):
                items = [
                    it for it in items if _tipo_filtro_coincide(it.get("categoria", ""), tipo_f)
                ]
            items = _filter_firmados_for_user(items)
            return jsonify({"documentos": items, "total": len(items)})
        except Exception as e:
            logger.warning("BUSCAR_FIRMADOS_ERROR | %s", e)
            abort(500, "Error en búsqueda de documentos")

    from services.comprobante_search import listar_firmados_comprobantes

    try:
        items = listar_firmados_comprobantes(
            g.db,
            aps,
            origen_f=origen_f,
            tipo_f=tipo_f,
        )
    except Exception as e:
        logger.warning("LISTA_FIRMADOS_BD | %s", e)
        abort(500, "No se pudo listar documentos firmados")
    if not items:
        logger.info(
            "LISTA_FIRMADOS_VACIA | usuario=%s | apartados=%s",
            (g.current_user or {}).get("username"),
            sorted(allowed),
        )
    items = _filter_firmados_for_user(items)
    return jsonify({"documentos": items, "total": len(items)})


def _metricas_apartados(modo_flujo: str, requested_apartados: list[str]):
    allowed = _effective_apartado_codes()
    if not allowed:
        return None, []
    if requested_apartados:
        allowed = [c for c in allowed if c in set(requested_apartados)]
        if not allowed:
            return None, []
    from models.apartado import Apartado

    aps = (
        g.db.query(Apartado)
        .filter(
            Apartado.activo.is_(True),
            Apartado.codigo.in_(allowed),
            Apartado.modo_flujo == modo_flujo,
        )
        .order_by(Apartado.orden, Apartado.codigo)
        .all()
    )
    return aps, allowed


@app.route("/api/metricas/ingresos")
@require_auth("registros:ver")
def metricas_ingresos():
    """
    Registros de ingresos desde Tango (rango año/mes).
    Con q no vacío, además busca en PDFs archivados.
    """
    q = (request.args.get("q", "") or "").strip()
    requested_apartados = [s.strip() for s in request.args.getlist("apartado") if (s or "").strip()]
    year_s = (request.args.get("year", "") or "").strip()
    month_s = (request.args.get("month", "") or "").strip()
    if not year_s:
        return jsonify({"error": "Indicá el año para consultar registros"}), 400
    try:
        year_i, month_i = metrics_tango.parse_year_month(year_s, month_s)
    except (TypeError, ValueError) as ex:
        return jsonify({"error": str(ex) or "Año o mes inválido"}), 400

    if not Config.tango_configured():
        return jsonify({"error": "Tango no configurado en el servidor"}), 503

    aps, allowed = _metricas_apartados("ingreso", requested_apartados)
    if aps is None:
        return jsonify({"documentos": [], "total": 0})
    if not allowed:
        return jsonify({"documentos": [], "total": 0, "filas_tango": 0, "pdfs_escaneados": 0})

    try:
        result = metrics_tango.query_ingresos(aps, year=year_i, month=month_i, q=q)
    except RuntimeError as ex:
        return jsonify({"error": str(ex)}), 503

    documentos = list(result.get("documentos") or [])
    archivos_generados: list = []
    pdfs_escaneados = 0
    if q:
        from services.comprobante_search import buscar_firmados_para_metricas

        archivos_generados = buscar_firmados_para_metricas(
            g.db, aps, q, year=year_i, month=month_i
        )
        pdfs_escaneados = len(archivos_generados)
        documentos.extend(archivos_generados)
    else:
        try:
            pdf_limit = int(request.args.get("limit", "2500") or "2500")
        except (TypeError, ValueError):
            pdf_limit = 2500
        archivos_generados, pdfs_escaneados = metrics_pdf.list_ingresos_pdfs(
            aps, year=year_s, month=month_s, q="", limit=pdf_limit, parse_content=False
        )

    payload = {
        "documentos": documentos,
        "archivos_generados": archivos_generados,
        "total": len(documentos),
        "filas_tango": result.get("filas_tango", 0),
        "comprobantes_tango": result.get("comprobantes_tango", 0),
        "fuentes": result.get("fuentes", {}),
        "pdfs_escaneados": pdfs_escaneados,
    }
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/metricas/transferencias")
@require_auth("registros:ver")
def metricas_transferencias():
    """
    Registros de transferencias desde Tango (rango año/mes).
    Con q no vacío, además busca en PDFs archivados.
    """
    q = (request.args.get("q", "") or "").strip()
    requested_apartados = [s.strip() for s in request.args.getlist("apartado") if (s or "").strip()]
    year_s = (request.args.get("year", "") or "").strip()
    month_s = (request.args.get("month", "") or "").strip()
    if not year_s:
        return jsonify({"error": "Indicá el año para consultar registros"}), 400
    try:
        year_i, month_i = metrics_tango.parse_year_month(year_s, month_s)
    except (TypeError, ValueError) as ex:
        return jsonify({"error": str(ex) or "Año o mes inválido"}), 400

    if not Config.tango_configured():
        return jsonify({"error": "Tango no configurado en el servidor"}), 503

    aps, allowed = _metricas_apartados("transferencia", requested_apartados)
    if aps is None:
        return jsonify({"documentos": [], "total": 0})
    if not allowed:
        return jsonify({"documentos": [], "total": 0, "filas_tango": 0, "pdfs_escaneados": 0})

    try:
        result = metrics_tango.query_transferencias(aps, year=year_i, month=month_i, q=q)
    except RuntimeError as ex:
        return jsonify({"error": str(ex)}), 503

    documentos = list(result.get("documentos") or [])
    archivos_generados: list = []
    pdfs_escaneados = 0
    if q:
        from services.comprobante_search import buscar_firmados_para_metricas

        archivos_generados = buscar_firmados_para_metricas(
            g.db, aps, q, year=year_i, month=month_i
        )
        pdfs_escaneados = len(archivos_generados)
        documentos.extend(archivos_generados)
    else:
        try:
            pdf_limit = int(request.args.get("limit", "2000") or "2000")
        except (TypeError, ValueError):
            pdf_limit = 2000
        archivos_generados, pdfs_escaneados = metrics_pdf.list_transferencias_pdfs(
            aps, year=year_s, month=month_s, q="", limit=pdf_limit, parse_content=False
        )

    payload = {
        "documentos": documentos,
        "archivos_generados": archivos_generados,
        "total": len(documentos),
        "filas_tango": result.get("filas_tango", 0),
        "comprobantes_tango": result.get("comprobantes_tango", 0),
        "fuentes": result.get("fuentes", {}),
        "pdfs_escaneados": pdfs_escaneados,
    }
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _apartado_from_nombre_firmado(nombre: str):
    s = (nombre or "").strip().replace("\\", "/")
    p0 = s.split("/")[0] if s else ""
    if not p0 or len(p0) > 8:
        return None
    return apartados_svc.get_by_prefijo(g.db, p0, active_only=False)


def _stream_firmado(allow_pdf_only: bool):
    nombre = (request.args.get("n", "") or "").strip()
    a = _apartado_from_nombre_firmado(nombre)
    if a and a.codigo not in _effective_apartado_codes():
        abort(403, "Sin acceso a este apartado")
    _require_firmado_carpeta_access(nombre, apartado_codigo=a.codigo if a else None)
    ruta = _safe_signed_path(nombre, g.db)
    if not ruta:
        abort(404, "Archivo no encontrado")
    if allow_pdf_only and ruta.suffix.lower() != ".pdf":
        abort(400, "Solo se admite PDF en esta ruta")
    mimetype, _ = mimetypes.guess_type(ruta.name)
    if not mimetype:
        mimetype = "application/octet-stream"
    logger.info(
        "VISUALIZACION_FIRMADO | archivo=%s | mimetype=%s | ip=%s",
        ruta.name,
        mimetype,
        request.remote_addr,
    )
    return send_file(
        str(ruta),
        mimetype=mimetype,
        as_attachment=False,
        download_name=ruta.name,
        conditional=True,
    )


@app.route("/api/firmados/archivo")
@require_auth("digitalizados:ver_archivo")
def get_signed_file():
    """Descarga o visualiza cualquier archivo firmado (MIME según extensión)."""
    return _stream_firmado(allow_pdf_only=False)


@app.route("/api/firmados/pdf")
@require_auth("digitalizados:ver_archivo")
def get_signed_pdf():
    """Compatibilidad: solo PDF (mismo visor antiguo)."""
    return _stream_firmado(allow_pdf_only=True)

@app.route("/api/firmados/path")
@require_auth("digitalizados:ver_archivo")
def get_signed_path():
    _require_reveal_location()
    nombre = request.args.get("n", "")
    a0 = _apartado_from_nombre_firmado(nombre)
    if a0 and a0.codigo not in _effective_apartado_codes():
        abort(403, "Sin acceso a este apartado")
    _require_firmado_carpeta_access(nombre, apartado_codigo=a0.codigo if a0 else None)
    ruta = _safe_signed_path(nombre, g.db)
    if not ruta:
        abort(404, "Archivo no encontrado")
    a = a0 or apartados_svc.get_by_prefijo(g.db, nombre.split("/")[0] if "/" in nombre else "", active_only=False)
    rel = ruta.name
    if a:
        from services.comprobante_text_index import nombre_ui_firmado

        rel = nombre_ui_firmado(a, ruta)
    return jsonify({
        "nombre": ruta.name,
        "ruta_relativa": rel,
        **_signed_path_locations(ruta),
    })


def _signed_path_locations(ruta: Path) -> dict[str, str]:
    from services.client_paths import path_locations

    return path_locations(ruta)

def _normalize_windows_path_for_explorer(p: str) -> str:
    """
    Explorer no siempre maneja bien rutas extendidas tipo \\?\\ o \\?\\UNC\\.
    Normalizamos a UNC estándar.
    """
    if not p or not isinstance(p, str):
        return p
    if p.startswith("\\\\?\\UNC\\"):
        return "\\\\" + p[len("\\\\?\\UNC\\"):]
    if p.startswith("\\\\?\\"):
        return p[len("\\\\?\\"):]
    return p


def _reveal_path_payload(ruta: Path, mode: str) -> dict[str, str | bool]:
    """Rutas para el cliente (navegador). No abre el explorador en el servidor."""
    locs = _signed_path_locations(ruta)
    client_path = locs["client_file"] if mode == "select" else locs["client_folder"]
    server_path = locs["server_file"] if mode == "select" else locs["server_folder"]
    return {
        "ok": True,
        "opened_locally": False,
        "client_path": client_path,
        "client_kind": locs.get("client_kind", "posix"),
        "server_path": server_path,
        "path": client_path,
        **locs,
    }


@app.route("/api/firmados/reveal")
@require_auth("digitalizados:ver_archivo")
def reveal_signed_in_explorer():
    """
    Devuelve rutas para abrir/copiar desde el navegador del usuario.
    No ejecuta explorer/xdg-open en el servidor (evita abrir en la PC del backend).
    """
    _require_reveal_location()
    nombre = request.args.get("n", "")
    a0 = _apartado_from_nombre_firmado(nombre)
    if a0 and a0.codigo not in _effective_apartado_codes():
        abort(403, "Sin acceso a este apartado")
    _require_firmado_carpeta_access(nombre, apartado_codigo=a0.codigo if a0 else None)
    mode = (request.args.get("mode", "select") or "select").strip().lower()
    ruta = _safe_signed_path(nombre, g.db)
    if not ruta:
        abort(404, "Archivo no encontrado")
    return jsonify(_reveal_path_payload(ruta, mode))


@app.route("/api/health")
def health():
    pending = documents.list_pending()
    try:
        eff = path_settings.get_resolved_paths(g.db)
        bandeja = eff["bandeja_entrada"]
        troot = eff["transferencias_root"]
        bing = eff["bandeja_ingresos"]
        ding = eff["destino_ingresos"]
    except Exception:
        bandeja = Config.BANDEJA_ENTRADA
        troot = Config.TRANSFERENCIAS_ROOT
        bing = Config.BANDEJA_INGRESOS
        ding = Config.DESTINO_INGRESOS
    return jsonify({
        "status": "ok",
        "pendientes": len(pending),
        "bandeja": bandeja,
        "bandeja_ingresos": bing,
        "transferencias": troot,
        "destino_ingresos": ding,
        "timestamp": datetime.now().isoformat(),
    })


# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(409)
@app.errorhandler(410)
@app.errorhandler(500)
def handle_error(e):
    return jsonify({"error": str(e.description)}), e.code


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_unc_path(path) -> bool:
    return str(path).replace("/", "\\").startswith("\\\\")


def _safe_signed_path(nombre: str, db) -> Path | None:
    if not nombre or not isinstance(nombre, str):
        return None
    nombre = nombre.strip().replace("\\", "/")
    if len(nombre) > 1024 or "\x00" in nombre or nombre.startswith("/"):
        return None
    parts = [p for p in nombre.split("/") if p]
    if len(parts) < 2 or ".." in parts:
        return None
    pfx = parts[0]
    if len(pfx) > 8:
        return None
    a = apartados_svc.get_by_prefijo(db, pfx, active_only=False)
    if not a:
        return None
    rest = parts[1:]
    last = rest[-1]
    if Path(last).suffix.lower() in _SIGNED_BLOCK_EXT:
        return None
    for p in rest:
        if p in (".", ""):
            return None

    from services.comprobante_text_index import ruta_firmado_desde_bd
    from services.path_settings import resolve_storage_path

    hit = ruta_firmado_desde_bd(db, a.id, last)
    if hit is not None:
        return hit

    try:
        base = resolve_storage_path(a.destino_path)
    except Exception:
        return None

    ruta = base.joinpath(*rest)
    try:
        if ruta.is_file():
            return ruta
    except OSError:
        pass

    if not _is_unc_path(base):
        try:
            if not base.is_dir():
                return None
            r_res = ruta.resolve()
            r_res.relative_to(base.resolve())
            if r_res.is_file():
                return r_res
        except (ValueError, OSError):
            pass

    from services.apartado_paths import SIN_FIRMAR

    sin_firmar = SIN_FIRMAR.upper()
    fname = parts[-1]
    try:
        if not _is_unc_path(base) and not base.is_dir():
            return None
        for candidate in base.rglob(fname):
            if not candidate.is_file():
                continue
            try:
                rel = candidate.relative_to(base)
            except (ValueError, OSError):
                continue
            if any(p.upper() == sin_firmar for p in rel.parts):
                continue
            return candidate
    except OSError:
        pass
    return None


def _pdf_matches(ruta: Path, q: str) -> bool:
    import fitz
    palabras = [p.lower() for p in q.split() if p]
    if not palabras:
        return True
    try:
        doc = fitz.open(str(ruta))
        texto = "\n".join(doc[i].get_text() or "" for i in range(len(doc))).lower()
        doc.close()
        return all(p in texto for p in palabras)
    except Exception:
        return False
