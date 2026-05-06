# orchestrator/tests/integration/test_flow_incomplete.py
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import respx
from sqlmodel import Session, select

from orchestrator.core.probe import AudioTrack, MediaInfo
from orchestrator.db.models import Item, ItemStatus, ItemSource, WebhookInbox
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
def test_italian_only_release_marked_incomplete_but_promoted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    staging = tmp_path / "staging/movies/Dune (2021)"
    staging.mkdir(parents=True)
    src = staging / "Dune.2021.1080p.WEB-DL.mkv"
    src.write_bytes(b"\x00")
    payload = json.loads((FIX / "radarr_on_import.json").read_text())
    payload["movieFile"]["path"] = str(src)

    respx.get("http://radarr:7878/api/v3/movie/12").mock(
        return_value=httpx.Response(200, json={
            "id": 12, "title": "Dune",
            "originalLanguage": {"id": 1, "name": "English"},
        })
    )

    with Session(get_engine()) as s:
        s.add(WebhookInbox(source=ItemSource.RADARR, payload=payload))
        s.commit()

    fake_info = MediaInfo(audio_tracks=[AudioTrack(1, "ac3", 6, "ita")])
    with patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_info):
        with Session(get_engine()) as s:
            process_inbox(s)

    with Session(get_engine()) as s:
        items = s.exec(select(Item)).all()
    incomplete = [i for i in items if i.source == ItemSource.RADARR]
    assert any(i.status == ItemStatus.INCOMPLETE and "missing" in (i.status_reason or "")
               for i in incomplete)
    assert any(i.library_path is not None for i in incomplete)
