from datetime import UTC, datetime

import pytest

from app.domain.exceptions import WeatherUnavailableError
from app.domain.ports import WeatherProvider
from app.domain.value_objects import Coordinates, WeatherConditions
from app.infrastructure.weather.cached import CachedWeatherProvider

PASTO = Coordinates(1.2136, -77.2811)
MOCOA = Coordinates(1.1500, -76.6480)


class CountingProvider(WeatherProvider):
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def get_conditions(self, point: Coordinates) -> WeatherConditions:
        self.calls += 1
        if self.fail:
            raise WeatherUnavailableError("caído")
        return WeatherConditions(1, 2, 3, 4, 0.3, 1.0, datetime.now(UTC), f"llamada-{self.calls}")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_reutiliza_el_clima_dentro_del_ttl():
    inner, clock = CountingProvider(), FakeClock()
    cached = CachedWeatherProvider(inner, ttl_seconds=900, clock=clock)
    first = cached.get_conditions(PASTO)
    clock.now = 899
    assert cached.get_conditions(Coordinates(1.21361, -77.28112)) is first  # mismo punto (~1 m)
    assert inner.calls == 1


def test_vuelve_a_consultar_al_vencer():
    inner, clock = CountingProvider(), FakeClock()
    cached = CachedWeatherProvider(inner, ttl_seconds=900, clock=clock)
    cached.get_conditions(PASTO)
    clock.now = 900
    assert cached.get_conditions(PASTO).source == "llamada-2"


def test_coordenadas_distintas_no_comparten_entrada():
    inner = CountingProvider()
    cached = CachedWeatherProvider(inner, ttl_seconds=900)
    cached.get_conditions(PASTO)
    cached.get_conditions(MOCOA)
    assert inner.calls == 2


def test_no_guarda_errores():
    inner = CountingProvider(fail=True)
    cached = CachedWeatherProvider(inner, ttl_seconds=900)
    for _ in range(2):
        with pytest.raises(WeatherUnavailableError):
            cached.get_conditions(PASTO)
    assert inner.calls == 2


def test_limita_el_numero_de_entradas():
    inner = CountingProvider()
    cached = CachedWeatherProvider(inner, ttl_seconds=900, max_entries=2)
    for lat in (1.0, 2.0, 3.0):
        cached.get_conditions(Coordinates(lat, -77.0))
    cached.get_conditions(Coordinates(1.0, -77.0))  # la más antigua fue descartada
    assert inner.calls == 4
