"""Candados para que una tarea (la evaluación completa) no corra dos veces a la vez."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, func, select

from app.domain.ports import JobLock


class InProcessJobLock(JobLock):
    """Suficiente con una sola instancia de la API (modo memoria o un solo contenedor)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    @contextmanager
    def hold(self) -> Iterator[bool]:
        acquired = self._lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                self._lock.release()


class PostgresAdvisoryJobLock(JobLock):
    """Advisory lock de PostgreSQL: coordina varias instancias o réplicas de la API.

    Primero toma el candado del proceso (barato) y luego el de la base, que se
    libera solo si la conexión se corta (p. ej. si el proceso muere a mitad).
    """

    def __init__(self, engine: Engine, key: int) -> None:
        self._engine = engine
        self._key = key
        self._local = InProcessJobLock()

    @contextmanager
    def hold(self) -> Iterator[bool]:
        with self._local.hold() as local:
            if not local:
                yield False
                return
            with self._engine.connect() as conn:
                acquired = bool(conn.execute(select(func.pg_try_advisory_lock(self._key))).scalar())
                try:
                    yield acquired
                finally:
                    if acquired:
                        conn.execute(select(func.pg_advisory_unlock(self._key)))
