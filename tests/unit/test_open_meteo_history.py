from datetime import UTC, date, datetime, timedelta

import httpx

from app.domain.value_objects import Coordinates
from app.infrastructure.weather.open_meteo import OpenMeteoWeatherProvider

FORECAST = "https://api.open-meteo.com/v1/forecast"
FLOOD = "https://flood-api.open-meteo.com/v1/flood"
TODAY = date(2026, 11, 16)  # hora de Colombia


def provider(discharge: float = 10.0, flood_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        past_days = int(params["past_days"])
        if "flood" in request.url.host:
            if flood_status != 200:
                return httpx.Response(flood_status)
            start = TODAY - timedelta(days=past_days)
            days = [start + timedelta(days=k) for k in range(past_days + 3)]
            return httpx.Response(200, json={"daily": {
                "time": [d.isoformat() for d in days],
                "river_discharge": [discharge] * len(days),
            }})
        # 1 mm por hora, humedad 0.3, desde las 00:00 UTC del primer día pedido.
        start = datetime(TODAY.year, TODAY.month, TODAY.day, tzinfo=UTC) - timedelta(days=past_days)
        hours = (past_days + 2) * 24
        times = [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(hours)]
        return httpx.Response(200, json={"hourly": {
            "time": times, "precipitation": [1.0] * hours, "soil_moisture_3_to_9cm": [0.3] * hours,
        }})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenMeteoWeatherProvider(FORECAST, FLOOD, client, sleep=lambda _: None)


def test_un_registro_por_dia_al_mediodia_de_colombia():
    history = provider().daily_history(Coordinates(1.21, -77.28), days=30, today=TODAY)
    assert len(history) == 30
    assert history[0].observed_at == datetime(2026, 10, 17, 17, tzinfo=UTC)  # 12:00 COT
    assert history[-1].observed_at == datetime(2026, 11, 15, 17, tzinfo=UTC)
    assert all(h.source == "open-meteo-historico" for h in history)


def test_aplica_las_mismas_ventanas_que_el_clima_actual():
    day = provider(discharge=10.0).daily_history(Coordinates(1.21, -77.28), days=3, today=TODAY)[0]
    assert (day.rain_24h_mm, day.rain_72h_mm, day.rain_7d_mm) == (24, 72, 168)
    assert day.rain_forecast_24h_mm == 24  # lo que realmente llovió después
    assert day.soil_moisture == 0.3 and day.river_discharge_ratio == 1.0


def test_sin_flood_api_el_caudal_es_neutral():
    p = provider(flood_status=503)
    history = p.daily_history(Coordinates(1.62, -78.67), days=2, today=TODAY)
    assert [h.river_discharge_ratio for h in history] == [1.0, 1.0]
