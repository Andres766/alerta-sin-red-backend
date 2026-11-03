from uuid import uuid4

API = "/api/v1"


def test_detalle_de_zona_sin_evaluar(client):
    zone = client.get(f"{API}/risk/snapshot").json()["items"][0]["zone"]
    body = client.get(f"{API}/zones/{zone['id']}").json()
    assert body["zone"]["name"] == zone["name"] and body["assessment"] is None


def test_detalle_trae_la_ultima_evaluacion(client, admin_token):
    client.post(f"{API}/admin/evaluations", headers={"Authorization": f"Bearer {admin_token}"})
    zone_id = client.get(f"{API}/risk/snapshot").json()["items"][0]["zone"]["id"]
    body = client.get(f"{API}/zones/{zone_id}").json()
    assert body["assessment"]["level"] in ("BAJO", "MODERADO", "ALTO", "MUY_ALTO")
    assert body["assessment"]["key_factors"] is not None


def test_zona_inexistente_y_id_invalido(client):
    assert client.get(f"{API}/zones/{uuid4()}").status_code == 404
    assert client.get(f"{API}/zones/no-es-un-uuid").status_code == 422


def test_la_ruta_nearby_no_choca_con_el_detalle(client):
    res = client.get(f"{API}/zones/nearby", params={"lat": 1.21, "lon": -77.28})
    assert res.status_code == 200 and isinstance(res.json(), list)
