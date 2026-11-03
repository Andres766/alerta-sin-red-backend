import pytest

from app.infrastructure.db.migrations import MIGRATIONS, Migration, pending


def test_versiones_consecutivas_y_unicas():
    versions = [m.version for m in MIGRATIONS]
    assert versions == list(range(1, len(MIGRATIONS) + 1))


def test_solo_devuelve_las_pendientes_en_orden():
    migrations = (Migration(3, "c", ("SELECT 3",)), Migration(1, "a", ("SELECT 1",)),
                  Migration(2, "b", ("SELECT 2",)))
    assert [m.version for m in pending({2}, migrations)] == [1, 3]
    assert pending({1, 2, 3}, migrations) == []


def test_detecta_versiones_repetidas():
    duplicated = (Migration(1, "a", ("SELECT 1",)), Migration(1, "b", ("SELECT 1",)))
    with pytest.raises(ValueError):
        pending(set(), duplicated)


def test_las_migraciones_son_idempotentes():
    # Deben poder reaplicarse sobre bases donde el cambio ya existía antes de versionarse.
    for migration in MIGRATIONS:
        for statement in migration.statements:
            assert "IF NOT EXISTS" in statement
