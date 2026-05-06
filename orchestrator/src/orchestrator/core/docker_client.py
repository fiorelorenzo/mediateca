from __future__ import annotations

import docker
from docker.models.containers import Container

_client: docker.DockerClient | None = None


def client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def get_container(name: str) -> Container:
    return client().containers.get(name)


def start_oneshot(name: str) -> None:
    container = get_container(name)
    container.start()


def restart_container(name: str) -> None:
    get_container(name).restart()
