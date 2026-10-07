"""Entidades del dominio: tienen identidad (UUID) y encapsulan sus reglas de negocio."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.domain.exceptions import ConsentRequiredError, ValidationError
from app.domain.value_objects import (
    Coordinates,
    HazardType,
    PhoneNumber,
    RiskFeatures,
    RiskLevel,
    RiskPrediction,
    WeatherConditions,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class Zone:
    """Zona monitoreada (barrio, vereda o tramo de río en riesgo)."""

    name: str
    municipality: str
    department: str
    hazard_type: HazardType
    susceptibility: int  # 1 (muy baja) – 5 (muy alta), escala SGC
    slope_deg: float
    location: Coordinates
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("La zona debe tener nombre")
        if not 1 <= self.susceptibility <= 5:
            raise ValidationError("La susceptibilidad debe estar entre 1 y 5")
        if not 0 <= self.slope_deg <= 90:
            raise ValidationError("La pendiente debe estar entre 0° y 90°")

    def build_features(self, weather: WeatherConditions) -> RiskFeatures:
        """Combina la capa estática de la zona (SGC) con las condiciones dinámicas del clima.

        En zonas expuestas solo a deslizamiento el caudal de ríos cercanos no es
        un factor de amenaza, así que se neutraliza (1.0 = caudal habitual).
        """
        discharge = (
            1.0 if self.hazard_type is HazardType.DESLIZAMIENTO else weather.river_discharge_ratio
        )
        return RiskFeatures(
            rain_24h_mm=weather.rain_24h_mm,
            rain_72h_mm=weather.rain_72h_mm,
            rain_7d_mm=weather.rain_7d_mm,
            rain_forecast_24h_mm=weather.rain_forecast_24h_mm,
            soil_moisture=weather.soil_moisture,
            river_discharge_ratio=discharge,
            slope_deg=self.slope_deg,
            susceptibility=self.susceptibility,
        )


@dataclass(slots=True)
class RiskAssessment:
    """Resultado de una evaluación del modelo de IA para una zona en un instante."""

    zone_id: UUID
    level: RiskLevel
    probability: float
    probabilities: dict[str, float]
    features: RiskFeatures
    model_version: str
    weather_source: str
    assessed_at: datetime = field(default_factory=utcnow)
    id: UUID = field(default_factory=uuid4)

    @classmethod
    def from_prediction(
        cls,
        zone: Zone,
        features: RiskFeatures,
        prediction: RiskPrediction,
        model_version: str,
        weather_source: str,
    ) -> RiskAssessment:
        return cls(
            zone_id=zone.id,
            level=prediction.level,
            probability=round(prediction.probability, 4),
            probabilities={k: round(v, 4) for k, v in prediction.probabilities.items()},
            features=features,
            model_version=model_version,
            weather_source=weather_source,
        )

    @property
    def requires_alert(self) -> bool:
        return self.level.requires_sms


@dataclass(slots=True)
class Subscriber:
    """Persona que recibirá SMS cuando su zona entre en riesgo alto."""

    zone_id: UUID
    phone: PhoneNumber
    consent_at: datetime
    active: bool = True
    created_at: datetime = field(default_factory=utcnow)
    id: UUID = field(default_factory=uuid4)

    @classmethod
    def subscribe(cls, zone_id: UUID, phone: PhoneNumber, consent: bool) -> Subscriber:
        # Ley 1581 de 2012 (Habeas Data): sin autorización expresa no se guarda el dato.
        if consent is not True:
            raise ConsentRequiredError("Se requiere autorización para el tratamiento de datos")
        return cls(zone_id=zone_id, phone=phone, consent_at=utcnow())


class NotificationStatus(StrEnum):
    SENT = "SENT"
    FAILED = "FAILED"


@dataclass(slots=True)
class AlertNotification:
    """Registro auditable de cada SMS intentado."""

    zone_id: UUID
    assessment_id: UUID
    subscriber_id: UUID
    level: RiskLevel
    channel: str
    status: NotificationStatus
    provider_message_id: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    id: UUID = field(default_factory=uuid4)


class Role(StrEnum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"


@dataclass(slots=True)
class User:
    """Operador del sistema (gestión del riesgo municipal)."""

    email: str
    password_hash: str
    role: Role = Role.OPERATOR
    active: bool = True
    created_at: datetime = field(default_factory=utcnow)
    id: UUID = field(default_factory=uuid4)

    def can_trigger_evaluations(self) -> bool:
        return self.active and self.role in (Role.ADMIN, Role.OPERATOR)
