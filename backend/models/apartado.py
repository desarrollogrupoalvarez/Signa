"""
Apartados: bandeja, destino firmados y modo de flujo; asignación por usuario vía `user_apartado`.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import relationship

from models.base import Base, TimestampMixin

user_apartado = Table(
    "user_apartado",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("apartado_id", Integer, ForeignKey("apartados.id", ondelete="CASCADE"), primary_key=True),
)


class Apartado(Base, TimestampMixin):
    __tablename__ = "apartados"

    id = Column(Integer, primary_key=True)
    codigo = Column(String(64), unique=True, nullable=False, index=True)
    nombre = Column(String(200), nullable=False)
    bandeja_path = Column(String(2000), nullable=False)
    destino_path = Column(String(2000), nullable=False)
    modo_flujo = Column(String(20), nullable=False)  # transferencia | ingreso
    prefijo = Column(String(8), unique=True, nullable=False)
    # Palabras clave (comma/semicolon/newline-separated). Si alguna aparece en el texto del PDF, se considera Importante.
    keywords_importante = Column(String(1000), nullable=False, default="")
    cod_deposito = Column(String(64), nullable=False, default="2")
    # JSON: [{"carpeta","tango_fuente","cod_depositos":[]}, ...]
    depositos_config = Column(Text, nullable=False, default="[]")
    # JSON: [{"nombre","keywords"?}, ...] — solo transferencia
    categorias_destino = Column(Text, nullable=False, default="[]")
    activo = Column(Boolean, default=True, nullable=False)
    orden = Column(Integer, default=0, nullable=False)

    users = relationship("User", secondary=user_apartado, back_populates="apartados", lazy="dynamic")

    def to_brief(self) -> dict:
        return {
            "id": self.id,
            "codigo": self.codigo,
            "nombre": self.nombre,
            "modo_flujo": self.modo_flujo,
            "prefijo": self.prefijo,
            "orden": self.orden,
        }

    def to_dict(self) -> dict:
        from services.apartado_paths import categorias_from_json, parse_depositos

        d = self.to_brief()
        deps = parse_depositos(self)
        cats = categorias_from_json(self.categorias_destino)
        d.update(
            {
                "bandeja_path": self.bandeja_path,
                "destino_path": self.destino_path,
                "keywords_importante": self.keywords_importante or "",
                "cod_deposito": (self.cod_deposito or "").strip(),
                "depositos_config": [
                    {
                        "carpeta": x.carpeta,
                        "tango_fuente": x.tango_fuente,
                        "cod_depositos": list(x.cod_depositos),
                        "categorias": [
                            {"nombre": c.nombre, **({"keywords": c.keywords} if c.keywords else {})}
                            for c in x.categorias
                        ],
                    }
                    for x in deps
                ],
                "categorias_destino": [
                    {"nombre": x.nombre, **({"keywords": x.keywords} if x.keywords else {})}
                    for x in cats
                ],
                "activo": self.activo,
                "orden": self.orden,
            }
        )
        return d
