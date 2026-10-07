"""Adaptadores de seguridad: hash de contraseñas, JWT, cifrado de datos personales
y limitación de tasa de peticiones."""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.domain.exceptions import AuthenticationError
from app.domain.ports import PasswordHasher, TokenClaims, TokenService
from app.domain.value_objects import PhoneNumber


class Argon2PasswordHasher(PasswordHasher):
    """Argon2id: ganador de la Password Hashing Competition, recomendado por OWASP."""

    def __init__(self) -> None:
        self._argon2 = _Argon2()

    def hash(self, password: str) -> str:
        return self._argon2.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._argon2.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False


class JwtTokenService(TokenService):
    _ISSUER = "alerta-sin-red"

    def __init__(self, secret: str, algorithm: str, expire_minutes: int) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._expire = timedelta(minutes=expire_minutes)

    def issue(self, claims: TokenClaims) -> tuple[str, int]:
        now = datetime.now(UTC)
        payload = {
            "sub": claims.subject,
            "role": claims.role,
            "iat": now,
            "nbf": now,
            "exp": now + self._expire,
            "iss": self._ISSUER,
        }
        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        return token, int(self._expire.total_seconds())

    def decode(self, token: str) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],  # lista fija: evita el ataque "alg=none"
                issuer=self._ISSUER,
                options={"require": ["exp", "iat", "sub", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Token inválido o expirado") from exc
        return TokenClaims(subject=payload["sub"], role=payload.get("role", ""))


class PhoneCipher:
    """Protege los celulares en reposo (dato personal, Ley 1581 de 2012).

    * ``encrypt``/``decrypt``: cifrado autenticado Fernet, para poder enviar el SMS.
    * ``blind_index``: HMAC-SHA256 determinista, para buscar duplicados sin
      descifrar la tabla ni guardar el número en claro.
    """

    def __init__(self, encryption_key: str, index_key: str) -> None:
        self._fernet = Fernet(encryption_key.encode())
        self._index_key = index_key.encode()

    def encrypt(self, phone: PhoneNumber) -> str:
        return self._fernet.encrypt(phone.value.encode()).decode()

    def decrypt(self, token: str) -> PhoneNumber:
        try:
            return PhoneNumber(self._fernet.decrypt(token.encode()).decode())
        except InvalidToken as exc:
            raise ValueError("No se pudo descifrar el teléfono (¿clave rotada?)") from exc

    def blind_index(self, phone: PhoneNumber) -> str:
        return hmac.new(self._index_key, phone.value.encode(), hashlib.sha256).hexdigest()


class SlidingWindowRateLimiter:
    """Limitador de ventana deslizante en memoria, seguro entre hilos.

    Suficiente para una sola instancia; con varias réplicas se reemplazaría por
    una implementación sobre Redis manteniendo la misma interfaz.
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self._window:
                hits.popleft()
            if len(hits) >= self._max:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:  # evita crecimiento ilimitado de memoria
                self._purge(now)
            return True

    def _purge(self, now: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or now - v[-1] > self._window]
        for key in stale:
            del self._hits[key]
