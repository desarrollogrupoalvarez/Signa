from sqlalchemy import Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import relationship
from models.base import Base, TimestampMixin

# Association table (many-to-many)
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id",       Integer, ForeignKey("roles.id",       ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id          = Column(Integer, primary_key=True)
    name        = Column(String(50),  unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=False, default="")

    permissions = relationship("Permission", secondary=role_permissions, lazy="joined")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "permissions": [p.name for p in self.permissions],
        }
