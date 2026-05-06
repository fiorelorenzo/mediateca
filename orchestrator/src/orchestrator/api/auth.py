from fastapi import Depends, Header, HTTPException, status

from orchestrator.config import get_settings


def _check(token: str | None, expected: str) -> None:
    if token is None or not token.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if token.removeprefix("Bearer ") != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


def _admin_dep(authorization: str | None = Header(default=None)) -> None:
    _check(authorization, get_settings().admin_api_token)


def _webhook_dep(authorization: str | None = Header(default=None)) -> None:
    _check(authorization, get_settings().webhook_token)


require_admin_token = Depends(_admin_dep)
require_webhook_token = Depends(_webhook_dep)
