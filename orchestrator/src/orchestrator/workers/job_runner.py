# orchestrator/src/orchestrator/workers/job_runner.py
from __future__ import annotations

import asyncio
from datetime import datetime

from sqlmodel import Session, select

from orchestrator.config import get_settings
from orchestrator.core.encoder_client import HlsEncoderClient
from orchestrator.core.event_bus import publish
from orchestrator.db.models import History, Item, ItemStatus, Job, JobKind, JobStatus
from orchestrator.db.session import get_engine
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


async def enqueue_encode(item: Item, session: Session) -> int:
    job = Job(item_id=item.id, kind=JobKind.ENCODE, status=JobStatus.QUEUED,  # type: ignore[arg-type]
              payload={"library_path": item.library_path})
    session.add(job); session.commit(); session.refresh(job)
    return job.id  # type: ignore[return-value]


async def run_encode_jobs() -> None:
    s = get_settings()
    client = HlsEncoderClient(s.hls_encoder_url)
    with Session(get_engine()) as session:
        jobs = session.exec(
            select(Job).where(Job.kind == JobKind.ENCODE, Job.status == JobStatus.QUEUED)
        ).all()
        for job in jobs:
            item = session.get(Item, job.item_id)
            if item is None or item.library_path is None:
                job.status = JobStatus.FAILED
                job.error = "item or library_path missing"
                session.add(job); session.commit()
                continue
            try:
                job.status = JobStatus.RUNNING
                job.started_at = datetime.utcnow()
                session.add(job); session.commit()
                external_id = await client.submit_job(item.library_path)
                while True:
                    await asyncio.sleep(10)
                    status = await client.get_job_status(external_id)
                    if status["status"] == "done":
                        item.status = ItemStatus.PROMOTED
                        item.updated_at = datetime.utcnow()
                        session.add(item)
                        session.add(History(item_id=item.id, event="ENCODED"))  # type: ignore[arg-type]
                        publish("item.status_changed",
                                {"item_id": item.id, "status": item.status})
                        job.status = JobStatus.DONE
                        job.ended_at = datetime.utcnow()
                        session.add(job); session.commit()
                        break
                    if status["status"] == "failed":
                        raise RuntimeError(status.get("error", "encoder failure"))
            except Exception as exc:  # noqa: BLE001
                log.exception("encode_job.failed", job_id=job.id)
                job.status = JobStatus.FAILED
                job.error = str(exc)
                job.ended_at = datetime.utcnow()
                item.status = ItemStatus.FAILED  # type: ignore[union-attr]
                item.status_reason = f"encode failed: {exc}"  # type: ignore[union-attr]
                session.add(job); session.add(item); session.commit()
