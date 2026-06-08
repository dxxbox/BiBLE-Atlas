"""
Tests for the v4 MEMORY import feature.

Covers design doc section 10 test cases:
1. tag=memory 正常导入 → 202 Accepted
2. tag 错误（非memory）→ 400 TAG_INVALID
3. 上传解析脚本优先链路（upload → dir_discovery → default 三链路）
4. meta.json 缺失时 parse 可正常处理（sandbox runner 实际运行）
5. 绑定首次创建
6. 向量模型本地命中（fake embedding）
7. 不带 vector_model 时跳过向量字段
8. ASTGuard 拒绝危险脚本
9. 成功任务后 staging 目录被清理
10. sweep_expired_task_workspaces 清理超期目录
"""

from __future__ import annotations

import io
import json
import os
import time
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from bible.common.errors import DomainError, ErrorCode
from bible.infrastructure.database.types import BulkWriteResult, IndexBinding
from bible.features import (
    MemoryUploadService,
    StoreMemory,
    ASTGuard,
    SandboxRunner,
    MemoryUploadPayload,
    ParseResult,
    FileStoreResult,
)

# ---------------------------------------------------------------------------
# In-memory database writer stub (replaces old OpenSearchWriter domain stub)
# ---------------------------------------------------------------------------

class _InMemoryWriter:
    """Minimal in-memory writer for tests that assert on stored binding/content data."""

    def __init__(self) -> None:
        self._bindings: dict = {}
        self._content_docs: list = []
        self._last_vector_options: dict[str, Any] | None = None

    def get_binding_by_domain_index(self, domain: str, kb_index: str):
        from bible.infrastructure.database.types import IndexBinding
        doc = self._bindings.get(f"{domain}:{kb_index}")
        if doc is None:
            return None
        if isinstance(doc, IndexBinding):
            return doc
        return IndexBinding(
            domain_type=doc.get("domain_type", domain),
            kb_index=doc.get("kb_index", kb_index),
            tag=doc.get("tag", ""),
            parser_script_source=doc.get("parser_script_source", ""),
            parser_script_sha256=doc.get("parser_script_sha256", ""),
            vector_model=doc.get("vector_model"),
            search_profile_json=doc.get("search_profile_json", {}),
            search_profile_sha256=doc.get("search_profile_sha256", ""),
        )

    def create_index_binding(self, binding_doc: dict) -> dict:
        domain = binding_doc.get("domain_type", "") or binding_doc.get("domain", "")
        kb_index = binding_doc.get("kb_index", "")
        binding = IndexBinding(
            domain_type=domain,
            kb_index=kb_index,
            tag=binding_doc.get("tag", ""),
            parser_script_source=binding_doc.get("parser_script_source", ""),
            parser_script_sha256=binding_doc.get("parser_script_sha256", ""),
            vector_model=binding_doc.get("vector_model"),
            search_profile_json=binding_doc.get("search_profile_json", {}),
            search_profile_sha256=binding_doc.get("search_profile_sha256", ""),
            created_at=binding_doc.get("created_at"),
        )
        self._bindings[f"{domain}:{kb_index}"] = binding
        return binding_doc

    def bulk_upsert_content_docs(
        self,
        index: str,
        docs: list,
        *,
        vector_options: dict[str, Any] | None = None,
    ) -> BulkWriteResult:
        self._last_vector_options = vector_options
        self._content_docs.extend(docs)
        return BulkWriteResult(success_count=len(docs), fail_count=0, errors=[])

    # Stub remaining IDatabaseWriter methods
    def get_binding_by_domain_tag(self, domain, tag): return None
    def deactivate_binding(self, domain, kb_index): return {}
    def upgrade_binding_vector_model(self, domain, kb_index, vector_model): return {}
    def bulk_upsert_file_registry(self, index, records):
        from bible.infrastructure.database.types import BulkWriteResult
        return BulkWriteResult(success_count=len(records))
    def create_async_task(self, task_doc): pass
    def get_async_task(self, task_id): return None
    def find_async_task_by_idempotency(self, task_type, key): return None
    def update_async_task(self, task_id, patch_doc, expected_statuses=None): return True


@contextmanager
def _patch_db_writer(writer=None):
    """Patch DatabaseFactory in store_memory to use the given writer instance.

    If writer is None, a plain MagicMock is used (sufficient when tests don't
    assert on stored data).
    """
    mock_factory = MagicMock()
    mock_factory.get_writer.return_value = writer if writer is not None else MagicMock()
    with patch(
        "bible.features.upload.memory_upload.storage.store_memory.DatabaseFactory",
        return_value=mock_factory,
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_PARSE_RESULT = {
    "chunks": [{"id": "c1", "text": "hello world"}],
    "search_profile": {"type": "bm25"},
    "local_file_storage_plan": None,
}

_MINIMAL_PARSER_SCRIPT = """\
import argparse
import json

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--context", default=None)
    args = parser.parse_args()
    result = {
        "chunks": [{"id": "chunk_1", "text": "test content"}],
        "search_profile": {"type": "bm25"},
        "local_file_storage_plan": None,
    }
    print(json.dumps(result))

if __name__ == "__main__":
    main()
"""

_DANGEROUS_SCRIPT = """\
import os
def parse():
    return {}
"""

_EVAL_SCRIPT = """\
def parse(code):
    return eval(code)
"""


def _make_test_config(tmp_path):
    """Create a minimal BibleAtlasConfig suitable for unit tests."""
    from bible.config.configure import (
        BibleAtlasConfig,
        FileSystemConfig,
        FileSystemLocalConfig,
        ImportMemoryConfig,
    )
    return BibleAtlasConfig(
        file_system=FileSystemConfig(
            backend="local",
            local=FileSystemLocalConfig(root_dir=str(tmp_path / "files")),
        ),
        import_memory=ImportMemoryConfig(
            custom_parsers_dir=str(tmp_path / "custom_parsers"),
            import_work_dir=str(tmp_path / "import_work"),
        ),
    )


def _make_store_memory(tmp_path) -> StoreMemory:
    """Create a StoreMemory instance backed by a real (tmp) config."""
    return StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))


def _make_payload(**kwargs) -> MemoryUploadPayload:
    defaults = {
        "kb_index": "test_kb",
        "tag": "memory",
        "vector_model": None,
        "parser_context": None,
    }
    defaults.update(kwargs)
    return MemoryUploadPayload(**defaults)


# ---------------------------------------------------------------------------
# Fixture: reset module-level singletons
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_globals():
    """Isolate module-level singletons between tests."""
    import importlib as _il; container_mod = _il.import_module('bible.features.upload.container')
    import bible.features.async_task.container as task_container_mod
    import bible.features.async_task.tasks.dispatch_task as dispatch_mod
    import bible.config.configure as config_mod
    from bible.config.configure import BibleAtlasConfig

    if container_mod._workspace_sweeper is not None:
        container_mod._workspace_sweeper.stop()
    container_mod._workspace_sweeper = None
    container_mod._upload_executor = None
    task_container_mod._task_service = None
    task_container_mod._task_repository = None
    task_container_mod._task_dispatcher = None
    dispatch_mod._repository = None
    dispatch_mod._dispatcher = None
    # Pre-seed a default config so code paths that call get_bible_atlas_config()
    # don't fail when no config file is present in the test environment.
    config_mod._config_instance = BibleAtlasConfig()

    yield

    if container_mod._workspace_sweeper is not None:
        container_mod._workspace_sweeper.stop()
    container_mod._workspace_sweeper = None
    container_mod._upload_executor = None
    task_container_mod._task_service = None
    task_container_mod._task_repository = None
    task_container_mod._task_dispatcher = None
    dispatch_mod._repository = None
    dispatch_mod._dispatcher = None
    config_mod._config_instance = None


