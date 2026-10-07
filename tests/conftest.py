from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.container import Container
from app.core.config import Settings
from app.core.security import Argon2PasswordHasher, JwtTokenService
from app.infrastructure.memory.repositories import InMemoryStore, InMemoryUnitOfWork
from app.infrastructure.ml.sklearn_model import SklearnRiskModel
from app.infrastructure.sms.gateways import ConsoleSmsGateway
from app.infrastructure.weather.fake import FakeWeatherProvider
from app.main import create_app

ADMIN_EMAIL = "admin@test.co"
ADMIN_PASSWORD = "clave-segura-de-prueba"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        repository_backend="memory",
        weather_provider="fake",
        jwt_secret="s" * 48,
        phone_encryption_key=Fernet.generate_key().decode(),
        phone_index_key="clave-indice-de-prueba",
        admin_email=ADMIN_EMAIL,
        admin_password=ADMIN_PASSWORD,
        login_rate_limit_per_minute=3,
    )


@pytest.fixture(scope="session")
def risk_model() -> SklearnRiskModel:
    s = Settings(_env_file=None, jwt_secret="s" * 48, phone_encryption_key="x",
                 phone_index_key="y")
    return SklearnRiskModel.load(s.model_path, s.model_metadata_path)


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def sms() -> ConsoleSmsGateway:
    return ConsoleSmsGateway()


def make_container(settings: Settings, store: InMemoryStore, sms: ConsoleSmsGateway,
                   model: SklearnRiskModel, scenario: str) -> Container:
    return Container(
        settings=settings,
        uow_factory=lambda: InMemoryUnitOfWork(store),
        weather=FakeWeatherProvider(scenario),
        sms=sms,
        model=model,
        hasher=Argon2PasswordHasher(),
        tokens=JwtTokenService(settings.jwt_secret.get_secret_value(), "HS256", 30),
    )


@pytest.fixture
def container(settings, store, sms, risk_model) -> Container:
    c = make_container(settings, store, sms, risk_model, "tormenta")
    c.seed()
    return c


@pytest.fixture
def client(settings, container) -> TestClient:
    with TestClient(create_app(settings, container)) as test_client:
        yield test_client


@pytest.fixture
def admin_token(client) -> str:
    res = client.post("/api/v1/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]
