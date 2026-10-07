import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings

BASE = dict(_env_file=None, jwt_secret="s" * 48,
            phone_encryption_key=Fernet.generate_key().decode(), phone_index_key="k")


@pytest.mark.parametrize("url", ["postgres://u:p@host:5432/db", "postgresql://u:p@host:5432/db"])
def test_normaliza_url_de_render_al_driver_psycopg(url):
    assert Settings(**BASE, database_url=url).database_url == "postgresql+psycopg://u:p@host:5432/db"


def test_agrega_el_dominio_de_render_a_hosts_permitidos(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "alerta-sin-red-api.onrender.com")
    assert "alerta-sin-red-api.onrender.com" in Settings(**BASE).allowed_hosts


def test_produccion_rechaza_cors_abierto():
    with pytest.raises(ValueError):
        Settings(**BASE, environment="production", cors_origins=["*"])
