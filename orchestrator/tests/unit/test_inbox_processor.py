# orchestrator/tests/unit/test_inbox_processor.py
import json
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, select

from orchestrator.core.probe import AudioTrack, MediaInfo
from orchestrator.db.models import Item, ItemSource, WebhookInbox
from orchestrator.db.session import get_engine, init_schema
from orchestrator.workers.webhook_inbox import process_inbox

FIX = Path(__file__).parents[1] / "fixtures"


def setup_module() -> None:
    init_schema()


def test_sonarr_payload_creates_item() -> None:
    with Session(get_engine()) as s:
        s.add(
            WebhookInbox(
                source=ItemSource.SONARR,
                payload=json.loads((FIX / "sonarr_on_import.json").read_text()),
            )
        )
        s.commit()

    fake = MediaInfo(audio_tracks=[AudioTrack(1, "aac", 6, "ita"), AudioTrack(2, "aac", 6, "eng")])
    with patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake):
        with Session(get_engine()) as s:
            n = process_inbox(s)

    assert n >= 1
    with Session(get_engine()) as s:
        items = s.exec(select(Item)).all()
    assert any(i.source == ItemSource.SONARR and i.audio_present == ["ita", "eng"] for i in items)
