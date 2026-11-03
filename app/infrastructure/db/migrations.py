"""Migraciones versionadas del esquema.

``create_all`` crea las tablas nuevas pero nunca altera las existentes. Los
cambios sobre tablas ya desplegadas (p. ej. en Render) se declaran aquí, con un
número de versión creciente. La tabla ``schema_migrations`` registra cuáles se
aplicaron y cuándo, así cada una se ejecuta una sola vez y en orden.

Regla: una migración publicada nunca se edita; un cambio nuevo es una
migración nueva con el número siguiente.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    description: str
    statements: tuple[str, ...]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "Código de baja de suscripciones", (
        "ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS cancel_token_hash VARCHAR(64)",
    )),
    Migration(2, "Tipo de notificación (alerta o fin de alerta)", (
        "ALTER TABLE alert_notifications "
        "ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'ALERT'",
    )),
    Migration(3, "Fecha del último cambio de contraseña", (
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ",
    )),
)

_CREATE_TABLE = text(
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    " version INTEGER PRIMARY KEY,"
    " description VARCHAR(200) NOT NULL,"
    " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
)


def pending(applied: set[int], migrations: tuple[Migration, ...] = MIGRATIONS) -> list[Migration]:
    """Migraciones aún no aplicadas, en orden de versión."""
    versions = [m.version for m in migrations]
    if len(set(versions)) != len(versions):
        raise ValueError("Hay versiones de migración repetidas")
    return sorted((m for m in migrations if m.version not in applied), key=lambda m: m.version)


def migrate(engine: Engine) -> list[int]:
    """Aplica las migraciones pendientes, cada una en su propia transacción."""
    with engine.begin() as conn:
        conn.execute(_CREATE_TABLE)
        applied = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}

    done: list[int] = []
    for migration in pending(applied):
        with engine.begin() as conn:
            for statement in migration.statements:
                conn.execute(text(statement))
            conn.execute(
                text("INSERT INTO schema_migrations (version, description) VALUES (:v, :d)"),
                {"v": migration.version, "d": migration.description},
            )
        logger.info("Migración %d aplicada: %s", migration.version, migration.description)
        done.append(migration.version)
    return done


def status(engine: Engine) -> list[tuple[int, str, str | None]]:
    """(versión, descripción, fecha de aplicación o None si está pendiente)."""
    with engine.begin() as conn:
        conn.execute(_CREATE_TABLE)
        applied = {
            row[0]: row[1].isoformat(timespec="seconds")
            for row in conn.execute(text("SELECT version, applied_at FROM schema_migrations"))
        }
    return [(m.version, m.description, applied.get(m.version)) for m in MIGRATIONS]
