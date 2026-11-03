"""Caso de uso: registrar y actualizar zonas monitoreadas (solo administradores)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.application.services.audit import AuditTrail
from app.domain.entities import AuditAction, User, Zone
from app.domain.exceptions import ConflictError, ValidationError, ZoneNotFoundError
from app.domain.ports import UnitOfWork
from app.domain.value_objects import Coordinates, HazardType

# Rectángulo que contiene el territorio colombiano, incluido San Andrés.
_COLOMBIA_LAT = (-4.3, 13.6)
_COLOMBIA_LON = (-82.0, -66.8)


@dataclass(frozen=True, slots=True)
class NewZone:
    name: str
    municipality: str
    department: str
    hazard_type: HazardType
    susceptibility: int
    slope_deg: float
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class ZoneChanges:
    hazard_type: HazardType | None = None
    susceptibility: int | None = None
    slope_deg: float | None = None


class ZoneAdminService:
    def __init__(self, uow: UnitOfWork, audit: AuditTrail) -> None:
        self._uow = uow
        self._audit = audit

    def create(self, data: NewZone, acting_user: User) -> Zone:
        name = data.name.strip()
        if any(z.name.lower() == name.lower() for z in self._uow.zones.list_all()):
            raise ConflictError("Ya existe una zona con ese nombre")
        location = Coordinates(data.latitude, data.longitude)
        if not (
            _COLOMBIA_LAT[0] <= location.latitude <= _COLOMBIA_LAT[1]
            and _COLOMBIA_LON[0] <= location.longitude <= _COLOMBIA_LON[1]
        ):
            raise ValidationError("Las coordenadas deben estar dentro de Colombia")
        zone = Zone(
            name=name,
            municipality=data.municipality.strip(),
            department=data.department.strip(),
            hazard_type=data.hazard_type,
            susceptibility=data.susceptibility,
            slope_deg=data.slope_deg,
            location=location,
        )
        self._uow.zones.add(zone)
        self._audit.record(acting_user.email, AuditAction.ZONE_CREATED, zone.name)
        self._uow.commit()
        return zone

    def update(self, zone_id: UUID, changes: ZoneChanges, acting_user: User) -> Zone:
        """Actualiza la capa estática (p. ej. al cargar la zonificación oficial del SGC)."""
        zone = self._uow.zones.get(zone_id)
        if zone is None:
            raise ZoneNotFoundError(str(zone_id))
        summary = []
        if changes.hazard_type is not None:
            summary.append(f"amenaza={changes.hazard_type.value}")
        if changes.susceptibility is not None:
            summary.append(f"susceptibilidad={changes.susceptibility}")
        if changes.slope_deg is not None:
            summary.append(f"pendiente={changes.slope_deg}")
        if not summary:
            raise ValidationError("No se indicó ningún cambio")
        updated = Zone(
            id=zone.id,
            name=zone.name,
            municipality=zone.municipality,
            department=zone.department,
            hazard_type=changes.hazard_type or zone.hazard_type,
            susceptibility=(
                zone.susceptibility if changes.susceptibility is None else changes.susceptibility
            ),
            slope_deg=zone.slope_deg if changes.slope_deg is None else changes.slope_deg,
            location=zone.location,
        )  # el constructor vuelve a validar los rangos
        self._uow.zones.add(updated)
        self._audit.record(
            acting_user.email, AuditAction.ZONE_UPDATED, zone.name, ", ".join(summary)
        )
        self._uow.commit()
        return updated
