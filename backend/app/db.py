"""Database engine, session factory, and ORM base."""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Create tables and the storage layout if missing."""
    from pathlib import Path

    from . import models  # noqa: F401  (register models on Base.metadata)

    if settings.database_url.startswith("sqlite"):
        # SQLite cannot create its file if the parent directory is missing.
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    voices_dir = settings.storage_path / "voices"
    narrations_dir = settings.storage_path / "narrations"
    voices_dir.mkdir(parents=True, exist_ok=True)
    narrations_dir.mkdir(parents=True, exist_ok=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
