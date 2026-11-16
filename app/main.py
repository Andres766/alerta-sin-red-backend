"""Punto de entrada de la API (patrón Application Factory).

Ejecución:  uvicorn app.main:create_app --factory
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.errors import register_error_handlers
from app.api.middleware import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.routers import admin, auth, public, weather
from app.container import Container, build_container
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.domain.exceptions import ConflictError

logger = logging.getLogger(__name__)


async def _periodic_evaluation(container: Container) -> None:
    """Evalúa todas las zonas cada N minutos sin bloquear el event loop."""
    interval = container.settings.scheduler_interval_minutes * 60

    def job() -> None:
        with container.uow_factory() as uow:
            try:
                report = container.risk_service(uow).evaluate_all()
            except ConflictError:
                logger.info("Evaluación programada omitida: ya hay una en curso")
                return
            logger.info("Evaluación programada: %d zonas, %d fallos",
                        len(report.assessments), len(report.failures))

    while True:
        try:
            await asyncio.to_thread(job)
        except Exception:
            logger.exception("Falló la evaluación programada")
        await asyncio.sleep(interval)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or build_container(settings)
        if settings.repository_backend == "memory":
            app.state.container.seed()
        task = (
            asyncio.create_task(_periodic_evaluation(app.state.container))
            if settings.scheduler_enabled
            else None
        )
        yield
        if task:
            task.cancel()
        app.state.container.close()

    show_docs = settings.expose_docs or not settings.is_production
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Alertas de riesgo climático offline-first con IA para comunidades en riesgo.",
        lifespan=lifespan,
        # La documentación interactiva no se publica en producción (salvo EXPOSE_DOCS=true).
        docs_url="/docs" if show_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if show_docs else None,
    )

    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,  # lista blanca explícita
        allow_credentials=False,  # se usa Bearer token, no cookies
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
    if settings.is_production:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    # Ninguna petición legítima de esta API supera unos pocos KB.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    # Se agrega al final para que sea el más externo y mida toda la petición.
    app.add_middleware(RequestContextMiddleware)

    register_error_handlers(app)
    for router in (public.router, auth.router, admin.router, weather.router):
        app.include_router(router, prefix=settings.api_prefix)
    return app