# ---------------------------------------------------------------------------
# API client fixture with injected test container
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client(tmp_path):
    """
    TestClient wired to a fully-constructed import container backed by tmp_path
    so no config file or real OpenSearch is needed.
    """
    from bible.main import create_app
    from bible.features.async_task.repository import AsyncTaskRepository
    from bible.features.async_task.service import AsyncTaskService
    from bible.features.async_task.dispatcher import AsyncTaskDispatcher
    from bible.features.async_task.tasks.dispatch_task import configure_dispatch
    from bible.features.async_task.celery_app import celery_app
    from bible.features import UploadTaskExecutor
    import bible.features.async_task.container as task_container_mod

    # No real broker in tests — run tasks synchronously inside a daemon thread.
    celery_app.conf.task_always_eager = True

    parsers_dir = str(tmp_path / "parsers")
    os.makedirs(parsers_dir, exist_ok=True)

    store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
    # Replace db_factory with an in-memory stub so tests don't need a real OpenSearch.
    _mock_db_factory = MagicMock()
    _mock_db_factory.get_writer.return_value = _InMemoryWriter()
    store._db_factory = _mock_db_factory
    ast_guard = ASTGuard()
    sandbox_runner = SandboxRunner(timeout_seconds=30)

    memory_svc = MemoryUploadService(
        store_memory=store,
        ast_guard=ast_guard,
        sandbox_runner=sandbox_runner,
        parsers_dir=parsers_dir,
        config=None,
    )
    executor = UploadTaskExecutor(memory_upload_service=memory_svc)
    repo = AsyncTaskRepository()
    dispatcher = AsyncTaskDispatcher()
    dispatcher.register("import.memory", executor)
    configure_dispatch(repository=repo, dispatcher=dispatcher)
    task_service = AsyncTaskService(repository=repo)

    task_container_mod._task_service = task_service
    task_container_mod._task_repository = repo
    task_container_mod._task_dispatcher = dispatcher

    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def api_client_with_parser(tmp_path, api_client):
    """api_client fixture but also writes a valid parser script into parsers_dir."""
    parsers_dir = str(tmp_path / "parsers")
    parser_file = os.path.join(parsers_dir, "parse_memory.py")
    with open(parser_file, "w") as f:
        f.write(_MINIMAL_PARSER_SCRIPT)
    return api_client


# ---------------------------------------------------------------------------
# Simpler client fixture: mock get_task_service
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_task_service():
    svc = MagicMock()
    svc.submit.return_value = {"task_id": "test-task-123", "status": "queued"}
    return svc


@pytest.fixture
def client_with_mock_service(mock_task_service, tmp_path):
    """TestClient where get_task_service is mocked — for pure API routing tests."""
    from bible.main import create_app

    mock_config = _make_test_config(tmp_path)
    with patch("bible.api.upload.memory_upload_api.get_task_service", return_value=mock_task_service):
        with patch("bible.api.upload.memory_upload_api._get_config", return_value=mock_config):
            app = create_app()
            yield TestClient(app)


# ===========================================================================
# TEST CASE 1: tag=memory 正常导入 → 202 Accepted
# ===========================================================================

class TestApiAcceptedOnValidMemoryTag:
    def test_returns_202(self, client_with_mock_service):
        response = client_with_mock_service.post(
            "/api/import/memory",
            data={"kb_index": "my_kb", "tag": "memory"},
            files={"files": ("sample.json", b"{}", "application/json")},
        )
        assert response.status_code == 202

    def test_response_contains_task_id(self, client_with_mock_service):
        response = client_with_mock_service.post(
            "/api/import/memory",
            data={"kb_index": "my_kb", "tag": "memory"},
            files={"files": ("sample.json", b"{}", "application/json")},
        )
        body = response.json()
        assert body["task_id"] == "test-task-123"
        assert body["status"] == "queued"
        assert body["domain"] == "MEMORY"
        assert body["kb_index"] == "my_kb"
        assert body["tag"] == "memory"

    def test_task_service_submit_called_with_correct_type(self, client_with_mock_service, mock_task_service):
        client_with_mock_service.post(
            "/api/import/memory",
            data={"kb_index": "my_kb", "tag": "memory"},
            files={"files": ("f.json", b"{}", "application/json")},
        )
        mock_task_service.submit.assert_called_once()
        call_kwargs = mock_task_service.submit.call_args
        assert call_kwargs.kwargs.get("task_type") == "import.memory" or (
            call_kwargs.args and call_kwargs.args[0] == "import.memory"
        )


# ===========================================================================
# TEST CASE 2: tag 错误 → 400 TAG_INVALID
# ===========================================================================

