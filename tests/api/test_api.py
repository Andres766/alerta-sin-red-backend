from uuid import uuid4

from app.infrastructure.seed import SEED_ZONES

API = "/api/v1"


def zone_id(client) -> str:
    return client.get(f"{API}/risk/snapshot").json()["items"][0]["zone"]["id"]


def test_health(client):
    body = client.get(f"{API}/health").json()
    assert body["status"] == "ok" and body["model_version"].startswith("rf-")


def test_cabeceras_de_seguridad(client):
    headers = client.get(f"{API}/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in headers["content-security-policy"]


def test_snapshot_para_modo_offline(client):
    body = client.get(f"{API}/risk/snapshot").json()
    assert len(body["items"]) == len(SEED_ZONES)
    assert body["items"][0]["assessment"] is None  # aún sin evaluar


def test_zonas_cercanas(client):
    res = client.get(f"{API}/zones/nearby", params={"lat": 1.2136, "lon": -77.2811,
                                                    "radius_km": 20})
    names = [z["zone"]["name"] for z in res.json()]
    assert res.status_code == 200 and names and all("Mocoa" not in n for n in names)


def test_suscripcion_enmascara_telefono(client):
    res = client.post(f"{API}/subscriptions", json={
        "phone": "300 123 4567", "zone_id": zone_id(client), "accepts_data_policy": True})
    assert res.status_code == 201
    assert res.json()["phone_masked"] == "+57 300 *** **67"
    assert "3001234567" not in res.text


def test_suscripcion_rechaza_campos_extra_y_datos_invalidos(client):
    zid = zone_id(client)
    extra = client.post(f"{API}/subscriptions", json={
        "phone": "3001234567", "zone_id": zid, "accepts_data_policy": True, "active": False})
    bad_phone = client.post(f"{API}/subscriptions", json={
        "phone": "<script>", "zone_id": zid, "accepts_data_policy": True})
    no_consent = client.post(f"{API}/subscriptions", json={
        "phone": "3001234567", "zone_id": zid, "accepts_data_policy": False})
    missing_zone = client.post(f"{API}/subscriptions", json={
        "phone": "3001234567", "zone_id": str(uuid4()), "accepts_data_policy": True})
    assert extra.status_code == 422
    assert bad_phone.status_code == 422
    assert no_consent.status_code == 422 and no_consent.json()["code"] == "consent_required"
    assert missing_zone.status_code == 404


def test_admin_requiere_token(client):
    assert client.post(f"{API}/admin/evaluations").status_code == 401
    bad = client.post(f"{API}/admin/evaluations", headers={"Authorization": "Bearer basura"})
    assert bad.status_code == 401


def test_login_con_credenciales_invalidas_es_generico(client):
    res = client.post(f"{API}/auth/login", json={"email": "nadie@x.co", "password": "12345678"})
    assert res.status_code == 401
    assert res.json()["detail"] == "No autenticado"


def test_login_limitado_contra_fuerza_bruta(client):
    codes = [client.post(f"{API}/auth/login",
                         json={"email": "a@b.co", "password": "incorrecta"}).status_code
             for _ in range(5)]
    assert codes[-1] == 429


def test_flujo_completo_evaluacion_y_alertas(client, admin_token, sms):
    auth = {"Authorization": f"Bearer {admin_token}"}
    snapshot = client.get(f"{API}/risk/snapshot").json()
    mocoa = next(i["zone"]["id"] for i in snapshot["items"] if "Mocoa" in i["zone"]["name"])
    client.post(f"{API}/subscriptions",
                json={"phone": "3109876543", "zone_id": mocoa, "accepts_data_policy": True})

    res = client.post(f"{API}/admin/evaluations", headers=auth)
    assert res.status_code == 200 and res.json()["evaluated"] == len(SEED_ZONES)

    after = client.get(f"{API}/risk/snapshot").json()["items"]
    assert after[0]["assessment"]["level"] in ("ALTO", "MUY_ALTO")
    assert after[0]["assessment"]["key_factors"]

    alerts = client.get(f"{API}/admin/alerts", headers=auth).json()
    assert len(alerts) == 1 and alerts[0]["status"] == "SENT"
    assert len(sms.outbox) == 1

    history = client.get(f"{API}/zones/{mocoa}/history").json()
    assert len(history) == 1


def test_baja_de_suscripcion_por_api(client):
    created = client.post(f"{API}/subscriptions", json={
        "phone": "3001112233", "zone_id": zone_id(client), "accepts_data_policy": True}).json()
    url = f"{API}/subscriptions/{created['id']}/cancel"
    assert client.post(url, json={"cancel_token": "x" * 30}).status_code == 404
    assert client.post(url, json={"cancel_token": created["cancel_token"]}).status_code == 204
    assert client.post(url, json={"cancel_token": created["cancel_token"]}).status_code == 404
