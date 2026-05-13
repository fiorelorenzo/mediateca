from __future__ import annotations

from typing import Any, cast

import httpx


class HlsEncoderClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base, timeout=self._timeout)

    async def submit_job(self, source_path: str) -> str:
        async with await self._client() as c:
            r = await c.post("/jobs", json={"source_path": source_path})
            r.raise_for_status()
            return cast(str, r.json()["job_id"])

    async def get_job_status(self, job_id: str) -> dict[str, Any]:
        async with await self._client() as c:
            r = await c.get(f"/jobs/{job_id}")
            r.raise_for_status()
            return cast(dict[str, Any], r.json())

    async def cancel_job(self, job_id: str) -> None:
        """Tell the encoder to terminate the job. 404 is treated as
        success — the job is already gone, which is what we want."""
        async with await self._client() as c:
            r = await c.delete(f"/jobs/{job_id}")
            if r.status_code == 404:
                return
            r.raise_for_status()

    async def healthz(self) -> bool:
        try:
            async with await self._client() as c:
                r = await c.get("/healthz", timeout=5.0)
                return r.status_code == 200
        except httpx.HTTPError:
            return False
