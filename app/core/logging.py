import logging
import sys
from contextvars import ContextVar

# Identificador de la petición en curso; lo fija RequestContextMiddleware.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Agrega el id de la petición a cada línea de log para poder seguirla de punta a punta."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s")
    )
    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)
    # httpx registra la URL completa de cada petición; se baja su nivel.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # El acceso ya lo registra RequestContextMiddleware (con id y duración).
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
