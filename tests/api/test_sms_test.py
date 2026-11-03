API = "/api/v1"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_envia_sms_de_prueba_y_lo_registra_enmascarado(client, admin_token, sms):
    res = client.post(f"{API}/admin/sms/test", headers=auth(admin_token),
                      json={"phone": "300 765 4321"})
    body = res.json()
    assert res.status_code == 200 and body["success"] and body["channel"] == "console"
    assert body["phone_masked"] == "+57 300 *** **21"
    assert len(sms.outbox) == 1 and "prueba" in sms.outbox[0][1]
    log = client.get(f"{API}/admin/audit", headers=auth(admin_token)).text
    assert "SMS_TEST_SENT" in log and "7654321" not in log


def test_limite_de_cinco_por_hora(client, admin_token):
    codes = [client.post(f"{API}/admin/sms/test", headers=auth(admin_token),
                         json={"phone": "3007654321"}).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]


def test_valida_el_numero(client, admin_token):
    res = client.post(f"{API}/admin/sms/test", headers=auth(admin_token),
                      json={"phone": "6012345678"})
    assert res.status_code == 422
