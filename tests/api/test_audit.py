from tests.conftest import ADMIN_EMAIL

API = "/api/v1"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def actions(client, token) -> list[tuple[str, str, str | None]]:
    entries = client.get(f"{API}/admin/audit", headers=auth(token)).json()
    return [(e["actor"], e["action"], e["target"]) for e in reversed(entries)]


def test_registra_inicios_de_sesion_exitosos_y_fallidos(client, admin_token):
    client.post(f"{API}/auth/login", json={"email": "Intruso@X.co", "password": "adivinando123"})
    log = actions(client, admin_token)
    assert (ADMIN_EMAIL, "LOGIN_SUCCEEDED", None) in log
    assert ("intruso@x.co", "LOGIN_FAILED", None) in log


def test_registra_gestion_de_cuentas_y_evaluaciones(client, admin_token):
    created = client.post(f"{API}/admin/users", headers=auth(admin_token),
                          json={"email": "op@pasto.gov.co", "password": "clave-operador-segura"})
    client.post(f"{API}/admin/users/{created.json()['id']}/deactivate", headers=auth(admin_token))
    client.post(f"{API}/admin/evaluations", headers=auth(admin_token))
    log = actions(client, admin_token)
    assert (ADMIN_EMAIL, "USER_CREATED", "op@pasto.gov.co") in log
    assert (ADMIN_EMAIL, "USER_DEACTIVATED", "op@pasto.gov.co") in log
    assert (ADMIN_EMAIL, "EVALUATION_RUN", None) in log


def test_la_bitacora_no_guarda_secretos(client, admin_token):
    client.post(f"{API}/admin/users", headers=auth(admin_token),
                json={"email": "op2@pasto.gov.co", "password": "clave-super-secreta-99"})
    text = client.get(f"{API}/admin/audit", headers=auth(admin_token)).text
    assert "clave-super-secreta-99" not in text and admin_token not in text


def test_solo_administradores_ven_la_bitacora(client, admin_token):
    client.post(f"{API}/admin/users", headers=auth(admin_token),
                json={"email": "op3@pasto.gov.co", "password": "clave-operador-segura"})
    op = client.post(f"{API}/auth/login",
                     json={"email": "op3@pasto.gov.co", "password": "clave-operador-segura"})
    res = client.get(f"{API}/admin/audit", headers=auth(op.json()["access_token"]))
    assert res.status_code == 403
