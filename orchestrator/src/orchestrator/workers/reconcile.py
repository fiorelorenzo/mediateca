# orchestrator/src/orchestrator/workers/reconcile.py
from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from orchestrator.config import get_settings
from orchestrator.db.models import Item, ItemSource, ItemStatus
from orchestrator.db.session import get_engine
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


def reconcile() -> list[tuple[int, str, str]]:
    """Returns the (id, title, reason) of items it just moved to FAILED so the
    caller can fire notifications asynchronously."""
    s = get_settings()
    media = Path(s.media_root)
    newly_failed: list[tuple[int, str, str]] = []
    with Session(get_engine()) as session:
        # 1. Items whose library file vanished → mark FAILED. We check both
        # PROMOTED (the obvious one) and INCOMPLETE — an item can be
        # INCOMPLETE while its file is still in the library (audio policy
        # not yet satisfied), and if that file is removed out of band the
        # DB row becomes a zombie pointing at nothing.
        rows = session.exec(
            select(Item).where(
                Item.status.in_(  # type: ignore[attr-defined]
                    (ItemStatus.PROMOTED, ItemStatus.INCOMPLETE)
                )
            )
        ).all()
        for it in rows:
            if it.library_path and not Path(it.library_path).exists():
                prev_status = it.status
                it.status = ItemStatus.FAILED
                it.status_reason = "library file vanished"
                session.add(it)
                if it.id is not None:
                    newly_failed.append(
                        (it.id, f"{it.title} (was {prev_status.value})", it.status_reason)
                    )
        # 2. Files in media/ not tracked → mark as LEGACY
        if media.exists():
            all_items = session.exec(select(Item)).all()
            tracked = {it.library_path for it in all_items if it.library_path}
            # Defense in depth: if a LEGACY row already points at this path
            # (e.g. a prior reconcile pass already inserted one and the
            # pipeline absorber hasn't run yet), don't insert a second one.
            # The real fix lives in pipeline._absorb_legacy_orphans_for_path;
            # this just keeps us from snowballing duplicates on every boot.
            existing_legacy_paths = {
                it.library_path
                for it in all_items
                if it.status == ItemStatus.LEGACY and it.library_path
            }
            for f in media.rglob("*.mkv"):
                path_str = str(f)
                if (
                    path_str not in tracked
                    and path_str not in existing_legacy_paths
                    and not f.name.startswith(".")
                ):
                    session.add(
                        Item(
                            source=ItemSource.SONARR,  # placeholder — LEGACY items aren't owned
                            source_id=0,
                            title=f.stem,
                            library_path=path_str,
                            status=ItemStatus.LEGACY,
                        )
                    )
        session.commit()
    log.info("reconcile.done")
    return newly_failed
