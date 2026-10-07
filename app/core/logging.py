import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )
    # httpx registra la URL completa de cada petición; se baja su nivel.
    logging.getLogger("httpx").setLevel(logging.WARNING)
