from __future__ import annotations

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.db.models import Base


def build_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_timeout=10,  # espera máxima por una conexión libre del pool
        # Sin este límite, una base caída deja la petición colgada indefinidamente.
        connect_args={"connect_timeout": 5},
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def ping_database(engine: Engine) -> None:
    """Comprueba que la base responde (lanza si no hay conexión)."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def init_db(engine: Engine) -> list[int]:
    """Crea la extensión PostGIS y las tablas, y aplica las migraciones pendientes.

    Devuelve las versiones de migración aplicadas en esta ejecución.
    """
    from app.infrastructure.db.migrations import migrate

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(engine)
    return migrate(engine)
