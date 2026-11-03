import logging

API = "/api/v1"


def test_cada_respuesta_lleva_un_id_de_peticion(client):
    first = client.get(f"{API}/health").headers["x-request-id"]
    second = client.get(f"{API}/health").headers["x-request-id"]
    assert len(first) == 32 and first != second


def test_reutiliza_un_id_valido_del_proxy(client):
    res = client.get(f"{API}/health", headers={"X-Request-ID": "vercel-abc12345"})
    assert res.headers["x-request-id"] == "vercel-abc12345"


def test_descarta_un_id_con_caracteres_peligrosos(client):
    res = client.get(f"{API}/health", headers={"X-Request-ID": "x\nFALSO log inyectado"})
    assert "\n" not in res.headers["x-request-id"]
    assert len(res.headers["x-request-id"]) == 32


def test_el_log_de_acceso_omite_la_ubicacion(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.access"):
        client.get(f"{API}/zones/nearby", params={"lat": 1.2136, "lon": -77.2811})
    line = next(r.getMessage() for r in caplog.records if r.name == "app.access")
    assert "/zones/nearby -> 200" in line and "1.2136" not in line
