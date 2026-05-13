from sqlmodel import Session, select

from orchestrator.db import models
from orchestrator.db.session import get_engine, init_schema


def test_status_enum_values() -> None:
    assert models.ItemStatus.PENDING == "PENDING"
    assert models.ItemStatus.PROMOTED == "PROMOTED"


def test_item_default_audio_present_empty() -> None:
    item = models.Item(source=models.ItemSource.SONARR, source_id=1, title="X")
    assert item.audio_present == []
    assert item.status == models.ItemStatus.PENDING


def test_deleting_item_cascades_to_history_and_jobs() -> None:
    """Wiping an item must not leave orphan jobs/history rows."""
    init_schema()
    with Session(get_engine()) as s:
        item = models.Item(source=models.ItemSource.SONARR, source_id=999, title="cascade")
        s.add(item)
        s.commit()
        s.refresh(item)
        item_id = item.id
        assert item_id is not None

        s.add(models.History(item_id=item_id, event="X"))
        s.add(models.Job(item_id=item_id, kind=models.JobKind.ENCODE))
        s.commit()

        s.delete(item)
        s.commit()

        assert s.exec(select(models.History).where(models.History.item_id == item_id)).all() == []
        assert s.exec(select(models.Job).where(models.Job.item_id == item_id)).all() == []
