import os

import pytest
from sqlalchemy import create_engine, text

# База для тестов отдельная: тесты дропают схему, и делать это с базой
# разработки нельзя. Задаётся до импорта app.* — конфиг читается на импорте.
BASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://pos@127.0.0.1:5432/pos_test"
)
os.environ["DATABASE_URL"] = BASE_URL

from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.seed import seed  # noqa: E402


def _ensure_database() -> None:
    admin_url = BASE_URL.rsplit("/", 1)[0] + "/postgres"
    name = BASE_URL.rsplit("/", 1)[1]
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
        ).first()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    _ensure_database()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


def _truncate() -> None:
    """Каждый тест начинается с чистой базы.

    Иначе сотрудники и чеки копятся между тестами, и падает не тот тест,
    который сломан, а тот, который шёл следом.
    """
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture()
def db(database):
    _truncate()
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def venue(db):
    return seed(db)


@pytest.fixture()
def client(venue):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def make_user(db, venue):
    """Сотрудник с известным PIN. Роль по умолчанию — официант."""
    from app.models import User
    from app.services.auth import issue_pin

    def factory(name: str, role: str = "waiter", pin: str = "1111", active: bool = True):
        user = User(venue_id=venue.id, name=name, role=role, active=active)
        db.add(user)
        db.flush()
        issue_pin(db, user, pin)
        db.commit()
        return user

    return factory
