from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bible.test_mode import routes as test_mode_routes
from bible.test_mode.app import create_app
from bible.test_mode.artifact_store import ArtifactStoreError
from bible.test_mode.fixture_store import FixtureLoadError, FixtureStore
from bible.test_mode.resolver import FixtureResolver
from bible.test_mode.schemas import RequestContext


class CapturingLogger:
    def __init__(self) -> None:
        self.info_messages: list[str] = []
        self.warning_messages: list[str] = []
        self.error_messages: list[str] = []

    def info(self, message: str, *args: object) -> None:
        self.info_messages.append(message % args)

    def warning(self, message: str, *args: object) -> None:
        self.warning_messages.append(message % args)

    def error(self, message: str, *args: object) -> None:
        self.error_messages.append(message % args)


def client(fixture_path: str | None = None, *, strict: bool = True) -> TestClient:
    return TestClient(create_app(fixture_path=fixture_path, strict=strict))


def write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def make_meta_json(**overrides: object) -> str:
    data = {
        "memory_id": "mem_test_001",
        "title": "Test Memory",
        "abstract": "Short summary.",
        "overview": "Overview",
        "created_at": "2026-05-22T10:00:00+00:00",
        "updated_at": "2026-05-22T11:00:00+00:00",
    }
    data.update(overrides)
    return json.dumps(data)


def skill_package(has_skill_md: bool = True, skill_name: str = "test-skill") -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        if has_skill_md:
            zf.writestr(f"{skill_name}/SKILL.md", "# Test Skill\n")
        zf.writestr(f"{skill_name}/api.py", "def run():\n    return 'ok'\n")
    return bio.getvalue()


def test_health_uses_test_mode_app_without_production_lifespan():
    response = client().get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "bible-atlas-test-mode"


def test_fixture_resolver_external_overrides_builtin(tmp_path):
    fixture = write_json(
        tmp_path / "fixture.json",
        {
            "version": 1,
            "routes": [
                {
                    "id": "override_memory",
                    "method": "POST",
                    "path": "/api/search/memory",
                    "domain": "MEMORY",
                    "selector": {"tag": "memory"},
                    "response": {
                        "status": 200,
                        "json": {
                            "success": True,
                            "domain": "MEMORY",
                            "tag": "memory",
                            "total": 1,
                            "results": {"memory": [{"id": "external"}]},
                        },
                    },
                }
            ],
        },
    )
    response = client(str(fixture)).post("/api/search/memory", json={"query": "q", "tag": "memory"})
    assert response.status_code == 200
    assert response.json()["results"]["memory"][0]["id"] == "external"


def test_fixture_resolver_external_same_id_replaces_builtin(tmp_path):
    fixture = write_json(
        tmp_path / "override.json",
        {
            "version": 1,
            "routes": [
                {
                    "id": "memory_search_default",
                    "method": "POST",
                    "path": "/api/search/memory",
                    "domain": "MEMORY",
                    "selector": {"tag": "memory", "query": "Fixture Memory"},
                    "response": {
                        "status": 200,
                        "json": {
                            "success": True,
                            "domain": "MEMORY",
                            "tag": "memory",
                            "total": 1,
                            "results": {"memory": [{"id": "external_replacement"}]},
                        },
                    },
                }
            ],
        },
    )

    response = client(str(fixture)).post("/api/search/memory", json={"query": "Fixture Memory", "tag": "memory"})

    assert response.status_code == 200
    assert response.json()["results"]["memory"][0]["id"] == "external_replacement"


def test_fixture_resolver_external_new_id_extends_builtin(tmp_path):
    fixture = write_json(
        tmp_path / "extension.json",
        {
            "version": 1,
            "routes": [
                {
                    "id": "memory_search_project_context",
                    "method": "POST",
                    "path": "/api/search/memory",
                    "domain": "MEMORY",
                    "selector": {"tag": "memory", "query": "project context"},
                    "response": {
                        "status": 200,
                        "json": {
                            "success": True,
                            "domain": "MEMORY",
                            "tag": "memory",
                            "total": 1,
                            "results": {"memory": [{"id": "external_project_context"}]},
                        },
                    },
                }
            ],
        },
    )
    c = client(str(fixture))

    builtin = c.post("/api/search/memory", json={"query": "Fixture Memory", "tag": "memory"})
    external = c.post("/api/search/memory", json={"query": "project context", "tag": "memory"})

    assert builtin.status_code == 200
    assert builtin.json()["results"]["memory"][0]["id"] == "memory_fixture_001"
    assert external.status_code == 200
    assert external.json()["results"]["memory"][0]["id"] == "external_project_context"


