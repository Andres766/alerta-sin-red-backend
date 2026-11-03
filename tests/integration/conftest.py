"""Pruebas de integración contra PostgreSQL + PostGIS reales.

Se ejecutan solo si existe TEST_DATABASE_URL (en CI se levanta un servicio
postgis/postgis). La base indicada se vacía en cada prueba: nunca la apunte a
datos reales.
"""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from app.container import Container
from app.core.config import Settings
from app.core.security import Argon2PasswordHasher, JwtTokenService, PhoneCipher
from app.infrastructure.db.repositories import SqlAlchemyUnitOfWork
from app.infrastructure.db.session import build_engine, build_session_factory, init_db
from app.infrastructure.sms.gateways import ConsoleSmsGateway
from app.infrastructure.weather.fake import FakeWeatherProvider

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL no definido (requiere PostgreSQL + PostGIS)"
)

_TABLES = ("audit_log", "alert_notifications", "subscribers", "risk_assessments", "users", "zones")


@pytest.fixture(scope="session")
def engine():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL no definido")
    url = TEST_DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = build_engine(url)
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def cipher() -> PhoneCipher:
    return PhoneCipher(Fernet.generate_key().decode(), "indice-integracion")


@pytest.fixture
def pg_container(engine, cipher, risk_model) -> Container:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(_TABLES)} CASCADE"))
    session_factory = build_session_factory(engine)
    settings = Settings(
        _env_file=None, environment="test", jwt_secret="s" * 48,
        phone_encryption_key=Fernet.generate_key().decode(), phone_index_key="k",
        admin_email="admin@test.co", admin_password="clave-integracion-12",
    )
    container = Container(
        settings=settings,
        uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory, cipher),
        weather=FakeWeatherProvider("tormenta"),
        sms=ConsoleSmsGateway(),
        model=risk_model,
        hasher=Argon2PasswordHasher(),
        tokens=JwtTokenService(settings.jwt_secret.get_secret_value(), "HS256", 30),
    )
    container.seed()
    return container
