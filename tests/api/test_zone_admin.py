API = "/api/v1"

NUEVA = {
    "name": "Ipiales - Barrio El Charco", "municipality": "Ipiales", "department": "Nariño",
    "hazard_type": "DESLIZAMIENTO", "susceptibility": 3, "slope_deg": 22,
    "latitude": 0.8300, "longitude": -77.6400,
}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_crear_zona_la_incluye_en_el_snapshot_y_la_evaluacion(client, admin_token):
    res = client.post(f"{API}/admin/zones", headers=auth(admin_token), json=NUEVA)
    assert res.status_code == 201 and res.json()["municipality"] == "Ipiales"
    names = [i["zone"]["name"] for i in client.get(f"{API}/risk/snapshot").json()["items"]]
    assert NUEVA["name"] in names
    report = client.post(f"{API}/admin/evaluations", headers=auth(admin_token)).json()
    assert report["evaluated"] == 7


def test_rechaza_nombre_repetido_y_coordenadas_fuera_de_colombia(client, admin_token):
    client.post(f"{API}/admin/zones", headers=auth(admin_token), json=NUEVA)
    dup = client.post(f"{API}/admin/zones", headers=auth(admin_token),
                      json={**NUEVA, "name": NUEVA["name"].upper()})
    lejos = client.post(f"{API}/admin/zones", headers=auth(admin_token),
                        json={**NUEVA, "name": "Quito", "latitude": -0.18, "longitude": -78.47 - 5})
    assert dup.status_code == 409
    assert lejos.status_code == 422


def test_actualiza_la_capa_estatica_y_valida_rangos(client, admin_token):
    zone_id = client.get(f"{API}/risk/snapshot").json()["items"][0]["zone"]["id"]
    ok = client.patch(f"{API}/admin/zones/{zone_id}", headers=auth(admin_token),
                      json={"susceptibility": 5, "slope_deg": 35.5})
    assert ok.status_code == 200
    assert ok.json()["susceptibility"] == 5 and ok.json()["slope_deg"] == 35.5
    bad = client.patch(f"{API}/admin/zones/{zone_id}", headers=auth(admin_token),
                       json={"susceptibility": 9})
    empty = client.patch(f"{API}/admin/zones/{zone_id}", headers=auth(admin_token), json={})
    assert bad.status_code == 422 and empty.status_code == 422


def test_solo_administradores_y_queda_en_la_bitacora(client, admin_token):
    client.post(f"{API}/admin/users", headers=auth(admin_token),
                json={"email": "op@x.co", "password": "clave-operador-segura"})
    op = client.post(f"{API}/auth/login",
                     json={"email": "op@x.co", "password": "clave-operador-segura"}).json()
    assert client.post(f"{API}/admin/zones", headers=auth(op["access_token"]),
                       json=NUEVA).status_code == 403
    client.post(f"{API}/admin/zones", headers=auth(admin_token), json=NUEVA)
    log = client.get(f"{API}/admin/audit", headers=auth(admin_token)).json()
    assert any(e["action"] == "ZONE_CREATED" and e["target"] == NUEVA["name"] for e in log)
