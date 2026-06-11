"""Áreas operativas (Depósitos) que agrupan apartados hijos."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import relationship

from models.base import Base, TimestampMixin

user_area = Table(
    "user_area",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("area_id", Integer, ForeignKey("areas.id", ondelete="CASCADE"), primary_key=True),
)


class Area(Base, TimestampMixin):
    __tablename__ = "areas"

    id = Column(Integer, primary_key=True)
    codigo = Column(String(64), unique=True, nullable=False, index=True)
    nombre = Column(String(200), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    orden = Column(Integer, default=0, nullable=False)

    apartados = relationship("Apartado", back_populates="area", lazy="selectin")
    users = relationship("User", secondary=user_area, back_populates="areas", lazy="dynamic")

    def to_brief(self) -> dict:
        return {
            "id": self.id,
            "codigo": self.codigo,
            "nombre": self.nombre,
            "activo": self.activo,
            "orden": self.orden,
        }

    def to_dict(self) -> dict:
        d = self.to_brief()
        d["apartados"] = [a.to_brief() for a in sorted(self.apartados or [], key=lambda x: (x.orden, x.codigo))]
        return d
