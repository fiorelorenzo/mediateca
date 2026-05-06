"""HLS Encoder — FastAPI entrypoint.

Exposes:
  POST /jobs          — queue a new encode job (202 Accepted)
  GET  /jobs/{id}     — poll job status
  GET  /healthz       — liveness check
"""
from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from encoder import encode_to_hls  # (source: Path) -> Path (the .strm path)

app = FastAPI(title="HLS Encoder")

_jobs: dict[str, dict[str, Any]] = {}
_pool = ProcessPoolExecutor(max_workers=1)


class JobRequest(BaseModel):
    source_path: str


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs", status_code=202)
async def create_job(req: JobRequest) -> dict[str, str]:
    job_id = uuid.uuid4().hex
    _jobs[job_id] = {"status": "queued", "source": req.source_path}

    async def run() -> None:
        _jobs[job_id]["status"] = "running"
        try:
            loop = asyncio.get_running_loop()
            strm = await loop.run_in_executor(
                _pool, encode_to_hls, Path(req.source_path)
            )
            _jobs[job_id].update(status="done", strm_path=str(strm))
        except Exception as exc:  # noqa: BLE001
            _jobs[job_id].update(status="failed", error=str(exc))

    asyncio.create_task(run())
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    if job_id not in _jobs:
        raise HTTPException(404)
    return _jobs[job_id]
