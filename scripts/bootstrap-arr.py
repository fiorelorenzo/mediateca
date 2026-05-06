#!/usr/bin/env python3
"""One-shot configuration of Sonarr/Radarr after first deploy.

Sets root folder to /data/staging/{tv,movies}, configures the orchestrator
webhook. Idempotent: safe to re-run.

Reads:  /opt/servarr/.env  (or env vars passed in)
"""
from __future__ import annotations

import os
import sys
from typing import Any

import httpx

ENV = os.environ
ORCH_URL = ENV.get("ORCH_URL_PUBLIC", "http://orchestrator:8000")
WEBHOOK_TOKEN = ENV["WEBHOOK_TOKEN"]
SONARR_URL = ENV.get("SONARR_URL", "http://sonarr:8989")
SONARR_KEY = ENV["SONARR_API_KEY"]
RADARR_URL = ENV.get("RADARR_URL", "http://radarr:7878")
RADARR_KEY = ENV["RADARR_API_KEY"]


def _arr(url: str, key: str) -> httpx.Client:
    return httpx.Client(base_url=url, headers={"X-Api-Key": key}, timeout=30)


def ensure_root_folder(client: httpx.Client, path: str) -> None:
    folders = client.get("/api/v3/rootfolder").json()
    if any(f["path"].rstrip("/") == path.rstrip("/") for f in folders):
        return
    client.post("/api/v3/rootfolder", json={"path": path}).raise_for_status()
    print(f"created root folder {path}")


def ensure_webhook(client: httpx.Client, name: str, target_url: str, token: str) -> None:
    notifications = client.get("/api/v3/notification").json()
    existing = next((n for n in notifications if n["name"] == name), None)
    body: dict[str, Any] = {
        "name": name,
        "implementation": "Webhook",
        "configContract": "WebhookSettings",
        "onGrab": False,
        "onDownload": True,
        "onUpgrade": True,
        "onRename": True,
        "onMovieDelete" if "radarr" in target_url else "onSeriesDelete": False,
        "fields": [
            {"name": "url", "value": target_url},
            {"name": "method", "value": 1},  # POST
            {"name": "username", "value": ""},
            {"name": "password", "value": ""},
            {"name": "headers", "value": [{"key": "Authorization",
                                            "value": f"Bearer {token}"}]},
        ],
        "tags": [],
    }
    if existing:
        body["id"] = existing["id"]
        client.put(f"/api/v3/notification/{existing['id']}", json=body).raise_for_status()
        print(f"updated webhook {name}")
    else:
        client.post("/api/v3/notification", json=body).raise_for_status()
        print(f"created webhook {name}")


def main() -> int:
    with _arr(SONARR_URL, SONARR_KEY) as s:
        ensure_root_folder(s, "/data/staging/tv")
        ensure_webhook(s, "Orchestrator", f"{ORCH_URL}/webhook/sonarr", WEBHOOK_TOKEN)
    with _arr(RADARR_URL, RADARR_KEY) as r:
        ensure_root_folder(r, "/data/staging/movies")
        ensure_webhook(r, "Orchestrator", f"{ORCH_URL}/webhook/radarr", WEBHOOK_TOKEN)
    return 0


if __name__ == "__main__":
    sys.exit(main())