class TestApiTagValidation:
    def test_wrong_tag_returns_400(self, client_with_mock_service):
        response = client_with_mock_service.post(
            "/api/import/memory",
            data={"kb_index": "my_kb", "tag": "wrong_tag"},
            files={"files": ("f.txt", b"data", "text/plain")},
        )
        assert response.status_code == 400

    def test_wrong_tag_error_code(self, client_with_mock_service):
        response = client_with_mock_service.post(
            "/api/import/memory",
            data={"kb_index": "my_kb", "tag": "pdf"},
            files={"files": ("f.txt", b"data", "text/plain")},
        )
        body = response.json()
        assert body["detail"]["code"] == "TAG_INVALID"

    def test_missing_kb_index_returns_400(self, client_with_mock_service):
        response = client_with_mock_service.post(
            "/api/import/memory",
            data={"kb_index": "   ", "tag": "memory"},
            files={"files": ("f.txt", b"data", "text/plain")},
        )
        assert response.status_code == 400

    def test_invalid_parser_context_json_returns_400(self, client_with_mock_service):
        response = client_with_mock_service.post(
            "/api/import/memory",
            data={"kb_index": "kb1", "tag": "memory", "parser_context": "{not valid json"},
            files={"files": ("f.txt", b"data", "text/plain")},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_ARGUMENT"


# ===========================================================================
# TEST CASE 3: 上传解析脚本优先链路 upload → dir_discovery → default
# ===========================================================================

class TestParserScriptSelectionChain:
    """MemoryUploadService._select_parser_script priority chain."""

    def _make_svc(self, tmp_path, parsers_dir: str):
        store = _make_store_memory(tmp_path)
        return MemoryUploadService(
            store_memory=store,
            ast_guard=ASTGuard(),
            sandbox_runner=SandboxRunner(),
            parsers_dir=parsers_dir,
            config=None,
        )

    def test_upload_uses_provided_path_directly(self, tmp_path):
        """When parser_script_path is set the service returns it without staging."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        svc = self._make_svc(tmp_path, parsers_dir)

        script_file = tmp_path / "session_abc" / "my_parser.py"
        script_file.parent.mkdir(parents=True)
        script_file.write_text(_MINIMAL_PARSER_SCRIPT)

        payload = _make_payload(
            parser_script_path=str(script_file),
            parser_script_filename="my_parser.py",
        )
        selected = svc._select_parser_script(payload, "upload-task-001")

        assert selected == str(script_file)
        assert os.path.isfile(selected)

    def test_upload_preserves_original_filename(self, tmp_path):
        """The path returned reflects the filename saved by the API layer."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        svc = self._make_svc(tmp_path, parsers_dir)

        script_file = tmp_path / "session_fn" / "custom_parser.py"
        script_file.parent.mkdir(parents=True)
        script_file.write_text("# script")

        payload = _make_payload(
            parser_script_path=str(script_file),
            parser_script_filename="custom_parser.py",
        )
        selected = svc._select_parser_script(payload, "task-fn-001")
        assert os.path.basename(selected) == "custom_parser.py"

    def test_upload_takes_priority_over_dir_script(self, tmp_path):
        """Uploaded script is chosen even when parse_memory.py exists in parsers_dir."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        with open(os.path.join(parsers_dir, "parse_memory.py"), "w") as f:
            f.write(_MINIMAL_PARSER_SCRIPT)

        script_file = tmp_path / "session_prio" / "uploaded.py"
        script_file.parent.mkdir(parents=True)
        script_file.write_text(_MINIMAL_PARSER_SCRIPT)

        svc = self._make_svc(tmp_path, parsers_dir)
        payload = _make_payload(
            parser_script_path=str(script_file),
            parser_script_filename="uploaded.py",
        )
        selected = svc._select_parser_script(payload, "task-prio-001")
        assert not selected.startswith(parsers_dir)

    def test_dir_discovery_finds_parse_memory(self, tmp_path):
        """Finds parse_memory.py in parsers_dir when no upload provided."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        script = os.path.join(parsers_dir, "parse_memory.py")
        with open(script, "w") as f:
            f.write(_MINIMAL_PARSER_SCRIPT)

        svc = self._make_svc(tmp_path, parsers_dir)
        payload = _make_payload()
        assert svc._select_parser_script(payload, "task-dir-001") == script

    def test_custom_dir_takes_priority_over_parsers_dir(self, tmp_path):
        """Finds custom parse_memory.py before the pre-registered parser."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        registered_script = os.path.join(parsers_dir, "parse_memory.py")
        with open(registered_script, "w") as f:
            f.write("# registered")
        custom_dir = os.path.join(parsers_dir, "custom")
        os.makedirs(custom_dir)
        custom_script = os.path.join(custom_dir, "parse_memory.py")
        with open(custom_script, "w") as f:
            f.write("# custom")

        svc = self._make_svc(tmp_path, parsers_dir)
        payload = _make_payload()
        assert svc._select_parser_script(payload, "task-custom-001") == custom_script

    def test_fallback_to_parse_default(self, tmp_path):
        """Falls back to parse_default.py when parse_memory.py not present."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        default_script = os.path.join(parsers_dir, "parse_default.py")
        with open(default_script, "w") as f:
            f.write(_MINIMAL_PARSER_SCRIPT)

        svc = self._make_svc(tmp_path, parsers_dir)
        payload = _make_payload()
        assert svc._select_parser_script(payload, "task-fb-001") == default_script

    def test_no_script_raises_domain_error(self, tmp_path):
        """Raises NOT_FOUND if no script found at all."""
        parsers_dir = str(tmp_path / "empty_parsers")
        os.makedirs(parsers_dir)
        svc = self._make_svc(tmp_path, parsers_dir)
        payload = _make_payload()
        with pytest.raises(DomainError) as exc_info:
            svc._select_parser_script(payload, "task-nf-001")
        assert exc_info.value.code == ErrorCode.NOT_FOUND

    def test_concurrent_uploads_do_not_overwrite_each_other(self, tmp_path):
        """Each session gets its own directory; concurrent tasks stay isolated."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        svc = self._make_svc(tmp_path, parsers_dir)

        script1 = tmp_path / "session_c1" / "p.py"
        script1.parent.mkdir(parents=True)
        script1.write_text("# script1")

        script2 = tmp_path / "session_c2" / "p.py"
        script2.parent.mkdir(parents=True)
        script2.write_text("# script2")

        path1 = svc._select_parser_script(
            _make_payload(parser_script_path=str(script1), parser_script_filename="p.py"),
            "task-concurrent-001",
        )
        path2 = svc._select_parser_script(
            _make_payload(parser_script_path=str(script2), parser_script_filename="p.py"),
            "task-concurrent-002",
        )
        assert path1 != path2
        assert open(path1).read() == "# script1"
        assert open(path2).read() == "# script2"

    def test_successful_uploaded_parser_is_persisted_to_custom_dir(self, tmp_path):
        """A user-supplied parser is atomically saved as custom/parse_memory.py after success."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        svc = self._make_svc(tmp_path, parsers_dir)
        mock_store = MagicMock()
        mock_store.build_staged_files_from_paths.return_value = []
        mock_store.build_parse_manifest.return_value = str(tmp_path / "manifest.json")
        mock_store.store.return_value = {
            "chunks_indexed": 1,
            "files_stored": 0,
            "kb_index": "test_kb",
        }
        mock_store.cleanup_task_workspace = MagicMock()
        svc._store_memory = mock_store
        svc._sandbox_runner = MagicMock()
        svc._sandbox_runner.run_parse.return_value = _MINIMAL_PARSE_RESULT
        script = tmp_path / "session" / "uploaded.py"
        script.parent.mkdir(parents=True)
        script.write_text(_MINIMAL_PARSER_SCRIPT)

        svc.execute_task(
            "task-persist-upload",
            _make_payload(
                parser_script_path=str(script),
                parser_script_filename="uploaded.py",
            ),
            [],
        )

        persisted = tmp_path / "parsers" / "custom" / "parse_memory.py"
        assert persisted.read_text() == _MINIMAL_PARSER_SCRIPT
        assert mock_store.store.call_args.kwargs["parser_script_source"] == "parse_memory.py"

    def test_ast_failure_does_not_overwrite_custom_parser(self, tmp_path):
        """A risky uploaded parser fails the task and leaves the existing custom parser unchanged."""
        parsers_dir = str(tmp_path / "parsers")
        custom_dir = tmp_path / "parsers" / "custom"
        custom_dir.mkdir(parents=True)
        persisted = custom_dir / "parse_memory.py"
        persisted.write_text("# existing custom parser")
        svc = self._make_svc(tmp_path, parsers_dir)
        dangerous = tmp_path / "session" / "dangerous.py"
        dangerous.parent.mkdir(parents=True)
        dangerous.write_text(_DANGEROUS_SCRIPT)

        with pytest.raises(DomainError) as exc_info:
            svc.execute_task(
                "task-ast-failure-no-persist",
                _make_payload(
                    parser_script_path=str(dangerous),
                    parser_script_filename="dangerous.py",
                ),
                [],
            )

        assert exc_info.value.details["code"] == "PARSER_SCRIPT_RISK"
        assert persisted.read_text() == "# existing custom parser"


# ===========================================================================
# TEST CASE 3b: stage_parser_script + _sanitize_script_filename
# ===========================================================================

class TestStageParserScript:
    """StoreMemory.stage_parser_script and _sanitize_script_filename."""

    def test_stage_saves_to_task_specific_path(self, tmp_path):
        store = _make_store_memory(tmp_path)
        path = store.stage_parser_script(b"# content", "my_parser.py", "task-stage-001")
        expected_dir = os.path.join(str(tmp_path), "import_work", "task-stage-001", "parser")
        assert path.startswith(expected_dir)
        assert os.path.isfile(path)

    def test_stage_writes_correct_content(self, tmp_path):
        store = _make_store_memory(tmp_path)
        content = b"import json\nprint('ok')"
        path = store.stage_parser_script(content, "parser.py", "task-stage-002")
        assert open(path, "rb").read() == content

    def test_stage_sanitizes_filename(self, tmp_path):
        store = _make_store_memory(tmp_path)
        path = store.stage_parser_script(b"x", "my parser (v2)!.py", "task-stage-003")
        fname = os.path.basename(path)
        assert " " not in fname
        assert "(" not in fname
        assert "!" not in fname
        assert fname.endswith(".py")

    def test_stage_strips_path_traversal(self, tmp_path):
        store = _make_store_memory(tmp_path)
        path = store.stage_parser_script(b"x", "../../etc/passwd.py", "task-stage-004")
        fname = os.path.basename(path)
        assert ".." not in fname
        assert "/" not in fname

    def test_stage_none_filename_falls_back(self, tmp_path):
        store = _make_store_memory(tmp_path)
        path = store.stage_parser_script(b"x", None, "task-stage-005")
        assert os.path.basename(path) == "parse_upload.py"

    def test_sanitize_ensures_py_extension(self, tmp_path):
        store = _make_store_memory(tmp_path)
        path = store.stage_parser_script(b"x", "my_script", "task-stage-006")
        assert os.path.basename(path).endswith(".py")


# ===========================================================================
# TEST CASE 3c: _hydrate_chunks_with_storage_paths
# ===========================================================================

class TestHydrateChunksWithStoragePaths:
    """StoreMemory._hydrate_chunks_with_storage_paths — reads metadata.related_file_refs."""

    def test_hydrates_storage_paths_from_metadata_related_file_refs(self, tmp_path):
        store = _make_store_memory(tmp_path)
        chunks = [
            {
                "doc_id": "c1",
                "metadata": {
                    "related_file_refs": ["ref_a", "ref_b"],
                    "related_storage_paths": [],
                },
            }
        ]
        ref_map = {
            "ref_a": {"storage_path": "/files/MEMORY/kb1/20260522/a.txt", "file_hash": "aa", "size_bytes": 10},
            "ref_b": {"storage_path": "/files/MEMORY/kb1/20260522/b.txt", "file_hash": "bb", "size_bytes": 20},
        }
        result = store._hydrate_chunks_with_storage_paths(chunks, ref_map)
        assert len(result) == 1
        paths = result[0]["metadata"]["related_storage_paths"]
        assert "/files/MEMORY/kb1/20260522/a.txt" in paths
        assert "/files/MEMORY/kb1/20260522/b.txt" in paths

    def test_missing_ref_in_map_is_skipped(self, tmp_path):
        store = _make_store_memory(tmp_path)
        chunks = [{"doc_id": "c1", "metadata": {"related_file_refs": ["ref_missing"], "related_storage_paths": []}}]
        result = store._hydrate_chunks_with_storage_paths(chunks, {})
        # ref not in map → empty paths
        assert result[0]["metadata"]["related_storage_paths"] == []

    def test_empty_ref_list_leaves_chunk_unchanged(self, tmp_path):
        store = _make_store_memory(tmp_path)
        chunks = [{"doc_id": "c1", "metadata": {"related_file_refs": [], "related_storage_paths": []}}]
        result = store._hydrate_chunks_with_storage_paths(chunks, {"ref_a": {"storage_path": "/x"}})
        assert result[0]["metadata"]["related_storage_paths"] == []

    def test_no_metadata_key_does_not_crash(self, tmp_path):
        store = _make_store_memory(tmp_path)
        chunks = [{"doc_id": "c1"}]  # no metadata at all
        result = store._hydrate_chunks_with_storage_paths(chunks, {"r": {"storage_path": "/x"}})
        assert result[0]["doc_id"] == "c1"

    def test_empty_ref_to_store_result_returns_original(self, tmp_path):
        store = _make_store_memory(tmp_path)
        chunks = [{"doc_id": "c1", "metadata": {"related_file_refs": ["r1"], "related_storage_paths": []}}]
        result = store._hydrate_chunks_with_storage_paths(chunks, {})
        assert result is chunks  # unchanged reference

    def test_does_not_look_at_top_level_file_refs(self, tmp_path):
        """Old bug: code read chunk['file_refs'] — ensure that field is now ignored."""
        store = _make_store_memory(tmp_path)
        chunks = [
            {
                "doc_id": "c1",
                "file_refs": ["ref_top"],  # old field — must be ignored
                "metadata": {"related_file_refs": [], "related_storage_paths": []},
            }
        ]
        ref_map = {"ref_top": {"storage_path": "/should-not-appear"}}
        result = store._hydrate_chunks_with_storage_paths(chunks, ref_map)
        assert result[0]["metadata"]["related_storage_paths"] == []


# ===========================================================================
# TEST CASE 4: SandboxRunner 实际运行 parser script
# ===========================================================================

class TestSandboxRunnerRealExecution:
    def test_runs_minimal_parser_and_returns_chunks(self, tmp_path):
        """SandboxRunner actually executes a parser script and parses JSON output."""
        script_path = str(tmp_path / "parse_memory.py")
        with open(script_path, "w") as f:
            f.write(_MINIMAL_PARSER_SCRIPT)

        manifest_path = str(tmp_path / "manifest.json")
        manifest = {"task_id": "t1", "kb_index": "k1", "tag": "memory", "files": []}
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        runner = SandboxRunner(timeout_seconds=30)
        result = runner.run_parse(script_path, manifest_path, parser_context=None)

        assert isinstance(result, dict)
        assert "chunks" in result
        assert isinstance(result["chunks"], list)
        assert len(result["chunks"]) > 0

    def test_parser_receives_context(self, tmp_path):
        """Parser script can receive --context as JSON string."""
        script_content = """\
import argparse
import json
parser = argparse.ArgumentParser()
parser.add_argument("--manifest")
parser.add_argument("--context", default=None)
args = parser.parse_args()
ctx = json.loads(args.context) if args.context else {}
print(json.dumps({"chunks": [{"ctx_key": ctx.get("key", "none")}], "search_profile": {}}))
"""
        script_path = str(tmp_path / "parser.py")
        with open(script_path, "w") as f:
            f.write(script_content)

        manifest_path = str(tmp_path / "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump({}, f)

        runner = SandboxRunner(timeout_seconds=30)
        result = runner.run_parse(script_path, manifest_path, parser_context={"key": "myvalue"})
        assert result["chunks"][0]["ctx_key"] == "myvalue"

    def test_bad_exit_code_raises_domain_error(self, tmp_path):
        """Non-zero exit code from parser script raises DomainError."""
        script_path = str(tmp_path / "failing.py")
        with open(script_path, "w") as f:
            f.write("import sys; sys.exit(1)\n")

        manifest_path = str(tmp_path / "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump({}, f)

        runner = SandboxRunner(timeout_seconds=30)
        with pytest.raises(DomainError) as exc_info:
            runner.run_parse(script_path, manifest_path)
        assert exc_info.value.details["code"] == "PARSER_SCRIPT_RUNTIME_ERROR"

    def test_invalid_json_output_raises_domain_error(self, tmp_path):
        """Parser producing non-JSON output raises DomainError."""
        script_path = str(tmp_path / "bad_output.py")
        with open(script_path, "w") as f:
            f.write('print("this is not json")\n')

        manifest_path = str(tmp_path / "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump({}, f)

        runner = SandboxRunner(timeout_seconds=30)
        with pytest.raises(DomainError) as exc_info:
            runner.run_parse(script_path, manifest_path)
        assert exc_info.value.details["code"] == "PARSER_SCRIPT_RUNTIME_ERROR"


# ===========================================================================
# TEST CASE 5: 绑定首次创建
# ===========================================================================

class TestBindingFirstCreation:
    def test_store_creates_binding_on_first_call(self, tmp_path):
        """store() creates a binding document in the writer on first call."""
        writer = _InMemoryWriter()
        with _patch_db_writer(writer):
            store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
            parse_result = ParseResult(
                chunks=[{"id": "c1", "text": "hello"}],
                search_profile={"type": "bm25"},
                local_file_storage_plan=None,
            )
            store.store(
                kb_index="kb1",
                parse_result=parse_result,
                vector_model=None,
                parser_script_source="parse_memory.py",
                parser_script_sha256="abc123",
            )

        assert "MEMORY:kb1" in writer._bindings
        binding = writer._bindings["MEMORY:kb1"]
        assert binding.kb_index == "kb1"
        assert binding.domain_type == "MEMORY"
        assert binding.parser_script_source == "parse_memory.py"

    def test_store_returns_correct_summary(self, tmp_path):
        """store() returns summary with kb_index, chunks_indexed, files_stored."""
        writer = _InMemoryWriter()
        with _patch_db_writer(writer):
            store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
            parse_result = ParseResult(
                chunks=[{"id": "c1"}, {"id": "c2"}],
                search_profile={"type": "bm25"},
                local_file_storage_plan=None,
            )
            result = store.store(
                kb_index="kb_test",
                parse_result=parse_result,
                vector_model=None,
                parser_script_source="test.py",
                parser_script_sha256="sha",
            )

        assert result["kb_index"] == "kb_test"
        assert result["chunks_indexed"] == 2
        assert result["files_stored"] == 0


# ===========================================================================
# TEST CASE 6: 向量模型本地命中（fake embedding）
# ===========================================================================

class TestVectorEmbeddingLocalHit:
    def test_builtin_profile_declares_vector_source_template(self):
        from bible.features.upload.memory_upload.parsers.memory_parser.search_profile_builder import (
            build_search_profile,
        )

        profile = build_search_profile()
        vector_profile = profile["search_type_profile"]["vector"]
        assert vector_profile["source_template"] == "{title}\n{abstract}\n{overview}"
        assert vector_profile["num_candidates"] == 100

    def test_embed_chunks_adds_content_vector(self, tmp_path):
        """With vector_model set, store adds content_vector to each chunk."""
        fake_vector = [0.1] * 384

        class _FakeModel:
            def encode(self, texts, **kwargs):
                return [fake_vector[:] for _ in texts]

        writer = _InMemoryWriter()
        with _patch_db_writer(writer):
            with patch("bible.infrastructure.vector.vector_tool.VectorTool._get_cached_model", return_value=_FakeModel()):
                store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
                parse_result = ParseResult(
                    chunks=[{"id": "c1", "text": "some text"}],
                    search_profile={"type": "dense", "source_template": "{text}"},
                    local_file_storage_plan=None,
                )
                result = store.store(
                    kb_index="kb_vec",
                    parse_result=parse_result,
                    vector_model="fake-model-384",
                    parser_script_source="test.py",
                    parser_script_sha256="sha",
                )

        assert result["chunks_indexed"] == 1
        assert len(writer._content_docs) == 1
        assert "content_vector" in writer._content_docs[0]
        assert len(writer._content_docs[0]["content_vector"]) == 384

    def test_vector_tool_embed_returns_all_chunks(self, tmp_path):
        """VectorTool.embed_chunks returns one enriched chunk per input chunk."""
        from bible.infrastructure.vector.vector_tool import VectorTool

        fake_vector = [0.1] * 384

        class _FakeModel:
            def encode(self, texts, **kwargs):
                return [fake_vector[:] for _ in texts]

        vt = VectorTool(workspace_dir=str(tmp_path))
        chunks = [{"id": "1", "text": "a"}, {"id": "2", "text": "b"}]
        with patch.object(vt, "_get_cached_model", return_value=_FakeModel()):
            result = vt.embed_chunks(chunks, "any-model", source_template=None)

        assert len(result) == 2
        for chunk in result:
            assert "content_vector" in chunk
            assert len(chunk["content_vector"]) == 384

    def test_source_template_not_persisted_in_binding_profile(self, tmp_path):
        """source_template is import-only and must not make search profiles invalid."""
        captured: dict[str, str | None] = {}

        def _fake_embed_chunks(self, chunks, model_name, source_template=None):
            del self, model_name
            captured["source_template"] = source_template
            return [{**chunk, "content_vector": [0.1, 0.2, 0.3]} for chunk in chunks]

        writer = _InMemoryWriter()
        with _patch_db_writer(writer):
            with patch(
                "bible.features.upload.memory_upload.storage.store_memory.VectorTool.embed_chunks",
                new=_fake_embed_chunks,
            ):
                store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
                parse_result = ParseResult(
                    chunks=[{"id": "c1", "title": "Title", "abstract": "Abstract"}],
                    search_profile={
                        "tag": "memory",
                        "search_type_profile": {
                            "vector": {
                                "enabled": True,
                                "vector_field": "content_vector",
                                "source_template": "{title}\n{abstract}",
                                "num_candidates": 123,
                            }
                        },
                        "response_fields": ["memory_id", "score"],
                    },
                    local_file_storage_plan=None,
                )
                store.store(
                    kb_index="kb_vec_template",
                    parse_result=parse_result,
                    vector_model="fake-model",
                    parser_script_source="test.py",
                    parser_script_sha256="sha",
                )

        binding = writer._bindings["MEMORY:kb_vec_template"]
        stored_profile = binding.search_profile_json
        assert captured["source_template"] == "{title}\n{abstract}"
        assert "source_template" not in stored_profile
        assert "source_template" not in stored_profile["search_type_profile"]["vector"]
        assert stored_profile["search_type_profile"]["vector"]["num_candidates"] == 123
        assert writer._last_vector_options == {"num_candidates": 123}


# ===========================================================================
# TEST CASE 7: 不带 vector_model 时跳过向量字段
# ===========================================================================

class TestNoVectorModelSkipsVectorFields:
    def test_no_vector_model_chunks_have_no_content_vector(self, tmp_path):
        """Without vector_model, chunks stored have no content_vector field."""
        writer = _InMemoryWriter()
        with _patch_db_writer(writer):
            store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
            parse_result = ParseResult(
                chunks=[{"id": "c1", "text": "no vectors here"}],
                search_profile={"type": "bm25"},
                local_file_storage_plan=None,
            )
            store.store(
                kb_index="kb_no_vec",
                parse_result=parse_result,
                vector_model=None,
                parser_script_source="test.py",
                parser_script_sha256="sha",
            )

        assert len(writer._content_docs) == 1
        assert "content_vector" not in writer._content_docs[0]

    def test_vectorize_if_needed_returns_unchanged_chunks_without_model(self, tmp_path):
        """StoreMemory._vectorize_if_needed is a no-op when vector_model is None."""
        store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
        chunks = [{"id": "c1", "text": "plain"}]
        result = store._vectorize_if_needed(chunks, vector_model=None, search_profile={})
        assert result is chunks  # same object, no transformation


# ===========================================================================
# TEST CASE 8: ASTGuard 拒绝危险脚本
# ===========================================================================

class TestASTGuardForbiddenScripts:
    def test_import_os_raises_domain_error(self, tmp_path):
        script_path = str(tmp_path / "dangerous.py")
        with open(script_path, "w") as f:
            f.write(_DANGEROUS_SCRIPT)

        guard = ASTGuard()
        with pytest.raises(DomainError) as exc_info:
            guard.validate(script_path)

        error = exc_info.value
        assert error.code == ErrorCode.INVALID_ARGUMENT
        assert error.details["code"] == "PARSER_SCRIPT_RISK"
        assert any("os" in v for v in error.details["violations"])

    def test_eval_call_raises_domain_error(self, tmp_path):
        script_path = str(tmp_path / "eval_script.py")
        with open(script_path, "w") as f:
            f.write(_EVAL_SCRIPT)

        guard = ASTGuard()
        with pytest.raises(DomainError) as exc_info:
            guard.validate(script_path)

        assert exc_info.value.details["code"] == "PARSER_SCRIPT_RISK"
        assert any("eval" in v for v in exc_info.value.details["violations"])

    def test_subprocess_import_raises_domain_error(self, tmp_path):
        script_path = str(tmp_path / "subproc.py")
        with open(script_path, "w") as f:
            f.write("import subprocess\nsubprocess.run(['ls'])\n")

        guard = ASTGuard()
        with pytest.raises(DomainError):
            guard.validate(script_path)

    def test_from_os_import_raises_domain_error(self, tmp_path):
        script_path = str(tmp_path / "from_os.py")
        with open(script_path, "w") as f:
            f.write("from os import path\n")

        guard = ASTGuard()
        with pytest.raises(DomainError) as exc_info:
            guard.validate(script_path)
        assert "os" in exc_info.value.message

    def test_exec_call_raises_domain_error(self, tmp_path):
        script_path = str(tmp_path / "exec_script.py")
        with open(script_path, "w") as f:
            f.write('exec("print(1)")\n')

        guard = ASTGuard()
        with pytest.raises(DomainError):
            guard.validate(script_path)

    def test_syntax_error_raises_domain_error(self, tmp_path):
        script_path = str(tmp_path / "syntax_err.py")
        with open(script_path, "w") as f:
            f.write("def broken(\n  # no closing paren\n")

        guard = ASTGuard()
        with pytest.raises(DomainError) as exc_info:
            guard.validate(script_path)
        assert exc_info.value.details["code"] == "PARSER_SCRIPT_RISK"

    def test_valid_script_passes_guard(self, tmp_path):
        script_path = str(tmp_path / "safe.py")
        with open(script_path, "w") as f:
            f.write(_MINIMAL_PARSER_SCRIPT)

        guard = ASTGuard()
        # Should not raise
        guard.validate(script_path)


# ===========================================================================
# TEST CASE 9: 成功任务后 staging 目录被清理
# ===========================================================================

class TestStagingCleanupAfterSuccess:
    def test_cleanup_task_workspace_removes_dir(self, tmp_path):
        store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
        task_id = "cleanup-test-001"

        # Create the staging directory
        task_dir = os.path.join(str(tmp_path), "import_work", task_id)
        staged = os.path.join(task_dir, "staged")
        os.makedirs(staged, exist_ok=True)
        test_file = os.path.join(staged, "test.txt")
        with open(test_file, "w") as f:
            f.write("content")

        assert os.path.isdir(task_dir)

        store.cleanup_task_workspace(task_id, keep_failed=False)

        assert not os.path.exists(task_dir)

    def test_cleanup_with_keep_failed_true_preserves_dir(self, tmp_path):
        store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
        task_id = "keep-failed-001"

        task_dir = os.path.join(str(tmp_path), "import_work", task_id)
        os.makedirs(task_dir, exist_ok=True)

        store.cleanup_task_workspace(task_id, keep_failed=True)

        assert os.path.isdir(task_dir)

    def test_stage_upload_creates_files(self, tmp_path):
        store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
        task_id = "stage-test-001"
        files = [
            {"filename": "doc1.txt", "content": b"hello doc1", "content_type": "text/plain"},
            {"filename": "doc2.txt", "content": b"hello doc2", "content_type": "text/plain"},
        ]
        staged = store.stage_upload_files(files, task_id)

        assert len(staged) == 2
        for entry in staged:
            assert os.path.isfile(entry["abs_path"])
            with open(entry["abs_path"], "rb") as f:
                content = f.read()
            assert content in (b"hello doc1", b"hello doc2")

    def test_execute_task_cleans_up_staging_on_success(self, tmp_path):
        """Full execute_task flow cleans up staging dir on success."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        script_path = os.path.join(parsers_dir, "parse_memory.py")
        with open(script_path, "w") as f:
            f.write(_MINIMAL_PARSER_SCRIPT)

        writer = _InMemoryWriter()
        with _patch_db_writer(writer):
            store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
            svc = MemoryUploadService(
                store_memory=store,
                ast_guard=ASTGuard(),
                sandbox_runner=SandboxRunner(timeout_seconds=30),
                parsers_dir=parsers_dir,
                config=None,
            )
            task_id = "exec-cleanup-001"
            payload = _make_payload()
            files = [{"filename": "data.txt", "content": b"test", "content_type": "text/plain"}]

            svc.execute_task(task_id, payload, files)

        task_dir = os.path.join(str(tmp_path), "import_work", task_id)
        assert not os.path.exists(task_dir), "Staging dir should be deleted after success"


# ===========================================================================
# TEST CASE 10: sweep_expired_task_workspaces 清理超期目录
# ===========================================================================

class TestSweepExpiredWorkspaces:
    def test_sweep_removes_old_directories(self, tmp_path):
        store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
        import_work = os.path.join(str(tmp_path), "import_work")

        old_dir = os.path.join(import_work, "old-task-001")
        os.makedirs(old_dir)
        # Set mtime to 48 hours ago
        old_mtime = time.time() - 48 * 3600
        os.utime(old_dir, (old_mtime, old_mtime))

        deleted = store.sweep_expired_task_workspaces(ttl_hours=24)
        assert deleted == 1
        assert not os.path.exists(old_dir)

    def test_sweep_preserves_recent_directories(self, tmp_path):
        store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
        import_work = os.path.join(str(tmp_path), "import_work")

        recent_dir = os.path.join(import_work, "recent-task-001")
        os.makedirs(recent_dir)
        # mtime is "now" by default

        deleted = store.sweep_expired_task_workspaces(ttl_hours=24)
        assert deleted == 0
        assert os.path.isdir(recent_dir)

    def test_sweep_returns_zero_on_empty_import_work(self, tmp_path):
        """Works gracefully when import_work dir is empty."""
        store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
        deleted = store.sweep_expired_task_workspaces(ttl_hours=24)
        assert deleted == 0

    def test_sweep_respects_limit(self, tmp_path):
        store = StoreMemory(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
        import_work = os.path.join(str(tmp_path), "import_work")

        old_mtime = time.time() - 48 * 3600
        for i in range(5):
            d = os.path.join(import_work, f"old-task-{i:03d}")
            os.makedirs(d)
            os.utime(d, (old_mtime, old_mtime))

        deleted = store.sweep_expired_task_workspaces(ttl_hours=24, limit=3)
        assert deleted == 3


# ===========================================================================
# Bonus: ParseResult schema validation (from design doc section 5)
# ===========================================================================

class TestParseResultSchemaValidation:
    def test_missing_chunks_raises(self, tmp_path):
        store = _make_store_memory(tmp_path)
        svc = MemoryUploadService(
            store_memory=store,
            ast_guard=ASTGuard(),
            sandbox_runner=SandboxRunner(),
            parsers_dir=str(tmp_path / "parsers"),
            config=None,
        )
        with pytest.raises(DomainError) as exc_info:
            svc.validate_parse_result_schema({"search_profile": {}})
        assert exc_info.value.details["code"] == "PARSE_RESULT_SCHEMA_INVALID"
        assert "chunks" in exc_info.value.message

    def test_missing_search_profile_raises(self, tmp_path):
        store = _make_store_memory(tmp_path)
        svc = MemoryUploadService(
            store_memory=store,
            ast_guard=ASTGuard(),
            sandbox_runner=SandboxRunner(),
            parsers_dir=str(tmp_path / "parsers"),
            config=None,
        )
        with pytest.raises(DomainError) as exc_info:
            svc.validate_parse_result_schema({"chunks": []})
        assert "search_profile" in exc_info.value.message

    def test_invalid_local_file_storage_plan_raises(self, tmp_path):
        store = _make_store_memory(tmp_path)
        svc = MemoryUploadService(
            store_memory=store,
            ast_guard=ASTGuard(),
            sandbox_runner=SandboxRunner(),
            parsers_dir=str(tmp_path / "parsers"),
            config=None,
        )
        with pytest.raises(DomainError):
            svc.validate_parse_result_schema(
                {"chunks": [], "search_profile": {}, "local_file_storage_plan": "not a dict"}
            )

    def test_valid_result_passes(self, tmp_path):
        store = _make_store_memory(tmp_path)
        svc = MemoryUploadService(
            store_memory=store,
            ast_guard=ASTGuard(),
            sandbox_runner=SandboxRunner(),
            parsers_dir=str(tmp_path / "parsers"),
            config=None,
        )
        # Should not raise
        svc.validate_parse_result_schema(_MINIMAL_PARSE_RESULT)

    def test_null_local_file_storage_plan_passes(self, tmp_path):
        store = _make_store_memory(tmp_path)
        svc = MemoryUploadService(
            store_memory=store,
            ast_guard=ASTGuard(),
            sandbox_runner=SandboxRunner(),
            parsers_dir=str(tmp_path / "parsers"),
            config=None,
        )
        svc.validate_parse_result_schema(
            {"chunks": [], "search_profile": {}, "local_file_storage_plan": None}
        )


# ===========================================================================
# GET /api/import/memory/task/{task_id}
# ===========================================================================

class TestGetImportTaskEndpoint:
    def test_get_task_not_found_returns_404(self, client_with_mock_service):
        mock_repo = MagicMock()
        mock_repo.get.return_value = None
        with patch("bible.api.upload.memory_upload_api.get_task_repository", return_value=mock_repo):
            from bible.main import create_app
            app = create_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/import/memory/task/nonexistent-id")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "NOT_FOUND"

    def test_get_task_found_returns_task_data(self, tmp_path):
        from bible.features.async_task.repository import AsyncTask, AsyncTaskRepository
        from datetime import datetime, timezone

        repo = AsyncTaskRepository()
        repo.create(task_id="t1", task_type="import.memory", payload={})
        task = repo.get("t1")

        mock_repo = MagicMock()
        mock_repo.get.return_value = task

        with patch("bible.api.upload.memory_upload_api.get_task_repository", return_value=mock_repo):
            with patch("bible.api.upload.memory_upload_api.get_task_service") as mock_svc:
                mock_svc.return_value.submit.return_value = {"task_id": "t1", "status": "queued"}
                from bible.main import create_app
                app = create_app()
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/import/memory/task/t1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == "t1"
        assert body["task_type"] == "import.memory"
        assert "status" in body




# ===========================================================================
# TEST CASE 15: StoreMemory._save_files_by_plan — 集成新接口
# ===========================================================================

class TestStoreMemorySaveFilesByPlan:
    def _store_and_plan(self, tmp_path, content: bytes, filename: str, task_id: str = "t1"):
        """Stage a file and return (store, plan) ready for _save_files_by_plan."""
        store = _make_store_memory(tmp_path)
        staged_dir = tmp_path / "import_work" / task_id / "staged"
        staged_dir.mkdir(parents=True, exist_ok=True)
        src = staged_dir / filename
        src.write_bytes(content)
        plan = {
            "task_id": task_id,
            "files": [
                {
                    "file_ref": "ref_0",
                    "filename": filename,
                    "abs_path": str(src),
                    "size_bytes": len(content),
                }
            ],
        }
        return store, plan

    def test_returns_storage_path_and_hash(self, tmp_path):
        import hashlib
        content = b"plan content"
        store, plan = self._store_and_plan(tmp_path, content, "doc.txt")
        with _patch_db_writer():
            result = store._save_files_by_plan("kb1", "MEMORY", plan)
        assert "ref_0" in result
        entry = result["ref_0"]
        assert entry["storage_path"] != ""
        assert entry["file_hash"] == hashlib.sha256(content).hexdigest()
        assert entry["size_bytes"] == len(content)

    def test_storage_path_is_relative(self, tmp_path):
        store, plan = self._store_and_plan(tmp_path, b"x", "f.txt")
        from pathlib import Path
        with _patch_db_writer():
            result = store._save_files_by_plan("kb1", "MEMORY", plan)
        assert not Path(result["ref_0"]["storage_path"]).is_absolute()

    def test_filename_in_result_is_sanitized(self, tmp_path):
        store, plan = self._store_and_plan(tmp_path, b"x", "my file (v2).txt")
        with _patch_db_writer():
            result = store._save_files_by_plan("kb1", "MEMORY", plan)
        fname = result["ref_0"]["filename"]
        assert " " not in fname
        assert "(" not in fname

    def test_missing_source_file_is_skipped(self, tmp_path):
        store = _make_store_memory(tmp_path)
        plan = {
            "task_id": "t1",
            "files": [
                {
                    "file_ref": "ref_ghost",
                    "filename": "ghost.txt",
                    "abs_path": str(tmp_path / "nonexistent.txt"),
                }
            ],
        }
        with _patch_db_writer():
            result = store._save_files_by_plan("kb1", "MEMORY", plan)
        assert result == {}

    def test_empty_plan_returns_empty_dict(self, tmp_path):
        store = _make_store_memory(tmp_path)
        with _patch_db_writer():
            result = store._save_files_by_plan("kb1", "MEMORY", None)
        assert result == {}

    def test_multiple_files_all_stored(self, tmp_path):
        store = _make_store_memory(tmp_path)
        staged_dir = tmp_path / "import_work" / "t2" / "staged"
        staged_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for i in range(3):
            src = staged_dir / f"file{i}.txt"
            src.write_bytes(f"content {i}".encode())
            files.append({"file_ref": f"ref_{i}", "filename": src.name, "abs_path": str(src)})
        plan = {"task_id": "t2", "files": files}
        with _patch_db_writer():
            result = store._save_files_by_plan("kb1", "MEMORY", plan)
        assert len(result) == 3
        paths = [result[f"ref_{i}"]["storage_path"] for i in range(3)]
        assert len(set(paths)) == 3  # all unique


# ===========================================================================
# TEST CASE 18: 端到端集成测试 — POST → 后台任务 → GET 轮询完成
# ===========================================================================

def _wait_for_terminal(
    client: TestClient,
    task_id: str,
    timeout: float = 10.0,
    interval: float = 0.05,
) -> dict:
    """Poll GET /api/import/memory/task/{task_id} until a terminal status or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/import/memory/task/{task_id}")
        assert r.status_code == 200, f"GET task returned {r.status_code}: {r.text}"
        body = r.json()
        if body["status"] in ("completed", "failed", "cancelled"):
            return body
        time.sleep(interval)
    raise TimeoutError(f"Task {task_id!r} did not reach terminal state within {timeout}s")


# Parser that reads the manifest and returns chunks + file storage plan.
# Uses Path.read_text() instead of open() to pass AST guard.
_E2E_PARSER_WITH_STORAGE = """\
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--context", default=None)
    args = p.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    files = manifest.get("files", [])

    chunks, plan_files = [], []
    for f in files:
        chunks.append({
            "id": f["file_ref"],
            "text": f["filename"],
            "metadata": {
                "source": f["filename"],
                "related_file_refs": [f["file_ref"]],
                "related_storage_paths": [],
            },
        })
        plan_files.append({
            "file_ref": f["file_ref"],
            "abs_path": f["abs_path"],
            "filename": f["filename"],
        })

    print(json.dumps({
        "chunks": chunks,
        "search_profile": {"type": "bm25"},
        "local_file_storage_plan": {"files": plan_files},
    }))


if __name__ == "__main__":
    main()
"""


class TestE2EMemoryImport:
    """End-to-end: POST /api/import/memory → background thread runs → GET until terminal."""

    def test_e2e_happy_path_with_preregistered_parser(self, api_client_with_parser):
        """Complete flow using the pre-registered parse_memory.py: 202 → completed."""
        response = api_client_with_parser.post(
            "/api/import/memory",
            data={"kb_index": "e2e_kb", "tag": "memory"},
            files={"files": ("data.json", b'{"key":"value"}', "application/json")},
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["kb_index"] == "e2e_kb"
        assert body["tag"] == "memory"
        assert body["domain"] == "MEMORY"
        assert body["status"] in ("queued", "running", "completed")  # eager/sync mode may already be done
        task_id = body["task_id"]

        result = _wait_for_terminal(api_client_with_parser, task_id)
        assert result["status"] == "completed", f"Task failed: {result.get('error')}"
        assert result["result"]["chunks_indexed"] >= 1
        assert result["result"]["kb_index"] == "e2e_kb"

    def test_e2e_with_uploaded_custom_parser(self, api_client):
        """POST with a user-supplied parser script (no pre-installed parser)."""
        response = api_client.post(
            "/api/import/memory",
            data={"kb_index": "e2e_custom", "tag": "memory"},
            files=[
                ("files", ("input.json", b'{"x":1}', "application/json")),
                ("parser_script", ("my_parser.py", _MINIMAL_PARSER_SCRIPT.encode(), "text/x-python")),
            ],
        )
        assert response.status_code == 202, response.text
        task_id = response.json()["task_id"]

        result = _wait_for_terminal(api_client, task_id)
        assert result["status"] == "completed", f"Task failed: {result.get('error')}"
        assert result["result"]["chunks_indexed"] >= 1

    def test_e2e_file_storage_plan_persists_files(self, api_client, tmp_path):
        """Parser returns local_file_storage_plan → files land on local FS."""
        response = api_client.post(
            "/api/import/memory",
            data={"kb_index": "e2e_fs", "tag": "memory"},
            files=[
                ("files", ("report.json", b'{"content":"test"}', "application/json")),
                ("parser_script", ("store_parser.py", _E2E_PARSER_WITH_STORAGE.encode(), "text/x-python")),
            ],
        )
        assert response.status_code == 202, response.text
        task_id = response.json()["task_id"]

        result = _wait_for_terminal(api_client, task_id)
        assert result["status"] == "completed", f"Task failed: {result.get('error')}"
        assert result["result"]["files_stored"] == 1

        # Verify the file physically landed on disk
        stored = list((tmp_path / "files").rglob("report.json"))
        assert len(stored) == 1, "Expected exactly one stored file on disk"

    def test_e2e_multiple_files_chunked_and_stored(self, api_client, tmp_path):
        """Two uploaded files → two chunks + two files stored."""
        response = api_client.post(
            "/api/import/memory",
            data={"kb_index": "e2e_multi", "tag": "memory"},
            files=[
                ("files", ("a.json", b'{"n":1}', "application/json")),
                ("files", ("b.json", b'{"n":2}', "application/json")),
                ("parser_script", ("p.py", _E2E_PARSER_WITH_STORAGE.encode(), "text/x-python")),
            ],
        )
        assert response.status_code == 202, response.text
        task_id = response.json()["task_id"]

        result = _wait_for_terminal(api_client, task_id)
        assert result["status"] == "completed", f"Task failed: {result.get('error')}"
        assert result["result"]["chunks_indexed"] == 2
        assert result["result"]["files_stored"] == 2

    def test_e2e_dangerous_parser_causes_task_failure(self, api_client):
        """Uploading a script with forbidden import → task transitions to failed."""
        response = api_client.post(
            "/api/import/memory",
            data={"kb_index": "e2e_danger", "tag": "memory"},
            files=[
                ("files", ("f.json", b"{}", "application/json")),
                ("parser_script", ("bad.py", _DANGEROUS_SCRIPT.encode(), "text/x-python")),
            ],
        )
        assert response.status_code == 202, response.text
        task_id = response.json()["task_id"]

        result = _wait_for_terminal(api_client, task_id)
        assert result["status"] == "failed"
        assert result["error"] is not None

    def test_e2e_unknown_task_id_returns_404(self, api_client):
        """GET on a non-existent task_id returns 404."""
        r = api_client.get("/api/import/memory/task/no-such-task-id")
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "NOT_FOUND"

    def test_e2e_duplicate_import_same_kb_both_complete(self, api_client_with_parser):
        """Two sequential imports to the same kb_index both complete successfully."""
        for i in range(2):
            resp = api_client_with_parser.post(
                "/api/import/memory",
                data={"kb_index": "e2e_dup", "tag": "memory"},
                files={"files": (f"f{i}.json", b'{}', "application/json")},
            )
            assert resp.status_code == 202
            result = _wait_for_terminal(api_client_with_parser, resp.json()["task_id"])
            assert result["status"] == "completed"
