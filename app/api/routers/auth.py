from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import ContainerDep, UowDep, rate_limited
from app.api.schemas import LoginIn, TokenOut

router = APIRouter(prefix="/auth", tags=["autenticación"])


@router.post(
    "/login",
    response_model=TokenOut,
    # Frena ataques de fuerza bruta / relleno de credenciales.
    dependencies=[Depends(rate_limited(lambda c: c.login_limiter))],
)
def login(body: LoginIn, uow: UowDep, container: ContainerDep) -> TokenOut:
    token = container.auth_service(uow).login(body.email, body.password)
    return TokenOut(access_token=token.token, expires_in=token.expires_in, role=token.role)
