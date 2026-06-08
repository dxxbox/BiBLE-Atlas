from __future__ import annotations

from fastapi.testclient import TestClient

from bible.test_mode import app as test_mode_app
from bible.test_mode import server as test_mode_server
from bible.test_mode.app import SERVICE_NAME, create_app
from bible.test_mode.server import main


class CapturingLogger:
    def __init__(self) -> None:
        self.info_messages: list[str] = []
        self.warning_messages: list[str] = []

    def info(self, message: str, *args: object) -> None:
        self.info_messages.append(message % args)

    def warning(self, message: str, *args: object) -> None:
        self.warning_messages.append(message % args)


def test_test_mode_health() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["x-bible-test-mode"] == "true"
    assert response.json() == {
        "status": "ok",
        "service": SERVICE_NAME,
        "mode": "server",
    }


def test_test_mode_app_does_not_use_production_lifespan(monkeypatch) -> None:
    import bible.features

    def fail_build_upload_container(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("production import container must not be initialized")

    monkeypatch.setattr(
        bible.features,
        "build_upload_container",
        fail_build_upload_container,
        raising=False,
    )

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_test_mode_logs_creation_and_health(monkeypatch) -> None:
    logger = CapturingLogger()
    monkeypatch.setattr(test_mode_app, "logger", logger)
    import bible.test_mode.routes as test_mode_routes

    monkeypatch.setattr(test_mode_routes, "logger", logger)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert any("Created Test Mode app" in message for message in logger.info_messages)
    assert any("fixture=<builtin-only>" in message for message in logger.info_messages)
    assert any("Test Mode health check" in message for message in logger.info_messages)


def test_test_mode_unknown_route_uses_flat_error_shape() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/missing")

    assert response.status_code == 404
    assert response.headers["x-bible-test-mode"] == "true"
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "Route not found",
        "details": {"path": "/missing"},
    }


def test_test_mode_logs_unknown_route(monkeypatch) -> None:
    logger = CapturingLogger()
    monkeypatch.setattr(test_mode_app, "logger", logger)

    with TestClient(create_app()) as client:
        response = client.get("/missing")

    assert response.status_code == 404
    assert any(
        "code=NOT_FOUND status_code=404 method=GET path=/missing" in message
        for message in logger.warning_messages
    )


def test_test_mode_server_main_passes_cli_options(monkeypatch, tmp_path) -> None:
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text('{"version": 1}', encoding="utf-8")
    captured = {}
    logger = CapturingLogger()

    def fake_run(app, *, host, port, log_config):  # noqa: ANN001, ANN202
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port
        captured["log_config"] = log_config

    monkeypatch.setattr("bible.test_mode.server.uvicorn.run", fake_run)
    monkeypatch.setattr(test_mode_server, "logger", logger)
    monkeypatch.setattr(
        "sys.argv",
        [
            "bible-test-mode",
            "--addr",
            "0.0.0.0:8001",
            "--fixture",
            str(fixture_path),
            "--strict",
            "false",
        ],
    )

    main()

    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8001
    assert captured["log_config"] is None
    assert captured["app"].state.fixture_path == fixture_path
    assert captured["app"].state.strict is False
    assert any(
        f"Starting Test Mode server host=0.0.0.0 port=8001 fixture={fixture_path} strict=False"
        in message
        for message in logger.info_messages
    )
