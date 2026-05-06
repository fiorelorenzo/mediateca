# orchestrator/src/orchestrator/app.py
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from orchestrator.api import health
from orchestrator.config import get_settings
from orchestrator.logging_setup import configure as configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings().log_level)
    yield


app = FastAPI(title="Mediateca Orchestrator", lifespan=lifespan)
app.include_router(health.router)
