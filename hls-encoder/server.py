"""HLS Encoder — FastAPI entrypoint.

Exposes:
  POST   /jobs          — queue a new encode job (202 Accepted)
  GET    /jobs/{id}     — poll job status
  DELETE /jobs/{id}     — cancel a running/queued job
  GET    /healthz       — liveness check

Each job runs in its own `multiprocessing.Process` so cancellation can
SIGTERM the worker — the worker's signal handler turns SIGTERM into
SystemExit, which lets `encode_to_hls`'s finally block tear down ffmpeg
cleanly.
"""
from __future__ import annotations

import asyncio
import multiprocessing as mp
import signal
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from encoder import encode_to_hls

app = FastAPI(title="HLS Encoder")

# job_id -> {status, source, proc, queue, strm_path?, error?}
_jobs: dict[str, dict[str, Any]] = {}


class JobRequest(BaseModel):
    source_path: str


def _worker(source_path: str, q: "mp.Queue[Any]") -> None:
    """Run in a child process. Encode and report result via queue.

    Convert SIGTERM into SystemExit so encode_to_hls's finally block
    runs and tears down ffmpeg before the worker dies.
    """
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        strm = encode_to_hls(Path(source_path))
        q.put({"status": "done", "strm_path": str(strm)})
    except SystemExit:
        pass
    except Exception as exc:  # noqa: BLE001
        q.put({"status": "failed", "error": str(exc)})


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs", status_code=202)
async def create_job(req: JobRequest) -> dict[str, str]:
    job_id = uuid.uuid4().hex
    q: "mp.Queue[Any]" = mp.Queue()
    proc = mp.Process(target=_worker, args=(req.source_path, q), daemon=False)
    proc.start()
    _jobs[job_id] = {
        "status": "running",
        "source": req.source_path,
        "proc": proc,
        "queue": q,
    }

    async def watch() -> None:
        while proc.is_alive():
            await asyncio.sleep(2)
        # Worker exited. If we already marked it cancelled, leave that.
        if _jobs[job_id].get("status") == "cancelled":
            return
        try:
            result = q.get_nowait()
            _jobs[job_id].update(result)
        except Exception:  # noqa: BLE001 — empty queue or other
            _jobs[job_id].update(
                status="failed",
                error=f"worker exited (code {proc.exitcode}) without result",
            )

    asyncio.create_task(watch())
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404)
    # Strip non-serialisable handles before returning.
    return {k: v for k, v in job.items() if k not in ("proc", "queue")}


@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str) -> dict[str, str]:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404)
    proc: mp.Process = job["proc"]
    if proc.is_alive():
        proc.terminate()
        await asyncio.to_thread(proc.join, 10)
        if proc.is_alive():
            # Last resort. Leaves the ffmpeg child orphaned (it runs in a
            # new session, see encoder.py) — accept this rare leak in
            # exchange for guaranteed unblocking on the orchestrator side.
            proc.kill()
            await asyncio.to_thread(proc.join, 5)
    job["status"] = "cancelled"
    return {"status": "cancelled"}
