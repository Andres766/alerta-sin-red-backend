"""Dependencias de FastAPI: Unit of Work por petición, autenticación y rate limiting."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.container import Container
from app.core.security import SlidingWindowRateLimiter
from app.domain.entities import Role
from app.domain.ports import TokenClaims, UnitOfWork

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_uow(container: ContainerDep) -> Iterator[UnitOfWork]:
    with container.uow_factory() as uow:
        yield uow


UowDep = Annotated[UnitOfWork, Depends(get_uow)]


def current_claims(
    container: ContainerDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TokenClaims:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "No autenticado", {"WWW-Authenticate": "Bearer"}
        )
    return container.tokens.decode(credentials.credentials)  # AuthenticationError -> 401


def require_role(*roles: Role) -> Callable[[TokenClaims], TokenClaims]:
    """Control de acceso basado en roles (RBAC)."""
    allowed = {r.value for r in roles}

    def checker(claims: Annotated[TokenClaims, Depends(current_claims)]) -> TokenClaims:
        if claims.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permisos insuficientes")
        return claims

    return checker


def client_ip(request: Request) -> str:
    # Detrás de un proxy, uvicorn --proxy-headers ya reescribe request.client.
    return request.client.host if request.client else "desconocido"


def rate_limited(select: Callable[[Container], SlidingWindowRateLimiter]) -> Callable[..., None]:
    def dependency(request: Request, container: ContainerDep) -> None:
        limiter = select(container)
        if not limiter.allow(f"{request.url.path}:{client_ip(request)}"):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Demasiadas solicitudes, intente más tarde",
                {"Retry-After": "60"},
            )

    return dependency
