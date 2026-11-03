"""Bitácora de acciones sensibles (OWASP A09: registro y monitoreo de seguridad)."""

from __future__ import annotations

from app.domain.entities import AuditAction, AuditEntry
from app.domain.ports import UnitOfWork


class AuditTrail:
    """Registra en la misma transacción del caso de uso que la origina.

    Nunca guarda contraseñas, tokens ni teléfonos: solo quién, qué y sobre qué.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def record(
        self, actor: str, action: AuditAction, target: str | None = None,
        details: str | None = None,
    ) -> None:
        self._uow.audit.add(AuditEntry(actor=actor, action=action, target=target, details=details))

    def recent(self, limit: int) -> list[AuditEntry]:
        return self._uow.audit.recent(limit)