def test_fixture_store_loads_directory_and_rejects_external_duplicate_ids(tmp_path):
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    write_json(
        fixture_dir / "01-search.json",
        {
            "version": 1,
            "routes": [
                {
                    "id": "memory_search_directory",
                    "method": "POST",
                    "path": "/api/search/memory",
                    "domain": "MEMORY",
                    "selector": {"tag": "memory", "query": "directory"},
                    "response": {
                        "status": 200,
                        "json": {
                            "success": True,
                            "domain": "MEMORY",
                            "tag": "memory",
                            "total": 1,
                            "results": {"memory": [{"id": "from_directory"}]},
                        },
                    },
                }
            ],
        },
    )
    write_json(fixture_dir / "02-task.json", {"version": 1, "tasks": []})

    response = client(str(fixture_dir)).post("/api/search/memory", json={"query": "directory", "tag": "memory"})

    assert response.status_code == 200
    assert response.json()["results"]["memory"][0]["id"] == "from_directory"

    duplicate_dir = tmp_path / "duplicates"
    duplicate_dir.mkdir()
    write_json(
        duplicate_dir / "01.json",
        {"version": 1, "tasks": [{"task_id": "same", "task_type": "x", "domain": "MEMORY"}]},
    )
    write_json(
        duplicate_dir / "02.json",
        {"version": 1, "tasks": [{"task_id": "same", "task_type": "x", "domain": "MEMORY"}]},
    )

    with pytest.raises(FixtureLoadError, match="duplicate task_id"):
        create_app(fixture_path=str(duplicate_dir))


def test_fixture_resolver_prefers_more_specific_selector():
    store = FixtureStore.load()
    resolver = FixtureResolver(store)
    context = RequestContext(
        method="POST",
        path="/api/search/memory",
        domain="MEMORY",
        body={"query": "Fixture Memory", "tag": "memory"},
    )
    route = resolver.resolve(context)
    assert route is not None
    assert route.id == "memory_search_default"


def test_fixture_schema_rejects_invalid_version(tmp_path):
    fixture = write_json(tmp_path / "bad.json", {"version": 2})
    with pytest.raises(FixtureLoadError):
        FixtureStore.load(fixture_path=str(fixture))


