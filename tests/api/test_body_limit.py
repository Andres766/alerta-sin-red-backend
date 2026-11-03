import json

API = "/api/v1"


def test_rechaza_cuerpos_grandes_con_413(client):
    huge = '{"phone": "' + "9" * 100_000 + '"}'
    res = client.post(f"{API}/subscriptions", content=huge,
                      headers={"Content-Type": "application/json"})
    assert res.status_code == 413 and res.json()["code"] == "payload_too_large"


def test_rechaza_cuerpos_grandes_sin_content_length(client):
    def chunks():
        for _ in range(100):
            yield b"x" * 1024

    res = client.post(f"{API}/auth/login", content=chunks(),
                      headers={"Content-Type": "application/json"})
    assert res.status_code == 413


def test_las_peticiones_normales_pasan(client):
    zone_id = client.get(f"{API}/risk/snapshot").json()["items"][0]["zone"]["id"]
    res = client.post(f"{API}/subscriptions", json={
        "phone": "3001234567", "zone_id": zone_id, "accepts_data_policy": True})
    assert res.status_code == 201


def test_cuerpo_por_partes_pequeno_llega_intacto(client):
    zone_id = client.get(f"{API}/risk/snapshot").json()["items"][0]["zone"]["id"]
    payload = json.dumps(
        {"phone": "3001234567", "zone_id": zone_id, "accepts_data_policy": True}
    )

    def chunks():
        yield payload[:20].encode()
        yield payload[20:].encode()

    res = client.post(f"{API}/subscriptions", content=chunks(),
                      headers={"Content-Type": "application/json"})
    assert res.status_code == 201
