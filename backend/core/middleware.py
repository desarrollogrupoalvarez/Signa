import logging
from functools import wraps

import jwt
from flask import abort, g, request

from core.jwt_utils import decode_token

logger = logging.getLogger("remitos")


def _extract_token() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.headers.get("X-Auth-Token") or request.args.get("token") or None


def require_auth(permission: str | list[str] | None = None):
    """
    Decorator that:
      1. Validates the JWT from Authorization: Bearer <token> or X-Auth-Token header.
      2. Optionally checks that `permission` (or any of a list) is in the token's permission list.
      3. Stores the decoded payload in Flask's `g.current_user`.

    Usage:
        @require_auth()                         # just authenticated
        @require_auth("documentos:firmar")      # authenticated + specific permission
        @require_auth(["apartados:crear", "apartados:gestionar"])
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            token = _extract_token()
            if not token:
                abort(401, "Token de autenticación requerido")

            try:
                payload = decode_token(token)
            except jwt.ExpiredSignatureError:
                abort(401, "Token expirado")
            except jwt.InvalidTokenError as e:
                logger.warning(f"JWT inválido: {e} | ip={request.remote_addr}")
                abort(401, "Token inválido")

            if not payload.get("sub"):
                abort(401, "Token malformado")

            if permission:
                required = [permission] if isinstance(permission, str) else list(permission)
                user_perms = payload.get("permissions", [])
                if not any(p in user_perms for p in required):
                    logger.warning(
                        f"ACCESO_DENEGADO | user={payload.get('username')} "
                        f"| perm={required} | ip={request.remote_addr}"
                    )
                    abort(403, f"Permiso requerido: {', '.join(required)}")

            g.current_user = payload
            return f(*args, **kwargs)
        return wrapper
    return decorator
