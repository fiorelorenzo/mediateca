# orchestrator/src/orchestrator/workers/reconcile.py
from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from orchestrator.config import get_settings
from orchestrator.db.models import Item, ItemSource, ItemStatus
from orchestrator.db.session import get_engine
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


def reconcile() -> None:
    s = get_settings()
    media = Path(s.media_root)
    with Session(get_engine()) as session:
        # 1. Items in PROMOTED whose library_path no longer exists → mark FAILED
        rows = session.exec(select(Item).where(Item.status == ItemStatus.PROMOTED)).all()
        for it in rows:
            if it.library_path and not Path(it.library_path).exists():
                it.status = ItemStatus.FAILED
                it.status_reason = "library file vanished"
                session.add(it)
        # 2. Files in media/ not tracked → mark as LEGACY
        if media.exists():
            tracked = {
                it.library_path for it in session.exec(select(Item)).all() if it.library_path
            }
            for f in media.rglob("*.mkv"):
                if str(f) not in tracked and not f.name.startswith("."):
                    session.add(
                        Item(
                            source=ItemSource.SONARR,  # placeholder — LEGACY items aren't owned
                            source_id=0,
                            title=f.stem,
                            library_path=str(f),
                            status=ItemStatus.LEGACY,
                        )
                    )
        session.commit()
    log.info("reconcile.done")
