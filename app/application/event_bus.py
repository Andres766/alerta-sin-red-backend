"""Bus de eventos en proceso (patrón Observer / Publish-Subscribe).

Desacopla la evaluación de riesgo del envío de alertas: el servicio de
evaluación no sabe que existen los SMS; solo publica ``RiskAssessed``.
Mañana se puede suscribir un notificador push o un webhook sin tocarlo
(principio abierto/cerrado).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import TypeVar

from app.domain.events import DomainEvent

E = TypeVar("E", bound=DomainEvent)
Handler = Callable[[E], object]

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Callable[[DomainEvent], object]]] = (
            defaultdict(list)
        )

    def subscribe(self, event_type: type[E], handler: Callable[[E], object]) -> None:
        self._handlers[event_type].append(handler)  # type: ignore[arg-type]

    def publish(self, event: DomainEvent) -> None:
        for handler in self._handlers[type(event)]:
            try:
                handler(event)
            except Exception:  # un suscriptor que falla no tumba a los demás
                logger.exception("Error en el manejador de %s", type(event).__name__)
