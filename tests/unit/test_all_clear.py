from datetime import timedelta
from uuid import uuid4

from app.domain.entities import (
    AlertNotification,
    NotificationKind,
    NotificationStatus,
    RiskAssessment,
    utcnow,
)
from app.domain.policies import AlertMessageBuilder, AlertPolicy
from app.domain.value_objects import RiskLevel
from app.infrastructure.weather.fake import FakeWeatherProvider
from tests.unit.test_domain import features, zone

POLICY = AlertPolicy(cooldown=timedelta(hours=6))


def assessment(level: RiskLevel) -> RiskAssessment:
    return RiskAssessment(zone_id=uuid4(), level=level, probability=0.9, probabilities={},
                          features=features(), model_version="t", weather_source="t")


def sent(kind: NotificationKind, level=RiskLevel.ALTO, hours_ago=1.0) -> AlertNotification:
    return AlertNotification(zone_id=uuid4(), assessment_id=uuid4(), subscriber_id=uuid4(),
                             level=level, channel="t", status=NotificationStatus.SENT,
                             kind=kind, created_at=utcnow() - timedelta(hours=hours_ago))


class TestPolitica:
    def test_fin_de_alerta_tras_una_alerta(self):
        assert POLICY.should_send_all_clear(assessment(RiskLevel.MODERADO),
                                            sent(NotificationKind.ALERT))

    def test_no_repite_el_fin_de_alerta(self):
        assert not POLICY.should_send_all_clear(assessment(RiskLevel.BAJO),
                                                sent(NotificationKind.ALL_CLEAR))

    def test_sin_alerta_previa_no_hay_fin(self):
        assert not POLICY.should_send_all_clear(assessment(RiskLevel.BAJO), None)

    def test_tras_el_fin_una_nueva_alerta_ignora_el_enfriamiento(self):
        last = sent(NotificationKind.ALL_CLEAR, level=RiskLevel.MODERADO, hours_ago=0.5)
        assert POLICY.should_alert(assessment(RiskLevel.ALTO), last, utcnow())


def test_mensaje_de_fin_de_alerta_cabe_en_un_sms():
    z = zone(name="Barrio con un nombre larguísimo que obliga a recortar el texto del SMS " * 2)
    text = AlertMessageBuilder().build_all_clear(z, assessment(RiskLevel.BAJO))
    assert len(text) <= 160 and text.isascii() and "termino la alerta" in text


def test_ciclo_alerta_fin_y_nueva_alerta(container, store, sms):
    mocoa = next(z for z in store.zones.values() if z.susceptibility == 5)
    with container.uow_factory() as uow:
        container.subscription_service(uow).subscribe("3001234567", mocoa.id, True)
        container.risk_service(uow).evaluate_zone(mocoa.id)          # tormenta: alerta
        container.weather = FakeWeatherProvider("seco")
        container.risk_service(uow).evaluate_zone(mocoa.id)          # baja: fin de alerta
        container.risk_service(uow).evaluate_zone(mocoa.id)          # sigue bajo: nada
        container.weather = FakeWeatherProvider("tormenta")
        container.risk_service(uow).evaluate_zone(mocoa.id)          # sube: alerta inmediata
        kinds = [a.kind for a in sorted(uow.alerts.recent(10), key=lambda a: a.created_at)]

    assert kinds == [NotificationKind.ALERT, NotificationKind.ALL_CLEAR, NotificationKind.ALERT]
    assert [m.split(":")[0] for _, m in sms.outbox] == [
        "ALERTA ROJA AlertaSinRed", "AlertaSinRed", "ALERTA ROJA AlertaSinRed"]
