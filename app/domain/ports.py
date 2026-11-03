"""Puertos (interfaces) de la arquitectura hexagonal.

El dominio y la aplicación dependen de estas abstracciones, nunca de
implementaciones concretas (principio de inversión de dependencias, la "D" de
SOLID). La infraestructura provee los adaptadores: PostgreSQL/PostGIS,
Open-Meteo, Twilio, Android SMS Gateway, scikit-learn, etc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from uuid import UUID

from app.domain.entities import (
    AlertNotification,
    AuditEntry,
    RiskAssessment,
    Subscriber,
    User,
    Zone,
)
from app.domain.value_objects import (
    Coordinates,
    PhoneNumber,
    RiskFeatures,
    RiskPrediction,
    WeatherConditions,
)

# --------------------------------------------------------------------------- #
# Repositorios (patrón Repository)
# --------------------------------------------------------------------------- #


class ZoneRepository(ABC):
    @abstractmethod
    def get(self, zone_id: UUID) -> Zone | None: ...

    @abstractmethod
    def list_all(self) -> list[Zone]: ...

    @abstractmethod
    def find_nearby(
        self, point: Coordinates, radius_km: float, limit: int
    ) -> list[tuple[Zone, float]]:
        """Zonas dentro del radio, ordenadas por distancia (km)."""

    @abstractmethod
    def add(self, zone: Zone) -> None: ...


class RiskAssessmentRepository(ABC):
    @abstractmethod
    def add(self, assessment: RiskAssessment) -> None: ...

    @abstractmethod
    def latest_by_zone(self) -> dict[UUID, RiskAssessment]: ...

    @abstractmethod
    def history(self, zone_id: UUID, limit: int) -> list[RiskAssessment]: ...

    @abstractmethod
    def since(self, moment: datetime, limit: int) -> list[RiskAssessment]:
        """Evaluaciones de todas las zonas desde ``moment``, en orden cronológico."""


class SubscriberRepository(ABC):
    @abstractmethod
    def add(self, subscriber: Subscriber) -> None: ...

    @abstractmethod
    def get(self, subscriber_id: UUID) -> Subscriber | None: ...

    @abstractmethod
    def find(self, zone_id: UUID, phone: PhoneNumber) -> Subscriber | None: ...

    @abstractmethod
    def active_for_zone(self, zone_id: UUID) -> list[Subscriber]: ...

    @abstractmethod
    def count_active(self) -> int: ...


class AlertRepository(ABC):
    @abstractmethod
    def add(self, notification: AlertNotification) -> None: ...

    @abstractmethod
    def last_sent_for_zone(self, zone_id: UUID) -> AlertNotification | None: ...

    @abstractmethod
    def recent(self, limit: int) -> list[AlertNotification]: ...

    @abstractmethod
    def count_since(self, since: datetime) -> dict[str, int]:
        """Cantidad de notificaciones por estado (SENT/FAILED) desde ``since``."""


class UserRepository(ABC):
    @abstractmethod
    def get(self, user_id: UUID) -> User | None: ...

    @abstractmethod
    def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    def list_all(self) -> list[User]: ...

    @abstractmethod
    def add(self, user: User) -> None: ...


class AuditRepository(ABC):
    @abstractmethod
    def add(self, entry: AuditEntry) -> None: ...

    @abstractmethod
    def recent(self, limit: int) -> list[AuditEntry]: ...


class UnitOfWork(ABC):
    """Agrupa los repositorios bajo una misma transacción (patrón Unit of Work)."""

    zones: ZoneRepository
    assessments: RiskAssessmentRepository
    subscribers: SubscriberRepository
    alerts: AlertRepository
    users: UserRepository
    audit: AuditRepository

    def __enter__(self) -> UnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.rollback()  # si no se hizo commit explícito, nada queda a medias

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...


# --------------------------------------------------------------------------- #
# Servicios externos (patrones Adapter + Strategy)
# --------------------------------------------------------------------------- #


class WeatherProvider(ABC):
    @abstractmethod
    def get_conditions(self, point: Coordinates) -> WeatherConditions:
        """Lanza ``WeatherUnavailableError`` si la fuente no responde."""


@dataclass(frozen=True, slots=True)
class SmsResult:
    success: bool
    provider_message_id: str | None = None
    error: str | None = None


class SmsGateway(ABC):
    @property
    @abstractmethod
    def channel(self) -> str: ...

    @abstractmethod
    def send(self, phone: PhoneNumber, message: str) -> SmsResult:
        """Nunca lanza por fallos del proveedor: devuelve ``SmsResult(success=False)``."""


@dataclass(frozen=True, slots=True)
class ModelCard:
    """Ficha técnica del modelo: qué es, con qué datos se entrenó y qué tan bien rinde."""

    version: str
    algorithm: str
    trained_at: str
    data_source: str
    n_samples: int
    feature_order: tuple[str, ...]
    feature_importances: dict[str, float]
    metrics: dict[str, float]
    confusion_matrix: list[list[int]]
    labels: tuple[str, ...]


class RiskModel(ABC):
    @property
    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    def predict(self, features: RiskFeatures) -> RiskPrediction: ...

    @abstractmethod
    def card(self) -> ModelCard: ...


# --------------------------------------------------------------------------- #
# Seguridad
# --------------------------------------------------------------------------- #


class PasswordHasher(ABC):
    @abstractmethod
    def hash(self, password: str) -> str: ...

    @abstractmethod
    def verify(self, password_hash: str, password: str) -> bool: ...

    @abstractmethod
    def needs_rehash(self, password_hash: str) -> bool:
        """True si el hash se generó con parámetros más débiles que los actuales."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: str
    role: str
    issued_at: datetime | None = None


class TokenService(ABC):
    @abstractmethod
    def issue(self, claims: TokenClaims) -> tuple[str, int]:
        """Devuelve (token, segundos de vigencia)."""

    @abstractmethod
    def decode(self, token: str) -> TokenClaims:
        """Lanza ``AuthenticationError`` si el token es inválido o expiró."""
