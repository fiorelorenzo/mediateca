from fastapi import APIRouter, HTTPException

from orchestrator.api.auth import require_admin_token
from orchestrator.core.docker_client import start_oneshot

router = APIRouter(prefix="/api/recyclarr", tags=["recyclarr"], dependencies=[require_admin_token])


@router.post("/sync")
def sync() -> dict[str, str]:
    try:
        start_oneshot("recyclarr")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"failed to start recyclarr: {exc}") from exc
    return {"status": "started"}
