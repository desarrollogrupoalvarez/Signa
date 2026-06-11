from config import Config
from flask import Blueprint, abort, g, jsonify, request

from core.apartado_admin import (
    PERM_CREAR,
    PERM_EDITAR,
    PERM_GESTIONAR,
    PERM_RUTAS_LEGACY,
    can_crear_apartados,
    can_list_apartados_admin,
    can_gestionar_todos,
    permissions_from_payload,
    query_apartados_admin,
    query_apartados_asignables,
    user_puede_editar_apartado,
)
from core.middleware import require_auth
from models.apartado import Apartado
from services import areas as areas_svc
from services import documents, path_settings
from services import apartados as apartados_svc



def _current_db_user():
    from models.user import User
    from sqlalchemy.orm import joinedload

    try:
        uid = int(g.current_user["sub"])
    except (TypeError, ValueError, KeyError):
        abort(401, "Token malformado")
    u = g.db.query(User).options(joinedload(User.role), joinedload(User.apartados), joinedload(User.areas)).get(uid)
    if not u:
        abort(404, "Usuario no encontrado")
    return u


def _auth_context():
    user = _current_db_user()
    role = user.role.name if user.role else None
    perms = permissions_from_payload(g.current_user)
    return user, role, perms


bp = Blueprint("apartados", __name__, url_prefix="/api/apartados")

_LIST_PERMS = [PERM_GESTIONAR, PERM_EDITAR, PERM_CREAR, PERM_RUTAS_LEGACY]


@bp.route("", methods=["GET"])
@require_auth(_LIST_PERMS)
def list_all():
    user, role, perms = _auth_context()
    if not can_list_apartados_admin(perms, role):
        abort(403, "Sin permiso para listar apartados")
    rows = query_apartados_admin(g.db, user, role, perms).all()
    return jsonify([a.to_dict() for a in rows])


@bp.route("", methods=["POST"])
@require_auth([PERM_GESTIONAR, PERM_CREAR])
def create():
    user, role, perms = _auth_context()
    if not can_crear_apartados(perms, role):
        abort(403, "Solo usuarios con permiso de creación pueden dar de alta apartados")
    data = request.get_json(force=True) or {}
    try:
        area_id = data.get("area_id")
        if area_id is None:
            abort(400, "area_id requerido")
        a = apartados_svc.create_apartado(
            g.db,
            codigo=(data.get("codigo") or "").strip(),
            nombre=(data.get("nombre") or "").strip(),
            bandeja_path=(data.get("bandeja_path") or "").strip(),
            destino_path=(data.get("destino_path") or "").strip(),
            modo_flujo=(data.get("modo_flujo") or "").strip(),
            prefijo=(data.get("prefijo") or "").strip(),
            area_id=int(area_id),
            activo=bool(data.get("activo", True)),
            orden=data.get("orden"),
            cod_deposito=(data.get("cod_deposito") or "").strip(),
            depositos_config=data.get("depositos_config"),
            categorias_destino=data.get("categorias_destino"),
        )
        g.db.commit()
        from pathlib import Path

        for p in (a.bandeja_path, a.destino_path):
            try:
                Path(p).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        try:
            documents.restart_inbox_watcher()
        except Exception as ex:
            from logging import getLogger

            getLogger("remitos").warning("restart_inbox_watcher: %s", ex)
        path_settings.invalidate_cache()
        return jsonify(a.to_dict()), 201
    except ValueError as e:
        abort(400, str(e))


@bp.route("/<int:apartado_id>", methods=["PUT"])
@require_auth([PERM_GESTIONAR, PERM_EDITAR, PERM_RUTAS_LEGACY])
def update(apartado_id: int):
    user, role, perms = _auth_context()
    if not user_puede_editar_apartado(g.db, user, role, perms, apartado_id):
        abort(403, "Sin permiso para modificar este apartado")
    data = request.get_json(force=True) or {}
    a = apartados_svc.get_by_id(g.db, apartado_id)
    if not a:
        abort(404, "Apartado no encontrado")
    try:
        apartados_svc.apply_apartado_config_fields(a, data)
    except ValueError as e:
        abort(400, str(e))
    g.db.commit()
    path_settings.invalidate_cache()
    try:
        documents.restart_inbox_watcher()
    except Exception as ex:
        from logging import getLogger

        getLogger("remitos").warning("restart_inbox_watcher: %s", ex)
    return jsonify(a.to_dict())


