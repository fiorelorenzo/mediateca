import httpx
import respx

from orchestrator.core.encoder_client import HlsEncoderClient


@respx.mock
async def test_submit_job_returns_id() -> None:
    respx.post("http://hls-encoder:8000/jobs").mock(
        return_value=httpx.Response(202, json={"job_id": "abc-123"})
    )
    c = HlsEncoderClient("http://hls-encoder:8000")
    jid = await c.submit_job(source_path="/data/media/foo.mkv")
    assert jid == "abc-123"


@respx.mock
async def test_get_job_status() -> None:
    respx.get("http://hls-encoder:8000/jobs/abc-123").mock(
        return_value=httpx.Response(200, json={"status": "running", "progress": 0.4})
    )
    c = HlsEncoderClient("http://hls-encoder:8000")
    s = await c.get_job_status("abc-123")
    assert s["status"] == "running"
