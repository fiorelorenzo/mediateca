# orchestrator/src/orchestrator/app.py
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from sqlmodel import Session

from orchestrator.api import health, settings as settings_api, webhooks
from orchestrator.config import get_settings
from orchestrator.core.policy_seed import seed_settings
from orchestrator.db.session import get_engine
from orchestrator.logging_setup import configure as configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.log_level)
    with Session(get_engine()) as session:
        seed_settings(session, s.policy_seed)
    yield


app = FastAPI(title="Mediateca Orchestrator", lifespan=lifespan)
app.include_router(health.router)
app.include_router(settings_api.router)
app.include_router(webhooks.router)
