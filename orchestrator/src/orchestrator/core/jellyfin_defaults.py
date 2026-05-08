# orchestrator/src/orchestrator/core/jellyfin_defaults.py
"""Push the stack-wide Jellyfin user defaults — exactly once per account.

Defaults: prefer Italian audio, fall back to the file's Default track
flag (which mkvmerge keeps pointing at the original language since our
merge keeps existing's tracks first), never auto-show subtitles.

We treat an *empty* AudioLanguagePreference (None or '') as the signal
that the user has never touched their preferences — that's the state
Jellyfin gives a freshly-created account. The moment the user picks
*anything* (including "Default" in the UI, which writes through as a
non-null sentinel on the user's first explicit save), we leave them
alone forever. This trades full enforcement for the "don't surprise me"
promise the user explicitly asked for."""

from __future__ import annotations

import httpx

from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


# Authoritative settings. Anything not listed here is left as-is on each user
# (the API requires the full Configuration object on every PUT, so we also
# read the existing value first to avoid clobbering unrelated fields).
DESIRED: dict[str, object] = {
    # Italian preferred when available; if the file has no Italian track,
    # Jellyfin falls back to the track marked Default in the container —
    # which for our merged outputs is the existing release's primary audio
    # (i.e. the original language, since mkvmerge preserves source flags
    # and our merge step keeps the existing file's tracks first).
    "AudioLanguagePreference": "ita",
    # CRITICAL: when True, Jellyfin ignores AudioLanguagePreference. Must be
    # False for the language preference to apply.
    "PlayDefaultAudioTrack": False,
    # No automatic subtitles ever.
    "SubtitleLanguagePreference": "",
    "SubtitleMode": "None",
}


async def push_user_defaults(jellyfin_url: str, api_key: str) -> None:
    headers = {"X-Emby-Token": api_key, "Accept": "application/json"}
    async with httpx.AsyncClient(
        base_url=jellyfin_url.rstrip("/"), headers=headers, timeout=15
    ) as c:
        try:
            r = await c.get("/Users")
            r.raise_for_status()
            users = r.json()
        except httpx.HTTPError as e:
            log.warning("jellyfin_defaults.fetch_users_failed", error=str(e))
            return

        for u in users:
            user_id = u["Id"]
            cfg = dict(u.get("Configuration") or {})
            # First-touch only: skip the moment AudioLanguagePreference holds
            # any non-empty value. It's None on a fresh account; the moment a
            # user opens the audio settings and clicks Save (even if they
            # leave it on "Default") it becomes a non-null string.
            if cfg.get("AudioLanguagePreference"):
                continue
            cfg.update(DESIRED)
            try:
                resp = await c.post(f"/Users/{user_id}/Configuration", json=cfg)
                resp.raise_for_status()
                log.info("jellyfin_defaults.initialised", user=u.get("Name"))
            except httpx.HTTPError as e:
                log.warning(
                    "jellyfin_defaults.apply_failed",
                    user=u.get("Name"),
                    error=str(e),
                )
