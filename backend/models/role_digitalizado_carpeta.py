from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from models.base import Base


class RoleDigitalizadoCarpeta(Base):
    __tablename__ = "role_digitalizado_carpetas"

    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    apartado_id = Column(Integer, ForeignKey("apartados.id", ondelete="CASCADE"), primary_key=True)
    carpeta = Column(String(128), nullable=False, primary_key=True)
    # '' = depósito completo; valor = categoría específica
    categoria = Column(String(128), nullable=False, default="", primary_key=True)

    role = relationship("Role", back_populates="digitalizado_carpetas")
    apartado = relationship("Apartado")

    def to_dict(self) -> dict:
        cat = (self.categoria or "").strip()
        return {
            "apartado_id": self.apartado_id,
            "carpeta": self.carpeta,
            "categoria": cat or None,
        }
