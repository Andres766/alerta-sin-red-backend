from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.domain.exceptions import WeatherUnavailableError
from app.domain.value_objects import Coordinates
from app.infrastructure.weather.open_meteo import OpenMeteoWeatherProvider

FORECAST = "https://api.open-meteo.com/v1/forecast"
FLOOD = "https://flood-api.open-meteo.com/v1/flood"


def hourly_payload() -> dict:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    times = [(now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(167, -25, -1)]
    return {"hourly": {"time": times, "precipitation": [0.5] * len(times),
                       "soil_moisture_3_to_9cm": [0.3] * len(times)}}


def provider(responses: list[httpx.Response]):
    waits: list[float] = []
    queue = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if "flood" in request.url.host:
            return httpx.Response(200, json={"daily": {"river_discharge": [10.0] * 33}})
        return next(queue)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenMeteoWeatherProvider(FORECAST, FLOOD, client, sleep=waits.append), waits


def test_reintenta_ante_429_respetando_retry_after():
    p, waits = provider([httpx.Response(429, headers={"Retry-After": "2"}),
                         httpx.Response(200, json=hourly_payload())])
    assert p.get_conditions(Coordinates(1.21, -77.28)).rain_24h_mm == 12
    assert waits == [2.0]


def test_retry_after_excesivo_se_acota():
    p, waits = provider([httpx.Response(503, headers={"Retry-After": "120"}),
                         httpx.Response(200, json=hourly_payload())])
    p.get_conditions(Coordinates(1.21, -77.28))
    assert waits == [5.0]


def test_espera_exponencial_sin_retry_after():
    p, waits = provider([httpx.Response(502), httpx.Response(500),
                         httpx.Response(200, json=hourly_payload())])
    p.get_conditions(Coordinates(1.21, -77.28))
    assert waits == [0.5, 1.0]


def test_se_rinde_tras_tres_intentos():
    p, waits = provider([httpx.Response(503)] * 3)
    with pytest.raises(WeatherUnavailableError):
        p.get_conditions(Coordinates(1.21, -77.28))
    assert len(waits) == 2


def test_no_reintenta_errores_del_cliente():
    p, waits = provider([httpx.Response(400)])
    with pytest.raises(WeatherUnavailableError):
        p.get_conditions(Coordinates(1.21, -77.28))
    assert waits == []


def test_tras_un_429_persistente_deja_de_consultar_un_rato():
    calls: list[str] = []
    now = [0.0]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(429)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    p = OpenMeteoWeatherProvider(FORECAST, FLOOD, client,
                                 sleep=lambda _: None, clock=lambda: now[0])
    with pytest.raises(WeatherUnavailableError, match="429"):
        p.get_conditions(Coordinates(1.21, -77.28))
    assert len(calls) == 3

    # Otra zona en la misma evaluación: falla al instante, sin gastar reintentos.
    with pytest.raises(WeatherUnavailableError, match="limitó"):
        p.get_conditions(Coordinates(1.62, -78.67))
    assert len(calls) == 3

    now[0] += OpenMeteoWeatherProvider.BLOCK_SECONDS + 1  # pasada la pausa, vuelve a intentar
    with pytest.raises(WeatherUnavailableError):
        p.get_conditions(Coordinates(1.21, -77.28))
    assert len(calls) == 6
