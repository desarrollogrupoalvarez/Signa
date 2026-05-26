# Import all models so Alembic autogenerate sees them.
from models.base import Base, TimestampMixin
from models.apartado import Apartado, user_apartado
from models.comprobante_tango import ComprobanteTango
from models.permission import Permission
from models.role import Role, role_permissions
from models.user import User

__all__ = [
    "Base",
    "TimestampMixin",
    "Apartado",
    "ComprobanteTango",
    "user_apartado",
    "Permission",
    "Role",
    "role_permissions",
    "User",
]
