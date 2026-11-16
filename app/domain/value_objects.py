"""Objetos de valor: inmutables, se validan al construirse y se comparan por valor."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from app.domain.exceptions import (
    InvalidCoordinatesError,
    InvalidPhoneNumberError,
    ValidationError,
)

# Nariño y Putumayo: hora de Colombia (UTC-5, sin horario de verano).
COLOMBIA_TZ = timezone(timedelta(hours=-5), "COT")


class RiskLevel(StrEnum):
    """Niveles de riesgo alineados con los colores de alerta del IDEAM/UNGRD."""

    BAJO = "BAJO"
    MODERADO = "MODERADO"
    ALTO = "ALTO"
    MUY_ALTO = "MUY_ALTO"

    @property
    def severity(self) -> int:
        return _SEVERITY[self]

    @property
    def alert_color(self) -> str:
        return _ALERT_COLOR[self]

    @property
    def requires_sms(self) -> bool:
        """A partir de ALTO (alerta naranja) se notifica por SMS."""
        return self.severity >= _SEVERITY[RiskLevel.ALTO]

    @property
    def label(self) -> str:
        return self.value.replace("_", " ")


_SEVERITY = {RiskLevel.BAJO: 0, RiskLevel.MODERADO: 1, RiskLevel.ALTO: 2, RiskLevel.MUY_ALTO: 3}
_ALERT_COLOR = {
    RiskLevel.BAJO: "verde",
    RiskLevel.MODERADO: "amarilla",
    RiskLevel.ALTO: "naranja",
    RiskLevel.MUY_ALTO: "roja",
}


class HazardType(StrEnum):
    DESLIZAMIENTO = "DESLIZAMIENTO"
    CRECIENTE = "CRECIENTE"
    MIXTO = "MIXTO"


_EARTH_RADIUS_KM = 6371.0088
_E164_CO_MOBILE = re.compile(r"^\+573\d{9}$")


@dataclass(frozen=True, slots=True)
class Coordinates:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if math.isnan(self.latitude) or math.isnan(self.longitude):
            raise InvalidCoordinatesError("Coordenadas inválidas")
        if not (-90.0 <= self.latitude <= 90.0) or not (-180.0 <= self.longitude <= 180.0):
            raise InvalidCoordinatesError("Coordenadas fuera de rango")

    def distance_km(self, other: Coordinates) -> float:
        """Distancia ortodrómica (fórmula de Haversine)."""
        lat1, lon1, lat2, lon2 = map(
            math.radians, (self.latitude, self.longitude, other.latitude, other.longitude)
        )
        a = (
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        )
        return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass(frozen=True, slots=True)
class PhoneNumber:
    """Celular colombiano normalizado a formato E.164 (+573XXXXXXXXX)."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _E164_CO_MOBILE.fullmatch(self.value):
            raise InvalidPhoneNumberError(
                "Debe ser un celular colombiano válido (+57 3XX XXX XXXX)"
            )

    @classmethod
    def parse(cls, raw: str) -> PhoneNumber:
        if not isinstance(raw, str) or len(raw) > 32:
            raise InvalidPhoneNumberError("Número de teléfono inválido")
        digits = re.sub(r"[\s\-().]", "", raw.strip())
        if digits.startswith("+"):
            normalized = digits
        elif digits.startswith("57") and len(digits) == 12:
            normalized = f"+{digits}"
        elif len(digits) == 10:
            normalized = f"+57{digits}"
        else:
            raise InvalidPhoneNumberError("Número de teléfono inválido")
        return cls(normalized)

    def masked(self) -> str:
        """Nunca se expone el número completo en respuestas ni en logs."""
        return f"+57 {self.value[3:6]} *** **{self.value[-2:]}"

    def __str__(self) -> str:  # evita imprimirlo completo por accidente
        return self.masked()

    def __repr__(self) -> str:
        return f"PhoneNumber({self.masked()!r})"


@dataclass(frozen=True, slots=True)
class WeatherConditions:
    """Condiciones hidrometeorológicas observadas y pronosticadas para un punto."""

    rain_24h_mm: float
    rain_72h_mm: float
    rain_7d_mm: float
    rain_forecast_24h_mm: float
    soil_moisture: float  # m³/m³ (0 a 1)
    river_discharge_ratio: float  # caudal pronosticado / caudal medio de 30 días
    observed_at: datetime
    source: str


# El orden de este vector es un contrato entre el entrenamiento y la inferencia.
FEATURE_ORDER: tuple[str, ...] = (
    "rain_24h_mm",
    "rain_72h_mm",
    "rain_7d_mm",
    "rain_forecast_24h_mm",
    "soil_moisture",
    "river_discharge_ratio",
    "slope_deg",
    "susceptibility",
)


@dataclass(frozen=True, slots=True)
class RiskFeatures:
    """Vector de entrada del modelo de IA."""

    rain_24h_mm: float
    rain_72h_mm: float
    rain_7d_mm: float
    rain_forecast_24h_mm: float
    soil_moisture: float
    river_discharge_ratio: float
    slope_deg: float
    susceptibility: int

    def __post_init__(self) -> None:
        for name in FEATURE_ORDER:
            value = getattr(self, name)
            if value is None or math.isnan(float(value)) or value < 0:
                raise ValidationError(f"Variable inválida: {name}")
        if self.soil_moisture > 1:
            raise ValidationError("La humedad del suelo debe estar entre 0 y 1")
        if not 1 <= self.susceptibility <= 5:
            raise ValidationError("La susceptibilidad debe estar entre 1 y 5")

    def as_vector(self) -> list[float]:
        return [float(getattr(self, name)) for name in FEATURE_ORDER]

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    def key_factors(self) -> list[str]:
        """Explicación legible de por qué el riesgo es el que es (IA explicable básica)."""
        factors: list[str] = []
        if self.rain_72h_mm >= 60:
            factors.append(f"Lluvia acumulada muy alta en 72 h ({self.rain_72h_mm:.0f} mm)")
        elif self.rain_72h_mm >= 30:
            factors.append(f"Lluvia acumulada alta en 72 h ({self.rain_72h_mm:.0f} mm)")
        if self.rain_forecast_24h_mm >= 25:
            factors.append(
                f"Se pronostican {self.rain_forecast_24h_mm:.0f} mm en las próximas 24 h"
            )
        if self.soil_moisture >= 0.40:
            factors.append("Suelo saturado de agua")
        if self.river_discharge_ratio >= 1.5:
            factors.append(
                f"Caudal del río {self.river_discharge_ratio:.1f} veces por encima de lo habitual"
            )
        if self.susceptibility >= 4:
            factors.append("Zona de susceptibilidad alta a movimientos en masa")
        if self.slope_deg >= 25:
            factors.append(f"Pendiente pronunciada del terreno ({self.slope_deg:.0f}°)")
        return factors


@dataclass(frozen=True, slots=True)
class RiskPrediction:
    level: RiskLevel
    probability: float
    probabilities: dict[str, float]
