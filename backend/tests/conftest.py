"""Shared fixtures.

Database tests run against a separate database (`<name>_test`) on the same server as
DATABASE_URL. It is created if missing and migrated with Alembic once per test session; each
test starts from empty tables.
"""

import os
import tempfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session

from app.core import config as app_config
from app.core import db as app_db


def _test_database_url() -> str:
    base = make_url(app_config.get_settings().database_url)
    name = base.database or "cmm_quality"
    if not name.endswith("_test"):
        name = f"{name}_test"
    return base.set(database=name).render_as_string(hide_password=False)


TEST_DATABASE_URL = _test_database_url()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["JWT_SECRET"] = "test-only-secret-with-enough-length-0123456789"
os.environ["DEMO_USER_PASSWORD"] = "test-demo-password"
os.environ["ESCALATION_PROFILE"] = "demo"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="cmm-test-data-")
app_config.get_settings.cache_clear()
app_db.get_engine.cache_clear()
app_db.get_sessionmaker.cache_clear()

_migrated = False


def _ensure_database() -> None:
    global _migrated
    if _migrated:
        return
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

    # Fresh schema every session so model/migration changes are always exercised.
    fresh = create_engine(url, isolation_level="AUTOCOMMIT")
    with fresh.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    fresh.dispose()

    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    command.upgrade(cfg, "head")
    _migrated = True


def truncate_all() -> None:
    from app.models import Base

    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with app_db.get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db() -> Iterator[Session]:
    """A session on a freshly emptied test database."""
    _ensure_database()
    truncate_all()
    session = app_db.get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())
