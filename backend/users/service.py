import re

from sqlalchemy.orm import Session

from core.security import hash_password
from users.repository import UsersRepository

_ROLE_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")


class UsersService:
    def __init__(self, db: Session):
        self._repo = UsersRepository(db)
        self._db = db

    # ── Roles ──────────────────────────────────────────────────────────────

    def list_roles(self) -> list[dict]:
        return [r.to_dict() for r in self._repo.list_roles()]

    def list_permissions(self) -> list[dict]:
        return [p.to_dict() for p in self._repo.list_permissions()]

    def create_role(self, name: str, description: str, permissions: list[str]) -> dict:
        self._validate_role_name(name)
        if self._repo.get_role_by_name(name):
            raise ValueError(f"Rol '{name}' ya existe")

        perms = self._resolve_permissions(permissions)
        role = self._repo.create_role(name=name, description=description or "")
        role.permissions = perms
        return role.to_dict()

    def update_role(self, role_id: int, data: dict) -> dict:
        role = self._repo.get_role_by_id(role_id)
        if not role:
            raise LookupError("Rol no encontrado")

        fields = {}
        if "name" in data and data["name"]:
            self._validate_role_name(data["name"])
            existing = self._repo.get_role_by_name(data["name"])
            if existing and existing.id != role_id:
                raise ValueError(f"Rol '{data['name']}' ya existe")
            fields["name"] = data["name"]

        if "description" in data:
            fields["description"] = data.get("description") or ""

        updated = self._repo.update_role(role, **fields)

        if "permissions" in data:
            perms = self._resolve_permissions(data.get("permissions") or [])
            updated.permissions = perms

        return updated.to_dict()

    # ── Users ──────────────────────────────────────────────────────────────

    def list_users(self) -> list[dict]:
        return [u.to_dict() for u in self._repo.list_all()]

    def get_user(self, user_id: int) -> dict:
        user = self._repo.get_by_id(user_id)
        if not user:
            raise LookupError("Usuario no encontrado")
        return user.to_dict()

    def create_user(self, username: str, password: str, role_name: str, apartado_ids: list[int] | None = None) -> dict:
        self._validate_username(username)
        self._validate_password(password)

        if self._repo.get_by_username(username):
            raise ValueError(f"El nombre de usuario '{username}' ya está en uso")

        role = self._repo.get_role_by_name(role_name)
        if not role:
            raise ValueError(f"Rol '{role_name}' no existe")

        user = self._repo.create(
            username=username,
            password_hash=hash_password(password),
            role_id=role.id,
        )
        # Nuevo comportamiento: por defecto, sin apartados (no ve nada).
        # Si el caller provee apartado_ids, se asignan (salvo superadmin).
        if role.name != "superadmin":
            from services import apartados as apartados_svc

            apartados_svc.assign_user_apartados_by_ids(self._db, user, apartado_ids or [])
        return user.to_dict()

    def update_user(self, user_id: int, data: dict) -> dict:
        user = self._repo.get_by_id(user_id)
        if not user:
            raise LookupError("Usuario no encontrado")

        fields = {}

        if "password" in data and data["password"]:
            self._validate_password(data["password"])
            fields["password_hash"] = hash_password(data["password"])

        if "role" in data:
            role = self._repo.get_role_by_name(data["role"])
            if not role:
                raise ValueError(f"Rol '{data['role']}' no existe")
            fields["role_id"] = role.id

        if "is_active" in data:
            fields["is_active"] = bool(data["is_active"])

        has_ap = "apartado_ids" in data

        updated = self._repo.update(user, **fields)
        if has_ap:
            from services import apartados as apartados_svc

            self._db.flush()
            self._db.refresh(updated)
            if updated.role and updated.role.name == "superadmin":
                apartados_svc.assign_user_apartados_by_ids(self._db, updated, [])
            else:
                apartados_svc.assign_user_apartados_by_ids(
                    self._db,
                    updated,
                    [int(x) for x in (data.get("apartado_ids") or []) if x is not None],
                )
            self._db.flush()
        return updated.to_dict()

    def deactivate_user(self, user_id: int, requester_id: int) -> dict:
        if user_id == requester_id:
            raise ValueError("No podés desactivar tu propia cuenta")
        user = self._repo.get_by_id(user_id)
        if not user:
            raise LookupError("Usuario no encontrado")
        updated = self._repo.update(user, is_active=False)
        return updated.to_dict()

    def delete_user(self, user_id: int, requester_id: int) -> dict:
        if user_id == requester_id:
            raise ValueError("No podés eliminar tu propia cuenta")
        user = self._repo.get_by_id(user_id)
        if not user:
            raise LookupError("Usuario no encontrado")
        if user.username == "superadmin":
            raise ValueError("No se puede eliminar el usuario superadmin")
        payload = user.to_dict()
        self._repo.delete(user)
        return payload

    # ── Validators ─────────────────────────────────────────────────────────

    def _validate_username(self, username: str) -> None:
        if not username or len(username) < 3:
            raise ValueError("El nombre de usuario debe tener al menos 3 caracteres")
        if not re.match(r"^[a-zA-Z0-9_.-]+$", username):
            raise ValueError("El nombre de usuario solo puede contener letras, números, _, . y -")

    def _validate_password(self, password: str) -> None:
        if not password:
            raise ValueError("La contraseña no puede estar vacía")

    def _validate_role_name(self, name: str) -> None:
        if not name or len(name) < 3:
            raise ValueError("El nombre del rol debe tener al menos 3 caracteres")
        if not _ROLE_RE.match(name):
            raise ValueError("El nombre del rol solo puede contener letras, números, _, . y -")

    def _resolve_permissions(self, names: list[str]) -> list:
        if not isinstance(names, list):
            raise ValueError("permissions debe ser una lista de strings")
        resolved = []
        missing = []
        for n in names:
            n = (n or "").strip()
            if not n:
                continue
            perm = self._repo.get_permission_by_name(n)
            if not perm:
                missing.append(n)
            else:
                resolved.append(perm)
        if missing:
            raise ValueError("Permisos inexistentes: " + ", ".join(missing))
        # dedupe while preserving order
        seen = set()
        out = []
        for p in resolved:
            if p.id in seen:
                continue
            seen.add(p.id)
            out.append(p)
        return out
