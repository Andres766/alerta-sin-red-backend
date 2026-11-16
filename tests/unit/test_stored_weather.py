from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.exceptions import WeatherUnavailableError
from app.domain.ports import WeatherProvider
from app.domain.value_objects import Coordinates, WeatherConditions
from app.infrastructure.memory.repositories import InMemoryStore, InMemoryUnitOfWork
from app.infrastructure.weather.stored import StoredWeatherProvider

NOW = datetime(2026, 11, 15, 20, 0, tzinfo=UTC)
PASTO = Coordinates(1.2136, -77.2811)


def conditions(observed_at: datetime, source: str = "open-meteo") -> WeatherConditions:
    return WeatherConditions(
        rain_24h_mm=10, rain_72h_mm=30, rain_7d_mm=60, rain_forecast_24h_mm=5,
        soil_moisture=0.3, river_discharge_ratio=1.0, observed_at=observed_at, source=source,
    )


class Unreachable(WeatherProvider):
    def get_conditions(self, point: Coordinates) -> WeatherConditions:
        raise WeatherUnavailableError("Open-Meteo respondió 429")


class Working(WeatherProvider):
    def get_conditions(self, point: Coordinates) -> WeatherConditions:
        return conditions(NOW, source="directo")


def provider(fallback: WeatherProvider):
    uow = InMemoryUnitOfWork(InMemoryStore())
    return uow, StoredWeatherProvider(uow.observations, fallback, timedelta(hours=3), lambda: NOW)


def test_usa_la_observacion_reciente_aunque_la_fuente_este_bloqueada():
    uow, p = provider(Unreachable())
    uow.observations.save(uuid4(), PASTO, conditions(NOW - timedelta(hours=1)))
    assert p.get_conditions(PASTO).source == "open-meteo"


def test_tolera_diferencias_minimas_de_coordenada():
    uow, p = provider(Unreachable())
    uow.observations.save(uuid4(), PASTO, conditions(NOW))
    assert p.get_conditions(Coordinates(1.21364, -77.28106)).source == "open-meteo"


def test_una_observacion_vieja_no_se_usa():
    uow, p = provider(Working())
    uow.observations.save(uuid4(), PASTO, conditions(NOW - timedelta(hours=4)))
    assert p.get_conditions(PASTO).source == "directo"


def test_sin_observacion_y_sin_fuente_falla_como_antes():
    _, p = provider(Unreachable())
    with pytest.raises(WeatherUnavailableError):
        p.get_conditions(PASTO)


def test_guardar_de_nuevo_reemplaza_la_observacion_de_la_zona():
    uow, p = provider(Unreachable())
    zone = uuid4()
    uow.observations.save(zone, PASTO, conditions(NOW - timedelta(hours=2)))
    uow.observations.save(zone, PASTO, conditions(NOW))
    assert p.get_conditions(PASTO).observed_at == NOW
