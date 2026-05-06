# orchestrator/tests/integration/test_flow_happy.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import respx
from sqlmodel import Session, select

from orchestrator.core.probe import AudioTrack, MediaInfo
from orchestrator.db.models import Item, ItemStatus, WebhookInbox, ItemSource
from orchestrator.db.session import get_engine, init_schema
from orchestrator.workers.webhook_inbox import process_inbox

FIX = Path(__file__).parents[1] / "fixtures"


def setup_module() -> None:
    init_schema()
    from sqlmodel import Session
    from orchestrator.core.policy_seed import seed_settings
    with Session(get_engine()) as s:
        seed_settings(s, None)


@respx.mock
def test_dual_audio_release_promotes_to_media(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    staging = tmp_path / "staging/tv/The Pitt/Season 01"
    staging.mkdir(parents=True)
    src = staging / "The Pitt - S01E01.mkv"
    src.write_bytes(b"\x00")

    payload = json.loads((FIX / "sonarr_on_import.json").read_text())
    payload["episodeFile"]["path"] = str(src)

    respx.get("http://sonarr:8989/api/v3/series/7").mock(
        return_value=httpx.Response(200, json={
            "id": 7, "title": "The Pitt",
            "originalLanguage": {"id": 1, "name": "English"},
        })
    )
    respx.delete("http://sonarr:8989/api/v3/episodefile/100").mock(
        return_value=httpx.Response(200, json={})
    )

    with Session(get_engine()) as s:
        s.add(WebhookInbox(source=ItemSource.SONARR, payload=payload))
        s.commit()

    fake_info = MediaInfo(audio_tracks=[
        AudioTrack(1, "aac", 6, "ita"),
        AudioTrack(2, "aac", 6, "eng"),
    ])
    with patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_info):
        with Session(get_engine()) as s:
            process_inbox(s)

    with Session(get_engine()) as s:
        items = s.exec(select(Item)).all()
    assert any(
        i.status == ItemStatus.PROMOTED and i.audio_present == ["ita", "eng"]
        for i in items
    )
