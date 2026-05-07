import httpx
from fastapi import APIRouter

from orchestrator.api.auth import require_admin_token
from orchestrator.config import get_settings

router = APIRouter(prefix="/api/services", tags=["services"], dependencies=[require_admin_token])

PROBES = {
    "sonarr": ("/api/v3/system/status", "sonarr_url", "sonarr_api_key"),
    "radarr": ("/api/v3/system/status", "radarr_url", "radarr_api_key"),
    "prowlarr": ("/api/v1/system/status", "prowlarr_url", "prowlarr_api_key"),
    "bazarr": ("/api/system/status", "bazarr_url", "bazarr_api_key"),
    "jellyfin": ("/System/Info/Public", "jellyfin_url", None),
    "seerr": ("/api/v1/status", "seerr_url", None),
}


@router.get("/health")
async def health() -> list[dict[str, object]]:
    s = get_settings()
    out: list[dict[str, object]] = []
    async with httpx.AsyncClient(timeout=5.0) as c:
        for key, (path, url_attr, key_attr) in PROBES.items():
            url = getattr(s, url_attr, None)
            if not url:
                out.append({"key": key, "healthy": False, "reason": "no url"})
                continue
            headers = {}
            if key_attr:
                api_key = getattr(s, key_attr, None)
                if api_key:
                    headers["X-Api-Key"] = api_key
            try:
                r = await c.get(url.rstrip("/") + path, headers=headers)
                out.append({"key": key, "healthy": r.status_code < 400})
            except Exception:
                out.append({"key": key, "healthy": False})
    return out


_SERVICES = [
    {"key": "sonarr", "name": "Sonarr", "subdomain": "sonarr"},
    {"key": "radarr", "name": "Radarr", "subdomain": "radarr"},
    {"key": "prowlarr", "name": "Prowlarr", "subdomain": "prowlarr"},
    {"key": "bazarr", "name": "Bazarr", "subdomain": "bazarr"},
    {"key": "qbit", "name": "qBittorrent", "subdomain": "qbit"},
    {"key": "jellyfin", "name": "Jellyfin", "subdomain": "media"},
    {"key": "seerr", "name": "Seerr", "subdomain": "streaming"},
    {"key": "dispatcharr", "name": "Dispatcharr", "subdomain": "tv"},
    {"key": "headscale", "name": "Headscale", "subdomain": "headscale"},
    {"key": "encoder", "name": "HLS encoder", "subdomain": "encoder-status"},
]


@router.get("")
def list_services() -> list[dict[str, str]]:
    return _SERVICES
