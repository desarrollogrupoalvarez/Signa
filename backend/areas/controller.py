"""Blueprint CRUD de areas / depositos."""

from flask import Blueprint, abort, g, jsonify, request

from core.apartado_admin import PERM_CREAR, PERM_EDITAR, PERM_GESTIONAR, can_gestionar_todos, permissions_from_payload
from core.middleware import require_auth
from services import areas as areas_svc

bp = Blueprint("areas", __name__, url_prefix="/api/areas")

_LIST_PERMS = [PERM_GESTIONAR, PERM_EDITAR, PERM_CREAR]


def _auth_context():
    from models.user import User
    from sqlalchemy.orm import joinedload

    try:
        uid = int(g.current_user["sub"])
    except (TypeError, ValueError, KeyError):
        abort(401, "Token malformado")
    u = g.db.query(User).options(joinedload(User.role)).get(uid)
    if not u:
        abort(404, "Usuario no encontrado")
    role = u.role.name if u.role else None
    perms = permissions_from_payload(g.current_user)
    return u, role, perms


@bp.route("", methods=["GET"])
@require_auth(_LIST_PERMS)
def list_areas():
    user, role, perms = _auth_context()
    from core.apartado_admin import can_list_apartados_admin

    if not can_list_apartados_admin(perms, role):
        abort(403, "Sin permiso para listar areas")
    rows = areas_svc.list_areas(g.db)
    return jsonify([a.to_dict() for a in rows])


@bp.route("", methods=["POST"])
@require_auth([PERM_GESTIONAR, PERM_CREAR])
def create_area():
    user, role, perms = _auth_context()
    if not can_gestionar_todos(perms, role) and PERM_CREAR not in perms:
        abort(403, "Sin permiso para crear areas")
    data = request.get_json(force=True) or {}
    try:
        area = areas_svc.create_area(
            g.db,
            codigo=(data.get("codigo") or "").strip(),
            nombre=(data.get("nombre") or "").strip(),
            activo=bool(data.get("activo", True)),
            orden=data.get("orden"),
        )
        g.db.commit()
        return jsonify(area.to_dict()), 201
    except ValueError as e:
        abort(400, str(e))


@bp.route("/<int:area_id>", methods=["PUT"])
@require_auth(PERM_GESTIONAR)
def update_area(area_id: int):
    user, role, perms = _auth_context()
    if not can_gestionar_todos(perms, role):
        abort(403, "Solo usuarios con gestion total pueden editar areas")
    area = areas_svc.get_by_id(g.db, area_id)
    if not area:
        abort(404, "Area no encontrada")
    data = request.get_json(force=True) or {}
    try:
        areas_svc.update_area(g.db, area, data)
        g.db.commit()
        return jsonify(area.to_dict())
    except ValueError as e:
        abort(400, str(e))


@bp.route("/<int:area_id>", methods=["DELETE"])
@require_auth(PERM_GESTIONAR)
def delete_area(area_id: int):
    user, role, perms = _auth_context()
    if not can_gestionar_todos(perms, role):
        abort(403, "Solo usuarios con gestion total pueden eliminar areas")
    area = areas_svc.get_by_id(g.db, area_id)
    if not area:
        abort(404, "Area no encontrada")
    try:
        areas_svc.delete_area(g.db, area)
        g.db.commit()
        return jsonify({"ok": True})
    except ValueError as e:
        abort(400, str(e))
