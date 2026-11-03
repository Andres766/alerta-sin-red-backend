import threading

import pytest

from app.domain.exceptions import ConflictError
from app.infrastructure.locks import InProcessJobLock

API = "/api/v1"


def test_candado_en_proceso_es_exclusivo_y_se_libera():
    lock = InProcessJobLock()
    with lock.hold() as first, lock.hold() as second:
        assert first is True and second is False
    with lock.hold() as again:
        assert again is True


def test_no_se_ejecutan_dos_evaluaciones_a_la_vez(container):
    started, release = threading.Event(), threading.Event()
    original = container.weather.get_conditions

    def slow(point):  # la primera evaluación se queda "trabajando"
        started.set()
        release.wait(5)
        return original(point)

    container.weather.get_conditions = slow
    results: dict[str, object] = {}

    def first() -> None:
        with container.uow_factory() as uow:
            results["first"] = container.risk_service(uow).evaluate_all()

    worker = threading.Thread(target=first)
    worker.start()
    started.wait(5)
    with container.uow_factory() as uow, pytest.raises(ConflictError):
        container.risk_service(uow).evaluate_all()
    release.set()
    worker.join(5)
    assert len(results["first"].assessments) == 6


def test_el_operador_recibe_409_si_esta_ocupada(client, admin_token, container):
    with container.evaluation_lock.hold():
        res = client.post(f"{API}/admin/evaluations",
                          headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 409 and "en curso" in res.json()["detail"]
