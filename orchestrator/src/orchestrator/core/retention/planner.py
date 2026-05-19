from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from orchestrator.core.retention._time import as_utc
from orchestrator.core.retention.models import (
    KeepUntil,
    PendingDeletion,
    RetentionState,
    SeriesEngagement,
    UserWatch,
)
from orchestrator.core.retention.settings import RetentionSettings
from orchestrator.db.models import Item, ItemSource, ItemStatus, Job, JobKind, JobStatus
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


_BLOCKED_STATUSES = {ItemStatus.FAILED, ItemStatus.FROZEN_AS_IS, ItemStatus.POLICY_OVERRIDDEN}


@dataclass
class PlannerSummary:
    items_evaluated: int = 0
    eligible: int = 0
    promoted_to_pending: int = 0
    protected_pin_temp: int = 0
    protected_favorite: int = 0
    protected_bait: int = 0
    protected_lookahead: int = 0
    pending_delete: int = 0
    keep: int = 0


def _has_inflight_encode(session: Session, item_id: int) -> bool:
    rows = session.exec(
        select(Job).where(
            Job.item_id == item_id,
            Job.kind == JobKind.ENCODE,
            Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),  # type: ignore[attr-defined]
        )
    ).all()
    return bool(rows)


def _active_users_for_series(
    session: Session,
    series_id: int,
    now: datetime,
    window_days: int,
) -> dict[str, SeriesEngagement]:
    cutoff = now - timedelta(days=window_days)
    rows = session.exec(
        select(SeriesEngagement).where(
            SeriesEngagement.series_source_id == series_id,
            SeriesEngagement.last_activity_at >= cutoff,
        )
    ).all()
    return {r.jellyfin_user_id: r for r in rows}


def _is_after(season_a: int, ep_a: int, season_b: int, ep_b: int) -> bool:
    """Is (a) strictly after (b) in chronological-season order?"""
    return (season_a, ep_a) > (season_b, ep_b)


def _next_n_after(
    series_episodes: list[tuple[int, int]],
    last_season: int,
    last_ep: int,
    n: int,
) -> list[tuple[int, int]]:
    later = sorted([se for se in series_episodes if _is_after(*se, last_season, last_ep)])
    return later[:n]


def _classify_episode(
    item: Item,
    session: Session,
    settings: RetentionSettings,
    now: datetime,
    series_episodes: list[tuple[int, int]],
) -> tuple[str, str | None]:
    if item.status != ItemStatus.PROMOTED or item.status in _BLOCKED_STATUSES:
        return "keep", "no_eligibility_yet"
    assert item.id is not None
    if _has_inflight_encode(session, item.id):
        return "keep", "no_eligibility_yet:inflight_encode"

    # 2. Pin temp
    ku = session.get(KeepUntil, item.id)
    if ku and as_utc(ku.until) > now:
        return "protected_pin_temp", None

    # 3. Favorite — respect Jellyfin favorites if enabled
    if settings.retention_respect_jellyfin_favorites and item.jellyfin_item_id:
        favs = session.exec(
            select(UserWatch).where(
                UserWatch.jellyfin_item_id == item.jellyfin_item_id,
                UserWatch.is_favorite == True,  # noqa: E712
            )
        ).all()
        if favs:
            return "protected_favorite", None

    # 4. Bait: season 1 + episode <= bait_first_n
    if (
        item.season == 1
        and item.episode is not None
        and item.episode <= settings.series_bait_first_n
    ):
        return "protected_bait", None

    # Active participants (depending on series)
    sid = item.series_id or item.source_id
    active = _active_users_for_series(session, sid, now, settings.series_engagement_window_days)

    # 5. Lookahead
    if active and item.season is not None and item.episode is not None:
        for _user_id, eng in active.items():
            if eng.last_played_season is None or eng.last_played_episode is None:
                continue
            next_window = _next_n_after(
                series_episodes,
                eng.last_played_season,
                eng.last_played_episode,
                settings.series_lookahead_n,
            )
            if (item.season, item.episode) in next_window:
                return "protected_lookahead", None

    # 6. Eligible — TTL-based, independent of engagement window. An episode is
    # eligible if every user who ever watched it watched it long enough ago that
    # the TTL has elapsed. Note: cold users (outside the engagement window) still
    # count as "watched it"; engagement gating is only meaningful for lookahead.
    if item.jellyfin_item_id:
        watches = list(
            session.exec(
                select(UserWatch).where(UserWatch.jellyfin_item_id == item.jellyfin_item_id)
            ).all()
        )
        if watches and all(w.played for w in watches):
            last = max(
                (as_utc(w.last_played_at) for w in watches if w.last_played_at),
                default=None,
            )
            if last is not None and (now - last).days >= settings.series_ttl_days:
                return "eligible", "ttl_expired"

    return "keep", None


