"""
Configuración centralizada de logs para todo el proyecto.

Escribe en un archivo (definido en config.yaml) y también en la consola,
para que el usuario pueda ver la actividad en tiempo real mientras el bot
corre, y además tenga un historial guardado en disco.
"""

import logging
from pathlib import Path


def setup_logging(log_path: str, level: str = "INFO") -> None:
    """Configura el sistema de logs de todo el proyecto.

    Debe llamarse una sola vez, al arrancar el programa (en main.py).
    Después, cualquier archivo puede usar logging.getLogger(__name__)
    y sus mensajes se escribirán con este formato, tanto en el archivo
    de logs como en la consola.
    """
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    # Evita handlers duplicados si setup_logging se llama más de una vez
    # (por ejemplo, durante las pruebas automatizadas).
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
