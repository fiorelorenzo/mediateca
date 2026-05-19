import pytest
import respx
from httpx import Response
from sqlmodel import Session, SQLModel, create_engine, select

# Import db.models so the `items` table is registered before
# SQLModel.metadata.create_all — retention FK columns reference it.
import orchestrator.db.models  # noqa: F401
from orchestrator.core.retention.jellyfin_sync import (
    SyncResult,
    sync_all_users,
    sync_user,
)
from orchestrator.core.retention.models import UserWatch


def _engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@respx.mock
async def test_sync_user_writes_user_watch_rows() -> None:
    respx.get("http://jf/Users/u1/Items").mock(
        return_value=Response(200, json={
            "Items": [
                {
                    "Id": "i1",
                    "Type": "Movie",
                    "UserData": {
                        "Played": True,
                        "LastPlayedDate": "2026-05-01T12:00:00.000Z",
                        "PlaybackPositionTicks": 0,
                        "IsFavorite": False,
                    },
                    "ProviderIds": {"Tmdb": "111"},
                },
                {
                    "Id": "i2",
                    "Type": "Episode",
                    "SeriesId": "s1",
                    "ParentIndexNumber": 1,
                    "IndexNumber": 3,
                    "UserData": {
                        "Played": False,
                        "PlaybackPositionTicks": 123,
                        "IsFavorite": True,
                    },
                    "ProviderIds": {"Tvdb": "222"},
                },
            ],
            "TotalRecordCount": 2,
        }),
    )
    eng = _engine()
    res = await sync_user("http://jf", "key", "u1", engine=eng)
    assert isinstance(res, SyncResult)
    assert res.rows_upserted == 2
    with Session(eng) as s:
        rows = s.exec(select(UserWatch)).all()
        assert len(rows) == 2
        by_id = {r.jellyfin_item_id: r for r in rows}
        assert by_id["i1"].played is True
        assert by_id["i1"].last_played_at is not None
        assert by_id["i2"].played is False
        assert by_id["i2"].position_ticks == 123
        assert by_id["i2"].is_favorite is True


@respx.mock
async def test_sync_user_paginates_until_total_reached() -> None:
    respx.get("http://jf/Users/u1/Items", params={"StartIndex": "0"}).mock(
        return_value=Response(200, json={
            "Items": [
                {"Id": f"i{i}", "Type": "Movie", "UserData": {"Played": True}}
                for i in range(2)
            ],
            "TotalRecordCount": 3,
        })
    )
    respx.get("http://jf/Users/u1/Items", params={"StartIndex": "2"}).mock(
        return_value=Response(200, json={
            "Items": [{"Id": "i2", "Type": "Movie", "UserData": {"Played": False}}],
            "TotalRecordCount": 3,
        })
    )
    eng = _engine()
    res = await sync_user("http://jf", "key", "u1", engine=eng, page_size=2)
    assert res.rows_upserted == 3


@respx.mock
async def test_sync_user_handles_auth_error() -> None:
    respx.get("http://jf/Users/u1/Items").mock(return_value=Response(401))
    eng = _engine()
    with pytest.raises(PermissionError):
        await sync_user("http://jf", "key", "u1", engine=eng)


@respx.mock
async def test_sync_all_users_respects_include_exclude() -> None:
    respx.get("http://jf/Users").mock(
        return_value=Response(200, json=[
            {"Id": "u1", "Name": "A"},
            {"Id": "u2", "Name": "B"},
            {"Id": "u3", "Name": "C"},
        ])
    )
    for uid in ["u1", "u3"]:
        respx.get(f"http://jf/Users/{uid}/Items").mock(
            return_value=Response(200, json={"Items": [], "TotalRecordCount": 0})
        )
    eng = _engine()
    summary = await sync_all_users(
        "http://jf", "key", engine=eng,
        include_user_ids=["u1", "u3"], exclude_user_ids=[],
    )
    assert set(summary.users_synced) == {"u1", "u3"}
