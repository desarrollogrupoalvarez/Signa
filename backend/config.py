import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

try:
    from dotenv import load_dotenv
    # En Windows el `.env` a veces está guardado como ANSI/CP1252 y además puede
    # existir `DATABASE_URL` a nivel sistema. Cargamos el `.env` forzando override
    # y probando encodings comunes para evitar que una `UnicodeDecodeError` deje
    # la app usando el fallback por defecto.
    _dotenv_path = BASE_DIR / ".env"
    for _enc in ("utf-8", "utf-8-sig", "cp1252", None):
        try:
            load_dotenv(_dotenv_path, override=True, encoding=_enc)
            break
        except UnicodeDecodeError:
            continue
except Exception:
    pass

_DEFAULT_ENTRADA = str(BASE_DIR / "datos" / "Bandeja_Entrada")
_DEFAULT_FIRMADOS = str(BASE_DIR / "datos" / "Remitos_Firmados")
# Carpeta «Transferencias» (ya creada); debajo: Importante|Regulares, Año, mes.
_DEFAULT_TRANSFERENCIAS_ROOT = str(BASE_DIR / "datos" / "Transferencias")
# Ingresos Tango (prefijo IN_): bandeja y destino separados de TRA
_DEFAULT_BANDEJA_INGRESOS = str(BASE_DIR / "datos" / "Bandeja_Ingresos")
_DEFAULT_DESTINO_INGRESOS = str(BASE_DIR / "datos" / "Ingresos")

# Claves en app_settings (tabla app_settings)
SETTING_PATH_BANDEJA = "path_bandeja"
SETTING_PATH_TRANSFERENCIAS = "path_transferencias"
SETTING_PATH_BANDEJA_INGRESOS = "path_bandeja_ingresos"
SETTING_PATH_DESTINO_INGRESOS = "path_destino_ingresos"

# Nombres de carpeta por depósito (configurables por apartado; defaults aquí)
CARPETA_AGROINDUSTRIAS = "AGROINDUSTRIAS"
CARPETA_TELECOMUNICACIONES = "TELECOMUNICACIONES"

# Legacy: inferencia de rutas ya archivadas en disco
DIR_TRANSFERENCIAS_SAN_RAFAEL = "TRANSFERENCIAS_SAN_RAFAEL"
DIR_TRANSFERENCIAS_CTC = "TRANSFERENCIAS_CTC"
BANDEJA_SUBDIR_SAN_RAFAEL = "SAN_RAFAEL_2011"
BANDEJA_SUBDIR_CTC = "CTC"
TANGO_FUENTE_SAN_RAFAEL = "SAN_RAFAEL"
TANGO_FUENTE_CTC = "CTC"


@dataclass(frozen=True)
class TangoTransferenciaSource:
    """Conexión a base Tango (id interno + nombre de base SQL)."""

    id: str
    database: str


class Config:
    # REMITOS_FIRMADOS: compat con despliegues antiguos (.env); la salida firmada usa TRANSFERENCIAS_ROOT.
    BANDEJA_ENTRADA = os.environ.get("BANDEJA_ENTRADA", _DEFAULT_ENTRADA)
    REMITOS_FIRMADOS = os.environ.get("REMITOS_FIRMADOS", _DEFAULT_FIRMADOS)
    TRANSFERENCIAS_ROOT = os.environ.get("TRANSFERENCIAS_ROOT", _DEFAULT_TRANSFERENCIAS_ROOT)
    BANDEJA_INGRESOS = os.environ.get("BANDEJA_INGRESOS", _DEFAULT_BANDEJA_INGRESOS)
    DESTINO_INGRESOS = os.environ.get("DESTINO_INGRESOS", _DEFAULT_DESTINO_INGRESOS)
    LOG_DIR = os.environ.get("LOG_DIR", str(BASE_DIR / "logs"))
    PORT = int(os.environ.get("PORT", 5000))
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")
    ALLOWED_IPS = os.environ.get("ALLOWED_IPS", "*")
    AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() == "true"
    AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "remitos-2024-token-secreto")
    MAX_FIRMA_SIZE = int(os.environ.get("MAX_FIRMA_SIZE", 5 * 1024 * 1024))
    DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/remitos")
    JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")

    # Tango SQL Server (opcional)
    TANGO_HOST = os.environ.get("TANGO_HOST", "").strip()
    TANGO_PORT = int(os.environ.get("TANGO_PORT", "1433") or "1433")
    TANGO_USERNAME = os.environ.get("TANGO_USERNAME", "").strip()
    TANGO_PASSWORD = os.environ.get("TANGO_PASSWORD", "")
    TANGO_DB_NAME = (
        os.environ.get("TANGO_DB_NAME", "").strip()
        or os.environ.get("TANGO_DATABASE", "").strip()
    )
    TANGO_DB_SAN_RAFAEL = (
        os.environ.get("TANGO_DB_SAN_RAFAEL", "").strip()
        or os.environ.get("TANGO_DB_NAME", "").strip()
        or os.environ.get("TANGO_DATABASE", "").strip()
    )
    TANGO_DB_CTC = os.environ.get("TANGO_DB_CTC", "").strip()
    TANGO_QUERY_TIMEOUT = int(os.environ.get("TANGO_QUERY_TIMEOUT", "60") or "60")

    @classmethod
    def tango_transferencia_sources(cls) -> list[TangoTransferenciaSource]:
        out: list[TangoTransferenciaSource] = []
        if cls.TANGO_DB_SAN_RAFAEL:
            out.append(
                TangoTransferenciaSource(
                    id=TANGO_FUENTE_SAN_RAFAEL,
                    database=cls.TANGO_DB_SAN_RAFAEL,
                )
            )
        if cls.TANGO_DB_CTC:
            out.append(
                TangoTransferenciaSource(
                    id=TANGO_FUENTE_CTC,
                    database=cls.TANGO_DB_CTC,
                )
            )
        return out

    @classmethod
    def tango_source_by_id(cls, source_id: str) -> TangoTransferenciaSource | None:
        sid = (source_id or "").strip().upper()
        for src in cls.tango_transferencia_sources():
            if src.id == sid:
                return src
        return None

    @classmethod
    def tango_default_database(cls) -> str:
        """Base para ingresos y compat legacy."""
        return cls.TANGO_DB_SAN_RAFAEL or cls.TANGO_DB_NAME

    @classmethod
    def tango_configured(cls) -> bool:
        if not (cls.TANGO_HOST and cls.TANGO_USERNAME):
            return False
        return bool(cls.tango_transferencia_sources() or cls.TANGO_DB_NAME)

