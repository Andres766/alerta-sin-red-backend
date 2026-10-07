from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


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
        if self._hsts:
            h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
