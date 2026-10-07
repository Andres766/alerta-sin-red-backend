"""Proveedor de clima simulado para demostraciones y pruebas.

Permite mostrar en clase el flujo completo (riesgo alto -> SMS) aunque ese día
no esté lloviendo en Nariño.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.ports import WeatherProvider
from app.domain.value_objects import Coordinates, WeatherConditions

_SCENARIOS = {
    #            24h   72h    7d  pron24  suelo  caudal
    "seco":     (0.5,  2.0,  10.0,  1.0,  0.22,  0.8),
    "lluvioso": (18.0, 40.0, 85.0, 15.0,  0.36,  1.3),
    "tormenta": (55.0, 120.0, 190.0, 60.0, 0.47,  2.6),
}


class FakeWeatherProvider(WeatherProvider):
    SOURCE = "simulado"

    def __init__(self, scenario: str = "lluvioso") -> None:
        if scenario not in _SCENARIOS:
            raise ValueError(f"Escenario desconocido: {scenario}")
        self._scenario = scenario

    def get_conditions(self, point: Coordinates) -> WeatherConditions:
        r24, r72, r7d, f24, soil, ratio = _SCENARIOS[self._scenario]
        # Variación determinista por coordenada para que no todas las zonas sean idénticas.
        seed = hashlib.sha256(f"{point.latitude:.4f},{point.longitude:.4f}".encode()).digest()
        k = 0.8 + (seed[0] / 255) * 0.4  # factor entre 0.8 y 1.2
        return WeatherConditions(
            rain_24h_mm=round(r24 * k, 2),
            rain_72h_mm=round(r72 * k, 2),
            rain_7d_mm=round(r7d * k, 2),
            rain_forecast_24h_mm=round(f24 * k, 2),
            soil_moisture=round(min(soil * (0.95 + (seed[1] / 255) * 0.1), 0.6), 4),
            river_discharge_ratio=round(ratio * k, 3),
            observed_at=datetime.now(UTC),
            source=f"{self.SOURCE}:{self._scenario}",
        )
