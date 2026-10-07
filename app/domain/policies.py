"""Reglas de negocio que no pertenecen a una sola entidad."""

from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta

from app.domain.entities import AlertNotification, RiskAssessment, Zone
from app.domain.value_objects import HazardType, RiskLevel


class AlertPolicy:
    """Decide si una evaluación debe disparar SMS.

    Evita la "fatiga de alertas": no se repite el SMS de una zona dentro del
    periodo de enfriamiento, salvo que el riesgo haya escalado de nivel.
    """

    def __init__(self, cooldown: timedelta) -> None:
        self._cooldown = cooldown

    def should_alert(
        self, assessment: RiskAssessment, last_sent: AlertNotification | None, now: datetime
    ) -> bool:
        if not assessment.requires_alert:
            return False
        if last_sent is None:
            return True
        if assessment.level.severity > last_sent.level.severity:
            return True
        return now - last_sent.created_at >= self._cooldown


class AlertMessageBuilder:
    """Construye el texto del SMS.

    Se limita a 160 caracteres y sin tildes (alfabeto GSM-7) para que llegue en
    un único segmento en cualquier celular, incluso los más básicos.
    """

    MAX_LENGTH = 160

    _ACTIONS = {
        RiskLevel.ALTO: "Prepare su plan de evacuacion y este atento.",
        RiskLevel.MUY_ALTO: "Evacue a zona segura YA.",
    }
    _HAZARD = {
        HazardType.DESLIZAMIENTO: "deslizamiento",
        HazardType.CRECIENTE: "creciente del rio",
        HazardType.MIXTO: "deslizamiento/creciente",
    }

    def build(self, zone: Zone, assessment: RiskAssessment) -> str:
        level = assessment.level
        header = f"ALERTA {level.alert_color.upper()} AlertaSinRed:"
        action = self._ACTIONS.get(level, "Mantengase informado.")
        body = f" riesgo {level.label} de {self._HAZARD[zone.hazard_type]} en {zone.name}. {action}"
        footer = " Linea 123"
        text = self._to_gsm7(header + body + footer)
        if len(text) > self.MAX_LENGTH:
            overflow = len(text) - self.MAX_LENGTH
            short_name = self._to_gsm7(zone.name)[: max(8, len(zone.name) - overflow - 1)]
            text = self._to_gsm7(
                header + body.replace(zone.name, short_name) + footer
            )[: self.MAX_LENGTH]
        return text

    @staticmethod
    def _to_gsm7(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text)
        return "".join(c for c in normalized if c.isascii() and (c.isprintable() or c == " "))
