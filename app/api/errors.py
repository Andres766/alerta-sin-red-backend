"""Traducción de excepciones de dominio a respuestas HTTP.

Nunca se devuelve una traza al cliente: los errores inesperados se registran
en el servidor y el cliente recibe un mensaje genérico (OWASP A05/A09).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.domain.exceptions import (
    AuthenticationError,
    AuthorizationError,
    DomainError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)

_STATUS_BY_ERROR: list[tuple[type[DomainError], int]] = [
    (ValidationError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (AuthenticationError, status.HTTP_401_UNAUTHORIZED),
    (AuthorizationError, status.HTTP_403_FORBIDDEN),
    (ExternalServiceError, status.HTTP_503_SERVICE_UNAVAILABLE),
]


def _status_for(exc: DomainError) -> int:
    for error_type, code in _STATUS_BY_ERROR:
        if isinstance(exc, error_type):
            return code
    return status.HTTP_400_BAD_REQUEST


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        code = _status_for(exc)
        detail = str(exc) if code != status.HTTP_401_UNAUTHORIZED else "No autenticado"
        headers = {"WWW-Authenticate": "Bearer"} if code == status.HTTP_401_UNAUTHORIZED else None
        if isinstance(exc, NotFoundError):
            detail = "Recurso no encontrado"
        return JSONResponse({"code": exc.code, "detail": detail}, status_code=code, headers=headers)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Error no controlado en %s %s", request.method, request.url.path)
        return JSONResponse(
            {"code": "internal_error", "detail": "Error interno del servidor"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
