"""Consultas de lectura sobre zonas y riesgo (lado "query" de CQRS ligero)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID

from app.domain.entities import RiskAssessment, Zone, utcnow
from app.domain.exceptions import ZoneNotFoundError
from app.domain.ports import UnitOfWork
from app.domain.value_objects import COLOMBIA_TZ, Coordinates, RiskLevel


@dataclass(frozen=True, slots=True)
class ZoneRisk:
    zone: Zone
    assessment: RiskAssessment | None


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    """Todo lo que la PWA necesita guardar para funcionar sin conexión."""

    generated_at: datetime
    items: list[ZoneRisk]


@dataclass(frozen=True, slots=True)
class DayRisk:
    """El peor nivel de un día (hora de Colombia) y cuántas evaluaciones lo respaldan."""

    day: date
    level: RiskLevel
    probability: float
    evaluations: int


class ZoneQueryService:
    MAX_RADIUS_KM = 200.0

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def snapshot(self) -> RiskSnapshot:
        latest = self._uow.assessments.latest_by_zone()
        items = [ZoneRisk(zone, latest.get(zone.id)) for zone in self._uow.zones.list_all()]
        items.sort(key=lambda i: (-(i.assessment.level.severity if i.assessment else -1),
                                  i.zone.name))
        return RiskSnapshot(generated_at=utcnow(), items=items)

    def detail(self, zone_id: UUID) -> ZoneRisk:
        """Una zona con su última evaluación (para enlaces directos a una zona)."""
        zone = self._uow.zones.get(zone_id)
        if zone is None:
            raise ZoneNotFoundError(str(zone_id))
        latest = self._uow.assessments.history(zone_id, 1)
        return ZoneRisk(zone, latest[0] if latest else None)

    def nearby(self, point: Coordinates, radius_km: float, limit: int) -> list[tuple[Zone, float]]:
        radius = min(radius_km, self.MAX_RADIUS_KM)
        return self._uow.zones.find_nearby(point, radius, limit)

    def daily(self, zone_id: UUID, days: int) -> list[DayRisk]:
        """Un registro por día con datos, del más antiguo al más reciente."""
        if self._uow.zones.get(zone_id) is None:
            raise ZoneNotFoundError(str(zone_id))
        today = utcnow().astimezone(COLOMBIA_TZ).date()
        start = datetime.combine(today - timedelta(days=days - 1), datetime.min.time(), COLOMBIA_TZ)
        by_day: dict[date, list[RiskAssessment]] = {}
        for a in self._uow.assessments.zone_since(zone_id, start):
            by_day.setdefault(a.assessed_at.astimezone(COLOMBIA_TZ).date(), []).append(a)
        result = []
        for day in sorted(by_day):
            worst = max(by_day[day], key=lambda a: (a.level.severity, a.probability))
            result.append(DayRisk(day, worst.level, worst.probability, len(by_day[day])))
        return result

    def history(self, zone_id: UUID, limit: int) -> list[RiskAssessment]:
        if self._uow.zones.get(zone_id) is None:
            raise ZoneNotFoundError(str(zone_id))
        return self._uow.assessments.history(zone_id, limit)
