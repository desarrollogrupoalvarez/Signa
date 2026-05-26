from flask import Blueprint, abort, g, jsonify, request

from auth.service import AuthService
from core.middleware import require_auth

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        abort(400, "Usuario y contraseña son requeridos")

    try:
        result = AuthService(g.db).login(username, password)
        return jsonify(result), 200
    except ValueError as e:
        abort(401, str(e))


@bp.route("/me", methods=["GET"])
@require_auth()
def me():
    try:
        user_id = int(g.current_user["sub"])
    except (TypeError, ValueError):
        abort(401, "Token malformado")

    user = AuthService(g.db).get_current_user(user_id)
    if not user:
        abort(404, "Usuario no encontrado")
    return jsonify(user)