def test_search_routes_validate_and_return_builtin_fixtures():
    c = client()
    response = c.post("/api/search/memory", json={"query": "Fixture Memory", "tag": "memory"})
    assert response.status_code == 200
    assert response.json()["results"]["memory"][0]["id"] == "memory_fixture_001"

    response = c.post("/api/search/memory", json={"query": "8148-A Task 3", "tag": "memory"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["results"]["memory"] == []

    response = c.post("/api/search/skill", json={"query": "skill-standard", "tag": "skill"})
    assert response.status_code == 200
    assert response.json()["results"]["skill"][0]["name"] == "skill-standard"

    response = c.post("/api/search/skill", json={"query": "memory-leak", "tag": "skill"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["results"]["skill"] == []

    response = c.post("/api/search/skill", json={"query": "skill", "tag": "memory"})
    assert response.status_code == 400
    assert response.json()["code"] == "TAG_INVALID"

    response = c.post("/api/search/memory", json={"tag": "memory"})
    assert response.status_code == 400
    assert response.json()["details"]["field"] == "query"


def test_test_mode_logs_client_json_input(monkeypatch):
    logger = CapturingLogger()
    monkeypatch.setattr(test_mode_routes, "logger", logger)

    response = client().post("/api/search/memory", json={"query": "project", "tag": "memory"})

    assert response.status_code == 200
    message = next(message for message in logger.info_messages if message.startswith("Test Mode client input "))
    payload = json.loads(message.removeprefix("Test Mode client input "))
    assert payload["method"] == "POST"
    assert payload["path"] == "/api/search/memory"
    assert payload["domain"] == "MEMORY"
    assert payload["body"] == {"query": "project", "tag": "memory"}


def test_test_mode_logs_client_multipart_input_before_validation(monkeypatch):
    logger = CapturingLogger()
    monkeypatch.setattr(test_mode_routes, "logger", logger)

    response = client().post(
        "/api/import/memory",
        data={"kb_index": "kb_memory_test", "tag": "bad"},
        files={"files": ("meta.json", make_meta_json(), "application/json")},
    )

    assert response.status_code == 400
    message = next(message for message in logger.info_messages if message.startswith("Test Mode client input "))
    payload = json.loads(message.removeprefix("Test Mode client input "))
    assert payload["path"] == "/api/import/memory"
    assert payload["domain"] == "MEMORY"
    assert payload["multipart"]["fields"]["tag"] == "bad"
    assert payload["multipart"]["file_names"] == ["meta.json"]
    assert payload["multipart"]["files"][0]["content_type"] == "application/json"


def test_memory_import_preflight_success_returns_completed():
    response = client().post(
        "/api/import/memory",
        data={"kb_index": "kb_memory_test", "tag": "memory"},
        files={"files": ("meta.json", make_meta_json(), "application/json")},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "completed"
    assert data["result"]["preflight"]["memory_id"] == "mem_test_001"


def test_memory_import_preflight_failure_does_not_create_task():
    response = client().post(
        "/api/import/memory",
        data={"kb_index": "kb_memory_test", "tag": "memory"},
        files={"files": ("note.txt", "not meta", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_ARGUMENT"


def test_skill_import_preflight_validates_skill_package():
    response = client().post(
        "/api/import/skill",
        data={"kb_index": "kb_skill_test", "tag": "skill"},
        files={"files": ("test.skill", skill_package(False), "application/zip")},
    )
    assert response.status_code == 400
    assert "SKILL.md" in response.json()["message"]


def test_skill_import_preflight_rejects_legacy_skills_manifest_only():
    legacy_package = io.BytesIO()
    with zipfile.ZipFile(legacy_package, "w") as zf:
        zf.writestr("legacy-skill/SKILLS.md", "# Legacy Skill\n")
        zf.writestr("legacy-skill/api.py", "def run():\n    return 'ok'\n")

    response = client().post(
        "/api/import/skill",
        data={"kb_index": "kb_skill_test", "tag": "skill"},
        files={"files": ("legacy.skill", legacy_package.getvalue(), "application/zip")},
    )

    assert response.status_code == 400
    assert "SKILL.md" in response.json()["message"]


def test_skill_import_preflight_accepts_standard_skill_package():
    response = client().post(
        "/api/import/skill",
        data={"kb_index": "kb_skill_test", "tag": "skill"},
        files={"files": ("test.skill", skill_package(True, "test-skill"), "application/zip")},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "completed"
    assert data["result"]["preflight"]["skill_package"] == "test.skill"


def test_skill_import_preflight_rejects_nonstandard_skill_package_shapes():
    root_file = io.BytesIO()
    with zipfile.ZipFile(root_file, "w") as zf:
        zf.writestr("SKILL.md", "# Root manifest\n")
    response = client().post(
        "/api/import/skill",
        data={"kb_index": "kb_skill_test", "tag": "skill"},
        files={"files": ("root.skill", root_file.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert "top-level directory" in response.json()["message"]

    multiple_roots = io.BytesIO()
    with zipfile.ZipFile(multiple_roots, "w") as zf:
        zf.writestr("one/SKILL.md", "# One\n")
        zf.writestr("two/SKILL.md", "# Two\n")
    response = client().post(
        "/api/import/skill",
        data={"kb_index": "kb_skill_test", "tag": "skill"},
        files={"files": ("multiple.skill", multiple_roots.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert "exactly one top-level directory" in response.json()["message"]


def test_parser_script_ast_guard_runs_in_preflight():
    response = client().post(
        "/api/import/memory",
        data={"kb_index": "kb_memory_test", "tag": "memory"},
        files=[
            ("files", ("meta.json", make_meta_json(), "application/json")),
            ("parser_script", ("parse.py", "import os\n", "text/x-python")),
        ],
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_ARGUMENT"


def test_download_task_polling_and_artifact_download():
    c = client()
    submit = c.post(
        "/api/download/memory/file",
        json={"tag": "memory", "storage_path": "memory/fixture-memory.json"},
    )
    assert submit.status_code == 202
    assert submit.json()["status"] == "queued"

    first = c.get("/api/control/admin/tasks/download_memory_builtin")
    assert first.status_code == 200
    assert first.json()["status"] == "running"

    second = c.get("/api/control/admin/tasks/download_memory_builtin")
    assert second.json()["status"] == "completed"
    artifact_id = second.json()["result"]["artifact_id"]

    artifact = c.get(f"/api/download/memory/artifact/{artifact_id}")
    assert artifact.status_code == 200
    assert artifact.headers["content-disposition"] == 'attachment; filename="memory-standard.json"'
    assert artifact.content.startswith(b"{")


def test_external_download_fixture_uses_relative_artifact_path(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    artifact_file = artifact_dir / "project-context.json"
    artifact_file.write_bytes(b'{"ok":true,"source":"external"}\n')
    fixture = write_json(
        tmp_path / "download.json",
        {
            "version": 1,
            "routes": [
                {
                    "id": "memory_download_project_context",
                    "method": "POST",
                    "path": "/api/download/memory/file",
                    "domain": "MEMORY",
                    "selector": {"tag": "memory", "storage_path": "memory/project-context.json"},
                    "response": {
                        "status": 202,
                        "json": {
                            "success": True,
                            "task_id": "download_memory_external",
                            "domain": "MEMORY",
                            "tag": "memory",
                            "status": "queued",
                        },
                    },
                }
            ],
            "tasks": [
                {
                    "task_id": "download_memory_external",
                    "task_type": "download.memory.file",
                    "domain": "MEMORY",
                    "tag": "memory",
                    "status": "queued",
                    "final_status": "completed",
                    "result": {
                        "artifact_id": "artifact_memory_external",
                        "artifact_name": "project-context.json",
                        "expires_at": "2099-01-01T00:00:00Z",
                    },
                }
            ],
            "artifacts": [
                {
                    "artifact_id": "artifact_memory_external",
                    "domain": "MEMORY",
                    "content_type": "application/json",
                    "file_name": "project-context.json",
                    "file_path": "artifacts/project-context.json",
                }
            ],
        },
    )
    c = client(str(fixture))

    submit = c.post("/api/download/memory/file", json={"tag": "memory", "storage_path": "memory/project-context.json"})
    first = c.get("/api/control/admin/tasks/download_memory_external")
    second = c.get("/api/control/admin/tasks/download_memory_external")
    artifact = c.get(f"/api/download/memory/artifact/{second.json()['result']['artifact_id']}")

    assert submit.status_code == 202
    assert first.json()["status"] == "running"
    assert second.json()["status"] == "completed"
    assert artifact.status_code == 200
    assert artifact.content == b'{"ok":true,"source":"external"}\n'


def test_external_import_fixture_uses_declared_task_result(tmp_path):
    fixture = write_json(
        tmp_path / "import.json",
        {
            "version": 1,
            "routes": [
                {
                    "id": "memory_import_external",
                    "method": "POST",
                    "path": "/api/import/memory",
                    "domain": "MEMORY",
                    "selector": {
                        "kb_index": "kb_memory_test",
                        "tag": "memory",
                        "file_names": ["meta.json"],
                    },
                    "response": {
                        "status": 202,
                        "json": {
                            "success": True,
                            "task_id": "import_memory_external",
                            "domain": "MEMORY",
                            "tag": "memory",
                            "status": "queued",
                        },
                    },
                }
            ],
            "tasks": [
                {
                    "task_id": "import_memory_external",
                    "task_type": "import.memory",
                    "domain": "MEMORY",
                    "tag": "memory",
                    "status": "queued",
                    "final_status": "completed",
                    "result": {"imported": 2, "skipped": 0, "failed": 0},
                }
            ],
        },
    )
    c = client(str(fixture))

    submit = c.post(
        "/api/import/memory",
        data={"kb_index": "kb_memory_test", "tag": "memory"},
        files={"files": ("meta.json", make_meta_json(), "application/json")},
    )
    first = c.get("/api/control/admin/tasks/import_memory_external")
    second = c.get("/api/control/admin/tasks/import_memory_external")

    assert submit.status_code == 202
    assert submit.json()["status"] == "queued"
    assert first.json()["status"] == "running"
    assert second.json()["status"] == "completed"
    assert second.json()["result"] == {"imported": 2, "skipped": 0, "failed": 0}


def test_skill_download_artifact_is_valid_skill_zip():
    c = client()
    submit = c.post(
        "/api/download/skill/file",
        json={"tag": "skill", "storage_path": "skill-standard"},
    )
    assert submit.status_code == 202
    assert submit.json()["status"] == "queued"

    first = c.get("/api/control/admin/tasks/download_skill_builtin")
    assert first.status_code == 200
    assert first.json()["status"] == "running"

    second = c.get("/api/control/admin/tasks/download_skill_builtin")
    assert second.status_code == 200
    assert second.json()["status"] == "completed"
    artifact_id = second.json()["result"]["artifact_id"]

    artifact = c.get(f"/api/download/skill/artifact/{artifact_id}")
    assert artifact.status_code == 200
    assert artifact.headers["content-disposition"] == 'attachment; filename="skill-standard.skill"'
    with zipfile.ZipFile(io.BytesIO(artifact.content)) as zf:
        assert "skill-standard/SKILL.md" in zf.namelist()
        assert "skill-standard/api.py" in zf.namelist()


def test_skill_download_unknown_skill_returns_not_found():
    c = client()
    response = c.post(
        "/api/download/skill/file",
        json={"tag": "skill", "storage_path": "sct-reviewer"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "SKILL_NOT_FOUND"
    assert "sct-reviewer" in response.json()["message"]

    task = c.app.state.task_store.get("download_skill_builtin", advance=False)
    assert task is not None
    assert task.status == "queued"


def test_invalid_artifact_base64_fails_app_initialization(tmp_path):
    fixture = write_json(
        tmp_path / "invalid_artifact.json",
        {
            "version": 1,
            "artifacts": [
                {
                    "artifact_id": "bad_skill_artifact",
                    "domain": "SKILL",
                    "content_type": "application/zip",
                    "file_name": "bad.skill",
                    "body_base64": "not valid base64",
                }
            ],
        },
    )

    with pytest.raises(ArtifactStoreError, match="artifact body_base64 is invalid: bad_skill_artifact"):
        create_app(fixture_path=str(fixture))


def test_unknown_artifact_and_cancel_task_errors():
    c = client()
    missing = c.get("/api/download/memory/artifact/missing")
    assert missing.status_code == 404
    assert missing.json()["code"] == "DOWNLOAD_ARTIFACT_NOT_FOUND"

    c.post("/api/download/memory/file", json={"tag": "memory", "storage_path": "x"})
    cancel = c.delete("/api/control/admin/tasks/download_memory_builtin")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"


def test_control_fixture_wildcard_requires_explicit_fixture(tmp_path):
    c = client()
    missing = c.get("/api/control/docs/list")
    assert missing.status_code == 404

    fixture = write_json(
        tmp_path / "control.json",
        {
            "version": 1,
            "routes": [
                {
                    "method": "GET",
                    "path": "/api/control/docs/list",
                    "selector": {},
                    "response": {"status": 200, "json": {"success": True, "items": []}},
                }
            ],
        },
    )
    response = client(str(fixture)).get("/api/control/docs/list")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_route_drift_list_core_routes_exist():
    c = client()
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in c.app.routes}
    expected_paths = {
        "/health",
        "/api/import/knowledge-base",
        "/api/import/skill",
        "/api/import/memory",
        "/api/search/knowledge-base",
        "/api/search/skill",
        "/api/search/memory",
        "/api/download/skill/file",
        "/api/download/skill/batch",
        "/api/download/skill/artifact/{artifact_id}",
        "/api/download/memory/file",
        "/api/download/memory/batch",
        "/api/download/memory/artifact/{artifact_id}",
        "/api/control/admin/tasks/{task_id}",
    }
    actual_paths = {path for path, _methods in routes}
    assert expected_paths.issubset(actual_paths)

