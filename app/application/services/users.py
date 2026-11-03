"""Caso de uso: administración de cuentas de operadores."""

from __future__ import annotations

from uuid import UUID

from app.application.services.audit import AuditTrail
from app.domain.entities import AuditAction, Role, User
from app.domain.exceptions import ConflictError, NotFoundError, UserAlreadyExistsError
from app.domain.ports import PasswordHasher, UnitOfWork


class UserManagementService:
    def __init__(self, uow: UnitOfWork, hasher: PasswordHasher, audit: AuditTrail) -> None:
        self._uow = uow
        self._hasher = hasher
        self._audit = audit

    def list_users(self) -> list[User]:
        return self._uow.users.list_all()

    def create(self, email: str, password: str, role: Role, acting_user: User) -> User:
        email = email.strip().lower()
        if self._uow.users.get_by_email(email) is not None:
            raise UserAlreadyExistsError("Ya existe una cuenta con ese correo")
        user = User(email=email, password_hash=self._hasher.hash(password), role=role)
        self._uow.users.add(user)
        self._audit.record(acting_user.email, AuditAction.USER_CREATED, email, f"rol {role.value}")
        self._uow.commit()
        return user

    def set_active(self, user_id: UUID, active: bool, acting_user: User) -> User:
        user = self._uow.users.get(user_id)
        if user is None:
            raise NotFoundError(str(user_id))
        if not active:
            if user.id == acting_user.id:
                raise ConflictError("No puede desactivar su propia cuenta")
            if user.is_admin and self._active_admins() <= 1:
                raise ConflictError("Debe quedar al menos un administrador activo")
            user.deactivate()
        else:
            user.activate()
        self._uow.users.add(user)
        action = AuditAction.USER_ACTIVATED if active else AuditAction.USER_DEACTIVATED
        self._audit.record(acting_user.email, action, user.email)
        self._uow.commit()
        return user

    def _active_admins(self) -> int:
        return sum(u.is_admin for u in self._uow.users.list_all())
