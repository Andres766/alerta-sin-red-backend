"""Caso de uso: recibir el clima de las zonas desde un trabajo externo y evaluar.

La API gratuita de Open-Meteo limita por IP y la IP de salida del servidor
(compartida con muchas aplicaciones) suele estar bloqueada con 429. Un trabajo
externo con otra IP consulta el clima y lo entrega aquí; el servidor guarda la
observación por zona y ejecuta el modelo con ella.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.services.audit import AuditTrail
from app.application.services.risk_assessment import EvaluationReport, RiskAssessmentService
from app.domain.entities import AuditAction, RiskAssessment, utcnow
from app.domain.ports import RiskModel, UnitOfWork
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


@dataclass(slots=True)
class BackfillReport:
    created: int = 0
    skipped: int = 0
    unknown_zones: list[UUID] = field(default_factory=list)


class HistoryBackfillService:
    """Completa el historial de riesgo con clima real de días pasados.

    Cada observación se evalúa con el mismo modelo y queda fechada en su
    instante (no "ahora"). No publica eventos: un día pasado nunca dispara SMS.
    Es idempotente: si ya existe una evaluación de la zona en ese instante, se omite.
    """

    MAX_AGE = timedelta(days=92)  # lo que conserva la API de pronóstico de Open-Meteo
    MIN_AGE = timedelta(hours=1)  # lo reciente es trabajo de la evaluación normal

    def __init__(self, uow: UnitOfWork, model: RiskModel, audit: AuditTrail) -> None:
        self._uow = uow
        self._model = model
        self._audit = audit

    def backfill(self, observations: list[ZoneObservation]) -> BackfillReport:
        report = BackfillReport()
        now = utcnow()
        by_zone: dict[UUID, list[ZoneObservation]] = {}
        for observation in observations:
            by_zone.setdefault(observation.zone_id, []).append(observation)

        for zone_id, items in by_zone.items():
            zone = self._uow.zones.get(zone_id)
            if zone is None:
                report.unknown_zones.append(zone_id)
                continue
            moments = [_utc(o.conditions.observed_at) for o in items]
            existing = {
                _utc(a.assessed_at) for a in self._uow.assessments.zone_since(zone_id, min(moments))
            }
            for observation, moment in zip(items, moments, strict=True):
                if moment in existing or not (now - self.MAX_AGE <= moment <= now - self.MIN_AGE):
                    report.skipped += 1
                    continue
                features = zone.build_features(observation.conditions)
                assessment = RiskAssessment.from_prediction(
                    zone, features, self._model.predict(features), self._model.version,
                    observation.conditions.source,
                )
                assessment.assessed_at = moment
                self._uow.assessments.add(assessment)
                existing.add(moment)
                report.created += 1

        if report.created:
            self._audit.record(
                EXTERNAL_FEED_ACTOR, AuditAction.EVALUATION_RUN,
                details=f"historial: {report.created} evaluaciones de días pasados",
            )
        self._uow.commit()
        return report


def _utc(moment: datetime) -> datetime:
    """Instante en UTC sin microsegundos, para comparar sin importar el origen."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).replace(microsecond=0)
