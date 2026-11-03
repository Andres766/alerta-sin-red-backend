"""Modelos ORM (SQLAlchemy 2.0 + GeoAlchemy2).

Se mantienen separados de las entidades del dominio: el dominio no sabe que
existe una base de datos. Los repositorios traducen entre ambos mundos.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from geoalchemy2 import Geography
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.entities import NotificationStatus, Role
from app.domain.value_objects import HazardType, RiskLevel


class Base(DeclarativeBase):
    pass


def _enum(enum_cls: type, name: str) -> Enum:
    return Enum(enum_cls, name=name, native_enum=True, validate_strings=True)


class ZoneModel(Base):
    __tablename__ = "zones"
    __table_args__ = (
        CheckConstraint("susceptibility BETWEEN 1 AND 5", name="ck_zone_susceptibility"),
        CheckConstraint("slope_deg BETWEEN 0 AND 90", name="ck_zone_slope"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    municipality: Mapped[str] = mapped_column(String(80))
    department: Mapped[str] = mapped_column(String(80))
    hazard_type: Mapped[HazardType] = mapped_column(_enum(HazardType, "hazard_type"))
    susceptibility: Mapped[int] = mapped_column(SmallInteger)
    slope_deg: Mapped[float] = mapped_column(Float)
    # geography(Point, 4326): distancias en metros sobre el elipsoide. Índice GiST automático.
    location: Mapped[object] = mapped_column(Geography(geometry_type="POINT", srid=4326))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RiskAssessmentModel(Base):
    __tablename__ = "risk_assessments"
    __table_args__ = (
        Index("ix_assessment_zone_time", "zone_id", "assessed_at"),
        CheckConstraint("probability BETWEEN 0 AND 1", name="ck_assessment_probability"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    zone_id: Mapped[UUID] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"))
    level: Mapped[RiskLevel] = mapped_column(_enum(RiskLevel, "risk_level"))
    probability: Mapped[float] = mapped_column(Float)
    probabilities: Mapped[dict] = mapped_column(JSONB)
    features: Mapped[dict] = mapped_column(JSONB)
    model_version: Mapped[str] = mapped_column(String(40))
    weather_source: Mapped[str] = mapped_column(String(40))
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SubscriberModel(Base):
    __tablename__ = "subscribers"
    __table_args__ = (UniqueConstraint("zone_id", "phone_index", name="uq_subscriber_zone_phone"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    zone_id: Mapped[UUID] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"))
    phone_ciphertext: Mapped[str] = mapped_column(String(255))  # Fernet
    phone_index: Mapped[str] = mapped_column(String(64), index=True)  # HMAC-SHA256
    cancel_token_hash: Mapped[str | None] = mapped_column(String(64))  # SHA-256
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AlertNotificationModel(Base):
    __tablename__ = "alert_notifications"
    __table_args__ = (Index("ix_alert_zone_time", "zone_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    zone_id: Mapped[UUID] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"))
    assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("risk_assessments.id", ondelete="CASCADE")
    )
    subscriber_id: Mapped[UUID] = mapped_column(ForeignKey("subscribers.id", ondelete="CASCADE"))
    level: Mapped[RiskLevel] = mapped_column(_enum(RiskLevel, "risk_level"))
    channel: Mapped[str] = mapped_column(String(30))
    status: Mapped[NotificationStatus] = mapped_column(
        _enum(NotificationStatus, "notification_status")
    )
    kind: Mapped[str] = mapped_column(String(20), default="ALERT", server_default="ALERT")
    provider_message_id: Mapped[str | None] = mapped_column(String(120))
    error: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"))
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEntryModel(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_time", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(254))
    action: Mapped[str] = mapped_column(String(40))
    target: Mapped[str | None] = mapped_column(String(254))
    details: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
