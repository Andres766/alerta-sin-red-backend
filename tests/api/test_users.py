import pytest

from app.domain.entities import Role
from app.domain.exceptions import ConflictError
from tests.conftest import ADMIN_EMAIL

API = "/api/v1"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_operator(client, admin_token, email="operador@pasto.gov.co"):
    return client.post(f"{API}/admin/users", headers=auth(admin_token),
                       json={"email": email, "password": "clave-operador-segura"})


def login(client, email="operador@pasto.gov.co", password="clave-operador-segura") -> str:
    res = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


def test_me_devuelve_la_sesion_sin_datos_sensibles(client, admin_token):
    body = client.get(f"{API}/auth/me", headers=auth(admin_token)).json()
    assert body["email"] == ADMIN_EMAIL and body["role"] == "ADMIN"
    assert "password_hash" not in body


def test_admin_crea_y_lista_operadores(client, admin_token):
    res = create_operator(client, admin_token)
    assert res.status_code == 201 and res.json()["role"] == "OPERATOR"
    users = client.get(f"{API}/admin/users", headers=auth(admin_token)).json()
    emails = [u["email"] for u in users]
    assert emails == [ADMIN_EMAIL, "operador@pasto.gov.co"]


def test_correo_duplicado_da_409(client, admin_token):
    create_operator(client, admin_token)
    assert create_operator(client, admin_token).status_code == 409


def test_contrasena_corta_rechazada(client, admin_token):
    res = client.post(f"{API}/admin/users", headers=auth(admin_token),
                      json={"email": "x@y.co", "password": "corta123"})
    assert res.status_code == 422


def test_operador_no_puede_gestionar_cuentas(client, admin_token):
    create_operator(client, admin_token)
    op_token = login(client)
    assert client.get(f"{API}/admin/users", headers=auth(op_token)).status_code == 403
    # pero sí puede operar el sistema
    assert client.get(f"{API}/admin/alerts", headers=auth(op_token)).status_code == 200


def test_desactivar_revoca_el_acceso_de_inmediato(client, admin_token):
    op = create_operator(client, admin_token).json()
    op_token = login(client)
    res = client.post(f"{API}/admin/users/{op['id']}/deactivate", headers=auth(admin_token))
    assert res.status_code == 200 and res.json()["active"] is False
    # El token aún no expira, pero la cuenta ya no tiene acceso.
    assert client.get(f"{API}/admin/alerts", headers=auth(op_token)).status_code == 401
    client.post(f"{API}/admin/users/{op['id']}/activate", headers=auth(admin_token))
    assert client.get(f"{API}/admin/alerts", headers=auth(op_token)).status_code == 200


def test_no_puede_desactivarse_a_si_mismo(client, admin_token):
    me = client.get(f"{API}/auth/me", headers=auth(admin_token)).json()
    res = client.post(f"{API}/admin/users/{me['id']}/deactivate", headers=auth(admin_token))
    assert res.status_code == 409


def test_siempre_queda_un_administrador_activo(container):
    with container.uow_factory() as uow:
        service = container.user_management(uow)
        admin = uow.users.get_by_email(ADMIN_EMAIL)
        operator = service.create("op@x.co", "otra-clave-segura", Role.OPERATOR, admin)
        # Aunque lo pidiera otra cuenta, el único administrador activo no se desactiva.
        with pytest.raises(ConflictError):
            service.set_active(admin.id, False, acting_user=operator)
