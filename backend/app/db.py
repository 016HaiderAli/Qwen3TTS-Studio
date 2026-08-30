"""Database engine, session factory, and ORM base."""
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()


def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    """SQLite does not enforce foreign keys unless each connection opts in.

    The schema declares ``ondelete="CASCADE"`` constraints (voices -> narrations,
    voices/narrations -> jobs); without this pragma those constraints are inert and
    deleting a parent would leave dangling child rows.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


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

if settings.database_url.startswith("sqlite"):
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _migrate_jobs_required_backend() -> None:
    """Add the ``required_backend`` capability column to an existing jobs table.

    ``create_all`` never alters existing tables; the live SQLite DB predates the
    capability gate, so existing jobs are backfilled as ``qwen`` (they were all
    web-tier jobs meant for the real worker).
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "jobs" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("jobs")}
    if "required_backend" in columns:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE jobs ADD COLUMN required_backend VARCHAR(30) "
                "NOT NULL DEFAULT 'qwen'"
            )
        )


def _migrate_jobs_lease_columns() -> None:
    """Add the job lease columns (``claimed_at``, ``claim_token``) to an
    existing jobs table. SQLite ``ALTER TABLE ADD COLUMN`` adds nullable
    columns; existing rows get NULL, which the stale-recovery treats as stale so
    a pre-deployment ``running`` job (which has no lease bookkeeping) is still
    recovered instead of stuck forever.
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "jobs" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("jobs")}
    with engine.begin() as conn:
        if "claimed_at" not in columns:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN claimed_at DATETIME"))
        if "claim_token" not in columns:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN claim_token VARCHAR(64)"))


def init_db() -> None:
    """Create tables and the storage layout if missing."""
    from pathlib import Path

    from . import models  # noqa: F401  (register models on Base.metadata)

    if settings.database_url.startswith("sqlite"):
        # SQLite cannot create its file if the parent directory is missing.
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _migrate_jobs_required_backend()
    _migrate_jobs_lease_columns()
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


def get_db_context() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
