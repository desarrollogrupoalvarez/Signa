from flask import Blueprint, abort, g, jsonify, request

from core.middleware import require_auth
from users.service import UsersService

bp = Blueprint("users", __name__, url_prefix="/api")


# ── Roles ─────────────────────────────────────────────────────────────────────

@bp.route("/roles", methods=["GET"])
@require_auth("roles:listar")
def list_roles():
    return jsonify(UsersService(g.db).list_roles())

@bp.route("/roles", methods=["POST"])
@require_auth("roles:gestionar")
def create_role():
    data = request.get_json(force=True) or {}
    required = ("name", "permissions")
    missing = [f for f in required if data.get(f) is None or data.get(f) == ""]
    if missing:
        abort(400, f"Campos requeridos: {', '.join(missing)}")
    try:
        role = UsersService(g.db).create_role(
            name=(data.get("name") or "").strip(),
            description=(data.get("description") or "").strip(),
            permissions=data.get("permissions") or [],
            digitalizado_carpetas=data.get("digitalizado_carpetas"),
        )
        g.db.commit()
        return jsonify(role), 201
    except ValueError as e:
        abort(400, str(e))


@bp.route("/roles/<int:role_id>", methods=["PUT"])
@require_auth("roles:gestionar")
def update_role(role_id):
    data = request.get_json(force=True) or {}
    try:
        role = UsersService(g.db).update_role(role_id, data)
        g.db.commit()
        return jsonify(role)
    except LookupError as e:
        abort(404, str(e))
    except ValueError as e:
        abort(400, str(e))


@bp.route("/roles/<int:role_id>", methods=["DELETE"])
@require_auth("roles:eliminar")
def delete_role(role_id):
    try:
        role = UsersService(g.db).delete_role(role_id)
        g.db.commit()
        return jsonify({"ok": True, "role": role})
    except LookupError as e:
        abort(404, str(e))
    except ValueError as e:
        abort(400, str(e))


@bp.route("/permissions", methods=["GET"])
@require_auth("roles:listar")
def list_permissions():
    return jsonify(UsersService(g.db).list_permissions())


# ── Users ─────────────────────────────────────────────────────────────────────

@bp.route("/users", methods=["GET"])
@require_auth("usuarios:listar")
def list_users():
    return jsonify(UsersService(g.db).list_users())


@bp.route("/users", methods=["POST"])
@require_auth("usuarios:crear")
def create_user():
    data = request.get_json(force=True) or {}
    required = ("username", "password", "role")
    missing = [f for f in required if not data.get(f)]
    if missing:
        abort(400, f"Campos requeridos: {', '.join(missing)}")
    try:
        apartado_ids = data.get("apartado_ids")
        if apartado_ids is not None and not isinstance(apartado_ids, list):
            abort(400, "apartado_ids debe ser una lista de ids")
        area_ids = data.get("area_ids")
        if area_ids is not None and not isinstance(area_ids, list):
            abort(400, "area_ids debe ser una lista de ids")
        user = UsersService(g.db).create_user(
            username=data["username"].strip(),
            password=data["password"],
            role_name=data["role"].strip(),
            apartado_ids=[int(x) for x in (apartado_ids or []) if x is not None] if apartado_ids is not None else None,
            area_ids=[int(x) for x in (area_ids or []) if x is not None] if area_ids is not None else None,
        )
        g.db.commit()
        return jsonify(user), 201
    except ValueError as e:
        abort(400, str(e))


@bp.route("/users/<int:user_id>", methods=["GET"])
@require_auth("usuarios:listar")
def get_user(user_id):
    try:
        return jsonify(UsersService(g.db).get_user(user_id))
    except LookupError as e:
        abort(404, str(e))


@bp.route("/users/<int:user_id>", methods=["PUT"])
@require_auth("usuarios:editar")
def update_user(user_id):
    data = request.get_json(force=True) or {}
    try:
        user = UsersService(g.db).update_user(user_id, data)
        g.db.commit()
        return jsonify(user)
    except LookupError as e:
        abort(404, str(e))
    except ValueError as e:
        abort(400, str(e))


@bp.route("/users/<int:user_id>", methods=["DELETE"])
@require_auth("usuarios:eliminar")
def deactivate_user(user_id):
    try:
        try:
            requester_id = int(g.current_user["sub"])
        except (TypeError, ValueError):
            abort(401, "Token malformado")

        user = UsersService(g.db).deactivate_user(user_id, requester_id)
        g.db.commit()
        return jsonify({"ok": True, "user": user})
    except LookupError as e:
        abort(404, str(e))
    except ValueError as e:
        abort(400, str(e))


@bp.route("/users/<int:user_id>/purge", methods=["DELETE"])
@require_auth("usuarios:eliminar")
def purge_user(user_id):
    try:
        try:
            requester_id = int(g.current_user["sub"])
        except (TypeError, ValueError):
            abort(401, "Token malformado")

        deleted = UsersService(g.db).delete_user(user_id, requester_id)
        g.db.commit()
        return jsonify({"ok": True, "deleted": deleted})
    except LookupError as e:
        abort(404, str(e))
    except ValueError as e:
        abort(400, str(e))