@bp.route("/<int:apartado_id>", methods=["DELETE"])
@require_auth(PERM_GESTIONAR)
def delete(apartado_id: int):
    user, role, perms = _auth_context()
    if not can_gestionar_todos(perms, role):
        abort(403, "Solo usuarios con gestión total pueden eliminar apartados")
    role_name = role
    a = apartados_svc.get_by_id(g.db, apartado_id)
    if not a:
        abort(404, "Apartado no encontrado")
    if a.area_id and a.activo:
        remaining = apartados_svc.count_apartados_modo_en_area(g.db, a.area_id, a.modo_flujo)
        if remaining <= 1:
            abort(
                400,
                f"No se puede eliminar el ultimo apartado de modo '{a.modo_flujo}' en esta area",
            )
    g.db.delete(a)
    g.db.commit()
    path_settings.invalidate_cache()
    try:
        documents.restart_inbox_watcher()
    except Exception as ex:
        from logging import getLogger

        getLogger("remitos").warning("restart_inbox_watcher: %s", ex)
    return jsonify({"ok": True})



@bp.route("/carpetas-disponibles", methods=["GET"])
@require_auth("roles:gestionar")
def carpetas_disponibles():
    from services.digitalizado_access import listar_carpetas_disponibles

    return jsonify(listar_carpetas_disponibles(g.db))


@bp.route("/<codigo>/sincronizar-tango", methods=["POST"])
@require_auth("pendientes:ver")
def sincronizar_tango(codigo: str):
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    from core.apartado_access import apartado_codes_for_user
    from services import tango_sync

    user = _current_db_user()
    role = user.role.name if user.role else None
    allowed = apartado_codes_for_user(g.db, user, role)
    c = (codigo or "").strip()
    if c not in allowed:
        abort(403, "Sin acceso a este apartado")

    a = apartados_svc.get_by_codigo(g.db, c, active_only=True)
    if not a:
        abort(404, "Apartado no encontrado")

    data = request.get_json(force=True, silent=True) or {}
    fecha_s = (data.get("fecha") or "").strip()
    if fecha_s:
        try:
            fecha = date.fromisoformat(fecha_s[:10])
        except ValueError:
            abort(400, "fecha invalida (YYYY-MM-DD)")
    else:
        fecha = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()

    if not Config.tango_configured():
        abort(503, "Tango no configurado en el servidor")

    es_super = role == "superadmin"
    result = tango_sync.sync_apartado(
        g.db,
        a,
        fecha,
        solicitante_username=user.username,
        solicitante_es_superadmin=es_super,
    )
    generados = result.get("generados") or []
    if generados:
        try:
            from services.documents import invalidate_pendientes_indice

            invalidate_pendientes_indice(a.id)
        except Exception:
            pass
    return jsonify({"ok": True, "fecha": fecha.isoformat(), **result})


@bp.route("/<codigo>/tango-ping", methods=["GET"])
@require_auth("pendientes:ver")
def tango_ping_route(codigo: str):
    from core.apartado_access import apartado_codes_for_user

    user = _current_db_user()
    role = user.role.name if user.role else None
    allowed = apartado_codes_for_user(g.db, user, role)
    c = (codigo or "").strip()
    if c not in allowed:
        abort(403, "Sin acceso a este apartado")
    if not Config.tango_configured():
        return jsonify({"ok": False, "error": "Tango no configurado"}), 503
    try:
        from services.tango_connection import ping_all_sources

        return jsonify(ping_all_sources())
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)}), 502


@bp.route("/asignables", methods=["GET"])
@require_auth("usuarios:editar")
def list_asignables():
    user, role, perms = _auth_context()
    rows = query_apartados_asignables(g.db, user, role, perms).all()
    return jsonify(areas_svc.asignables_tree(g.db, rows))
