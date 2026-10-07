"""Endpoints de operación, protegidos con JWT + RBAC."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ContainerDep, UowDep, require_role
from app.api.schemas import AlertOut, AssessmentOut, EvaluationOut
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


@router.get("/stats")
def stats(uow: UowDep) -> dict[str, int]:
    return {"active_subscribers": uow.subscribers.count_active(),
            "zones": len(uow.zones.list_all())}
