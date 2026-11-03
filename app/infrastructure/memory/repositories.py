"""Implementación en memoria de los repositorios.

Sirve para las pruebas automáticas y para ejecutar una demo sin base de datos.
Que exista demuestra el valor del patrón Repository: los casos de uso
funcionan igual con PostGIS o con diccionarios de Python.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.domain.entities import (
    AlertNotification,
    AuditEntry,
    NotificationStatus,
    RiskAssessment,
    Subscriber,
    User,
    Zone,
)
from app.domain.ports import (
    AlertRepository,
    AuditRepository,
    RiskAssessmentRepository,
    SubscriberRepository,
    UnitOfWork,
    UserRepository,
    ZoneRepository,
)
from app.domain.value_objects import Coordinates, PhoneNumber


@dataclass
class InMemoryStore:
    zones: dict[UUID, Zone] = field(default_factory=dict)
    assessments: list[RiskAssessment] = field(default_factory=list)
    subscribers: dict[UUID, Subscriber] = field(default_factory=dict)
    alerts: list[AlertNotification] = field(default_factory=list)
    users: dict[str, User] = field(default_factory=dict)
    audit: list[AuditEntry] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)


class InMemoryZoneRepository(ZoneRepository):
    def __init__(self, store: InMemoryStore) -> None:
        self._s = store

    def get(self, zone_id: UUID) -> Zone | None:
        return self._s.zones.get(zone_id)

    def list_all(self) -> list[Zone]:
        return sorted(self._s.zones.values(), key=lambda z: z.name)

    def find_nearby(
        self, point: Coordinates, radius_km: float, limit: int
    ) -> list[tuple[Zone, float]]:
        with_distance = ((z, point.distance_km(z.location)) for z in self._s.zones.values())
        inside = sorted((p for p in with_distance if p[1] <= radius_km), key=lambda p: p[1])
        return inside[:limit]

    def add(self, zone: Zone) -> None:
        with self._s.lock:
            self._s.zones[zone.id] = zone


class InMemoryRiskAssessmentRepository(RiskAssessmentRepository):
    def __init__(self, store: InMemoryStore) -> None:
        self._s = store

    def add(self, assessment: RiskAssessment) -> None:
        with self._s.lock:
            self._s.assessments.append(assessment)

    def latest_by_zone(self) -> dict[UUID, RiskAssessment]:
        latest: dict[UUID, RiskAssessment] = {}
        for a in self._s.assessments:
            current = latest.get(a.zone_id)
            if current is None or a.assessed_at >= current.assessed_at:
                latest[a.zone_id] = a
        return latest

    def history(self, zone_id: UUID, limit: int) -> list[RiskAssessment]:
        rows = [a for a in self._s.assessments if a.zone_id == zone_id]
        return sorted(rows, key=lambda a: a.assessed_at, reverse=True)[:limit]

    def since(self, moment: datetime, limit: int) -> list[RiskAssessment]:
        rows = [a for a in self._s.assessments if a.assessed_at >= moment]
        return sorted(rows, key=lambda a: a.assessed_at)[:limit]


class InMemorySubscriberRepository(SubscriberRepository):
    def __init__(self, store: InMemoryStore) -> None:
        self._s = store

    def add(self, subscriber: Subscriber) -> None:
        with self._s.lock:
            self._s.subscribers[subscriber.id] = subscriber

    def get(self, subscriber_id: UUID) -> Subscriber | None:
        return self._s.subscribers.get(subscriber_id)

    def find(self, zone_id: UUID, phone: PhoneNumber) -> Subscriber | None:
        return next(
            (s for s in self._s.subscribers.values() if s.zone_id == zone_id and s.phone == phone),
            None,
        )

    def active_for_zone(self, zone_id: UUID) -> list[Subscriber]:
        return [s for s in self._s.subscribers.values() if s.zone_id == zone_id and s.active]

    def count_active(self) -> int:
        return sum(s.active for s in self._s.subscribers.values())


class InMemoryAlertRepository(AlertRepository):
    def __init__(self, store: InMemoryStore) -> None:
        self._s = store

    def add(self, notification: AlertNotification) -> None:
        with self._s.lock:
            self._s.alerts.append(notification)

    def last_sent_for_zone(self, zone_id: UUID) -> AlertNotification | None:
        sent = [
            a for a in self._s.alerts
            if a.zone_id == zone_id and a.status is NotificationStatus.SENT
        ]
        return max(sent, key=lambda a: a.created_at, default=None)

    def recent(self, limit: int) -> list[AlertNotification]:
        return sorted(self._s.alerts, key=lambda a: a.created_at, reverse=True)[:limit]

    def count_since(self, since: datetime) -> dict[str, int]:
        counts = {s.value: 0 for s in NotificationStatus}
        for a in self._s.alerts:
            if a.created_at >= since:
                counts[a.status.value] += 1
        return counts


class InMemoryUserRepository(UserRepository):
    def __init__(self, store: InMemoryStore) -> None:
        self._s = store

    def get(self, user_id: UUID) -> User | None:
        return next((u for u in self._s.users.values() if u.id == user_id), None)

    def get_by_email(self, email: str) -> User | None:
        return self._s.users.get(email)

    def list_all(self) -> list[User]:
        return sorted(self._s.users.values(), key=lambda u: u.created_at)

    def add(self, user: User) -> None:
        with self._s.lock:
            self._s.users[user.email] = user


class InMemoryAuditRepository(AuditRepository):
    def __init__(self, store: InMemoryStore) -> None:
        self._s = store

    def add(self, entry: AuditEntry) -> None:
        with self._s.lock:
            self._s.audit.append(entry)

    def recent(self, limit: int) -> list[AuditEntry]:
        return sorted(self._s.audit, key=lambda e: e.created_at, reverse=True)[:limit]


class InMemoryUnitOfWork(UnitOfWork):
    """Sin transacciones reales: commit/rollback solo registran la llamada."""

    def __init__(self, store: InMemoryStore) -> None:
        self.zones = InMemoryZoneRepository(store)
        self.assessments = InMemoryRiskAssessmentRepository(store)
        self.subscribers = InMemorySubscriberRepository(store)
        self.alerts = InMemoryAlertRepository(store)
        self.users = InMemoryUserRepository(store)
        self.audit = InMemoryAuditRepository(store)
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass
