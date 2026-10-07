"""Endpoints públicos que consume la PWA (no requieren autenticación)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import ContainerDep, UowDep, rate_limited
from app.api.schemas import (
    AssessmentOut,
    HealthOut,
    NearbyZoneOut,
    SnapshotOut,
    SubscriptionIn,
    SubscriptionOut,
    ZoneOut,
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
    subscriber = container.subscription_service(uow).subscribe(
        body.phone, body.zone_id, body.accepts_data_policy
    )
    return SubscriptionOut.of(subscriber)
