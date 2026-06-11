import httpx
from fastapi import APIRouter

from orchestrator.api.auth import require_admin_token
from orchestrator.config import get_settings

router = APIRouter(prefix="/api/services", tags=["services"], dependencies=[require_admin_token])

# Each probe is (path, url_attr_on_settings, key_attr_or_None,
#                accept_any_response_under_500).
# When `accept_any` is True, even 401/403/404 means "the service is up and
# answering HTTP" — useful for services that don't expose an unauthenticated
# liveness endpoint (qBittorrent, Dispatcharr, etc).
PROBES: dict[str, tuple[str, str, str | None, bool]] = {
    "sonarr":      ("/api/v3/system/status", "sonarr_url",   "sonarr_api_key",   False),
    "radarr":      ("/api/v3/system/status", "radarr_url",   "radarr_api_key",   False),
    "prowlarr":    ("/api/v1/system/status", "prowlarr_url", "prowlarr_api_key", False),
    "bazarr":      ("/api/system/status",    "bazarr_url",   "bazarr_api_key",   False),
    "jellyfin":    ("/System/Info/Public",   "jellyfin_url", None,               False),
    "seerr":       ("/api/v1/status",        "seerr_url",    None,               False),
    "qbit":        ("/api/v2/app/version",   "qbit_url",     None,               True),
    "dispatcharr": ("/",                     "dispatcharr_url", None,            True),
}


@router.get("/health")
async def health() -> list[dict[str, object]]:
    s = get_settings()
    out: list[dict[str, object]] = []
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as c:
        for key, (path, url_attr, key_attr, accept_any) in PROBES.items():
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
                if accept_any:
                    healthy = r.status_code < 500
                else:
                    healthy = r.status_code < 400
                out.append({"key": key, "healthy": healthy})
            except Exception:
                out.append({"key": key, "healthy": False})
    return out


_SERVICES = [
    {"key": "sonarr", "name": "Sonarr", "subdomain": "sonarr"},
    {"key": "radarr", "name": "Radarr", "subdomain": "radarr"},
    {"key": "prowlarr", "name": "Prowlarr", "subdomain": "prowlarr"},
    {"key": "bazarr", "name": "Bazarr", "subdomain": "bazarr"},
    {"key": "qbit", "name": "qBittorrent", "subdomain": "qbit"},
    {"key": "jellyfin", "name": "Jellyfin", "subdomain": "streaming"},
    {"key": "seerr", "name": "Seerr", "subdomain": ""},
    {"key": "dispatcharr", "name": "Dispatcharr", "subdomain": "tv"},
    {"key": "encoder", "name": "HLS encoder", "subdomain": "encoder-status"},
]


@router.get("")
def list_services() -> list[dict[str, str]]:
    return _SERVICES
