# Import all models so Alembic autogenerate sees them.
from models.base import Base, TimestampMixin
from models.apartado import Apartado, user_apartado
from models.area import Area, user_area
from models.comprobante_tango import ComprobanteTango
from models.permission import Permission
from models.role import Role, role_permissions
from models.role_digitalizado_carpeta import RoleDigitalizadoCarpeta
from models.user import User

__all__ = [
    "Base",
    "TimestampMixin",
    "Apartado",
    "Area",
    "ComprobanteTango",
    "user_apartado",
    "user_area",
    "Permission",
    "Role",
    "RoleDigitalizadoCarpeta",
    "role_permissions",
    "User",
]
