from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import make_container

API = "/api/v1"


def test_limite_por_cuenta_aunque_cambie_la_ip(store, sms, risk_model):
    # Límite por IP alto para aislar el límite por cuenta.
    settings = Settings(
        _env_file=None, environment="test", repository_backend="memory",
        weather_provider="fake", jwt_secret="s" * 48,
        phone_encryption_key=Fernet.generate_key().decode(), phone_index_key="k",
        login_rate_limit_per_minute=100, login_attempts_per_account=3,
    )
    container = make_container(settings, store, sms, risk_model, "tormenta")
    with TestClient(create_app(settings, container)) as client:
        codes = [
            client.post(f"{API}/auth/login",
                        json={"email": "victima@x.co", "password": "intento-incorrecto"},
                        headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
            for i in range(5)
        ]
        other = client.post(f"{API}/auth/login",
                            json={"email": "otra@x.co", "password": "intento-incorrecto"})
    assert codes[:3] == [401, 401, 401]
    assert codes[3:] == [429, 429]
    assert other.status_code == 401  # las demás cuentas no se ven afectadas


def test_estadisticas_del_panel(client, admin_token):
    auth = {"Authorization": f"Bearer {admin_token}"}
    before = client.get(f"{API}/admin/stats", headers=auth).json()
    assert before["zones_by_level"]["SIN_EVALUAR"] == 6
    assert before["last_evaluation_at"] is None

    snapshot = client.get(f"{API}/risk/snapshot").json()["items"]
    mocoa = next(i["zone"]["id"] for i in snapshot if "Mocoa" in i["zone"]["name"])
    client.post(f"{API}/subscriptions",
                json={"phone": "3109876543", "zone_id": mocoa, "accepts_data_policy": True})
    client.post(f"{API}/admin/evaluations", headers=auth)

    after = client.get(f"{API}/admin/stats", headers=auth).json()
    levels = after["zones_by_level"]
    assert levels["SIN_EVALUAR"] == 0 and sum(levels.values()) == 6
    assert after["sms_sent_24h"] == 1 and after["sms_failed_24h"] == 0
    assert after["active_subscribers"] == 1 and after["last_evaluation_at"]
