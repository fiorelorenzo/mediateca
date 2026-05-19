# orchestrator/tests/unit/test_items_api.py
import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from orchestrator.api.items import delete_item_files
from orchestrator.app import app
from orchestrator.config import Settings
from orchestrator.core.arr_client import RadarrClient, SonarrClient
from orchestrator.core.encoder_client import HlsEncoderClient
from orchestrator.core.retention.models import (  # noqa: F401  # register tables
    PendingDeletion,
    RetentionState,
    UserWatch,
)
from orchestrator.db.models import History, Item, ItemSource, ItemStatus
from orchestrator.db.session import get_engine, init_schema

H = {"Authorization": "Bearer test-admin-token"}


def setup_module() -> None:
    init_schema()


def _seed_item() -> int:
    with Session(get_engine()) as s:
        i = Item(
            source=ItemSource.SONARR,
            source_id=999,
            title="X",
            status=ItemStatus.INCOMPLETE,
            audio_present=["ita"],
        )
        s.add(i)
        s.commit()
        s.refresh(i)
        return i.id  # type: ignore[return-value]


def test_list_items() -> None:
    _seed_item()
    c = TestClient(app)
    r = c.get("/api/items", headers=H)
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_accept_as_is_transition() -> None:
    iid = _seed_item()
    c = TestClient(app)
    r = c.post(f"/api/items/{iid}/accept-as-is", headers=H)
    assert r.status_code == 200
    assert r.json()["status"] == "FROZEN_AS_IS"


def test_override_policy() -> None:
    iid = _seed_item()
    c = TestClient(app)
    r = c.post(
        f"/api/items/{iid}/override-policy",
        headers=H,
        json={"required_audio_langs": ["jpn", "eng"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["audio_required"] == ["jpn", "eng"]
    assert body["status"] == "POLICY_OVERRIDDEN"


# ── delete_item_files: *arr id semantics ──────────────────────────────────
# Regression for two Critical bugs introduced when the helper was extracted
# from delete_item: Item.source_id is the parent id (movieId / episodeId),
# NOT the file id. The helper must resolve the *FileId via *arr before
# calling DELETE /moviefile or /episodefile.


@respx.mock
async def test_delete_item_files_radarr_resolves_movie_file_id() -> None:
    init_schema()
    with Session(get_engine()) as s:
        it = Item(
            source=ItemSource.RADARR,
            source_id=42,  # movieId
            title="M",
            status=ItemStatus.PROMOTED,
        )
        s.add(it)
        s.commit()
        s.refresh(it)
        item_id = it.id

    get_route = respx.get("http://radarr:7878/api/v3/movie/42").mock(
        return_value=httpx.Response(
            200, json={"id": 42, "title": "M", "movieFile": {"id": 777}}
        )
    )
    delete_route = respx.delete("http://radarr:7878/api/v3/moviefile/777").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    settings = Settings(
        admin_api_token="t",
        webhook_token="w",
        sonarr_api_key="sk",
        radarr_api_key="rk",
    )
    encoder = HlsEncoderClient(settings.hls_encoder_url)
    radarr = RadarrClient(settings.radarr_url, settings.radarr_api_key)
    with Session(get_engine()) as s:
        item = s.get(Item, item_id)
        assert item is not None
        result = await delete_item_files(
            s, item, settings=settings, encoder=encoder, radarr=radarr
        )

    assert get_route.called, "must GET /movie/{id} to resolve movieFile.id"
    assert delete_route.called, "must DELETE /moviefile/{movieFileId}"
    assert result.get("radarr_file_deleted") is True


@respx.mock
async def test_delete_item_files_radarr_no_movie_file_skips_delete() -> None:
    init_schema()
    with Session(get_engine()) as s:
        it = Item(
            source=ItemSource.RADARR,
            source_id=43,
            title="N",
            status=ItemStatus.PROMOTED,
        )
        s.add(it)
        s.commit()
        s.refresh(it)
        item_id = it.id

    respx.get("http://radarr:7878/api/v3/movie/43").mock(
        return_value=httpx.Response(200, json={"id": 43, "title": "N"})
    )
    # No DELETE route mocked — calling it would error.

    settings = Settings(
        admin_api_token="t",
        webhook_token="w",
        sonarr_api_key="sk",
        radarr_api_key="rk",
    )
    encoder = HlsEncoderClient(settings.hls_encoder_url)
    radarr = RadarrClient(settings.radarr_url, settings.radarr_api_key)
    with Session(get_engine()) as s:
        item = s.get(Item, item_id)
        assert item is not None
        result = await delete_item_files(
            s, item, settings=settings, encoder=encoder, radarr=radarr
        )

    assert result.get("radarr_file_skipped") == "no movieFile.id"
    assert "radarr_file_deleted" not in result


@respx.mock
async def test_delete_item_files_sonarr_resolves_episode_file_id() -> None:
    init_schema()
    with Session(get_engine()) as s:
        it = Item(
            source=ItemSource.SONARR,
            source_id=555,  # episodeId
            series_id=12,
            title="S - S01E01",
            status=ItemStatus.PROMOTED,
        )
        s.add(it)
        s.commit()
        s.refresh(it)
        item_id = it.id

    monitor_route = respx.put("http://sonarr:8989/api/v3/episode/monitor").mock(
        return_value=httpx.Response(202, json={})
    )
    list_route = respx.get(
        "http://sonarr:8989/api/v3/episode", params={"seriesId": 12}
    ).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 554, "episodeFileId": 8000},
                {"id": 555, "episodeFileId": 9001},
                {"id": 556, "episodeFileId": 8002},
            ],
        )
    )
    delete_route = respx.delete("http://sonarr:8989/api/v3/episodefile/9001").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    settings = Settings(
        admin_api_token="t",
        webhook_token="w",
        sonarr_api_key="sk",
        radarr_api_key="rk",
    )
    encoder = HlsEncoderClient(settings.hls_encoder_url)
    sonarr = SonarrClient(settings.sonarr_url, settings.sonarr_api_key)
    with Session(get_engine()) as s:
        item = s.get(Item, item_id)
        assert item is not None
        result = await delete_item_files(
            s, item, settings=settings, encoder=encoder, sonarr=sonarr
        )

    assert monitor_route.called, "must PUT /episode/monitor to unmonitor first"
    # The unmonitor call must come before the file delete (regrab guard).
    assert monitor_route.calls.last.request.read().find(b'"monitored": false') != -1 or \
        monitor_route.calls.last.request.read().find(b'"monitored":false') != -1
    assert list_route.called, "must GET /episode?seriesId=… to resolve episodeFileId"
    assert delete_route.called, "must DELETE /episodefile/{episodeFileId}"
    assert result.get("sonarr_unmonitored") is True
    assert result.get("sonarr_file_deleted") is True


