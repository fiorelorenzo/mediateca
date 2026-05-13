from collections.abc import Iterator
from typing import Any

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from orchestrator.config import get_settings

_engine: Any = None


def get_engine() -> Any:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            f"sqlite:///{settings.state_db}",
            connect_args={"check_same_thread": False},
            echo=False,
        )

        @event.listens_for(_engine, "connect")
        def _enable_sqlite_fks(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return _engine


def init_schema() -> None:
    """For tests only — production uses Alembic."""
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
