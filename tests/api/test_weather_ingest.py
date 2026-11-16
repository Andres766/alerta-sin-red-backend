"""Ingesta de clima desde un trabajo externo: token propio, guardado y evaluación."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

API = "/api/v1"
TOKEN = "token-de-ingesta-de-prueba-con-largo-suficiente"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None, environment="test", repository_backend="memory",
        weather_provider="fake", jwt_secret="s" * 48,
        phone_encryption_key=Fernet.generate_key().decode(), phone_index_key="clave",
        admin_email=ADMIN_EMAIL, admin_password=ADMIN_PASSWORD,
        weather_ingest_token=TOKEN,
    )


def observation(zone_id: str, rain_72h: float = 120.0) -> dict:
    return {
        "zone_id": zone_id, "rain_24h_mm": 55, "rain_72h_mm": rain_72h, "rain_7d_mm": 190,
        "rain_forecast_24h_mm": 60, "soil_moisture": 0.47, "river_discharge_ratio": 2.6,
        "observed_at": datetime.now(UTC).isoformat(), "source": "open-meteo",
    }


def zone_ids(client) -> list[str]:
    return [i["zone"]["id"] for i in client.get(f"{API}/risk/snapshot").json()["items"]]


def test_sin_token_o_con_token_malo_se_rechaza(client):
    body = {"observations": [observation(str(uuid4()))]}
    assert client.post(f"{API}/weather/observations", json=body).status_code == 401
    bad = client.post(f"{API}/weather/observations", json=body, headers={"X-Ingest-Token": "x"})
    assert bad.status_code == 401


def test_guarda_el_clima_y_evalua_con_el(client):
    ids = zone_ids(client)
    body = {"observations": [observation(z) for z in ids] + [observation(str(uuid4()))]}
    res = client.post(f"{API}/weather/observations", json=body, headers={"X-Ingest-Token": TOKEN})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["stored"] == len(ids)
    assert len(data["unknown_zones"]) == 1
    assert data["evaluated"] == len(ids) and data["failures"] == {}

    items = client.get(f"{API}/risk/snapshot").json()["items"]
    # El riesgo se calculó con el clima recibido, no con el proveedor configurado (simulado).
    assert all(i["assessment"]["weather_source"] == "open-meteo" for i in items)
    assert all(i["assessment"]["features"]["rain_72h_mm"] == 120.0 for i in items)


def test_queda_en_la_bitacora_como_clima_externo(client, admin_token):
    ids = zone_ids(client)
    client.post(f"{API}/weather/observations", json={"observations": [observation(ids[0])]},
                headers={"X-Ingest-Token": TOKEN})
    entries = client.get(f"{API}/admin/audit", headers={"Authorization": f"Bearer {admin_token}"})
    actions = [(e["actor"], e["action"]) for e in entries.json()]
    assert ("clima-externo", "EVALUATION_RUN") in actions


def test_valores_fuera_de_rango_se_rechazan(client):
    bad = observation(str(uuid4()))
    bad["soil_moisture"] = 1.5
    res = client.post(f"{API}/weather/observations", json={"observations": [bad]},
                      headers={"X-Ingest-Token": TOKEN})
    assert res.status_code == 422


def test_sin_token_configurado_el_endpoint_esta_apagado(client, container):
    container.settings.weather_ingest_token = None
    res = client.post(f"{API}/weather/observations", json={"observations": []},
                      headers={"X-Ingest-Token": TOKEN})
    assert res.status_code == 503
