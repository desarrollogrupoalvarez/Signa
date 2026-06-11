"""
Production entry point — Waitress WSGI server.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from waitress import serve

from app import app, logger
from config import Config
from services.comprobante_index_queue import start_index_worker, stop_index_worker
from services.documents import (
    get_bandeja_tuples_for_rescan,
    start_bandejas_boot,
    stop_inbox_watcher,
)

if __name__ == "__main__":
    import threading

    print("Signa: iniciando servidor...", flush=True)

    logger.info("=" * 60)
    logger.info("Signa — Remitos — PRODUCCIÓN")
    logger.info(f"URL         : http://0.0.0.0:{Config.PORT}")
    logger.info(f"Auth        : {'ON' if Config.AUTH_ENABLED else 'OFF'}")
    logger.info("=" * 60)

    def _boot_bandejas() -> None:
        try:
            b_list = get_bandeja_tuples_for_rescan()
            if b_list:
                for pth, ac, _mf, _pr in b_list:
                    logger.info("Apartado %-16s : bandeja %s", ac, pth)
            else:
                logger.warning(
                    "No hay apartados activos: ejecutá migrate/seed o creá apartados en Admin."
                )
            start_bandejas_boot(b_list)
        except Exception as ex:
            logger.error("Arranque de bandejas falló: %s", ex)

    start_index_worker()
    threading.Thread(target=_boot_bandejas, name="boot-bandejas-init", daemon=True).start()

    logger.info("Servidor listo — escuchando en http://0.0.0.0:%s", Config.PORT)

    try:
        serve(app, host="0.0.0.0", port=Config.PORT, threads=8, channel_timeout=120)
    except KeyboardInterrupt:
        logger.info("Interrupción recibida")
    finally:
        stop_index_worker()
        stop_inbox_watcher()
        logger.info("Sistema detenido correctamente")
