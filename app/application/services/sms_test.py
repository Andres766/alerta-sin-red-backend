"""Caso de uso: verificar la pasarela SMS con un mensaje de prueba."""

from __future__ import annotations

from app.application.services.audit import AuditTrail
from app.domain.entities import AuditAction, User
from app.domain.ports import SmsGateway, SmsResult, UnitOfWork
from app.domain.value_objects import PhoneNumber

TEST_MESSAGE = (
    "AlertaSinRed: mensaje de prueba. Si lo recibe, la pasarela SMS funciona. "
    "No requiere ninguna accion."
)


class SmsTestService:
    def __init__(self, uow: UnitOfWork, sms: SmsGateway, audit: AuditTrail) -> None:
        self._uow = uow
        self._sms = sms
        self._audit = audit

    def send(self, raw_phone: str, acting_user: User) -> SmsResult:
        phone = PhoneNumber.parse(raw_phone)
        result = self._sms.send(phone, TEST_MESSAGE)
        outcome = "enviado" if result.success else f"falló ({result.error})"
        # En la bitácora solo queda el número enmascarado.
        self._audit.record(acting_user.email, AuditAction.SMS_TEST_SENT, phone.masked(),
                           f"{self._sms.channel}: {outcome}")
        self._uow.commit()
        return result
