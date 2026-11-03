"""Endpoints públicos que consume la PWA (no requieren autenticación)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import ContainerDep, UowDep, rate_limited
from app.api.schemas import (
    AssessmentOut,
    CancelSubscriptionIn,
    HealthOut,
    ModelCardOut,
    NearbyZoneOut,
    ReadinessOut,
    SnapshotOut,
    SubscriptionIn,
    SubscriptionOut,
    ZoneOut,
    ZoneRiskOut,
)
from app.domain.value_objects import Coordinates

router = APIRouter()


@router.get("/health", response_model=HealthOut, tags=["sistema"])
def health(container: ContainerDep) -> HealthOut:
    return HealthOut(
        status="ok",
        model_version=container.model.version,
        weather_provider=container.settings.weather_provider,
        sms_channel=container.sms.channel,
    )


@router.get(
    "/health/ready",
    response_model=ReadinessOut,
    tags=["sistema"],
    responses={503: {"model": ReadinessOut, "description": "Alguna dependencia no responde"}},
)
def readiness(container: ContainerDep, response: Response) -> ReadinessOut:
    """Disponibilidad: además de estar vivo, ¿puede atender? (p. ej. la base de datos responde)."""
    checks = container.readiness()
    ready = all(result == "ok" for result in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    response.headers["Cache-Control"] = "no-store"
    return ReadinessOut(status="ready" if ready else "unavailable", checks=checks)


# Limitaciones declaradas: parte de una IA honesta (se muestran junto a las métricas).
MODEL_LIMITATIONS = [
    "Fase 1: entrenado con datos sintéticos de base física; las métricas miden qué tan "
    "bien aprende esa relación, no su acierto frente a eventos reales.",
    "Fase 2 (pendiente): reentrenar con eventos reales de SIMMA (SGC) y DesInventar.",
    "Usa lluvia absoluta: en la costa pacífica, más lluviosa, puede sobrestimar el riesgo "
    "hasta calibrarse con la climatología local.",
    "La susceptibilidad y la pendiente de las zonas piloto son provisionales.",
]


@router.get("/model", response_model=ModelCardOut, tags=["riesgo"])
def model_card(container: ContainerDep, response: Response) -> ModelCardOut:
    """Ficha técnica del modelo de IA: datos, métricas, variables más influyentes y límites."""
    card = container.model.card()
    response.headers["Cache-Control"] = "public, max-age=3600"
    return ModelCardOut(
        version=card.version, algorithm=card.algorithm, trained_at=card.trained_at,
        data_source=card.data_source, n_samples=card.n_samples,
        feature_order=list(card.feature_order), feature_importances=card.feature_importances,
        metrics=card.metrics, confusion_matrix=card.confusion_matrix,
        labels=list(card.labels), limitations=MODEL_LIMITATIONS,
    )


@router.get("/risk/snapshot", response_model=SnapshotOut, tags=["riesgo"])
def risk_snapshot(uow: UowDep, container: ContainerDep, response: Response) -> SnapshotOut:
    """Instantánea completa (zonas + última evaluación) que la PWA guarda en IndexedDB."""
    # El navegador puede reutilizarla 60 s; el Service Worker aplica su propia estrategia.
    response.headers["Cache-Control"] = "public, max-age=60"
    return SnapshotOut.of(container.zone_queries(uow).snapshot())


@router.get("/zones/nearby", response_model=list[NearbyZoneOut], tags=["zonas"])
def nearby_zones(
    uow: UowDep,
    container: ContainerDep,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    radius_km: Annotated[float, Query(gt=0, le=200)] = 50,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[NearbyZoneOut]:
    """Consulta espacial con PostGIS (``ST_DWithin`` sobre índice GiST)."""
    results = container.zone_queries(uow).nearby(Coordinates(lat, lon), radius_km, limit)
    return [NearbyZoneOut(zone=ZoneOut.of(z), distance_km=d) for z, d in results]


@router.get("/zones/{zone_id}", response_model=ZoneRiskOut, tags=["zonas"])
def zone_detail(
    zone_id: UUID, uow: UowDep, container: ContainerDep, response: Response
) -> ZoneRiskOut:
    """Zona con su última evaluación: permite abrir un enlace directo sin el snapshot."""
    response.headers["Cache-Control"] = "public, max-age=60"
    return ZoneRiskOut.of(container.zone_queries(uow).detail(zone_id))


@router.get("/zones/{zone_id}/history", response_model=list[AssessmentOut], tags=["zonas"])
def zone_history(
    zone_id: UUID,
    uow: UowDep,
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> list[AssessmentOut]:
    return [AssessmentOut.of(a) for a in container.zone_queries(uow).history(zone_id, limit)]


@router.post(
    "/subscriptions",
    response_model=SubscriptionOut,
    status_code=status.HTTP_201_CREATED,
    tags=["suscripciones"],
    dependencies=[Depends(rate_limited(lambda c: c.subscribe_limiter))],
)
def subscribe(body: SubscriptionIn, uow: UowDep, container: ContainerDep) -> SubscriptionOut:
    result = container.subscription_service(uow).subscribe(
        body.phone, body.zone_id, body.accepts_data_policy
    )
    return SubscriptionOut.of(result)


@router.post(
    "/subscriptions/{subscription_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["suscripciones"],
    dependencies=[Depends(rate_limited(lambda c: c.subscribe_limiter))],
)
def cancel_subscription(
    subscription_id: UUID, body: CancelSubscriptionIn, uow: UowDep, container: ContainerDep
) -> Response:
    """Baja de alertas SMS con el código que el celular recibió al suscribirse."""
    container.subscription_service(uow).cancel(subscription_id, body.cancel_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
