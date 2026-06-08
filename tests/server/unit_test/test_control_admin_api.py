from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bible.api.control import control_router
from bible.api.deps import get_async_task_service
from bible.main import create_app


TASK_RESPONSE: dict[str, Any] = {
    "task_id": "task-1",
    "task_type": "import.skill",
    "status": "queued",
    "result": None,
    "error": None,
    "created_at": "2026-06-03T00:00:00+00:00",
    "updated_at": "2026-06-03T00:00:00+00:00",
}


class FakeTaskService:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {"task-1": TASK_RESPONSE}
        self.cancel_side_effect: Exception | None = None
        self.cancelled: list[str] = []

    def get(self, task_id: str) -> dict[str, Any] | None:
        return self.tasks.get(task_id)

    def cancel(self, task_id: str) -> dict[str, Any]:
        if self.cancel_side_effect is not None:
            raise self.cancel_side_effect
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        self.cancelled.append(task_id)
        return {**task, "status": "cancelled"}


def _client(service: FakeTaskService | None = None) -> tuple[TestClient, FakeTaskService]:
    fake_service = service or FakeTaskService()
    app = FastAPI()
    app.include_router(control_router)
    app.dependency_overrides[get_async_task_service] = lambda: fake_service
    return TestClient(app, raise_server_exceptions=False), fake_service


class TestControlAdminTasksApi:
    def test_get_task_returns_status(self) -> None:
        client, _ = _client()
        resp = client.get("/api/control/admin/tasks/task-1")
        assert resp.status_code == 200
        assert resp.json()["task_id"] == "task-1"
        assert resp.json()["status"] == "queued"

    def test_get_task_not_found(self) -> None:
        client, _ = _client()
        resp = client.get("/api/control/admin/tasks/missing")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "NOT_FOUND"

    def test_delete_task_cancels_task(self) -> None:
        client, service = _client()
        resp = client.delete("/api/control/admin/tasks/task-1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        assert service.cancelled == ["task-1"]

    def test_delete_task_not_found(self) -> None:
        client, _ = _client()
        resp = client.delete("/api/control/admin/tasks/missing")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "NOT_FOUND"

    def test_delete_task_internal_error_is_sanitized(self) -> None:
        service = FakeTaskService()
        service.cancel_side_effect = RuntimeError("broker password leaked")
        client, _ = _client(service)
        resp = client.delete("/api/control/admin/tasks/task-1")
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == "INTERNAL_ERROR"
        assert "broker password" not in resp.text

    def test_create_app_registers_control_router(self) -> None:
        app = create_app()
        paths = {getattr(route, "path", "") for route in app.routes}
        assert "/api/control/admin/tasks/{task_id}" in paths
