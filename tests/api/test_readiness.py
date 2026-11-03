API = "/api/v1"


def test_listo_cuando_todas_las_verificaciones_pasan(client, container):
    container.readiness_checks["database"] = lambda: None
    res = client.get(f"{API}/health/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_503_si_la_base_de_datos_no_responde(client, container):
    def caida() -> None:
        raise ConnectionError("conexión rechazada por 10.0.0.5:5432")

    container.readiness_checks["database"] = caida
    res = client.get(f"{API}/health/ready")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "unavailable"
    # Solo el tipo de error: nunca direcciones internas ni mensajes del driver.
    assert body["checks"]["database"] == "error: ConnectionError"
    assert "10.0.0.5" not in res.text


def test_liveness_no_depende_de_la_base(client, container):
    container.readiness_checks["database"] = lambda: (_ for _ in ()).throw(OSError())
    assert client.get(f"{API}/health").status_code == 200
