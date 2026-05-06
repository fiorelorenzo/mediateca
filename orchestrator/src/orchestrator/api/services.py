from fastapi import APIRouter

from orchestrator.api.auth import require_admin_token

router = APIRouter(prefix="/api/services", tags=["services"], dependencies=[require_admin_token])

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
