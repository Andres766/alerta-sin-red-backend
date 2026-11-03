"""Raíz de composición (Composition Root).

Es el ÚNICO lugar que conoce las implementaciones concretas. Construye los
objetos de larga vida una vez (Singleton por contenedor) y fabrica los de
vida corta por petición. Para las pruebas basta con construir un contenedor
con otras piezas: ningún caso de uso cambia.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta

import httpx

from app.application.event_bus import EventBus
from app.application.services.alert_dispatcher import AlertDispatcher
from app.application.services.auth import AuthService
from app.application.services.dashboard import DashboardService
from app.application.services.risk_assessment import RiskAssessmentService
from app.application.services.subscriptions import SubscriptionService
from app.application.services.users import UserManagementService
from app.application.services.zones import ZoneQueryService
from app.core.config import Settings
from app.core.security import (
    Argon2PasswordHasher,
    JwtTokenService,
    PhoneCipher,
    SlidingWindowRateLimiter,
)
from app.domain.entities import Role, utcnow
from app.domain.events import RiskAssessed
from app.domain.policies import AlertMessageBuilder, AlertPolicy
from app.domain.ports import (
    PasswordHasher,
    RiskModel,
    SmsGateway,
    TokenService,
    UnitOfWork,
    WeatherProvider,
)
from app.infrastructure.seed import seed_zones

logger = logging.getLogger(__name__)


class Container:
    def __init__(
        self,
        settings: Settings,
        uow_factory: Callable[[], UnitOfWork],
        weather: WeatherProvider,
        sms: SmsGateway,
        model: RiskModel,
        hasher: PasswordHasher,
        tokens: TokenService,
        http_client: httpx.Client | None = None,
        readiness_checks: dict[str, Callable[[], None]] | None = None,
    ) -> None:
        self.settings = settings
        # Verificaciones de disponibilidad (nombre -> función que lanza si falla).
        self.readiness_checks = readiness_checks or {}
        self.uow_factory = uow_factory
        self.weather = weather
        self.sms = sms
        self.model = model
        self.hasher = hasher
        self.tokens = tokens
        self.alert_policy = AlertPolicy(timedelta(hours=settings.alert_cooldown_hours))
        self.message_builder = AlertMessageBuilder()
        self.login_limiter = SlidingWindowRateLimiter(settings.login_rate_limit_per_minute, 60)
        # Límite por cuenta: la IP se puede falsear con X-Forwarded-For, el correo atacado no.
        self.account_login_limiter = SlidingWindowRateLimiter(
            settings.login_attempts_per_account, 15 * 60
        )
        self.subscribe_limiter = SlidingWindowRateLimiter(
            settings.subscribe_rate_limit_per_hour, 3600
        )
        self._http_client = http_client
        self._dummy_hash = hasher.hash("usuario-inexistente-señuelo")

    # ---- Fábricas de casos de uso (una instancia por Unit of Work) ---------- #

    def risk_service(self, uow: UnitOfWork) -> RiskAssessmentService:
        bus = EventBus()
        bus.subscribe(
            RiskAssessed,
            AlertDispatcher(uow, self.sms, self.alert_policy, self.message_builder, utcnow),
        )
        return RiskAssessmentService(uow, self.weather, self.model, bus)

    def subscription_service(self, uow: UnitOfWork) -> SubscriptionService:
        return SubscriptionService(uow)

    def zone_queries(self, uow: UnitOfWork) -> ZoneQueryService:
        return ZoneQueryService(uow)

    def dashboard(self, uow: UnitOfWork) -> DashboardService:
        return DashboardService(uow)

    def user_management(self, uow: UnitOfWork) -> UserManagementService:
        return UserManagementService(uow, self.hasher)

    def auth_service(self, uow: UnitOfWork) -> AuthService:
        return AuthService(uow, self.hasher, self.tokens, self._dummy_hash)

    # ---- Ciclo de vida ------------------------------------------------------ #

    def seed(self) -> None:
        with self.uow_factory() as uow:
            created = seed_zones(uow)
            if self.settings.admin_email and self.settings.admin_password:
                self.auth_service(uow).ensure_user(
                    self.settings.admin_email,
                    self.settings.admin_password.get_secret_value(),
                    Role.ADMIN,
                )
        logger.info("Siembra completada: %d zonas nuevas", created)

    def readiness(self) -> dict[str, str]:
        """Ejecuta cada verificación y devuelve "ok" o el tipo de error (sin detalles internos)."""
        results: dict[str, str] = {}
        for name, check in self.readiness_checks.items():
            try:
                check()
                results[name] = "ok"
            except Exception as exc:  # noqa: BLE001 - se informa, no se propaga
                logger.warning("Verificación de disponibilidad '%s' falló: %s", name, exc)
                results[name] = f"error: {type(exc).__name__}"
        return results

    def close(self) -> None:
        if self._http_client is not None:
            self._http_client.close()


def build_container(settings: Settings) -> Container:
    """Arma el contenedor de producción/desarrollo a partir de la configuración."""
    from app.infrastructure.ml.sklearn_model import SklearnRiskModel
    from app.infrastructure.sms.gateways import SmsGatewayFactory
    from app.infrastructure.weather.fake import FakeWeatherProvider
    from app.infrastructure.weather.open_meteo import OpenMeteoWeatherProvider

    http_client = httpx.Client(
        timeout=settings.http_timeout_seconds,
        transport=httpx.HTTPTransport(retries=2),  # reintenta fallos de conexión
        headers={"User-Agent": "AlertaSinRed/0.1 (proyecto academico UCC Pasto)"},
        follow_redirects=False,
    )

    readiness_checks: dict[str, Callable[[], None]] = {}
    if settings.repository_backend == "memory":
        from app.infrastructure.memory.repositories import InMemoryStore, InMemoryUnitOfWork

        store = InMemoryStore()
        uow_factory: Callable[[], UnitOfWork] = lambda: InMemoryUnitOfWork(store)  # noqa: E731
    else:
        from app.infrastructure.db.repositories import SqlAlchemyUnitOfWork
        from app.infrastructure.db.session import (
            build_engine,
            build_session_factory,
            ping_database,
        )

        engine = build_engine(settings.database_url)
        session_factory = build_session_factory(engine)
        readiness_checks["database"] = lambda: ping_database(engine)
        cipher = PhoneCipher(
            settings.phone_encryption_key.get_secret_value(),
            settings.phone_index_key.get_secret_value(),
        )
        uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory, cipher)  # noqa: E731

    weather: WeatherProvider
    if settings.weather_provider == "fake":
        weather = FakeWeatherProvider(settings.fake_weather_scenario)
    else:
        weather = OpenMeteoWeatherProvider(
            settings.open_meteo_forecast_url, settings.open_meteo_flood_url, http_client
        )
    if settings.weather_cache_minutes > 0:
        from app.infrastructure.weather.cached import CachedWeatherProvider

        # Decorator: misma interfaz, con caché por coordenada.
        weather = CachedWeatherProvider(weather, ttl_seconds=settings.weather_cache_minutes * 60)

    return Container(
        settings=settings,
        uow_factory=uow_factory,
        weather=weather,
        sms=SmsGatewayFactory.create(settings, http_client),
        model=SklearnRiskModel.load(settings.model_path, settings.model_metadata_path),
        hasher=Argon2PasswordHasher(),
        tokens=JwtTokenService(
            settings.jwt_secret.get_secret_value(),
            settings.jwt_algorithm,
            settings.jwt_expire_minutes,
        ),
        http_client=http_client,
        readiness_checks=readiness_checks,
    )
