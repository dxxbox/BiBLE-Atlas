from __future__ import annotations

import logging
import os
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

from _helpers import BackendLogAssertions, BACKEND_LOG_PATHS


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "bible-atlas.entity-test.yaml"
FALLBACK_CONFIG_PATH = PROJECT_ROOT / "bible-atlas.yaml"
BASE_URL = os.environ.get("BIBLE_API_BASE_URL", "http://127.0.0.1:15555").rstrip("/")
TIMEOUT = float(os.environ.get("BIBLE_API_TIMEOUT", "10"))
LOG_PATH = Path(
    os.environ.get(
        "BIBLE_API_TEST_LOG",
        Path(__file__).resolve().parent / "logs" / "api_requests.log",
    )
)

if DEFAULT_CONFIG_PATH.exists():
    os.environ.setdefault("BIBLE_ATLAS_CONFIG_PATH", str(DEFAULT_CONFIG_PATH))
elif FALLBACK_CONFIG_PATH.exists():
    os.environ.setdefault("BIBLE_ATLAS_CONFIG_PATH", str(FALLBACK_CONFIG_PATH))

_AUTOSTARTED_SERVICES: list[str] = []
_OPENSEARCH_INSTANCE = os.environ.get("BIBLE_ENTITY_TEST_OPENSEARCH_INSTANCE", "bible_entity_test")
_REDIS_INSTANCE = os.environ.get("BIBLE_ENTITY_TEST_REDIS_INSTANCE", "bible_entity_test")
_OPENSEARCH_DASHBOARD_PORT = os.environ.get("BIBLE_ENTITY_TEST_OPENSEARCH_DASHBOARD_PORT", "15602")
_OPENSEARCH_CPU_CORES = os.environ.get("BIBLE_ENTITY_TEST_OPENSEARCH_CPU_CORES", "4")
_OPENSEARCH_MEMORY_GB = os.environ.get("BIBLE_ENTITY_TEST_OPENSEARCH_MEMORY_GB", "4")
_REDIS_MEMORY_MB = os.environ.get("BIBLE_ENTITY_TEST_REDIS_MEMORY_MB", "512")


