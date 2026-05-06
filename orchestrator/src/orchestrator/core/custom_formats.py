# orchestrator/src/orchestrator/core/custom_formats.py
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from orchestrator.logging_setup import get_logger

log = get_logger(__name__)

STACK_MANAGED_PATH = Path("/config/custom-formats")
SCORES = {"Dual Audio (ITA + Original)": 500, "Italian Only": 50}
TARGET_PROFILE = "Multi-Audio Preferred"


async def push_custom_formats(arr_url: str, api_key: str) -> None:
    """Idempotent: create or update each JSON-defined custom format on the
    *arr instance and ensure its score is set on the Multi-Audio Preferred
    profile."""

    def _load_cf_files() -> list[dict[str, object]]:
        return [json.loads(p.read_text()) for p in STACK_MANAGED_PATH.glob("*.json")]

    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    async with httpx.AsyncClient(base_url=arr_url, headers=headers, timeout=30) as c:
        existing = (await c.get("/api/v3/customformat")).json()
        existing_by_name = {cf["name"]: cf for cf in existing}
        cf_files = await asyncio.to_thread(_load_cf_files)
        for cf in cf_files:
            current = existing_by_name.get(cf["name"])
            if current is None:
                resp = await c.post("/api/v3/customformat", json=cf)
                resp.raise_for_status()
                log.info("custom_format.created", name=cf["name"])
            else:
                cf["id"] = current["id"]
                resp = await c.put(f"/api/v3/customformat/{current['id']}", json=cf)
                resp.raise_for_status()
                log.info("custom_format.updated", name=cf["name"])

        # Apply scores to Multi-Audio Preferred
        profiles = (await c.get("/api/v3/qualityprofile")).json()
        target = next((p for p in profiles if p["name"] == TARGET_PROFILE), None)
        if target is None:
            log.warning("custom_format.no_profile_found", profile=TARGET_PROFILE)
            return
        cfs_after = (await c.get("/api/v3/customformat")).json()
        cfs_by_name = {cf["name"]: cf for cf in cfs_after}
        formats_in_profile = {item["format"]: item for item in target["formatItems"]}
        changed = False
        for cf_name, score in SCORES.items():
            matched_cf = cfs_by_name.get(cf_name)
            if matched_cf is None:
                continue
            entry = formats_in_profile.get(matched_cf["id"])
            if entry is None:
                target["formatItems"].append(
                    {"format": matched_cf["id"], "name": cf_name, "score": score}
                )
                changed = True
            elif entry.get("score") != score:
                entry["score"] = score
                changed = True
        if changed:
            await c.put(f"/api/v3/qualityprofile/{target['id']}", json=target)
            log.info("custom_format.profile_updated", profile=TARGET_PROFILE)
