import time

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

API = "/api/v1"
NEW = "una-clave-nueva-y-larga"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def change(client, token, current=ADMIN_PASSWORD, new=NEW):
    return client.post(f"{API}/auth/change-password", headers=auth(token),
                       json={"current_password": current, "new_password": new})


def test_cambia_la_clave_y_cierra_las_demas_sesiones(client, admin_token):
    time.sleep(1.1)  # el token anterior queda emitido en un segundo previo al cambio
    res = change(client, admin_token)
    assert res.status_code == 200
    fresh = res.json()["access_token"]

    assert client.get(f"{API}/auth/me", headers=auth(admin_token)).status_code == 401
    assert client.get(f"{API}/auth/me", headers=auth(fresh)).status_code == 200
    old = client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    new = client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": NEW})
    assert old.status_code == 401 and new.status_code == 200


def test_exige_la_clave_actual(client, admin_token):
    res = change(client, admin_token, current="clave-equivocada")
    assert res.status_code == 401
    assert client.get(f"{API}/auth/me", headers=auth(admin_token)).status_code == 200


def test_rechaza_claves_debiles_o_repetidas(client, admin_token):
    assert change(client, admin_token, new="corta").status_code == 422
    assert change(client, admin_token, new=ADMIN_PASSWORD).status_code == 422
    assert change(client, admin_token, new="admin-con-mi-usuario-123").status_code == 422


def test_queda_en_la_bitacora(client, admin_token):
    fresh = change(client, admin_token).json()["access_token"]
    actions = [e["action"] for e in client.get(f"{API}/admin/audit", headers=auth(fresh)).json()]
    assert "PASSWORD_CHANGED" in actions
