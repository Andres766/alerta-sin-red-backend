"""Caso de uso: recibir el clima de las zonas desde un trabajo externo y evaluar.

La API gratuita de Open-Meteo limita por IP y la IP de salida del servidor
(compartida con muchas aplicaciones) suele estar bloqueada con 429. Un trabajo
externo con otra IP consulta el clima y lo entrega aquí; el servidor guarda la
observación por zona y ejecuta el modelo con ella.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from app.application.services.audit import AuditTrail
from app.application.services.risk_assessment import EvaluationReport, RiskAssessmentService
from app.domain.entities import AuditAction
from app.domain.ports import UnitOfWork
from app.domain.value_objects import WeatherConditions

logger = logging.getLogger(__name__)

# Identidad con la que queda en la bitácora: no es una cuenta de operador.
EXTERNAL_FEED_ACTOR = "clima-externo"


@dataclass(frozen=True, slots=True)
class ZoneObservation:
    zone_id: UUID
    conditions: WeatherConditions


@dataclass(slots=True)
class IngestReport:
    stored: int = 0
    unknown_zones: list[UUID] = field(default_factory=list)
    evaluation: EvaluationReport = field(default_factory=EvaluationReport)


class WeatherIngestService:
    def __init__(
        self, uow: UnitOfWork, risk: RiskAssessmentService, audit: AuditTrail
    ) -> None:
        self._uow = uow
        self._risk = risk
        self._audit = audit

    def ingest(self, observations: list[ZoneObservation]) -> IngestReport:
        report = IngestReport()
        for observation in observations:
            zone = self._uow.zones.get(observation.zone_id)
            if zone is None:
                report.unknown_zones.append(observation.zone_id)
                continue
            self._uow.observations.save(zone.id, zone.location, observation.conditions)
            report.stored += 1
        # Se confirma antes de evaluar: si la evaluación falla, el clima ya quedó guardado
        # para la próxima ejecución programada.
        self._uow.commit()
        if report.stored == 0:
            return report

        report.evaluation = self._risk.evaluate_all()
        self._audit.record(
            EXTERNAL_FEED_ACTOR, AuditAction.EVALUATION_RUN,
            details=(
                f"{report.stored} observaciones recibidas, "
                f"{len(report.evaluation.assessments)} zonas, "
                f"{len(report.evaluation.failures)} fallos"
            ),
        )
        self._uow.commit()
        logger.info("Clima externo: %d observaciones, %d zonas evaluadas",
                    report.stored, len(report.evaluation.assessments))
        return report
