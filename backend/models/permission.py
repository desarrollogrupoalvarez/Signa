from sqlalchemy import Column, Integer, String
from models.base import Base, TimestampMixin


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    id          = Column(Integer, primary_key=True)
    name        = Column(String(100), unique=True, nullable=False, index=True)  # e.g. "documentos:firmar"
    description = Column(String(255), nullable=False, default="")
    resource    = Column(String(50),  nullable=False)   # e.g. "documentos"
    action      = Column(String(50),  nullable=False)   # e.g. "firmar"

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "description": self.description,
                "resource": self.resource, "action": self.action}
