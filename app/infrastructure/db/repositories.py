"""Repositorios sobre PostgreSQL + PostGIS y su Unit of Work.

Todas las consultas se construyen con el ORM/Core de SQLAlchemy, por lo que
los valores viajan como parámetros enlazados: no hay concatenación de SQL y
se elimina la inyección SQL por diseño.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from geoalchemy2 import Geography, Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import PhoneCipher
from app.domain.entities import (
    AlertNotification,
    AuditAction,
    AuditEntry,
    NotificationKind,
    NotificationStatus,
    RiskAssessment,
    Subscriber,
    User,
    Zone,
)
from app.domain.ports import (
    AlertRepository,
    AuditRepository,
    RiskAssessmentRepository,
    SubscriberRepository,
    UnitOfWork,
    UserRepository,
    ZoneRepository,
)
from app.domain.value_objects import Coordinates, PhoneNumber, RiskFeatures
from app.infrastructure.db.models import (
    AlertNotificationModel,
    AuditEntryModel,
    RiskAssessmentModel,
    SubscriberModel,
    UserModel,
    ZoneModel,
)

# --------------------------------------------------------------------------- #
# Zonas (consultas espaciales con PostGIS)
# --------------------------------------------------------------------------- #

_LAT = func.ST_Y(cast(ZoneModel.location, Geometry)).label("lat")
_LON = func.ST_X(cast(ZoneModel.location, Geometry)).label("lon")


def _to_zone(row: ZoneModel, lat: float, lon: float) -> Zone:
    return Zone(
        id=row.id,
        name=row.name,
        municipality=row.municipality,
        department=row.department,
        hazard_type=row.hazard_type,
        susceptibility=row.susceptibility,
        slope_deg=row.slope_deg,
        location=Coordinates(lat, lon),
    )


class SqlZoneRepository(ZoneRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, zone_id: UUID) -> Zone | None:
        row = self._session.execute(
            select(ZoneModel, _LAT, _LON).where(ZoneModel.id == zone_id)
        ).first()
        return _to_zone(*row) if row else None

    def list_all(self) -> list[Zone]:
        rows = self._session.execute(select(ZoneModel, _LAT, _LON).order_by(ZoneModel.name))
        return [_to_zone(*r) for r in rows]

    def find_nearby(
        self, point: Coordinates, radius_km: float, limit: int
    ) -> list[tuple[Zone, float]]:
        origin = cast(
            func.ST_SetSRID(func.ST_MakePoint(point.longitude, point.latitude), 4326),
            Geography(srid=4326),
        )
        distance_m = func.ST_Distance(ZoneModel.location, origin).label("distance_m")
        stmt = (
            select(ZoneModel, _LAT, _LON, distance_m)
            # ST_DWithin aprovecha el índice espacial GiST.
            .where(func.ST_DWithin(ZoneModel.location, origin, radius_km * 1000))
            .order_by(distance_m)
            .limit(limit)
        )
        return [
            (_to_zone(z, lat, lon), round(d / 1000, 3))
            for z, lat, lon, d in self._session.execute(stmt)
        ]

    def add(self, zone: Zone) -> None:
        self._session.merge(
            ZoneModel(
                id=zone.id,
                name=zone.name,
                municipality=zone.municipality,
                department=zone.department,
                hazard_type=zone.hazard_type,
                susceptibility=zone.susceptibility,
                slope_deg=zone.slope_deg,
                location=WKTElement(
                    f"POINT({zone.location.longitude} {zone.location.latitude})", srid=4326
                ),
            )
        )


# --------------------------------------------------------------------------- #
# Evaluaciones de riesgo
# --------------------------------------------------------------------------- #


def _to_assessment(row: RiskAssessmentModel) -> RiskAssessment:
    return RiskAssessment(
        id=row.id,
        zone_id=row.zone_id,
        level=row.level,
        probability=row.probability,
        probabilities=row.probabilities,
        features=RiskFeatures(**row.features),
        model_version=row.model_version,
        weather_source=row.weather_source,
        assessed_at=row.assessed_at,
    )


class SqlRiskAssessmentRepository(RiskAssessmentRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, assessment: RiskAssessment) -> None:
        self._session.add(
            RiskAssessmentModel(
                id=assessment.id,
                zone_id=assessment.zone_id,
                level=assessment.level,
                probability=assessment.probability,
                probabilities=assessment.probabilities,
                features=assessment.features.to_dict(),
                model_version=assessment.model_version,
                weather_source=assessment.weather_source,
                assessed_at=assessment.assessed_at,
            )
        )

    def latest_by_zone(self) -> dict[UUID, RiskAssessment]:
        # DISTINCT ON de PostgreSQL: la fila más reciente por zona en una sola consulta.
        stmt = (
            select(RiskAssessmentModel)
            .distinct(RiskAssessmentModel.zone_id)
            .order_by(RiskAssessmentModel.zone_id, RiskAssessmentModel.assessed_at.desc())
        )
        return {r.zone_id: _to_assessment(r) for r in self._session.scalars(stmt)}

    def history(self, zone_id: UUID, limit: int) -> list[RiskAssessment]:
        stmt = (
            select(RiskAssessmentModel)
            .where(RiskAssessmentModel.zone_id == zone_id)
            .order_by(RiskAssessmentModel.assessed_at.desc())
            .limit(limit)
        )
        return [_to_assessment(r) for r in self._session.scalars(stmt)]


# --------------------------------------------------------------------------- #
# Suscriptores (teléfono cifrado + índice ciego)
# --------------------------------------------------------------------------- #


class SqlSubscriberRepository(SubscriberRepository):
    def __init__(self, session: Session, cipher: PhoneCipher) -> None:
        self._session = session
        self._cipher = cipher

    def _to_entity(self, row: SubscriberModel) -> Subscriber:
        return Subscriber(
            id=row.id,
            zone_id=row.zone_id,
            phone=self._cipher.decrypt(row.phone_ciphertext),
            consent_at=row.consent_at,
            active=row.active,
            created_at=row.created_at,
            cancel_token_hash=row.cancel_token_hash,
        )

    def get(self, subscriber_id: UUID) -> Subscriber | None:
        row = self._session.get(SubscriberModel, subscriber_id)
        return self._to_entity(row) if row else None

    def add(self, subscriber: Subscriber) -> None:
        self._session.merge(
            SubscriberModel(
                id=subscriber.id,
                zone_id=subscriber.zone_id,
                phone_ciphertext=self._cipher.encrypt(subscriber.phone),
                phone_index=self._cipher.blind_index(subscriber.phone),
                consent_at=subscriber.consent_at,
                active=subscriber.active,
                created_at=subscriber.created_at,
                cancel_token_hash=subscriber.cancel_token_hash,
            )
        )

    def find(self, zone_id: UUID, phone: PhoneNumber) -> Subscriber | None:
        row = self._session.scalars(
            select(SubscriberModel).where(
                SubscriberModel.zone_id == zone_id,
                SubscriberModel.phone_index == self._cipher.blind_index(phone),
            )
        ).first()
        return self._to_entity(row) if row else None

    def active_for_zone(self, zone_id: UUID) -> list[Subscriber]:
        rows = self._session.scalars(
            select(SubscriberModel).where(
                SubscriberModel.zone_id == zone_id, SubscriberModel.active.is_(True)
            )
        )
        return [self._to_entity(r) for r in rows]

    def count_active(self) -> int:
        return self._session.scalar(
            select(func.count()).select_from(SubscriberModel).where(SubscriberModel.active)
        ) or 0


# --------------------------------------------------------------------------- #
# Notificaciones y usuarios
# --------------------------------------------------------------------------- #


def _to_notification(row: AlertNotificationModel) -> AlertNotification:
    return AlertNotification(
        id=row.id,
        zone_id=row.zone_id,
        assessment_id=row.assessment_id,
        subscriber_id=row.subscriber_id,
        level=row.level,
        channel=row.channel,
        status=row.status,
        provider_message_id=row.provider_message_id,
        error=row.error,
        created_at=row.created_at,
        kind=NotificationKind(row.kind),
    )


class SqlAlertRepository(AlertRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, n: AlertNotification) -> None:
        self._session.add(
            AlertNotificationModel(
                id=n.id,
                zone_id=n.zone_id,
                assessment_id=n.assessment_id,
                subscriber_id=n.subscriber_id,
                level=n.level,
                channel=n.channel,
                status=n.status,
                kind=n.kind.value,
                provider_message_id=n.provider_message_id,
                error=(n.error or "")[:255] or None,
                created_at=n.created_at,
            )
        )

    def last_sent_for_zone(self, zone_id: UUID) -> AlertNotification | None:
        row = self._session.scalars(
            select(AlertNotificationModel)
            .where(
                AlertNotificationModel.zone_id == zone_id,
                AlertNotificationModel.status == NotificationStatus.SENT,
            )
            .order_by(AlertNotificationModel.created_at.desc())
            .limit(1)
        ).first()
        return _to_notification(row) if row else None

    def recent(self, limit: int) -> list[AlertNotification]:
        rows = self._session.scalars(
            select(AlertNotificationModel)
            .order_by(AlertNotificationModel.created_at.desc())
            .limit(limit)
        )
        return [_to_notification(r) for r in rows]

    def count_since(self, since: datetime) -> dict[str, int]:
        counts = {s.value: 0 for s in NotificationStatus}
        rows = self._session.execute(
            select(AlertNotificationModel.status, func.count())
            .where(AlertNotificationModel.created_at >= since)
            .group_by(AlertNotificationModel.status)
        )
        for status, total in rows:
            counts[status.value] = total
        return counts


def _to_user(row: UserModel) -> User:
    return User(
        id=row.id,
        email=row.email,
        password_hash=row.password_hash,
        role=row.role,
        active=row.active,
        created_at=row.created_at,
        password_changed_at=row.password_changed_at,
    )


class SqlUserRepository(UserRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: UUID) -> User | None:
        row = self._session.get(UserModel, user_id)
        return _to_user(row) if row else None

    def get_by_email(self, email: str) -> User | None:
        row = self._session.scalars(select(UserModel).where(UserModel.email == email)).first()
        return _to_user(row) if row else None

    def list_all(self) -> list[User]:
        return [_to_user(r) for r in self._session.scalars(
            select(UserModel).order_by(UserModel.created_at)
        )]

    def add(self, user: User) -> None:
        self._session.merge(
            UserModel(
                id=user.id,
                email=user.email,
                password_hash=user.password_hash,
                role=user.role,
                active=user.active,
                created_at=user.created_at,
                password_changed_at=user.password_changed_at,
            )
        )


class SqlAuditRepository(AuditRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entry: AuditEntry) -> None:
        self._session.add(
            AuditEntryModel(
                id=entry.id,
                actor=entry.actor,
                action=entry.action.value,
                target=entry.target,
                details=entry.details,
                created_at=entry.created_at,
            )
        )

    def recent(self, limit: int) -> list[AuditEntry]:
        rows = self._session.scalars(
            select(AuditEntryModel).order_by(AuditEntryModel.created_at.desc()).limit(limit)
        )
        return [
            AuditEntry(id=r.id, actor=r.actor, action=AuditAction(r.action), target=r.target,
                       details=r.details, created_at=r.created_at)
            for r in rows
        ]


class SqlAlchemyUnitOfWork(UnitOfWork):
    def __init__(self, session_factory: sessionmaker[Session], cipher: PhoneCipher) -> None:
        self._session_factory = session_factory
        self._cipher = cipher
        self._session: Session | None = None

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        self.zones = SqlZoneRepository(self._session)
        self.assessments = SqlRiskAssessmentRepository(self._session)
        self.subscribers = SqlSubscriberRepository(self._session, self._cipher)
        self.alerts = SqlAlertRepository(self._session)
        self.users = SqlUserRepository(self._session)
        self.audit = SqlAuditRepository(self._session)
        return self

    def __exit__(self, *args: object) -> None:
        super().__exit__(*args)  # type: ignore[arg-type]
        if self._session is not None:
            self._session.close()
            self._session = None

    def commit(self) -> None:
        assert self._session is not None, "Unit of Work usada fuera de 'with'"
        self._session.commit()

    def rollback(self) -> None:
        if self._session is not None:
            self._session.rollback()
