"""Consulta de indicadores para el panel del operador."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.entities import utcnow
from app.domain.ports import UnitOfWork
from app.domain.value_objects import RiskLevel

NOT_EVALUATED = "SIN_EVALUAR"


@dataclass(frozen=True, slots=True)
class DashboardStats:
    zones: int
    active_subscribers: int
    zones_by_level: dict[str, int]
    sms_sent_24h: int
    sms_failed_24h: int
    last_evaluation_at: datetime | None


class DashboardService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def stats(self) -> DashboardStats:
        zones = self._uow.zones.list_all()
        latest = self._uow.assessments.latest_by_zone()
        by_level = Counter(
            latest[z.id].level.value if z.id in latest else NOT_EVALUATED for z in zones
        )
        alerts = self._uow.alerts.count_since(utcnow() - timedelta(hours=24))
        return DashboardStats(
            zones=len(zones),
            active_subscribers=self._uow.subscribers.count_active(),
            zones_by_level={
                **{lvl.value: by_level.get(lvl.value, 0) for lvl in RiskLevel},
                NOT_EVALUATED: by_level.get(NOT_EVALUATED, 0),
            },
            sms_sent_24h=alerts.get("SENT", 0),
            sms_failed_24h=alerts.get("FAILED", 0),
            last_evaluation_at=max((a.assessed_at for a in latest.values()), default=None),
        )
