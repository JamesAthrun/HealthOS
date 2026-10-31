import pytest

from app.config import Settings
from tests import conftest


def test_postgres_password_with_url_reserved_characters_is_preserved():
    settings = Settings(
        _env_file=None,
        database_url=None,
        postgres_host="postgres",
        postgres_db="healthos",
        postgres_user="healthos_app",
        postgres_password="strong@password:/#%",
    )

    url = settings.sqlalchemy_database_url

    assert url.get_backend_name() == "postgresql"
    assert url.host == "postgres"
    assert url.password == "strong@password:/#%"


def test_postgres_test_database_must_use_test_suffix(monkeypatch):
    monkeypatch.setattr(
        conftest,
        "TEST_DATABASE_URL",
        "postgresql+psycopg://healthos:secret@localhost/healthos",
    )

    with pytest.raises(RuntimeError, match="必须以 _test 结尾"):
        conftest._assert_safe_test_database()
