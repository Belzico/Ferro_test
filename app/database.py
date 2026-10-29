from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Base(DeclarativeBase):
    pass


def resolve_database_url(configured_url: str) -> str:
    """Resolve relative SQLite paths against the project root."""

    url = make_url(configured_url)

    if url.get_backend_name() != "sqlite":
        return configured_url

    if not url.database or url.database == ":memory:":
        return configured_url

    database_path = Path(url.database)

    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path

    database_path = database_path.resolve()

    return url.set(database=str(database_path)).render_as_string(
        hide_password=False
    )


DATABASE_URL = resolve_database_url(settings.database.url)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def init_db(database_engine=None):
    from app import models

    Base.metadata.create_all(
        bind=database_engine if database_engine is not None else engine
    )


def get_db():
    with SessionLocal() as session:
        yield session