def _classify_movie(
    item: Item,
    session: Session,
    settings: RetentionSettings,
    now: datetime,
) -> tuple[str, str | None]:
    if item.status != ItemStatus.PROMOTED or item.status in _BLOCKED_STATUSES:
        return "keep", "no_eligibility_yet"
    assert item.id is not None
    if _has_inflight_encode(session, item.id):
        return "keep", "no_eligibility_yet:inflight_encode"

    ku = session.get(KeepUntil, item.id)
    if ku and as_utc(ku.until) > now:
        return "protected_pin_temp", None

    if settings.retention_respect_jellyfin_favorites and item.jellyfin_item_id:
        favs = session.exec(
            select(UserWatch).where(
                UserWatch.jellyfin_item_id == item.jellyfin_item_id,
                UserWatch.is_favorite == True,  # noqa: E712
            )
        ).all()
        if favs:
            return "protected_favorite", None

    if item.jellyfin_item_id:
        watches = list(
            session.exec(
                select(UserWatch).where(UserWatch.jellyfin_item_id == item.jellyfin_item_id)
            ).all()
        )
        if watches and all(w.played for w in watches):
            last = max(
                (as_utc(w.last_played_at) for w in watches if w.last_played_at),
                default=None,
            )
            if last is not None and (now - last).days >= settings.movie_ttl_days:
                return "eligible", "ttl_expired"
    return "keep", None


def _score(
    item: Item,
    classification: str,
    last_watched: datetime | None,
    now: datetime,
) -> float:
    """Spec §5 step 3:
        score = age_days * 1.0
              + size_gb * 0.5
              + (10 if not in lookahead else 0)
              + (5 if movie else 0)

    Only eligible items get a non-zero score. The cascade order in
    `_classify_*` guarantees that anything reaching `eligible` is not in
    lookahead, so the `+10` baseline always applies here.
    """
    if classification != "eligible":
        return 0.0
    age_days = (now - last_watched).days if last_watched else 0
    size_gb = (item.size_bytes or 0) / (1024 ** 3)
    movie_bonus = 5.0 if item.source == ItemSource.RADARR else 0.0
    return age_days * 1.0 + size_gb * 0.5 + 10.0 + movie_bonus


def _update_series_engagement(session: Session, now: datetime) -> int:
    """Aggregate ``UserWatch`` rows into ``SeriesEngagement`` per (series, user).

    The planner reads ``SeriesEngagement`` for `protected_lookahead` gating
    and the look-ahead worker reads it to compute next-N targets. Nothing else
    populates it, so without this step both code paths are dead. Returns the
    number of rows upserted.
    """
    items = list(
        session.exec(
            select(Item).where(
                Item.source == ItemSource.SONARR,
                Item.jellyfin_item_id.is_not(None),  # type: ignore[union-attr]
            )
        ).all()
    )
    by_series: dict[int, list[Item]] = {}
    for it in items:
        sid = it.series_id or it.source_id
        by_series.setdefault(sid, []).append(it)

    n_upsert = 0
    for series_id, eps in by_series.items():
        jf_ids = [e.jellyfin_item_id for e in eps if e.jellyfin_item_id]
        if not jf_ids:
            continue
        watches = list(
            session.exec(
                select(UserWatch).where(
                    UserWatch.jellyfin_item_id.in_(jf_ids)  # type: ignore[attr-defined]
                )
            ).all()
        )
        by_user: dict[str, list[UserWatch]] = {}
        for w in watches:
            by_user.setdefault(w.jellyfin_user_id, []).append(w)

        ep_map: dict[str, Item] = {
            e.jellyfin_item_id: e for e in eps if e.jellyfin_item_id
        }
        for user_id, user_watches in by_user.items():
            relevant = [
                w for w in user_watches
                if w.played or (w.position_ticks or 0) > 0
            ]
            if not relevant:
                continue
            sorted_watches = sorted(
                relevant,
                key=lambda w: as_utc(w.last_played_at)
                or datetime.min.replace(tzinfo=UTC),
                reverse=True,
            )
            latest = sorted_watches[0]
            last_activity = as_utc(latest.last_played_at) or now
            last_ep = ep_map.get(latest.jellyfin_item_id)
            last_season = last_ep.season if last_ep else None
            last_episode_num = last_ep.episode if last_ep else None

            existing = session.get(SeriesEngagement, (series_id, user_id))
            if existing is None:
                session.add(
                    SeriesEngagement(
                        series_source_id=series_id,
                        jellyfin_user_id=user_id,
                        last_activity_at=last_activity,
                        last_played_season=last_season,
                        last_played_episode=last_episode_num,
                        updated_at=now,
                    )
                )
            else:
                existing.last_activity_at = last_activity
                existing.last_played_season = last_season
                existing.last_played_episode = last_episode_num
                existing.updated_at = now
                session.add(existing)
            n_upsert += 1
    session.commit()
    return n_upsert


