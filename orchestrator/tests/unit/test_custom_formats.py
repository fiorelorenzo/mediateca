# orchestrator/tests/unit/test_custom_formats.py
import json
from pathlib import Path

import httpx
import respx

from orchestrator.core.custom_formats import push_custom_formats


@respx.mock
async def test_push_creates_missing_format(tmp_path: Path, monkeypatch) -> None:
    cf_dir = tmp_path / "cf"
    cf_dir.mkdir()
    (cf_dir / "x.json").write_text(json.dumps({"name": "TestFormat", "specifications": []}))
    monkeypatch.setattr("orchestrator.core.custom_formats.STACK_MANAGED_PATH", cf_dir)

    respx.get("http://sonarr:8989/api/v3/customformat").mock(
        return_value=httpx.Response(200, json=[])
    )
    create_route = respx.post("http://sonarr:8989/api/v3/customformat").mock(
        return_value=httpx.Response(201, json={"id": 1, "name": "TestFormat"})
    )
    respx.get("http://sonarr:8989/api/v3/qualityprofile").mock(
        return_value=httpx.Response(200, json=[])
    )
    await push_custom_formats("http://sonarr:8989", "k")
    assert create_route.called