@respx.mock
async def test_delete_item_files_sonarr_no_episode_file_skips_delete() -> None:
    init_schema()
    with Session(get_engine()) as s:
        it = Item(
            source=ItemSource.SONARR,
            source_id=556,
            series_id=12,
            title="S - S01E02",
            status=ItemStatus.PROMOTED,
        )
        s.add(it)
        s.commit()
        s.refresh(it)
        item_id = it.id

    respx.put("http://sonarr:8989/api/v3/episode/monitor").mock(
        return_value=httpx.Response(202, json={})
    )
    respx.get(
        "http://sonarr:8989/api/v3/episode", params={"seriesId": 12}
    ).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 556, "episodeFileId": 0}],
        )
    )
    # No episodefile DELETE route — would error if called.

    settings = Settings(
        admin_api_token="t",
        webhook_token="w",
        sonarr_api_key="sk",
        radarr_api_key="rk",
    )
    encoder = HlsEncoderClient(settings.hls_encoder_url)
    sonarr = SonarrClient(settings.sonarr_url, settings.sonarr_api_key)
    with Session(get_engine()) as s:
        item = s.get(Item, item_id)
        assert item is not None
        result = await delete_item_files(
            s, item, settings=settings, encoder=encoder, sonarr=sonarr
        )

    assert result.get("sonarr_file_skipped") == "no episodeFileId"
    assert "sonarr_file_deleted" not in result


# ── lifecycle aggregator ──────────────────────────────────────────────────
# Isolated client fixture (mirrors test_retention_api.py): a fresh in-memory
# SQLite engine via StaticPool, swapped into session_mod so every caller
# (including FastAPI's get_session dep) sees the same DB.


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    import orchestrator.db.session as session_mod

    monkeypatch.setattr(session_mod, "_engine", eng, raising=False)
    return TestClient(app)


def test_lifecycle_endpoint_aggregates_history_and_retention(
    client: TestClient,
) -> None:
    from datetime import UTC, datetime, timedelta

    eng = get_engine()
    with Session(eng) as s:
        item = Item(
            source=ItemSource.RADARR,
            source_id=1,
            title="M",
            status=ItemStatus.PROMOTED,
            jellyfin_item_id="jf-1",
        )
        s.add(item)
        s.commit()
        s.refresh(item)
        s.add(
            History(
                item_id=item.id,  # type: ignore[arg-type]
                event="REQUESTED",
                created_at=datetime.now(UTC) - timedelta(days=5),
            )
        )
        s.add(
            History(
                item_id=item.id,  # type: ignore[arg-type]
                event="PROMOTED",
                created_at=datetime.now(UTC) - timedelta(days=4),
            )
        )
        s.add(
            UserWatch(
                jellyfin_user_id="u1",
                jellyfin_item_id="jf-1",
                played=True,
                last_played_at=datetime.now(UTC) - timedelta(days=1),
                synced_at=datetime.now(UTC),
            )
        )
        s.add(
            RetentionState(
                item_id=item.id,  # type: ignore[arg-type]
                classification="eligible",
                reason="ttl_expired",
                updated_at=datetime.now(UTC),
            )
        )
        s.commit()
        iid = item.id

    r = client.get(f"/api/items/{iid}/lifecycle", headers=H)
    assert r.status_code == 200
    body = r.json()
    stage_names = [stg["stage"] for stg in body["stages"]]
    assert "requested" in stage_names
    assert "available" in stage_names
    assert "watched" in stage_names
    assert "eligible" in stage_names
    assert body["item_id"] == iid
    assert body["current"] == "eligible"


def test_lifecycle_endpoint_404_for_unknown_item(client: TestClient) -> None:
    r = client.get("/api/items/999999/lifecycle", headers=H)
    assert r.status_code == 404