def run_planner_tick(
    engine: Engine,
    settings: RetentionSettings,
    *,
    now: datetime,
) -> PlannerSummary:
    summary = PlannerSummary()
    with Session(engine) as s:
        _update_series_engagement(s, now)
        # Collect series → list[(season, episode)] for lookahead computation
        all_eps = s.exec(select(Item).where(Item.source == ItemSource.SONARR)).all()
        series_ep_map: dict[int, list[tuple[int, int]]] = {}
        for it in all_eps:
            sid = it.series_id or it.source_id
            if it.season is not None and it.episode is not None:
                series_ep_map.setdefault(sid, []).append((it.season, it.episode))

        # Deterministic ordering for reproducible logs (spec §5).
        items = s.exec(
            select(Item).order_by(Item.series_id, Item.season, Item.episode, Item.id)  # type: ignore[arg-type]
        ).all()
        for item in items:
            assert item.id is not None
            summary.items_evaluated += 1
            sid = item.series_id or item.source_id
            if item.source == ItemSource.SONARR:
                cls, reason = _classify_episode(
                    item, s, settings, now, series_ep_map.get(sid, [])
                )
            else:
                cls, reason = _classify_movie(item, s, settings, now)

            rs = s.get(RetentionState, item.id)
            prev_eligible_since = as_utc(rs.eligible_since) if rs else None
            last_watched: datetime | None = None
            if item.jellyfin_item_id:
                lp = s.exec(
                    select(UserWatch.last_played_at).where(
                        UserWatch.jellyfin_item_id == item.jellyfin_item_id
                    )
                ).all()
                last_watched = max((as_utc(d) for d in lp if d), default=None)
            score = _score(item, cls, last_watched, now)

            # Anti-flap promotion gate
            new_classification = cls
            eligible_since = prev_eligible_since
            if cls == "eligible":
                if eligible_since is None:
                    eligible_since = now
                else:
                    # Promote on 2nd consecutive tick (>= anti-flap window from the first)
                    if (
                        (now - eligible_since)
                        >= timedelta(minutes=settings.retention_anti_flap_min_minutes)
                        and not settings.retention_dry_run
                    ):
                        # Promote to pending_delete + emit row
                        existing_pd = s.exec(
                            select(PendingDeletion).where(
                                PendingDeletion.item_id == item.id,
                                PendingDeletion.executed_at.is_(None),  # type: ignore[union-attr]
                                PendingDeletion.cancelled_at.is_(None),  # type: ignore[union-attr]
                            )
                        ).first()
                        if existing_pd is None:
                            grace_days = (
                                settings.movie_grace_days
                                if item.source == ItemSource.RADARR
                                else settings.series_grace_days
                            )
                            s.add(
                                PendingDeletion(
                                    item_id=item.id,
                                    proposed_at=now,
                                    delete_after=now + timedelta(days=grace_days),
                                    reason="ttl_expired",
                                    size_bytes=item.size_bytes,
                                )
                            )
                            new_classification = "pending_delete"
                            summary.promoted_to_pending += 1
            else:
                eligible_since = None

            final_reason = (
                "dry_run" if (cls == "eligible" and settings.retention_dry_run) else reason
            )

            if rs is None:
                rs = RetentionState(
                    item_id=item.id,
                    classification=new_classification,
                    reason=final_reason,
                    eligible_since=eligible_since,
                    score=score,
                    updated_at=now,
                )
            else:
                rs.classification = new_classification
                rs.reason = final_reason
                rs.eligible_since = eligible_since
                rs.score = score
                rs.updated_at = now
            s.add(rs)

            if new_classification == "eligible":
                summary.eligible += 1
            elif new_classification == "protected_bait":
                summary.protected_bait += 1
            elif new_classification == "protected_lookahead":
                summary.protected_lookahead += 1
            elif new_classification == "protected_pin_temp":
                summary.protected_pin_temp += 1
            elif new_classification == "protected_favorite":
                summary.protected_favorite += 1
            elif new_classification == "pending_delete":
                summary.pending_delete += 1
            else:
                summary.keep += 1

        s.commit()
    log.info("retention.planner.tick", **summary.__dict__)
    return summary
