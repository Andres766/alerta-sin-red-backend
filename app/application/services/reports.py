"""Exportación del historial de evaluaciones para informes de gestión del riesgo."""

from __future__ import annotations

import csv
import io
from datetime import timedelta

from app.domain.entities import utcnow
from app.domain.ports import UnitOfWork
from app.domain.value_objects import FEATURE_ORDER

MAX_ROWS = 50_000

_HEADER = [
    "fecha_utc", "zona", "municipio", "departamento", "amenaza", "nivel", "alerta",
    "probabilidad", *FEATURE_ORDER, "modelo", "fuente_clima",
]

# Una celda que empieza con estos caracteres se interpreta como fórmula en Excel o
# LibreOffice (inyección de CSV, OWASP). Se antepone un apóstrofo para neutralizarla.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe(value: object) -> object:
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


class AssessmentReportService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def csv_since_days(self, days: int) -> str:
        zones = {z.id: z for z in self._uow.zones.list_all()}
        rows = self._uow.assessments.since(utcnow() - timedelta(days=days), MAX_ROWS)
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(_HEADER)
        for a in rows:
            zone = zones.get(a.zone_id)
            if zone is None:
                continue
            features = a.features.to_dict()
            writer.writerow([_safe(v) for v in [
                a.assessed_at.isoformat(timespec="seconds"), zone.name, zone.municipality,
                zone.department, zone.hazard_type.value, a.level.value, a.level.alert_color,
                f"{a.probability:.4f}", *(features[name] for name in FEATURE_ORDER),
                a.model_version, a.weather_source,
            ]])
        # BOM UTF-8: Excel en español abre bien las tildes y la ñ.
        return "\ufeff" + buffer.getvalue()
