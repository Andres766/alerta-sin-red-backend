import pytest

from app.domain.exceptions import ConsentRequiredError, ZoneNotFoundError
from app.domain.value_objects import RiskLevel
from app.infrastructure.memory.repositories import InMemoryUnitOfWork
from tests.conftest import make_container


def first_zone(store):
    return next(z for z in store.zones.values() if z.susceptibility == 5)


class TestRiskAssessmentService:
    def test_tormenta_dispara_sms_a_suscriptores(self, container, store, sms):
        zone = first_zone(store)
        with container.uow_factory() as uow:
            container.subscription_service(uow).subscribe("3001234567", zone.id, True)
            report = container.risk_service(uow).evaluate_all()

        assert len(report.assessments) == len(store.zones)
        mocoa = next(a for a in report.assessments if a.zone_id == zone.id)
        assert mocoa.level in (RiskLevel.ALTO, RiskLevel.MUY_ALTO)
        assert len(sms.outbox) == 1
        phone, message = sms.outbox[0]
        assert phone.value == "+573001234567" and "ALERTA" in message

    def test_enfriamiento_no_repite_el_sms(self, container, store, sms):
        zone = first_zone(store)
        with container.uow_factory() as uow:
            container.subscription_service(uow).subscribe("3001234567", zone.id, True)
            container.risk_service(uow).evaluate_all()
            container.risk_service(uow).evaluate_all()
        assert len(sms.outbox) == 1

    def test_clima_seco_no_alerta(self, settings, store, sms, risk_model):
        dry = make_container(settings, store, sms, risk_model, "seco")
        dry.seed()
        with dry.uow_factory() as uow:
            dry.subscription_service(uow).subscribe("3001234567", first_zone(store).id, True)
            report = dry.risk_service(uow).evaluate_all()
        assert all(not a.requires_alert for a in report.assessments)
        assert sms.outbox == []


class TestSubscriptionService:
    def test_es_idempotente(self, container, store):
        zone = first_zone(store)
        with container.uow_factory() as uow:
            service = container.subscription_service(uow)
            a = service.subscribe("300 123 4567", zone.id, True)
            b = service.subscribe("+573001234567", zone.id, True)
        assert a.id == b.id
        assert len(store.subscribers) == 1

    def test_zona_inexistente(self, container):
        from uuid import uuid4
        with container.uow_factory() as uow, pytest.raises(ZoneNotFoundError):
            container.subscription_service(uow).subscribe("3001234567", uuid4(), True)

    def test_requiere_consentimiento(self, container, store):
        with container.uow_factory() as uow, pytest.raises(ConsentRequiredError):
            container.subscription_service(uow).subscribe(
                "3001234567", first_zone(store).id, False
            )


def test_snapshot_ordena_por_severidad(container, store):
    with container.uow_factory() as uow:
        container.risk_service(uow).evaluate_all()
        snap = container.zone_queries(InMemoryUnitOfWork(store)).snapshot()
    severities = [i.assessment.level.severity for i in snap.items]
    assert severities == sorted(severities, reverse=True)
