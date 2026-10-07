"""Consultas de lectura sobre zonas y riesgo (lado "query" de CQRS ligero)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.entities import RiskAssessment, Zone, utcnow
from app.domain.exceptions import ZoneNotFoundError
from app.domain.ports import UnitOfWork
from app.domain.value_objects import Coordinates


@dataclass(frozen=True, slots=True)
class ZoneRisk:
    zone: Zone
    assessment: RiskAssessment | None


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    """Todo lo que la PWA necesita guardar para funcionar sin conexión."""

    generated_at: datetime
    items: list[ZoneRisk]


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

    def nearby(self, point: Coordinates, radius_km: float, limit: int) -> list[tuple[Zone, float]]:
        radius = min(radius_km, self.MAX_RADIUS_KM)
        return self._uow.zones.find_nearby(point, radius, limit)

    def history(self, zone_id: UUID, limit: int) -> list[RiskAssessment]:
        if self._uow.zones.get(zone_id) is None:
            raise ZoneNotFoundError(str(zone_id))
        return self._uow.assessments.history(zone_id, limit)
