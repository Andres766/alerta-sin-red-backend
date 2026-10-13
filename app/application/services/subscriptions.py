"""Casos de uso: suscribir un celular a las alertas SMS de una zona y darse de baja."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.entities import Subscriber
from app.domain.exceptions import NotFoundError, ZoneNotFoundError
from app.domain.ports import UnitOfWork
from app.domain.value_objects import PhoneNumber


@dataclass(frozen=True, slots=True)
class SubscriptionResult:
    subscriber: Subscriber
    # Código para darse de baja. Solo se entrega cuando se crea (o reactiva) la
    # suscripción: después únicamente existe su huella en la base de datos.
    cancel_token: str | None


class SubscriptionService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def subscribe(self, raw_phone: str, zone_id: UUID, consent: bool) -> SubscriptionResult:
        """Idempotente: repetir la misma suscripción devuelve la existente.

        Es imprescindible para la arquitectura offline-first: la PWA puede
        reenviar la misma petición desde su bandeja de salida (outbox) si no
        alcanzó a recibir la respuesta, y no debe crear duplicados.

        Una suscripción ya activa NO recibe un código de baja nuevo: si se
        emitiera, cualquiera que conozca un número podría obtener un código y
        dar de baja a esa persona.
        """
        phone = PhoneNumber.parse(raw_phone)
        if self._uow.zones.get(zone_id) is None:
            raise ZoneNotFoundError(str(zone_id))

        # Se construye primero para que la regla de consentimiento aplique siempre.
        subscriber = Subscriber.subscribe(zone_id, phone, consent)
        existing = self._uow.subscribers.find(zone_id, phone)
        if existing is not None and existing.active:
            return SubscriptionResult(existing, cancel_token=None)

        target = existing or subscriber
        target.active = True
        token = target.issue_cancel_token()
        self._uow.subscribers.add(target)
        self._uow.commit()
        return SubscriptionResult(target, cancel_token=token)

    def cancel(self, subscription_id: UUID, cancel_token: str) -> None:
        """Da de baja la suscripción si el código coincide.

        Ante un código incorrecto responde "no encontrado", igual que si la
        suscripción no existiera, para no revelar qué identificadores son válidos.
        """
        subscriber = self._uow.subscribers.get(subscription_id)
        if subscriber is None or not subscriber.can_be_cancelled_with(cancel_token):
            raise NotFoundError("Suscripción no encontrada")
        subscriber.cancel()
        self._uow.subscribers.add(subscriber)
        self._uow.commit()
