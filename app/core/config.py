"""Configuración tipada y validada, leída de variables de entorno (12-factor app).

Ningún secreto vive en el código: si falta uno obligatorio la aplicación no
arranca, y en producción se rechazan valores de ejemplo o débiles.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # carpeta backend/

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "AlertaSinRed API"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # Persistencia: "postgres" (PostgreSQL + PostGIS) o "memory" (demo/pruebas).
    repository_backend: Literal["postgres", "memory"] = "postgres"
    database_url: str = "postgresql+psycopg://alerta:alerta@localhost:5432/alerta_sin_red"

    # Seguridad
    jwt_secret: SecretStr
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_expire_minutes: int = Field(default=30, ge=5, le=240)
    phone_encryption_key: SecretStr  # clave Fernet (AES-128-CBC + HMAC-SHA256)
    phone_index_key: SecretStr  # clave HMAC para el índice ciego de teléfonos
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "backend"]
    # Documentación interactiva (/docs). Apagada en producción salvo que se pida.
    expose_docs: bool = False
    login_rate_limit_per_minute: int = Field(default=5, ge=1)
    login_attempts_per_account: int = Field(default=10, ge=3)  # por cada 15 minutos
    subscribe_rate_limit_per_hour: int = Field(default=20, ge=1)

    # Usuario administrador inicial (solo lo usa el script de siembra)
    admin_email: str | None = None
    admin_password: SecretStr | None = None

    # Clima
    weather_provider: Literal["open_meteo", "fake"] = "open_meteo"
    fake_weather_scenario: Literal["seco", "lluvioso", "tormenta"] = "lluvioso"
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_flood_url: str = "https://flood-api.open-meteo.com/v1/flood"
    http_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    # SMS
    sms_provider: Literal["console", "twilio", "android_gateway"] = "console"
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_number: str | None = None
    android_gateway_url: str | None = None
    android_gateway_user: str | None = None
    android_gateway_password: SecretStr | None = None

    # Modelo de IA
    model_path: Path = BASE_DIR / "models" / "risk_model.joblib"
    model_metadata_path: Path = BASE_DIR / "models" / "risk_model.meta.json"

    # Alertas y tareas programadas
    alert_cooldown_hours: int = Field(default=6, ge=1, le=72)
    scheduler_enabled: bool = False
    scheduler_interval_minutes: int = Field(default=60, ge=5)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, url: str) -> str:
        """Render/Heroku entregan ``postgres://`` o ``postgresql://``; SQLAlchemy
        necesita que se indique el driver instalado (psycopg 3)."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @model_validator(mode="after")
    def _add_platform_host(self) -> Settings:
        # Render inyecta el dominio público del servicio en esta variable.
        render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
        if render_host and render_host not in self.allowed_hosts:
            self.allowed_hosts = [*self.allowed_hosts, render_host]
        return self

    @model_validator(mode="after")
    def _validate_security(self) -> Settings:
        if len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET debe tener al menos 32 caracteres")
        if self.is_production:
            if "cambiar" in self.jwt_secret.get_secret_value().lower():
                raise ValueError("JWT_SECRET de ejemplo no permitido en producción")
            if any(o == "*" for o in self.cors_origins):
                raise ValueError("CORS abierto (*) no permitido en producción")
            if self.sms_provider == "console":
                logger.warning("SMS_PROVIDER=console: los SMS solo se registrarán en el log")
        if self.sms_provider == "twilio" and not (
            self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number
        ):
            raise ValueError("Faltan credenciales de Twilio")
        if self.sms_provider == "android_gateway" and not (
            self.android_gateway_url and self.android_gateway_user and self.android_gateway_password
        ):
            raise ValueError("Faltan credenciales del Android SMS Gateway")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
