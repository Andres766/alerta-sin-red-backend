"""Endpoints de operación, protegidos con JWT + RBAC."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import ContainerDep, CurrentUser, UowDep, require_role
from app.api.schemas import (
    AlertOut,
    AssessmentOut,
    EvaluationOut,
    StatsOut,
    UserCreateIn,
    UserOut,
)
from app.domain.entities import Role

router = APIRouter(
    prefix="/admin",
    tags=["administración"],
    dependencies=[Depends(require_role(Role.ADMIN, Role.OPERATOR))],
)


@router.post("/evaluations", response_model=EvaluationOut)
def run_evaluation(uow: UowDep, container: ContainerDep) -> EvaluationOut:
    """Ejecuta el modelo de IA sobre todas las zonas y dispara los SMS necesarios."""
    report = container.risk_service(uow).evaluate_all()
    return EvaluationOut(
        evaluated=len(report.assessments),
        failures=report.failures,
        assessments=[AssessmentOut.of(a) for a in report.assessments],
    )


@router.get("/alerts", response_model=list[AlertOut])
def recent_alerts(
    uow: UowDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[AlertOut]:
    return [AlertOut.of(n) for n in uow.alerts.recent(limit)]


@router.get("/stats", response_model=StatsOut)
def stats(uow: UowDep, container: ContainerDep) -> StatsOut:
    s = container.dashboard(uow).stats()
    return StatsOut(
        zones=s.zones, active_subscribers=s.active_subscribers, zones_by_level=s.zones_by_level,
        sms_sent_24h=s.sms_sent_24h, sms_failed_24h=s.sms_failed_24h,
        last_evaluation_at=s.last_evaluation_at,
    )


# ---- Gestión de operadores (solo ADMIN) ---------------------------------------

admin_only = [Depends(require_role(Role.ADMIN))]


@router.get("/users", response_model=list[UserOut], dependencies=admin_only)
def list_users(uow: UowDep, container: ContainerDep) -> list[UserOut]:
    return [UserOut.of(u) for u in container.user_management(uow).list_users()]


@router.post(
    "/users", response_model=UserOut, status_code=status.HTTP_201_CREATED,
    dependencies=admin_only,
)
def create_user(body: UserCreateIn, uow: UowDep, container: ContainerDep) -> UserOut:
    user = container.user_management(uow).create(body.email, body.password, body.role)
    return UserOut.of(user)


@router.post("/users/{user_id}/deactivate", response_model=UserOut, dependencies=admin_only)
def deactivate_user(
    user_id: UUID, me: CurrentUser, uow: UowDep, container: ContainerDep
) -> UserOut:
    return UserOut.of(container.user_management(uow).set_active(user_id, False, me))


@router.post("/users/{user_id}/activate", response_model=UserOut, dependencies=admin_only)
def activate_user(
    user_id: UUID, me: CurrentUser, uow: UowDep, container: ContainerDep
) -> UserOut:
    return UserOut.of(container.user_management(uow).set_active(user_id, True, me))
