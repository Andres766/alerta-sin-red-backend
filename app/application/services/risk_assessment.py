"""Caso de uso: evaluar el riesgo climático de las zonas con el modelo de IA."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from app.application.event_bus import EventBus
from app.domain.entities import RiskAssessment, Zone
from app.domain.events import RiskAssessed
from app.domain.exceptions import ConflictError, ExternalServiceError, ZoneNotFoundError
from app.domain.ports import JobLock, RiskModel, UnitOfWork, WeatherProvider

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EvaluationReport:
    assessments: list[RiskAssessment] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)  # nombre de zona -> motivo


class RiskAssessmentService:
    def __init__(
        self,
        uow: UnitOfWork,
        weather: WeatherProvider,
        model: RiskModel,
        events: EventBus,
        lock: JobLock | None = None,
    ) -> None:
        self._uow = uow
        self._weather = weather
        self._model = model
        self._events = events
        self._lock = lock

    def evaluate_zone(self, zone_id: UUID) -> RiskAssessment:
        zone = self._uow.zones.get(zone_id)
        if zone is None:
            raise ZoneNotFoundError(str(zone_id))
        return self._evaluate(zone)

    def evaluate_all(self) -> EvaluationReport:
        """Evalúa todas las zonas; si ya hay una evaluación en curso, no la duplica.

        Correr dos a la vez (tarea programada + botón del operador) duplicaría las
        consultas a Open-Meteo y podría enviar SMS repetidos.
        """
        if self._lock is None:
            return self._evaluate_all()
        with self._lock.hold() as acquired:
            if not acquired:
                raise ConflictError("Ya hay una evaluación en curso; intente en un momento")
            return self._evaluate_all()

    def _evaluate_all(self) -> EvaluationReport:
        report = EvaluationReport()
        for zone in self._uow.zones.list_all():
            try:
                report.assessments.append(self._evaluate(zone))
            except ExternalServiceError as exc:
                # Una zona sin datos no impide evaluar las demás.
                logger.warning("No se pudo evaluar %s: %s", zone.name, exc)
                # Código y causa: así el operador ve desde el panel si fue un
                # tiempo de espera, un 429 o un fallo de conexión, sin abrir los logs.
                report.failures[zone.name] = f"{exc.code}: {exc}"
        return report

    def _evaluate(self, zone: Zone) -> RiskAssessment:
        weather = self._weather.get_conditions(zone.location)
        features = zone.build_features(weather)
        prediction = self._model.predict(features)
        assessment = RiskAssessment.from_prediction(
            zone, features, prediction, self._model.version, weather.source
        )
        self._uow.assessments.add(assessment)
        self._uow.commit()
        logger.info(
            "Zona %s evaluada: %s (p=%.2f)",
            zone.name, assessment.level.value, assessment.probability,
        )
        # Se publica DESPUÉS del commit: los suscriptores ven datos ya persistidos.
        self._events.publish(RiskAssessed(zone=zone, assessment=assessment))
        return assessment
