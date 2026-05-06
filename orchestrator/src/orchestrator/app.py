# orchestrator/src/orchestrator/app.py
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from sqlmodel import Session

from orchestrator.api import events as events_api, health, items, metrics, recyclarr, services as svcs, settings as settings_api, webhooks
from orchestrator.config import get_settings
from orchestrator.core.custom_formats import push_custom_formats
from orchestrator.core.policy_seed import seed_settings
from orchestrator.db.session import get_engine
from orchestrator.logging_setup import configure as configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.log_level)
    with Session(get_engine()) as session:
        seed_settings(session, s.policy_seed)
    from orchestrator.workers.reconcile import reconcile
    reconcile()
    try:
        await push_custom_formats(s.sonarr_url, s.sonarr_api_key)
        await push_custom_formats(s.radarr_url, s.radarr_api_key)
    except Exception:  # noqa: BLE001
        # Don't block boot on *arr being temporarily unreachable
        pass
    from orchestrator.workers.catch_up import start_scheduler
    scheduler = start_scheduler()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Mediateca Orchestrator", lifespan=lifespan)
app.include_router(health.router)
app.include_router(settings_api.router)
app.include_router(webhooks.router)
app.include_router(items.router)
app.include_router(events_api.router)
app.include_router(recyclarr.router)
app.include_router(metrics.router)
app.include_router(svcs.router)
