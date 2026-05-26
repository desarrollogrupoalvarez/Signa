"""
Audit log helpers.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from config import Config

logger = logging.getLogger("remitos")


def record(
    doc: dict,
    dispositivo: str,
    ip: str,
    page_num: int,
    placement: dict,
    ruta_firmado: Path,
    hash_firmado: str,
    ruta_relativa: str | None = None,
) -> None:
    audit_dir = Path(Config.LOG_DIR) / "auditoria"
    audit_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "doc_id": doc["id"],
        "nombre_original": doc["nombre"],
        "nombre_firmado": ruta_firmado.name,
        "ruta_relativa": ruta_relativa,
        "ruta_completa": str(ruta_firmado),
        "dispositivo": dispositivo,
        "ip": ip,
        "pagina": page_num,
        "placement": placement,
        "recibido_en": doc["recibido_en"],
        "firmado_en": datetime.now().isoformat(),
        "hash_original": doc["hash_original"],
        "hash_firmado": hash_firmado,
    }
    path = audit_dir / f"{doc['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)


def record_ingreso_completado(
    doc: dict,
    dispositivo: str,
    ip: str,
    ruta_destino: Path,
    hash_archivo: str,
    ruta_relativa: str | None,
) -> None:
    """Ingreso cerrado sin firma digital (solo escaneos anexados al PDF)."""
    audit_dir = Path(Config.LOG_DIR) / "auditoria"
    audit_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "doc_id": doc["id"],
        "tipo": "ingreso_completado_sin_firma",
        "nombre_original": doc["nombre"],
        "nombre_destino": ruta_destino.name,
        "ruta_relativa": ruta_relativa,
        "ruta_completa": str(ruta_destino),
        "dispositivo": dispositivo,
        "ip": ip,
        "recibido_en": doc["recibido_en"],
        "completado_en": datetime.now().isoformat(),
        "hash_original": doc["hash_original"],
        "hash_destino": hash_archivo,
    }
    path = audit_dir / f"{doc['id']}_ingreso_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)


def record_transferencia_sin_firma(
    doc: dict,
    dispositivo: str,
    ip: str,
    ruta_destino: Path,
    hash_archivo: str,
    ruta_relativa: str | None,
) -> None:
    """Transferencia archivada en destino sin firma digital en el PDF."""
    audit_dir = Path(Config.LOG_DIR) / "auditoria"
    audit_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "doc_id": doc["id"],
        "tipo": "transferencia_archivada_sin_firma",
        "nombre_original": doc["nombre"],
        "nombre_destino": ruta_destino.name,
        "ruta_relativa": ruta_relativa,
        "ruta_completa": str(ruta_destino),
        "dispositivo": dispositivo,
        "ip": ip,
        "recibido_en": doc["recibido_en"],
        "archivado_en": datetime.now().isoformat(),
        "hash_original": doc["hash_original"],
        "hash_destino": hash_archivo,
    }
    path = audit_dir / f"{doc['id']}_tra_sin_firma_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
