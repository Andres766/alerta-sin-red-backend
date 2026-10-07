from datetime import timedelta
from uuid import uuid4

import pytest

from app.domain.entities import (
    AlertNotification,
    NotificationStatus,
    RiskAssessment,
    Subscriber,
    Zone,
    utcnow,
)
from app.domain.exceptions import (
    ConsentRequiredError,
    InvalidCoordinatesError,
    InvalidPhoneNumberError,
    ValidationError,
)
from app.domain.policies import AlertMessageBuilder, AlertPolicy
from app.domain.value_objects import (
    Coordinates,
    HazardType,
    PhoneNumber,
    RiskFeatures,
    RiskLevel,
)


def features(**overrides) -> RiskFeatures:
    base = dict(rain_24h_mm=1, rain_72h_mm=3, rain_7d_mm=10, rain_forecast_24h_mm=1,
                soil_moisture=0.2, river_discharge_ratio=1.0, slope_deg=10, susceptibility=2)
    return RiskFeatures(**{**base, **overrides})


def zone(**overrides) -> Zone:
    base = dict(name="Barrio de prueba con un nombre bastante largo para el SMS",
                municipality="Pasto", department="Nariño",
                hazard_type=HazardType.DESLIZAMIENTO, susceptibility=4, slope_deg=25,
                location=Coordinates(1.21, -77.28))
    return Zone(**{**base, **overrides})


def assessment(level: RiskLevel, z: Zone | None = None) -> RiskAssessment:
    return RiskAssessment(zone_id=(z or zone()).id, level=level, probability=0.9,
                          probabilities={}, features=features(), model_version="t",
                          weather_source="t")


class TestPhoneNumber:
    @pytest.mark.parametrize("raw", ["3001234567", "300 123 4567", "+57 300-123-4567",
                                     "573001234567"])
    def test_normaliza_formatos_colombianos(self, raw):
        assert PhoneNumber.parse(raw).value == "+573001234567"

    @pytest.mark.parametrize("raw", ["12345", "6012345678", "+1 555 123 4567", "3001234567x",
                                     "' OR 1=1 --", "9" * 40])
    def test_rechaza_numeros_invalidos(self, raw):
        with pytest.raises(InvalidPhoneNumberError):
            PhoneNumber.parse(raw)

    def test_nunca_se_imprime_completo(self):
        phone = PhoneNumber.parse("3001234567")
        assert str(phone) == "+57 300 *** **67"
        assert "1234567" not in repr(phone)


class TestValueObjects:
    def test_coordenadas_fuera_de_rango(self):
        with pytest.raises(InvalidCoordinatesError):
            Coordinates(95, 0)

    def test_distancia_pasto_mocoa(self):
        pasto, mocoa = Coordinates(1.2136, -77.2811), Coordinates(1.1500, -76.6480)
        assert 69 < pasto.distance_km(mocoa) < 72

    def test_variables_negativas_invalidas(self):
        with pytest.raises(ValidationError):
            features(rain_24h_mm=-1)

    def test_factores_explican_el_riesgo(self):
        factors = features(rain_72h_mm=80, soil_moisture=0.45, susceptibility=5).key_factors()
        assert any("72 h" in f for f in factors)
        assert "Suelo saturado de agua" in factors

    def test_niveles_que_requieren_sms(self):
        assert [lvl.requires_sms for lvl in RiskLevel] == [False, False, True, True]


class TestSubscriber:
    def test_sin_consentimiento_no_se_suscribe(self):
        with pytest.raises(ConsentRequiredError):
            Subscriber.subscribe(uuid4(), PhoneNumber.parse("3001234567"), consent=False)


class TestAlertPolicy:
    policy = AlertPolicy(cooldown=timedelta(hours=6))

    def _sent(self, level: RiskLevel, hours_ago: float) -> AlertNotification:
        return AlertNotification(zone_id=uuid4(), assessment_id=uuid4(), subscriber_id=uuid4(),
                                 level=level, channel="t", status=NotificationStatus.SENT,
                                 created_at=utcnow() - timedelta(hours=hours_ago))

    def test_riesgo_bajo_no_alerta(self):
        assert not self.policy.should_alert(assessment(RiskLevel.MODERADO), None, utcnow())

    def test_primera_alerta_alta(self):
        assert self.policy.should_alert(assessment(RiskLevel.ALTO), None, utcnow())

    def test_enfriamiento_evita_repetir(self):
        last = self._sent(RiskLevel.ALTO, hours_ago=1)
        assert not self.policy.should_alert(assessment(RiskLevel.ALTO), last, utcnow())

    def test_escalamiento_ignora_enfriamiento(self):
        last = self._sent(RiskLevel.ALTO, hours_ago=1)
        assert self.policy.should_alert(assessment(RiskLevel.MUY_ALTO), last, utcnow())

    def test_repite_tras_enfriamiento(self):
        last = self._sent(RiskLevel.ALTO, hours_ago=7)
        assert self.policy.should_alert(assessment(RiskLevel.ALTO), last, utcnow())


class TestAlertMessage:
    def test_sms_en_un_segmento_gsm7(self):
        z = zone(name="Pasto - Ladera de la Quebrada Chapal, sector Mijitayo y alrededores " * 2)
        text = AlertMessageBuilder().build(z, assessment(RiskLevel.MUY_ALTO, z))
        assert len(text) <= 160
        assert text.isascii()
        assert text.startswith("ALERTA ROJA")
