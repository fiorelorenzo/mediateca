from collections.abc import Iterator
from typing import Any

from sqlmodel import Session, SQLModel, create_engine

from orchestrator.config import get_settings

_engine: Any = None


def get_engine() -> Any:  # type: ignore[no-untyped-def]
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            f"sqlite:///{settings.state_db}",
            connect_args={"check_same_thread": False},
            echo=False,
        )
    return _engine


def init_schema() -> None:
    """For tests only — production uses Alembic."""
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
