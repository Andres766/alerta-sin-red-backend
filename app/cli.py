"""Comandos de operación.

    python -m app.cli gen-keys     # genera secretos aleatorios para el .env
    python -m app.cli init-db      # crea extensión PostGIS y tablas
    python -m app.cli seed         # zonas piloto + usuario administrador
    python -m app.cli evaluate     # ejecuta el modelo sobre todas las zonas
"""

from __future__ import annotations

import argparse
import secrets

from cryptography.fernet import Fernet


def _gen_keys() -> None:
    print(f"JWT_SECRET={secrets.token_urlsafe(48)}")
    print(f"PHONE_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
    print(f"PHONE_INDEX_KEY={secrets.token_urlsafe(32)}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="alerta-sin-red")
    parser.add_argument("command", choices=["gen-keys", "init-db", "seed", "evaluate"])
    command = parser.parse_args().command

    if command == "gen-keys":  # no requiere configuración previa
        _gen_keys()
        return

    from app.container import build_container
    from app.core.config import get_settings
    from app.core.logging import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level)

    if command == "init-db":
        from app.infrastructure.db.session import build_engine, init_db

        init_db(build_engine(settings.database_url))
        print("Base de datos inicializada")
        return

    container = build_container(settings)
    try:
        if command == "seed":
            container.seed()
        elif command == "evaluate":
            with container.uow_factory() as uow:
                report = container.risk_service(uow).evaluate_all()
            for a in report.assessments:
                print(f"{a.zone_id}  {a.level.value:<9} p={a.probability:.2f}")
            for zone, reason in report.failures.items():
                print(f"FALLÓ {zone}: {reason}")
    finally:
        container.close()


if __name__ == "__main__":
    main()
