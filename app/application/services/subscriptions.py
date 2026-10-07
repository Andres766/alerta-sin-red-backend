"""Caso de uso: suscribir un celular a las alertas SMS de una zona."""

from __future__ import annotations

from uuid import UUID

from app.domain.entities import Subscriber
from app.domain.exceptions import ZoneNotFoundError
from app.domain.ports import UnitOfWork
from app.domain.value_objects import PhoneNumber


class SubscriptionService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def subscribe(self, raw_phone: str, zone_id: UUID, consent: bool) -> Subscriber:
        """Idempotente: repetir la misma suscripción devuelve la existente.

        Es imprescindible para la arquitectura offline-first: la PWA puede
        reenviar la misma petición desde su bandeja de salida (outbox) si no
        alcanzó a recibir la respuesta, y no debe crear duplicados. Además, al
        responder igual en ambos casos no se revela si un número ya existía.
        """
        phone = PhoneNumber.parse(raw_phone)
        if self._uow.zones.get(zone_id) is None:
            raise ZoneNotFoundError(str(zone_id))

        # Se construye primero para que la regla de consentimiento aplique siempre.
        subscriber = Subscriber.subscribe(zone_id, phone, consent)
        existing = self._uow.subscribers.find(zone_id, phone)
        if existing is not None:
            if not existing.active:
                existing.active = True
                self._uow.subscribers.add(existing)
                self._uow.commit()
            return existing

        self._uow.subscribers.add(subscriber)
        self._uow.commit()
        return subscriber
