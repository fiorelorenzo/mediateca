# orchestrator/src/orchestrator/api/health.py
from fastapi import APIRouter, Response, status
from sqlmodel import Session, select

from orchestrator.db.session import get_engine

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(response: Response) -> dict[str, str]:
    try:
        with Session(get_engine()) as s:
            s.exec(select(1)).one()
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "db-unreachable"}
    return {"status": "ok"}