def _env_flag_enabled(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() not in {
        "0",
        "false",
        "no",
    }


def _autostart_enabled() -> bool:
    return _env_flag_enabled("BIBLE_ENTITY_TEST_AUTOSTART", default="1")


def _keep_services_enabled() -> bool:
    return _env_flag_enabled("BIBLE_ENTITY_TEST_KEEP_SERVICES")


def _api_logger() -> logging.Logger:
    logger = logging.getLogger("server_entity_api_requests")
    if logger.handlers:
        return logger

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("server_entity API test log started base_url=%s", BASE_URL)
    return logger


def _tcp_open(host: str, port: int, timeout_seconds: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _wait_for_tcp(host: str, port: int, *, timeout_seconds: float, label: str) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _tcp_open(host, port):
            return
        time.sleep(1)
    raise RuntimeError(f"{label} did not become reachable at {host}:{port}")


def _opensearch_healthy(config) -> bool:
    host, port = _opensearch_host_port(config)
    url = f"http://{host}:{port}/_cluster/health"
    username = config.database.opensearch.username or None
    password = config.database.opensearch.password or None
    auth = (username, password) if username and password else None
    try:
        response = httpx.get(url, auth=auth, timeout=2.0, trust_env=False)
        if response.status_code != 200:
            return False
        payload = response.json()
        return payload.get("status") in {"green", "yellow"}
    except (httpx.HTTPError, ValueError):
        return False


def _wait_for_opensearch_health(config, *, timeout_seconds: float = 180.0) -> None:
    host, port = _opensearch_host_port(config)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _opensearch_healthy(config):
            return
        time.sleep(2)
    raise RuntimeError(
        f"OpenSearch port is reachable but cluster health did not become ready at {host}:{port}"
    )


def _backend_healthy() -> bool:
    try:
        response = httpx.get(f"{BASE_URL}/health", timeout=2.0, trust_env=False)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def _wait_for_backend(timeout_seconds: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _backend_healthy():
            return
        time.sleep(1)
    raise RuntimeError(f"backend did not become healthy at {BASE_URL}/health")


def _run(command: list[str]) -> None:
    subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
    )


def _load_entity_test_config():
    from bible.config.configure import load_bible_atlas_config_from_file

    config_path = Path(os.environ["BIBLE_ATLAS_CONFIG_PATH"])
    return load_bible_atlas_config_from_file(config_path)


def _opensearch_host_port(config) -> tuple[str, int]:
    host = config.database.opensearch.hosts[0]
    hostname, port = host.rsplit(":", 1)
    return hostname, int(port)


def _redis_host_port(config) -> tuple[str, int]:
    parsed = urlparse(config.celery.broker_url)
    return parsed.hostname or "localhost", parsed.port or 6379


def _backend_port() -> int:
    parsed = urlparse(BASE_URL)
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def _ensure_opensearch(config) -> bool:
    host, port = _opensearch_host_port(config)
    if _opensearch_healthy(config):
        return False

    script = PROJECT_ROOT / "scripts" / "opensearch_deploy" / "deploy.sh"
    instance_dir = script.parent / "opensearch" / _OPENSEARCH_INSTANCE
    if not instance_dir.exists():
        _run(
            [
                "bash",
                str(script),
                "create",
                _OPENSEARCH_INSTANCE,
                str(port),
                _OPENSEARCH_DASHBOARD_PORT,
                _OPENSEARCH_CPU_CORES,
                _OPENSEARCH_MEMORY_GB,
            ]
        )
    started = False
    if not _tcp_open(host, port):
        _run(["bash", str(script), "start", _OPENSEARCH_INSTANCE])
        _wait_for_tcp(host, port, timeout_seconds=180, label="OpenSearch")
        started = True
    _wait_for_opensearch_health(config)
    return started


def _ensure_redis(config) -> bool:
    host, port = _redis_host_port(config)
    if _tcp_open(host, port):
        return False

    script = PROJECT_ROOT / "scripts" / "redis_celery_deploy" / "deploy.sh"
    instance_dir = script.parent / "redis" / _REDIS_INSTANCE
    if not instance_dir.exists():
        _run(
            [
                "bash",
                str(script),
                "redis",
                "create",
                _REDIS_INSTANCE,
                str(port),
                _REDIS_MEMORY_MB,
            ]
        )
    _run(["bash", str(script), "redis", "start", _REDIS_INSTANCE])
    _wait_for_tcp(host, port, timeout_seconds=60, label="Redis")
    return True


def _ensure_backend() -> bool:
    if _backend_healthy():
        return False

    script = PROJECT_ROOT / "scripts" / "server_deploy" / "deploy.sh"
    _run(
        [
            "bash",
            str(script),
            "start",
            "--profile",
            "test",
            "--config",
            os.environ["BIBLE_ATLAS_CONFIG_PATH"],
            "--host",
            "127.0.0.1",
            "--port",
            str(_backend_port()),
            "--concurrency",
            "1",
            "--loglevel",
            "info",
        ]
    )
    _wait_for_backend()
    return True


def pytest_sessionstart(session: pytest.Session) -> None:
    del session
    if not _autostart_enabled():
        return

    config = _load_entity_test_config()
    if _ensure_opensearch(config):
        _AUTOSTARTED_SERVICES.append("opensearch")
    if _ensure_redis(config):
        _AUTOSTARTED_SERVICES.append("redis")
    if _ensure_backend():
        _AUTOSTARTED_SERVICES.append("backend")


def pytest_sessionfinish(
    session: pytest.Session,
    exitstatus: int | pytest.ExitCode,
) -> None:
    del session, exitstatus
    if not _autostart_enabled():
        return

    if _keep_services_enabled():
        _api_logger().info(
            "BIBLE_ENTITY_TEST_KEEP_SERVICES enabled; keeping autostarted services: %s",
            ",".join(_AUTOSTARTED_SERVICES) or "<none>",
        )
        return

    for service in reversed(_AUTOSTARTED_SERVICES):
        if service == "backend":
            _run(
                [
                    "bash",
                    str(PROJECT_ROOT / "scripts" / "server_deploy" / "deploy.sh"),
                    "stop",
                    "--profile",
                    "test",
                ]
            )
        elif service == "redis":
            _run(
                [
                    "bash",
                    str(PROJECT_ROOT / "scripts" / "redis_celery_deploy" / "deploy.sh"),
                    "redis",
                    "stop",
                    _REDIS_INSTANCE,
                ]
            )
        elif service == "opensearch":
            _run(
                [
                    "bash",
                    str(PROJECT_ROOT / "scripts" / "opensearch_deploy" / "deploy.sh"),
                    "stop",
                    _OPENSEARCH_INSTANCE,
                ]
            )

def _header_summary(headers: httpx.Headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() in {"content-type", "content-length"}
    }


def _preview(text: str, limit: int = 1000) -> str:
    text = text.replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated>"


def _log_request(request: httpx.Request) -> None:
    _api_logger().info(
        "REQUEST method=%s url=%s headers=%s",
        request.method,
        request.url,
        _header_summary(request.headers),
    )


def _log_response(response: httpx.Response) -> None:
    response.read()
    _api_logger().info(
        "RESPONSE method=%s url=%s status_code=%d headers=%s body=%s",
        response.request.method,
        response.request.url,
        response.status_code,
        _header_summary(response.headers),
        _preview(response.text),
    )


@pytest.fixture(scope="session")
def client() -> Iterator[httpx.Client]:
    _api_logger()
    with httpx.Client(
        base_url=BASE_URL,
        timeout=TIMEOUT,
        trust_env=False,
        event_hooks={"request": [_log_request], "response": [_log_response]},
    ) as http_client:
        try:
            http_client.get("/health")
        except httpx.HTTPError as exc:
            pytest.skip(f"live backend is not reachable at {BASE_URL}: {exc}")
        yield http_client


@pytest.fixture
def backend_log() -> Iterator[BackendLogAssertions]:
    assertions = BackendLogAssertions(BACKEND_LOG_PATHS)
    yield assertions
    assertions.assert_expected()
