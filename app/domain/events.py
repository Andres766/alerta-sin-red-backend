"""Eventos de dominio: hechos que ya ocurrieron y a los que otros componentes reaccionan."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.entities import RiskAssessment, Zone


@dataclass(frozen=True, slots=True)
class DomainEvent:
    pass


@dataclass(frozen=True, slots=True)
class RiskAssessed(DomainEvent):
    zone: Zone
    assessment: RiskAssessment
