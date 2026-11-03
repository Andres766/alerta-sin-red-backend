from datetime import timedelta

from sqlalchemy import text

from app.domain.entities import NotificationKind, utcnow
from app.domain.value_objects import Coordinates
from app.infrastructure.db.migrations import MIGRATIONS
from app.infrastructure.weather.fake import FakeWeatherProvider

PASTO = Coordinates(1.2136, -77.2811)


def test_consulta_espacial_ordena_por_distancia_con_postgis(pg_container):
    with pg_container.uow_factory() as uow:
        nearby = uow.zones.find_nearby(PASTO, radius_km=20, limit=10)
    names = [z.name for z, _ in nearby]
    distances = [d for _, d in nearby]
    assert names[0] == "Pasto - Ribera del río Pasto"
    assert distances == sorted(distances) and all(d <= 20 for d in distances)
    assert not any("Mocoa" in n for n in names)  # Mocoa está a ~70 km


def test_ultima_evaluacion_por_zona_con_distinct_on(pg_container):
    with pg_container.uow_factory() as uow:
        service = pg_container.risk_service(uow)
        service.evaluate_all()
        pg_container.weather = FakeWeatherProvider("seco")
        second = pg_container.risk_service(uow).evaluate_all()
        latest = uow.assessments.latest_by_zone()
    assert len(latest) == 6
    assert {a.id for a in latest.values()} == {a.id for a in second.assessments}


def test_telefono_cifrado_en_reposo_y_sin_duplicados(pg_container, engine):
    with pg_container.uow_factory() as uow:
        zone = uow.zones.list_all()[0]
        service = pg_container.subscription_service(uow)
        first = service.subscribe("3001234567", zone.id, True)
        again = service.subscribe("+57 300 123 4567", zone.id, True)
    assert first.subscriber.id == again.subscriber.id
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT phone_ciphertext, phone_index FROM subscribers")).all()
    assert len(rows) == 1
    ciphertext, index = rows[0]
    assert "3001234567" not in ciphertext and "3001234567" not in index


def test_flujo_completo_alerta_y_fin_de_alerta(pg_container):
    mocoa = None
    with pg_container.uow_factory() as uow:
        mocoa = next(z for z in uow.zones.list_all() if "Mocoa" in z.name)
        pg_container.subscription_service(uow).subscribe("3109876543", mocoa.id, True)
        pg_container.risk_service(uow).evaluate_zone(mocoa.id)
        pg_container.weather = FakeWeatherProvider("seco")
        pg_container.risk_service(uow).evaluate_zone(mocoa.id)
        kinds = [a.kind for a in uow.alerts.recent(10)]
        counts = uow.alerts.count_since(utcnow() - timedelta(hours=1))
    assert kinds == [NotificationKind.ALL_CLEAR, NotificationKind.ALERT]
    assert counts == {"SENT": 2, "FAILED": 0}


def test_migraciones_registradas(engine):
    with engine.connect() as conn:
        versions = [r[0] for r in conn.execute(text("SELECT version FROM schema_migrations"))]
    assert sorted(versions) == [m.version for m in MIGRATIONS]


def test_bitacora_persistente(pg_container):
    with pg_container.uow_factory() as uow:
        pg_container.auth_service(uow).login("admin@test.co", "clave-integracion-12")
        actions = [e.action.value for e in uow.audit.recent(5)]
    assert "LOGIN_SUCCEEDED" in actions
