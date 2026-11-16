"""Ingesta de clima desde un trabajo externo (GitHub Actions).

Se protege con un token propio, distinto del JWT de los operadores: el trabajo
no es una persona, no tiene cuenta y solo puede hacer esta operación.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.deps import ContainerDep, UowDep
from app.api.schemas import WeatherIngestIn, WeatherIngestOut
from app.application.services.weather_ingest import ZoneObservation
from app.domain.value_objects import WeatherConditions

router = APIRouter(prefix="/weather", tags=["clima"])


def require_ingest_token(
    container: ContainerDep,
    x_ingest_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = container.settings.weather_ingest_token
    if expected is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Ingesta de clima no habilitada"
        )
    # Comparación en tiempo constante: no revela cuántos caracteres coinciden.
    if not x_ingest_token or not hmac.compare_digest(
        x_ingest_token.encode(), expected.get_secret_value().encode()
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de ingesta inválido")


@router.post(
    "/observations",
    response_model=WeatherIngestOut,
    dependencies=[Depends(require_ingest_token)],
)
def ingest_observations(
    payload: WeatherIngestIn, uow: UowDep, container: ContainerDep
) -> WeatherIngestOut:
    """Guarda el clima de cada zona y evalúa el riesgo con el modelo de IA."""
    observations = [
        ZoneObservation(
            zone_id=o.zone_id,
            conditions=WeatherConditions(
                rain_24h_mm=o.rain_24h_mm, rain_72h_mm=o.rain_72h_mm, rain_7d_mm=o.rain_7d_mm,
                rain_forecast_24h_mm=o.rain_forecast_24h_mm, soil_moisture=o.soil_moisture,
                river_discharge_ratio=o.river_discharge_ratio, observed_at=o.observed_at,
                source=o.source,
            ),
        )
        for o in payload.observations
    ]
    report = container.weather_ingest(uow).ingest(observations)
    return WeatherIngestOut(
        stored=report.stored,
        unknown_zones=report.unknown_zones,
        evaluated=len(report.evaluation.assessments),
        failures=report.evaluation.failures,
    )
