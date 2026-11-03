"""Caché en memoria para cualquier proveedor de clima (patrón Decorator).

Implementa el mismo puerto ``WeatherProvider`` que envuelve, así que el resto
del sistema no nota la diferencia. Evita repetir consultas a Open-Meteo cuando
se evalúa varias veces en poco tiempo (tarea programada + evaluación manual) y
reduce el riesgo de exceder el límite de uso de la API gratuita.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from app.domain.ports import WeatherProvider
from app.domain.value_objects import Coordinates, WeatherConditions


class CachedWeatherProvider(WeatherProvider):
    def __init__(
        self,
        inner: WeatherProvider,
        ttl_seconds: float,
        max_entries: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._entries: OrderedDict[tuple[float, float], tuple[float, WeatherConditions]] = (
            OrderedDict()
        )
        self._lock = threading.Lock()

    def get_conditions(self, point: Coordinates) -> WeatherConditions:
        # ~11 m de precisión: puntos prácticamente iguales comparten la entrada.
        key = (round(point.latitude, 4), round(point.longitude, 4))
        now = self._clock()
        with self._lock:
            cached = self._entries.get(key)
            if cached and now - cached[0] < self._ttl:
                self._entries.move_to_end(key)
                return cached[1]

        # Fuera del candado: la consulta HTTP no bloquea a otras zonas.
        # Si falla, la excepción sube y no se guarda nada (no se cachean errores).
        conditions = self._inner.get_conditions(point)
        with self._lock:
            self._entries[key] = (now, conditions)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)  # descarta la menos usada
        return conditions

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
