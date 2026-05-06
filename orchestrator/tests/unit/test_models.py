from orchestrator.db import models


def test_status_enum_values() -> None:
    assert models.ItemStatus.PENDING == "PENDING"
    assert models.ItemStatus.PROMOTED == "PROMOTED"


def test_item_default_audio_present_empty() -> None:
    item = models.Item(source=models.ItemSource.SONARR, source_id=1, title="X")
    assert item.audio_present == []
    assert item.status == models.ItemStatus.PENDING
