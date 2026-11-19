"""Engine and session factory. The URL is read when the engine is first used."""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from axiom.config import database_url
from axiom.db.models import Base

_engine = None
_factory: sessionmaker[Session] | None = None


def get_engine():
    global _engine, _factory
    if _engine is None:
        _engine = create_engine(
            database_url(),
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @event.listens_for(_engine, "connect")
        def _wal(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        _factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _factory is not None
    return _factory


def open_session() -> Session:
    return session_factory()()


def reset_engine() -> None:
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _factory = None


def init_db() -> None:
    import axiom.lifecycle.tables  # noqa: F401  registers lifecycle tables on Base

    get_engine()
    Base.metadata.create_all(get_engine())
