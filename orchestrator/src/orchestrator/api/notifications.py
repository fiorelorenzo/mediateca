from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from orchestrator.api.auth import require_admin_token
from orchestrator.core.notify import send_via
from orchestrator.db.session import get_session

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class TestPayload(BaseModel):
    url: str
    title: str | None = None
    body: str | None = None


@router.post("/test", dependencies=[require_admin_token])
async def test_channel(
    payload: TestPayload,
    _: Session = Depends(get_session),
) -> dict[str, object]:
    """Fire a one-shot notification at the given Apprise URL. Lets the admin
    app verify a channel before saving it. Returns {ok, message}."""
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    title = payload.title or "[mediateca] test"
    body = payload.body or f"Test notification from mediateca at {datetime.utcnow().isoformat()}Z"
    ok, message = await send_via(url, title, body, "info")
    return {"ok": ok, "message": message}
