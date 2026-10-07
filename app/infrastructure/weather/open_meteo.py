"""Adaptador de Open-Meteo (patrón Adapter).

Traduce las respuestas JSON de dos APIs públicas a un objeto de dominio
``WeatherConditions``:

* Forecast API: precipitación horaria de los últimos 7 días + pronóstico de
  24 h y humedad volumétrica del suelo a 3–9 cm.
* Flood API (GloFAS): caudal diario del río más cercano.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from statistics import fmean

import httpx

from app.domain.exceptions import WeatherUnavailableError
from app.domain.ports import WeatherProvider
from app.domain.value_objects import Coordinates, WeatherConditions

logger = logging.getLogger(__name__)


class OpenMeteoWeatherProvider(WeatherProvider):
    SOURCE = "open-meteo"

    def __init__(self, forecast_url: str, flood_url: str, client: httpx.Client) -> None:
        self._forecast_url = forecast_url
        self._flood_url = flood_url
        self._client = client

    def get_conditions(self, point: Coordinates) -> WeatherConditions:
        hourly = self._fetch_hourly(point)
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        times = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in hourly["time"]]
        rain = [v or 0.0 for v in hourly["precipitation"]]
        soil = hourly["soil_moisture_3_to_9cm"]

        # Índice de la hora actual: separa lo observado (pasado) del pronóstico.
        current = max((i for i, t in enumerate(times) if t <= now), default=None)
        if current is None:
            raise WeatherUnavailableError("Serie horaria sin datos para la hora actual")
        past = rain[: current + 1]
        soil_now = next((s for s in reversed(soil[: current + 1]) if s is not None), None)
        if soil_now is None:
            raise WeatherUnavailableError("Sin dato de humedad del suelo")

        return WeatherConditions(
            rain_24h_mm=round(sum(past[-24:]), 2),
            rain_72h_mm=round(sum(past[-72:]), 2),
            rain_7d_mm=round(sum(past[-168:]), 2),
            rain_forecast_24h_mm=round(sum(rain[current + 1 : current + 25]), 2),
            soil_moisture=round(min(max(soil_now, 0.0), 1.0), 4),
            river_discharge_ratio=self._discharge_ratio(point),
            observed_at=now,
            source=self.SOURCE,
        )

    def _fetch_hourly(self, point: Coordinates) -> dict:
        params = {
            "latitude": point.latitude,
            "longitude": point.longitude,
            "hourly": "precipitation,soil_moisture_3_to_9cm",
            "past_days": 7,
            "forecast_days": 2,
            "timezone": "GMT",
        }
        data = self._get_json(self._forecast_url, params)
        hourly = data.get("hourly")
        if not isinstance(hourly, dict) or "precipitation" not in hourly:
            raise WeatherUnavailableError("Respuesta de pronóstico con formato inesperado")
        return hourly

    def _discharge_ratio(self, point: Coordinates) -> float:
        """Caudal máximo pronosticado a 3 días / caudal medio de los últimos 30 días.

        Si la Flood API falla, se usa 1.0 (neutral) para no bloquear la
        evaluación de deslizamientos por falta de un dato secundario.
        """
        params = {
            "latitude": point.latitude,
            "longitude": point.longitude,
            "daily": "river_discharge",
            "past_days": 30,
            "forecast_days": 3,
        }
        try:
            daily = self._get_json(self._flood_url, params)["daily"]
            values = [v for v in daily["river_discharge"] if v is not None]
            history, forecast = values[:-3], values[-3:]
            baseline = fmean(history) if history else 0.0
            if baseline <= 0 or not forecast:
                return 1.0
            # Se acota al rango observado en entrenamiento para no extrapolar.
            return round(min(max(forecast) / baseline, 8.0), 3)
        except (WeatherUnavailableError, KeyError, TypeError, ValueError) as exc:
            logger.info("Flood API no disponible (%s); se usa caudal neutral", exc)
            return 1.0

    def _get_json(self, url: str, params: dict) -> dict:
        try:
            response = self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WeatherUnavailableError(f"Open-Meteo no respondió: {type(exc).__name__}") from exc
