from __future__ import annotations

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
            return r.json()["job_id"]

    async def get_job_status(self, job_id: str) -> dict:
        async with await self._client() as c:
            r = await c.get(f"/jobs/{job_id}")
            r.raise_for_status()
            return r.json()

    async def healthz(self) -> bool:
        try:
            async with await self._client() as c:
                r = await c.get("/healthz", timeout=5.0)
                return r.status_code == 200
        except httpx.HTTPError:
            return False
