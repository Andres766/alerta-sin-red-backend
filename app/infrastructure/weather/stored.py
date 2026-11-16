"""Proveedor de clima con observaciones recibidas de fuera (patrón Decorator).

Primero busca una observación reciente guardada para la coordenada (la envía
un trabajo externo que sí puede consultar Open-Meteo, p. ej. GitHub Actions);
si no la hay o es vieja, delega en el proveedor interno. Así el sistema sigue
funcionando aunque la red del servidor tenga bloqueada la API del clima.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from app.domain.entities import utcnow
from app.domain.ports import WeatherObservationRepository, WeatherProvider
from app.domain.value_objects import Coordinates, WeatherConditions

logger = logging.getLogger(__name__)


class StoredWeatherProvider(WeatherProvider):
    def __init__(
        self,
        observations: WeatherObservationRepository,
        fallback: WeatherProvider,
        max_age: timedelta,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._observations = observations
        self._fallback = fallback
        self._max_age = max_age
        self._now = now

    def get_conditions(self, point: Coordinates) -> WeatherConditions:
        stored = self._observations.latest_near(point)
        if stored is not None and self._now() - stored.observed_at <= self._max_age:
            return stored
        if stored is not None:
            logger.info("Observación guardada demasiado vieja (%s); se consulta la fuente",
                        stored.observed_at.isoformat(timespec="minutes"))
        return self._fallback.get_conditions(point)
