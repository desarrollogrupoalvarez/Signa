import re

from sqlalchemy.orm import Session

from core.permissions import (
    LEGACY_PERMISSION_NAMES,
    PERM_DIGITALIZADOS_VER,
    PERM_DIGITALIZADOS_VER_TODO,
    PERM_PENDIENTES_VER,
    RESERVED_ROLE_NAMES,
)
from core.security import hash_password
from models.apartado import Apartado
from models.role_digitalizado_carpeta import RoleDigitalizadoCarpeta
from services.apartado_paths import depositos_from_json
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
        from core.permissions import LEGACY_PERMISSION_NAMES

        return [
            p.to_dict()
            for p in self._repo.list_permissions()
            if p.name not in LEGACY_PERMISSION_NAMES
        ]

    def create_role(self, name: str, description: str, permissions: list[str], digitalizado_carpetas: list | None = None) -> dict:
        self._validate_role_name(name)
        if self._repo.get_role_by_name(name):
            raise ValueError(f"Rol '{name}' ya existe")

        perms = self._resolve_permissions(permissions)
        self._validate_digitalizado_carpetas(perms, digitalizado_carpetas)
        role = self._repo.create_role(name=name, description=description or "")
        role.permissions = perms
        self._apply_digitalizado_carpetas(role, digitalizado_carpetas)
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

        perm_names = {p.name for p in updated.permissions}
        carpetas = data.get("digitalizado_carpetas") if "digitalizado_carpetas" in data else None
        if carpetas is not None or "permissions" in data:
            if carpetas is None and "permissions" in data:
                carpetas = [c.to_dict() for c in (updated.digitalizado_carpetas or [])]
            self._validate_digitalizado_carpetas(updated.permissions, carpetas)
            self._apply_digitalizado_carpetas(updated, carpetas)

        if PERM_DIGITALIZADOS_VER not in perm_names:
            updated.digitalizado_carpetas = []

        return updated.to_dict()

    def delete_role(self, role_id: int) -> dict:
        role = self._repo.get_role_by_id(role_id)
        if not role:
            raise LookupError("Rol no encontrado")
        if role.name in RESERVED_ROLE_NAMES:
            raise ValueError(f"No se puede eliminar el rol reservado '{role.name}'")
        from models.user import User

        users_count = self._db.query(User).filter(User.role_id == role.id).count()
        if users_count:
            raise ValueError("No se puede eliminar un rol con usuarios asignados")
        payload = role.to_dict()
        self._repo.delete_role(role)
        return payload

    # ── Users ──────────────────────────────────────────────────────────────

    def list_users(self) -> list[dict]:
        return [u.to_dict() for u in self._repo.list_all()]

    def get_user(self, user_id: int) -> dict:
        user = self._repo.get_by_id(user_id)
        if not user:
            raise LookupError("Usuario no encontrado")
        return user.to_dict()

    def create_user(self, username: str, password: str, role_name: str, apartado_ids: list[int] | None = None, area_ids: list[int] | None = None) -> dict:
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
        if role.name != "superadmin":
            from services import apartados as apartados_svc

            apartados_svc.assign_user_areas_by_ids(self._db, user, area_ids or [])
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
        has_area = "area_ids" in data

        updated = self._repo.update(user, **fields)
        if has_ap or has_area:
            from services import apartados as apartados_svc

            self._db.flush()
            self._db.refresh(updated)
            if updated.role and updated.role.name == "superadmin":
                apartados_svc.assign_user_apartados_by_ids(self._db, updated, [])
                apartados_svc.assign_user_areas_by_ids(self._db, updated, [])
            else:
                if has_area:
                    apartados_svc.assign_user_areas_by_ids(
                        self._db,
                        updated,
                        [int(x) for x in (data.get("area_ids") or []) if x is not None],
                    )
                if has_ap:
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
        resolved = [p for p in resolved if p.name not in LEGACY_PERMISSION_NAMES]
        seen = set()
        out = []
        for p in resolved:
            if p.id in seen:
                continue
            seen.add(p.id)
            out.append(p)
        return out

    def _validate_digitalizado_carpetas(self, perms, carpetas: list | None) -> None:
        perm_names = {p.name for p in perms}
        if PERM_DIGITALIZADOS_VER not in perm_names:
            return
        if PERM_DIGITALIZADOS_VER_TODO in perm_names:
            return
        if not carpetas:
            raise ValueError(
                "Con acceso a Digitalizados sin 'ver todo', debe seleccionar al menos una carpeta"
            )

    def _apply_digitalizado_carpetas(self, role, carpetas: list | None) -> None:
        role.digitalizado_carpetas = []
        if not carpetas:
            self._db.flush()
            return
        valid = self._valid_carpeta_keys()
        seen: set[tuple[int, str, str]] = set()
        for item in carpetas:
            if not isinstance(item, dict):
                continue
            try:
                apartado_id = int(item.get("apartado_id"))
            except (TypeError, ValueError):
                continue
            carpeta = (item.get("carpeta") or "").strip()
            if not carpeta:
                continue
            categoria = (item.get("categoria") or "").strip()
            key = (apartado_id, carpeta.upper(), categoria.upper())
            if key not in valid:
                raise ValueError(f"Carpeta no válida para el apartado: {carpeta}")
            if key in seen:
                continue
            seen.add(key)
            role.digitalizado_carpetas.append(
                RoleDigitalizadoCarpeta(
                    apartado_id=apartado_id,
                    carpeta=carpeta,
                    categoria=categoria,
                )
            )
        self._db.flush()

    def _valid_carpeta_keys(self) -> set[tuple[int, str, str]]:
        out: set[tuple[int, str, str]] = set()
        for a in self._db.query(Apartado).filter(Apartado.activo.is_(True)).all():
            for dep in depositos_from_json(a.depositos_config):
                cu = dep.carpeta.upper()
                out.add((int(a.id), cu, ""))
                for cat in dep.categorias or ():
                    out.add((int(a.id), cu, cat.nombre.upper()))
        return out
