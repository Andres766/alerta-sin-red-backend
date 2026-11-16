"""Adaptador de Open-Meteo (patrón Adapter).

Traduce las respuestas JSON de dos APIs públicas a un objeto de dominio
``WeatherConditions``:

* Forecast API: precipitación horaria de los últimos 7 días + pronóstico de
  24 h y humedad volumétrica del suelo a 3–9 cm.
* Flood API (GloFAS): caudal diario del río más cercano.

Además del clima actual, puede reconstruir las condiciones de días pasados
(``daily_history``) con la misma fórmula, para llenar el historial de riesgo.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from statistics import fmean

import httpx

from app.domain.exceptions import WeatherUnavailableError
from app.domain.ports import WeatherProvider
from app.domain.value_objects import COLOMBIA_TZ, Coordinates, WeatherConditions

logger = logging.getLogger(__name__)


class OpenMeteoWeatherProvider(WeatherProvider):
    SOURCE = "open-meteo"
    HISTORY_SOURCE = "open-meteo-historico"

    # Estados que suelen ser temporales: vale la pena reintentar.
    RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
    MAX_ATTEMPTS = 3
    BASE_DELAY_SECONDS = 0.5
    MAX_RETRY_AFTER_SECONDS = 5.0
    # Tras un 429 persistente no se insiste: cada zona gastaría ~10 s en reintentos y
    # una evaluación completa superaría el tiempo de espera del panel (disyuntor).
    BLOCK_SECONDS = 600.0
    MAX_HISTORY_DAYS = 60

    def __init__(
        self,
        forecast_url: str,
        flood_url: str,
        client: httpx.Client,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._forecast_url = forecast_url
        self._flood_url = flood_url
        self._client = client
        self._sleep = sleep
        self._clock = clock
        self._blocked_until = 0.0

    # ---- Clima actual ---------------------------------------------------------- #

    def get_conditions(self, point: Coordinates) -> WeatherConditions:
        hourly = self._fetch_hourly(point, past_days=7)
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        times, rain, soil = self._series(hourly)

        # Índice de la hora actual: separa lo observado (pasado) del pronóstico.
        current = max((i for i, t in enumerate(times) if t <= now), default=None)
        if current is None:
            raise WeatherUnavailableError("Serie horaria sin datos para la hora actual")
        conditions = self._conditions_at(current, rain, soil, now, self.SOURCE)
        if conditions is None:
            raise WeatherUnavailableError("Sin dato de humedad del suelo")
        return WeatherConditions(
            rain_24h_mm=conditions.rain_24h_mm,
            rain_72h_mm=conditions.rain_72h_mm,
            rain_7d_mm=conditions.rain_7d_mm,
            rain_forecast_24h_mm=conditions.rain_forecast_24h_mm,
            soil_moisture=conditions.soil_moisture,
            river_discharge_ratio=self._discharge_ratio(point),
            observed_at=now,
            source=self.SOURCE,
        )

    # ---- Historial ------------------------------------------------------------- #

    def daily_history(
        self, point: Coordinates, days: int, local_hour: int = 12, today: date | None = None
    ) -> list[WeatherConditions]:
        """Condiciones a las ``local_hour`` (hora de Colombia) de cada uno de los
        últimos ``days`` días, sin incluir hoy.

        La "lluvia pronosticada 24 h" de un día pasado es la que realmente cayó en
        las 24 h siguientes (lo observado en retrospectiva).
        """
        if not 1 <= days <= self.MAX_HISTORY_DAYS:
            raise ValueError(f"days debe estar entre 1 y {self.MAX_HISTORY_DAYS}")
        # 8 días extra: la ventana de 7 días del primer día necesita datos anteriores.
        times, rain, soil = self._series(self._fetch_hourly(point, past_days=days + 8))
        index = {t: i for i, t in enumerate(times)}
        discharge = self._discharge_by_day(point, past_days=days + 31)

        today = today or datetime.now(COLOMBIA_TZ).date()
        history: list[WeatherConditions] = []
        for offset in range(days, 0, -1):
            day = today - timedelta(days=offset)
            moment = datetime.combine(day, clock_time(local_hour), COLOMBIA_TZ).astimezone(UTC)
            i = index.get(moment)
            # Se necesitan 7 días antes y 24 h después del instante.
            if i is None or i < 167 or i + 24 >= len(rain):
                continue
            conditions = self._conditions_at(i, rain, soil, moment, self.HISTORY_SOURCE)
            if conditions is None:
                continue
            forecast = [discharge.get(day + timedelta(days=k)) for k in range(3)]
            past = [discharge.get(day - timedelta(days=k)) for k in range(1, 31)]
            history.append(WeatherConditions(
                rain_24h_mm=conditions.rain_24h_mm,
                rain_72h_mm=conditions.rain_72h_mm,
                rain_7d_mm=conditions.rain_7d_mm,
                rain_forecast_24h_mm=conditions.rain_forecast_24h_mm,
                soil_moisture=conditions.soil_moisture,
                river_discharge_ratio=_ratio(
                    [v for v in past if v is not None], [v for v in forecast if v is not None]
                ),
                observed_at=moment,
                source=self.HISTORY_SOURCE,
            ))
        return history

    # ---- Detalles ---------------------------------------------------------------- #

    @staticmethod
    def _conditions_at(
        i: int, rain: list[float], soil: list[float | None], moment: datetime, source: str
    ) -> WeatherConditions | None:
        """Variables de lluvia y suelo en el índice ``i`` (caudal neutral)."""
        past = rain[: i + 1]
        soil_now = next((s for s in reversed(soil[: i + 1]) if s is not None), None)
        if soil_now is None:
            return None
        return WeatherConditions(
            rain_24h_mm=round(sum(past[-24:]), 2),
            rain_72h_mm=round(sum(past[-72:]), 2),
            rain_7d_mm=round(sum(past[-168:]), 2),
            rain_forecast_24h_mm=round(sum(rain[i + 1 : i + 25]), 2),
            soil_moisture=round(min(max(soil_now, 0.0), 1.0), 4),
            river_discharge_ratio=1.0,
            observed_at=moment,
            source=source,
        )

    @staticmethod
    def _series(hourly: dict) -> tuple[list[datetime], list[float], list[float | None]]:
        times = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in hourly["time"]]
        rain = [v or 0.0 for v in hourly["precipitation"]]
        return times, rain, hourly["soil_moisture_3_to_9cm"]

    def _fetch_hourly(self, point: Coordinates, past_days: int) -> dict:
        params = {
            "latitude": point.latitude,
            "longitude": point.longitude,
            "hourly": "precipitation,soil_moisture_3_to_9cm",
            "past_days": past_days,
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
            return _ratio(values[:-3], values[-3:])
        except (WeatherUnavailableError, KeyError, TypeError, ValueError) as exc:
            logger.info("Flood API no disponible (%s); se usa caudal neutral", exc)
            return 1.0

    def _discharge_by_day(self, point: Coordinates, past_days: int) -> dict[date, float]:
        """Caudal diario por fecha; vacío si la Flood API no responde (caudal neutral)."""
        params = {
            "latitude": point.latitude,
            "longitude": point.longitude,
            "daily": "river_discharge",
            "past_days": past_days,
            "forecast_days": 3,
        }
        try:
            daily = self._get_json(self._flood_url, params)["daily"]
            return {
                date.fromisoformat(day): value
                for day, value in zip(daily["time"], daily["river_discharge"], strict=True)
                if value is not None
            }
        except (WeatherUnavailableError, KeyError, TypeError, ValueError) as exc:
            logger.info("Flood API no disponible (%s); se usa caudal neutral", exc)
            return {}

    def _get_json(self, url: str, params: dict) -> dict:
        """GET con reintentos ante 429/5xx y espera exponencial (0.5 s, 1 s, ...).

        Si el servidor envía Retry-After se respeta, con un tope para no dejar
        la evaluación de las demás zonas esperando demasiado. Tras un 429 que
        persiste, se deja de consultar durante ``BLOCK_SECONDS``.
        """
        host = httpx.URL(url).host
        if self._clock() < self._blocked_until:
            raise WeatherUnavailableError(
                f"Open-Meteo limitó las consultas (429 en {host}); se reintenta en unos minutos"
            )
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                response = self._client.get(url, params=params)
                if (
                    response.status_code in self.RETRYABLE_STATUS
                    and attempt < self.MAX_ATTEMPTS
                ):
                    delay = self._retry_delay(response, attempt)
                    logger.info(
                        "Open-Meteo respondió %d; reintento %d en %.1f s",
                        response.status_code, attempt, delay,
                    )
                    self._sleep(delay)
                    continue
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    self._blocked_until = self._clock() + self.BLOCK_SECONDS
                    logger.warning("Open-Meteo sigue respondiendo 429; pausa de %.0f s",
                                   self.BLOCK_SECONDS)
                raise WeatherUnavailableError(
                    f"Open-Meteo respondió {exc.response.status_code} en {host}"
                ) from exc
            except (httpx.HTTPError, ValueError) as exc:
                raise WeatherUnavailableError(
                    f"Open-Meteo no respondió ({type(exc).__name__} en {host})"
                ) from exc
        raise WeatherUnavailableError("Open-Meteo no respondió tras reintentar")  # inalcanzable

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(float(retry_after), self.MAX_RETRY_AFTER_SECONDS)
        return self.BASE_DELAY_SECONDS * 2 ** (attempt - 1)


def _ratio(history: list[float], forecast: list[float]) -> float:
    """Caudal máximo pronosticado / caudal medio histórico, acotado a [0, 8]."""
    baseline = fmean(history) if history else 0.0
    if baseline <= 0 or not forecast:
        return 1.0
    # Se acota al rango observado en entrenamiento para no extrapolar.
    return round(min(max(forecast) / baseline, 8.0), 3)
