from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from models.apartado import user_apartado
from models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True)
    username      = Column(String(50),  unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role_id       = Column(Integer, ForeignKey("roles.id"), nullable=False)
    is_active     = Column(Boolean, default=True, nullable=False)

    role = relationship("Role", lazy="joined")
    apartados = relationship("Apartado", secondary=user_apartado, back_populates="users", lazy="selectin")

    def to_dict(self) -> dict:
        ap_ids = [a.id for a in sorted(self.apartados or [], key=lambda x: (x.orden, x.codigo))]
        return {
            "id":            self.id,
            "username":      self.username,
            "role":          self.role.name if self.role else None,
            "is_active":     self.is_active,
            "created_at":    self.created_at.isoformat() if self.created_at else None,
            "permissions":   [p.name for p in self.role.permissions] if self.role else [],
            "apartado_ids":  ap_ids,
        }
