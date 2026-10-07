"""Zonas piloto en Nariño y Putumayo.

La susceptibilidad y la pendiente son PROVISIONALES (estimadas a partir de la
cartografía pública del SGC a escala 1:100.000). En la siguiente fase se
reemplazan por la intersección espacial con la capa oficial de zonificación
del portal MIIG del Servicio Geológico Colombiano.
"""

from __future__ import annotations

from uuid import UUID, uuid5

from app.domain.entities import Zone
from app.domain.ports import UnitOfWork
from app.domain.value_objects import Coordinates, HazardType

_NAMESPACE = UUID("6f1c2f5e-3a4b-4c1d-9e8f-a1b2c3d4e5f6")

SEED_ZONES: list[dict] = [
    dict(name="Pasto - Laderas de Aranda", municipality="Pasto", department="Nariño",
         hazard_type=HazardType.DESLIZAMIENTO, susceptibility=4, slope_deg=27,
         lat=1.2265, lon=-77.2650),
    dict(name="Pasto - Ribera del río Pasto", municipality="Pasto", department="Nariño",
         hazard_type=HazardType.CRECIENTE, susceptibility=3, slope_deg=6,
         lat=1.2105, lon=-77.2775),
    dict(name="La Florida - Zona de influencia Galeras", municipality="La Florida",
         department="Nariño", hazard_type=HazardType.DESLIZAMIENTO, susceptibility=4,
         slope_deg=31, lat=1.2976, lon=-77.4062),
    dict(name="Mocoa - Barrio San Miguel", municipality="Mocoa", department="Putumayo",
         hazard_type=HazardType.MIXTO, susceptibility=5, slope_deg=18,
         lat=1.1500, lon=-76.6480),
    dict(name="Barbacoas - Río Telembí", municipality="Barbacoas", department="Nariño",
         hazard_type=HazardType.CRECIENTE, susceptibility=4, slope_deg=8,
         lat=1.6717, lon=-78.1400),
    dict(name="Tumaco - Río Mira", municipality="Tumaco", department="Nariño",
         hazard_type=HazardType.CRECIENTE, susceptibility=3, slope_deg=2,
         lat=1.6250, lon=-78.6700),
]


def seed_zones(uow: UnitOfWork) -> int:
    """Idempotente: IDs deterministas (UUIDv5) a partir del nombre de la zona."""
    created = 0
    for data in SEED_ZONES:
        zone_id = uuid5(_NAMESPACE, data["name"])
        if uow.zones.get(zone_id) is not None:
            continue
        uow.zones.add(
            Zone(
                id=zone_id,
                name=data["name"],
                municipality=data["municipality"],
                department=data["department"],
                hazard_type=data["hazard_type"],
                susceptibility=data["susceptibility"],
                slope_deg=data["slope_deg"],
                location=Coordinates(data["lat"], data["lon"]),
            )
        )
        created += 1
    uow.commit()
    return created
