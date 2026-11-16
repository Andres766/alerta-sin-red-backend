"""Consulta Open-Meteo para las zonas y entrega el clima a la API (trabajo externo).

Además completa el historial: para cada zona revisa qué días de los últimos
``HISTORY_DAYS`` no tienen evaluación y los evalúa con el clima real de ese día.

Pensado para GitHub Actions, cuya IP de salida no está bloqueada por Open-Meteo
(la de Render sí: responde 429). Reutiliza el mismo adaptador que usa el
servidor, así el cálculo de las variables es idéntico. Solo necesita ``httpx``.

    API_URL=https://alerta-sin-red-api.onrender.com \\
    WEATHER_INGEST_TOKEN=... python scripts/push_weather.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # importar ``app`` sin instalar

from app.domain.exceptions import WeatherUnavailableError  # noqa: E402
from app.domain.value_objects import COLOMBIA_TZ, Coordinates  # noqa: E402
from app.infrastructure.weather.open_meteo import OpenMeteoWeatherProvider  # noqa: E402

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
# La instancia gratuita de Render tarda hasta ~1 min en despertar.
WAKE_ATTEMPTS = 8
WAKE_DELAY_SECONDS = 15
# Pausa entre zonas: respeta el límite por minuto de Open-Meteo.
PAUSE_BETWEEN_ZONES = 1.0
# Si Open-Meteo no responde (cortes breves), se vuelve a intentar toda la lista.
PASSES = 3
PAUSE_BETWEEN_PASSES = 30.0
# Días hacia atrás que se mantienen completos en el historial de cada zona.
HISTORY_DAYS = 30


def wake_up(api: httpx.Client) -> None:
    for attempt in range(1, WAKE_ATTEMPTS + 1):
        try:
            if api.get("/api/v1/health").status_code == 200:
                return
        except httpx.HTTPError as exc:
            print(f"API aún no responde ({type(exc).__name__}); intento {attempt}")
        time.sleep(WAKE_DELAY_SECONDS)
    raise SystemExit("La API no despertó a tiempo")


def main() -> int:
    api_url = os.environ.get("API_URL", "").rstrip("/")
    # strip(): al pegar el secreto en GitHub o Render suele colarse un salto de línea.
    token = os.environ.get("WEATHER_INGEST_TOKEN", "").strip()
    if not api_url or not token:
        raise SystemExit("Faltan API_URL o WEATHER_INGEST_TOKEN")

    with httpx.Client(base_url=api_url, timeout=120.0) as api, httpx.Client(
        timeout=httpx.Timeout(30.0, connect=15.0),
        transport=httpx.HTTPTransport(retries=3),  # reintenta fallos de conexión
        headers={"User-Agent": "AlertaSinRed/0.1 (clima desde GitHub Actions)"},
    ) as meteo:
        wake_up(api)
        zones = [item["zone"] for item in api.get("/api/v1/risk/snapshot").json()["items"]]
        provider = OpenMeteoWeatherProvider(FORECAST_URL, FLOOD_URL, meteo)

        observations: list[dict] = []
        pending = list(zones)
        for attempt in range(1, PASSES + 1):
            if attempt > 1:
                print(f"Reintentando {len(pending)} zona(s) en {PAUSE_BETWEEN_PASSES:.0f} s "
                      f"(pasada {attempt} de {PASSES})")
                time.sleep(PAUSE_BETWEEN_PASSES)
            failed: list[dict] = []
            for zone in pending:
                try:
                    c = provider.get_conditions(Coordinates(zone["latitude"], zone["longitude"]))
                except WeatherUnavailableError as exc:
                    print(f"SIN CLIMA {zone['name']}: {exc}")
                    failed.append(zone)
                    continue
                observations.append(as_payload(zone["id"], c))
                print(f"{zone['name']}: 72 h = {c.rain_72h_mm} mm, suelo = {c.soil_moisture}")
                time.sleep(PAUSE_BETWEEN_ZONES)
            pending = failed
            if not pending:
                break

        status = deliver_current(api, token, observations)
        # El historial es un complemento: si falla, no cambia el resultado del trabajo.
        fill_history(api, token, provider, zones)
        return status


def as_payload(zone_id: str, c) -> dict:
    return {
        "zone_id": zone_id,
        "rain_24h_mm": c.rain_24h_mm, "rain_72h_mm": c.rain_72h_mm,
        "rain_7d_mm": c.rain_7d_mm, "rain_forecast_24h_mm": c.rain_forecast_24h_mm,
        "soil_moisture": c.soil_moisture, "river_discharge_ratio": c.river_discharge_ratio,
        "observed_at": c.observed_at.isoformat(), "source": c.source,
    }


def deliver_current(api: httpx.Client, token: str, observations: list[dict]) -> int:
    if not observations:
        print("Ninguna zona obtuvo clima; no se envía nada")
        return 1
    response = api.post(
        "/api/v1/weather/observations",
        json={"observations": observations},
        headers={"X-Ingest-Token": token},
    )
    if response.status_code != 200:
        print(f"La API rechazó la ingesta: {response.status_code} {response.text[:300]}")
        return 1
    result = response.json()
    print(f"Guardadas {result['stored']} observaciones; "
          f"{result['evaluated']} zonas evaluadas; fallos: {result['failures'] or 'ninguno'}")
    return 0 if result["evaluated"] else 1


def fill_history(
    api: httpx.Client, token: str, provider: OpenMeteoWeatherProvider, zones: list[dict]
) -> None:
    """Evalúa los días de los últimos HISTORY_DAYS que aún no tienen evaluación."""
    today = datetime.now(COLOMBIA_TZ).date()
    wanted = {today - timedelta(days=k) for k in range(1, HISTORY_DAYS + 1)}
    created = 0
    for zone in zones:
        try:
            response = api.get(f"/api/v1/zones/{zone['id']}/days",
                               params={"days": HISTORY_DAYS + 1})
            if response.status_code == 404:
                print("La API aún no tiene historial por día (versión anterior); se omite")
                return
            response.raise_for_status()
            covered = {datetime.fromisoformat(d["day"]).date() for d in response.json()}
            missing = wanted - covered
            if not missing:
                continue
            history = provider.daily_history(
                Coordinates(zone["latitude"], zone["longitude"]), HISTORY_DAYS
            )
            items = [as_payload(zone["id"], h) for h in history
                     if h.observed_at.astimezone(COLOMBIA_TZ).date() in missing]
            if not items:
                continue
            result = api.post("/api/v1/weather/history", json={"observations": items},
                              headers={"X-Ingest-Token": token})
            result.raise_for_status()
            created += result.json()["created"]
            print(f"Historial {zone['name']}: {result.json()['created']} día(s) nuevo(s)")
            time.sleep(PAUSE_BETWEEN_ZONES)
        except (httpx.HTTPError, WeatherUnavailableError, KeyError, ValueError) as exc:
            print(f"Historial {zone['name']}: no se pudo completar ({exc})")
    print(f"Historial: {created} evaluación(es) de días pasados agregada(s)")


if __name__ == "__main__":
    sys.exit(main())
