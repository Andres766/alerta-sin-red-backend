import pytest
from argon2 import PasswordHasher as Argon2

from app.core.security import Argon2PasswordHasher
from app.domain.entities import Role, User
from app.domain.exceptions import AuthenticationError

WEAK = Argon2PasswordHasher(Argon2(time_cost=1, memory_cost=8 * 1024, parallelism=1))
CURRENT = Argon2PasswordHasher()


def test_detecta_hashes_con_parametros_viejos():
    assert CURRENT.needs_rehash(WEAK.hash("clave-de-prueba-12"))
    assert not CURRENT.needs_rehash(CURRENT.hash("clave-de-prueba-12"))
    assert CURRENT.needs_rehash("no-es-un-hash")


def test_el_login_actualiza_el_hash_sin_cambiar_la_clave(container):
    with container.uow_factory() as uow:
        old_hash = WEAK.hash("clave-antigua-12345")
        uow.users.add(User(email="veterano@x.co", password_hash=old_hash, role=Role.OPERATOR))
        container.auth_service(uow).login("veterano@x.co", "clave-antigua-12345")
        user = uow.users.get_by_email("veterano@x.co")

    assert user.password_hash != old_hash
    assert not CURRENT.needs_rehash(user.password_hash)
    assert CURRENT.verify(user.password_hash, "clave-antigua-12345")
    # No cuenta como cambio de contraseña: las sesiones abiertas siguen válidas.
    assert user.password_changed_at is None


def test_un_login_fallido_no_toca_el_hash(container):
    with container.uow_factory() as uow:
        old_hash = WEAK.hash("clave-antigua-12345")
        uow.users.add(User(email="veterano2@x.co", password_hash=old_hash))
        with pytest.raises(AuthenticationError):
            container.auth_service(uow).login("veterano2@x.co", "clave-equivocada")
        assert uow.users.get_by_email("veterano2@x.co").password_hash == old_hash
