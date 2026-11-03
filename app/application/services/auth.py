"""Caso de uso: autenticación de operadores del sistema."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.services.audit import AuditTrail
from app.domain.entities import AuditAction, Role, User
from app.domain.exceptions import AuthenticationError
from app.domain.ports import PasswordHasher, TokenClaims, TokenService, UnitOfWork


@dataclass(frozen=True, slots=True)
class AccessToken:
    token: str
    expires_in: int
    role: str


class AuthService:
    def __init__(
        self,
        uow: UnitOfWork,
        hasher: PasswordHasher,
        tokens: TokenService,
        dummy_hash: str | None = None,
        audit: AuditTrail | None = None,
    ) -> None:
        self._audit = audit or AuditTrail(uow)
        self._uow = uow
        self._hasher = hasher
        self._tokens = tokens
        # Hash señuelo: se verifica aunque el usuario no exista, para que el
        # tiempo de respuesta no revele qué correos están registrados.
        self._dummy_hash = dummy_hash or hasher.hash("usuario-inexistente-señuelo")

    def login(self, email: str, password: str) -> AccessToken:
        user = self._uow.users.get_by_email(email.strip().lower())
        valid = self._hasher.verify(user.password_hash if user else self._dummy_hash, password)
        if user is None or not valid or not user.active:
            # Se registra (y confirma) antes de responder: los intentos fallidos repetidos
            # contra una cuenta son la señal de un ataque de fuerza bruta.
            self._audit.record(email.strip().lower(), AuditAction.LOGIN_FAILED)
            self._uow.commit()
            raise AuthenticationError("Credenciales inválidas")  # mensaje genérico a propósito
        self._audit.record(user.email, AuditAction.LOGIN_SUCCEEDED)
        self._uow.commit()
        claims = TokenClaims(subject=user.email, role=user.role.value)
        token, expires_in = self._tokens.issue(claims)
        return AccessToken(token=token, expires_in=expires_in, role=user.role.value)

    def ensure_user(self, email: str, password: str, role: Role) -> User:
        """Crea el usuario si no existe (usado por el script de siembra)."""
        email = email.strip().lower()
        existing = self._uow.users.get_by_email(email)
        if existing is not None:
            return existing
        user = User(email=email, password_hash=self._hasher.hash(password), role=role)
        self._uow.users.add(user)
        self._uow.commit()
        return user
