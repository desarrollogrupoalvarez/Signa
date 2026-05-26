import logging

from sqlalchemy.orm import Session

from auth.repository import AuthRepository
from core.jwt_utils import create_token
from core.security import verify_password

logger = logging.getLogger("remitos")


class AuthService:
    def __init__(self, db: Session):
        self._db = db
        self._repo = AuthRepository(db)

    def login(self, username: str, password: str) -> dict:
        user = self._repo.get_by_username(username)

        # Use constant-time comparison to avoid timing attacks
        if not user or not verify_password(password, user.password_hash):
            logger.warning(f"LOGIN_FALLIDO | username={username}")
            raise ValueError("Usuario o contraseña incorrectos")

        if not user.is_active:
            logger.warning(f"LOGIN_INACTIVO | username={username}")
            raise ValueError("Cuenta desactivada. Contactá al administrador")

        permissions = [p.name for p in user.role.permissions]
        from services import apartados as ap

        ap_codes = ap.codigos_for_jwt_user(self._db, user)
        token = create_token({
            # PyJWT valida que `sub` sea string (RFC 7519). Guardamos el id como string
            # y lo parseamos a int donde corresponda.
            "sub":         str(user.id),
            "username":    user.username,
            "role":        user.role.name,
            "permissions": permissions,
            "apartados":   ap_codes,
        })

        logger.info(f"LOGIN_OK | username={username} | role={user.role.name}")
        d = user.to_dict()
        d["apartados"] = ap.briefs_for_effective_user(self._db, user)
        return {
            "token": token,
            "user":  d,
        }

    def get_current_user(self, user_id: int) -> dict | None:
        from services import apartados as ap

        user = self._repo.get_by_id(user_id)
        if not user:
            return None
        d = user.to_dict()
        d["apartados"] = ap.briefs_for_effective_user(self._db, user)
        return d
