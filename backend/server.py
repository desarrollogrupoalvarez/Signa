"""
Production entry point — Waitress WSGI server.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from waitress import serve

from app import app, logger
from config import Config
from services.documents import get_bandeja_tuples_for_rescan, scan_inbox, start_rescan_loop, start_watcher, stop_inbox_watcher

if __name__ == "__main__":

    def _get_tuples_bandeja():
        return get_bandeja_tuples_for_rescan()

    b_list = get_bandeja_tuples_for_rescan()

    logger.info("=" * 60)
    logger.info("Signa — Remitos — PRODUCCIÓN")
    logger.info(f"URL         : http://0.0.0.0:{Config.PORT}")
    if b_list:
        for pth, ac, _mf, _pr in b_list:
            logger.info("Apartado %-16s : bandeja %s", ac, pth)
    else:
        logger.warning("No hay apartados activos: ejecutá migrate/seed o creá apartados en Admin.")
    logger.info(f"Auth        : {'ON' if Config.AUTH_ENABLED else 'OFF'}")
    logger.info("=" * 60)

    for pth, ac, mf, pr in b_list:
        scan_inbox(pth, apartado_codigo=ac, modo_flujo=mf, prefijo=pr)
        start_watcher(pth, ac, mf, pr)
    rescan_stop, _rescan_th = start_rescan_loop(_get_tuples_bandeja, interval=60.0)

    try:
        serve(app, host="0.0.0.0", port=Config.PORT, threads=4, channel_timeout=120)
    except KeyboardInterrupt:
        logger.info("Interrupción recibida")
    finally:
        rescan_stop.set()
        stop_inbox_watcher()
        _rescan_th.join(timeout=2)
        logger.info("Sistema detenido correctamente")
