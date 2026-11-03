from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_var

access_logger = logging.getLogger("app.access")

# Solo se acepta un id entrante con formato seguro: evita inyectar texto en los logs.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Asigna un id a cada petición, lo devuelve en X-Request-ID y registra la duración.

    Si el cliente o un proxy envían un X-Request-ID válido se reutiliza, para
    poder correlacionar la petición entre Vercel, Render y la API.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            # Solo la ruta, sin parámetros: la consulta puede llevar la ubicación del usuario.
            access_logger.info(
                "%s %s -> %d (%.0f ms)", request.method, request.url.path, status, elapsed_ms
            )
            request_id_var.reset(token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Cabeceras de seguridad recomendadas por OWASP Secure Headers Project."""

    def __init__(self, app, hsts: bool) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        if request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
            # Swagger UI necesita cargar su JS/CSS desde un CDN.
            h["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
                "img-src 'self' data: fastapi.tiangolo.com; frame-ancestors 'none'"
            )
        else:
            h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if request.url.path.startswith("/api/") and request.method != "GET":
            h["Cache-Control"] = "no-store"
        h["Access-Control-Expose-Headers"] = "X-Request-ID"
        if self._hsts:
            h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
