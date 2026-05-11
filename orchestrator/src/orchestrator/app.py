# orchestrator/src/orchestrator/app.py
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import Session

from orchestrator.api import custom_formats as custom_formats_api
from orchestrator.api import events as events_api
from orchestrator.api import health, items, metrics, notifications, recyclarr, webhooks
from orchestrator.api import logs as logs_api
from orchestrator.api import services as svcs
from orchestrator.api import settings as settings_api
from orchestrator.config import get_settings
from orchestrator.core.custom_formats import push_custom_formats
from orchestrator.core.jellyfin_defaults import push_user_defaults
from orchestrator.core.policy_seed import seed_settings
from orchestrator.db.session import get_engine
from orchestrator.logging_setup import configure as configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.log_level)
    with Session(get_engine()) as session:
        seed_settings(session, s.policy_seed)
    from orchestrator.core.notify import maybe_notify_failed
    from orchestrator.workers.reconcile import reconcile

    newly_failed = reconcile()
    if newly_failed:
        with Session(get_engine()) as nsess:
            for item_id, title, reason in newly_failed:
                await maybe_notify_failed(nsess, item_id=item_id, title=title, reason=reason)
    try:
        await push_custom_formats(s.sonarr_url, s.sonarr_api_key)
        await push_custom_formats(s.radarr_url, s.radarr_api_key)
    except Exception:  # noqa: BLE001
        # Don't block boot on *arr being temporarily unreachable
        pass
    if s.jellyfin_api_key:
        try:
            await push_user_defaults(s.jellyfin_url, s.jellyfin_api_key)
        except Exception:  # noqa: BLE001
            # Same rationale: Jellyfin may still be starting on a fresh boot.
            pass
    from orchestrator.workers.catch_up import start_scheduler

    scheduler = start_scheduler()
    metrics.start_load_sampler()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        metrics.stop_load_sampler()


app = FastAPI(title="Mediateca Orchestrator", lifespan=lifespan)
app.include_router(health.router)
app.include_router(settings_api.router)
app.include_router(webhooks.router)
app.include_router(items.router)
app.include_router(events_api.router)
app.include_router(recyclarr.router)
app.include_router(metrics.router)
app.include_router(svcs.router)
app.include_router(custom_formats_api.router)
app.include_router(logs_api.router)
app.include_router(notifications.router)
