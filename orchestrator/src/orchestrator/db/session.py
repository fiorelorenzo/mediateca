from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from orchestrator.config import get_settings

_settings = get_settings()
_engine = create_engine(
    f"sqlite:///{_settings.state_db}",
    connect_args={"check_same_thread": False},
    echo=False,
)


def init_schema() -> None:
    """For tests only — production uses Alembic."""
    SQLModel.metadata.create_all(_engine)


def get_session() -> Iterator[Session]:
    with Session(_engine) as session:
        yield session


def get_engine():  # type: ignore[no-untyped-def]
    return _engine
