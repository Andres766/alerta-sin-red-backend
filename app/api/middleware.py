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


class BodySizeLimitMiddleware:
    """Rechaza con 413 los cuerpos de petición mayores que ``max_bytes``.

    Middleware ASGI puro. Si llega Content-Length se decide de inmediato; si el
    cliente envía el cuerpo por partes sin declararlo, se lee aquí hasta el límite
    y luego se entrega intacto a la aplicación. Evita que un cuerpo enorme agote
    la memoria de una instancia pequeña.
    """

    def __init__(self, app, max_bytes: int) -> None:  # type: ignore[no-untyped-def]
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)

        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None:
            if not declared.isdigit() or int(declared) > self.max_bytes:
                return await self._reject(send)
            return await self.app(scope, receive, send)

        # Sin Content-Length: se lee por partes, contando, hasta el final o el límite.
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return await self.app(scope, receive, send)  # desconexión del cliente
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                return await self._reject(send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        delivered = False

        async def replay():  # type: ignore[no-untyped-def]
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(self, send) -> None:  # type: ignore[no-untyped-def]
        body = b'{"code":"payload_too_large","detail":"La solicitud es demasiado grande"}'
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
