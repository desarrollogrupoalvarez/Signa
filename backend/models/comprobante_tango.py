"""Estado de comprobantes sincronizados desde Tango por apartado."""

from __future__ import annotations

from sqlalchemy import Column, Date, ForeignKey, Integer, String, Text, UniqueConstraint

from models.base import Base, TimestampMixin


class ComprobanteTango(Base, TimestampMixin):
    __tablename__ = "comprobante_tango"
    __table_args__ = (UniqueConstraint("apartado_id", "clave", name="uq_comprobante_tango_apartado_clave"),)

    id = Column(Integer, primary_key=True)
    apartado_id = Column(Integer, ForeignKey("apartados.id", ondelete="CASCADE"), nullable=False, index=True)
    clave = Column(String(512), nullable=False)
    estado = Column(String(20), nullable=False, default="pendiente")  # pendiente | firmado
    pdf_filename = Column(String(512), nullable=False, default="")
    ruta = Column(Text, nullable=True)
    tango_fecha = Column(Date, nullable=True)
    texto_contenido = Column(Text, nullable=True)


