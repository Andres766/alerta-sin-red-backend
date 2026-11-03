"""DTOs de entrada/salida (Pydantic).

* Las entradas usan ``extra="forbid"`` y límites explícitos: cualquier campo
  inesperado o fuera de rango se rechaza con 422 antes de llegar al dominio
  (defensa contra asignación masiva y cargas maliciosas).
* Las salidas nunca exponen datos sensibles (teléfonos enmascarados, sin hashes).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.application.services.subscriptions import SubscriptionResult
from app.application.services.zones import RiskSnapshot, ZoneRisk
from app.domain.entities import AlertNotification, RiskAssessment, Role, Subscriber, User, Zone
from app.domain.value_objects import HazardType, RiskLevel


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ------------------------------- Entradas ---------------------------------- #


class SubscriptionIn(InputModel):
    phone: Annotated[str, StringConstraints(min_length=10, max_length=20,
                                            pattern=r"^[0-9+\s\-().]+$")]
    zone_id: UUID
    accepts_data_policy: bool = Field(
        description="Autorización de tratamiento de datos (Ley 1581 de 2012)"
    )


class CancelSubscriptionIn(InputModel):
    cancel_token: Annotated[str, StringConstraints(min_length=20, max_length=100)]


class UserCreateIn(InputModel):
    email: EmailStr
    # Política mínima: 12 caracteres (NIST SP 800-63B prioriza longitud sobre complejidad).
    password: Annotated[str, StringConstraints(min_length=12, max_length=128)]
    role: Role = Role.OPERATOR


class LoginIn(InputModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)]


# ------------------------------- Salidas ----------------------------------- #


class ZoneOut(BaseModel):
    id: UUID
    name: str
    municipality: str
    department: str
    hazard_type: HazardType
    susceptibility: int
    slope_deg: float
    latitude: float
    longitude: float

    @classmethod
    def of(cls, z: Zone) -> ZoneOut:
        return cls(
            id=z.id, name=z.name, municipality=z.municipality, department=z.department,
            hazard_type=z.hazard_type, susceptibility=z.susceptibility, slope_deg=z.slope_deg,
            latitude=z.location.latitude, longitude=z.location.longitude,
        )


class AssessmentOut(BaseModel):
    id: UUID
    level: RiskLevel
    alert_color: str
    probability: float
    probabilities: dict[str, float]
    features: dict[str, float]
    key_factors: list[str]
    model_version: str
    weather_source: str
    assessed_at: datetime

    @classmethod
    def of(cls, a: RiskAssessment) -> AssessmentOut:
        return cls(
            id=a.id, level=a.level, alert_color=a.level.alert_color, probability=a.probability,
            probabilities=a.probabilities, features=a.features.to_dict(),
            key_factors=a.features.key_factors(), model_version=a.model_version,
            weather_source=a.weather_source, assessed_at=a.assessed_at,
        )


class ZoneRiskOut(BaseModel):
    zone: ZoneOut
    assessment: AssessmentOut | None

    @classmethod
    def of(cls, item: ZoneRisk) -> ZoneRiskOut:
        return cls(
            zone=ZoneOut.of(item.zone),
            assessment=AssessmentOut.of(item.assessment) if item.assessment else None,
        )


class SnapshotOut(BaseModel):
    generated_at: datetime
    items: list[ZoneRiskOut]

    @classmethod
    def of(cls, s: RiskSnapshot) -> SnapshotOut:
        return cls(generated_at=s.generated_at, items=[ZoneRiskOut.of(i) for i in s.items])


class NearbyZoneOut(BaseModel):
    zone: ZoneOut
    distance_km: float


class SubscriptionOut(BaseModel):
    id: UUID
    zone_id: UUID
    phone_masked: str
    active: bool
    cancel_token: str | None = Field(
        default=None,
        description="Código de baja. Se entrega una sola vez: el dispositivo debe guardarlo.",
    )
    message: str = "Suscripción registrada. Recibirá SMS si el riesgo de su zona es alto."

    @classmethod
    def of(cls, result: SubscriptionResult) -> SubscriptionOut:
        s: Subscriber = result.subscriber
        return cls(id=s.id, zone_id=s.zone_id, phone_masked=s.phone.masked(), active=s.active,
                   cancel_token=result.cancel_token)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - no es una contraseña
    expires_in: int
    role: str


class EvaluationOut(BaseModel):
    evaluated: int
    failures: dict[str, str]
    assessments: list[AssessmentOut]


class AlertOut(BaseModel):
    id: UUID
    zone_id: UUID
    level: RiskLevel
    channel: str
    status: str
    error: str | None
    created_at: datetime

    @classmethod
    def of(cls, n: AlertNotification) -> AlertOut:
        return cls(id=n.id, zone_id=n.zone_id, level=n.level, channel=n.channel,
                   status=n.status.value, error=n.error, created_at=n.created_at)


class UserOut(BaseModel):
    id: UUID
    email: str
    role: Role
    active: bool
    created_at: datetime

    @classmethod
    def of(cls, u: User) -> UserOut:
        return cls(id=u.id, email=u.email, role=u.role, active=u.active, created_at=u.created_at)


class StatsOut(BaseModel):
    zones: int
    active_subscribers: int
    zones_by_level: dict[str, int]
    sms_sent_24h: int
    sms_failed_24h: int
    last_evaluation_at: datetime | None


class ReadinessOut(BaseModel):
    status: str
    checks: dict[str, str]


class HealthOut(BaseModel):
    status: str
    model_version: str
    weather_provider: str
    sms_channel: str


class ErrorOut(BaseModel):
    code: str
    detail: str
