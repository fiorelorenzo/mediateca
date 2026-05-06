# orchestrator/src/orchestrator/api/webhooks.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from orchestrator.api.auth import require_webhook_token
from orchestrator.db.models import ItemSource, WebhookInbox
from orchestrator.db.session import get_session
from orchestrator.logging_setup import get_logger

router = APIRouter(prefix="/webhook", tags=["webhooks"])
log = get_logger(__name__)


@router.post("/sonarr", dependencies=[require_webhook_token])
async def sonarr_webhook(
    payload: dict,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    if payload.get("eventType") not in ("Download", "Rename"):
        return {"status": "ignored"}
    session.add(WebhookInbox(source=ItemSource.SONARR, payload=payload))
    session.commit()
    log.info("webhook.sonarr.received", event_type=payload.get("eventType"))
    return {"status": "buffered"}


@router.post("/radarr", dependencies=[require_webhook_token])
async def radarr_webhook(
    payload: dict,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    if payload.get("eventType") not in ("Download", "Rename"):
        return {"status": "ignored"}
    session.add(WebhookInbox(source=ItemSource.RADARR, payload=payload))
    session.commit()
    log.info("webhook.radarr.received", event_type=payload.get("eventType"))
    return {"status": "buffered"}
