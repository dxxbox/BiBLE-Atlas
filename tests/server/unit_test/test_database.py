"""
Unit tests for bible/infrastructure/database/.

Covers (aligned with design doc §8 test checklist):
  1. Types: IndexBinding, BulkWriteResult, DatabaseError
  2. OpenSearchWriter – binding CRUD (get/create/deactivate)
  3. OpenSearchWriter – bulk upsert (content_docs & file_registry)
  4. OpenSearchWriter – async task operations
  5. DatabaseFactory  – backend routing, caching, reset, unsupported backend
  6. DatabaseFactory  – concurrent get_writer creates client once

All OpenSearch tests use a mock client; no real server is required.
opensearch-py does not need to be installed.
"""

from __future__ import annotations

import sys
import threading
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ===========================================================================
# Fake opensearch module tree – injected via patch.dict(sys.modules, ...)
# ===========================================================================


class _NotFoundError(Exception):
    pass


class _ConflictError(Exception):
    pass


class _TransportError(Exception):
    pass


def _make_os_modules(bulk_return: tuple[int, list] = (0, [])) -> dict:
    """Build a fresh set of fake opensearch sys.modules entries."""
    exc_mod = types.ModuleType("opensearchpy.exceptions")
    exc_mod.NotFoundError = _NotFoundError  # type: ignore[attr-defined]
    exc_mod.ConflictError = _ConflictError  # type: ignore[attr-defined]
    exc_mod.TransportError = _TransportError  # type: ignore[attr-defined]

    helpers_mod = types.ModuleType("opensearchpy.helpers")
    helpers_mod.bulk = MagicMock(return_value=bulk_return)  # type: ignore[attr-defined]

    os_mod = types.ModuleType("opensearchpy")
    os_mod.OpenSearch = MagicMock  # type: ignore[attr-defined]
    os_mod.exceptions = exc_mod  # type: ignore[attr-defined]

    return {
        "opensearchpy": os_mod,
        "opensearchpy.exceptions": exc_mod,
        "opensearchpy.helpers": helpers_mod,
    }


# Module-level default – tests that need custom bulk behaviour build a new one
_OS_MODULES = _make_os_modules()


# ===========================================================================
# Config / writer helpers
# ===========================================================================


def _make_os_cfg():
    from bible.config.configure import BibleAtlasConfig, DatabaseConfig, OpenSearchDatabaseConfig

    return BibleAtlasConfig(
        database=DatabaseConfig(
            backend="opensearch",
            opensearch=OpenSearchDatabaseConfig(
                hosts=["localhost:9200"],
                binding_index="test_bindings",
                async_task_index="test_async_tasks",
                refresh_policy="false",
                bulk_chunk_size=500,
                request_timeout_seconds=30,
            ),
        )
    )


def _make_writer(mock_client: MagicMock, cfg=None):
    from bible.infrastructure.database.opensearch.writer import OpenSearchWriter

    return OpenSearchWriter(mock_client, cfg or _make_os_cfg())


def _binding_input(**overrides) -> dict[str, Any]:
    """Minimal valid binding_doc for create_index_binding."""
    base: dict[str, Any] = {
        "domain_type": "MEMORY",
        "kb_index": "kb_test",
        "tag": "mem-tag",
        "parser_script_source": "def parse(): pass",
        "parser_script_sha256": "abc123",
        "vector_model": "my-model",
        "search_profile_json": {"top_k": 5},
        "search_profile_sha256": "def456",
    }
    return {**base, **overrides}


def _binding_source(**overrides) -> dict[str, Any]:
    """A stored binding _source document (includes all fields)."""
    base: dict[str, Any] = {
        **_binding_input(),
        "is_active": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "deleted_at": None,
    }
    return {**base, **overrides}


# ===========================================================================
# §1 – Types
# ===========================================================================


class TestDatabaseTypes:
    def test_index_binding_to_dict_round_trips(self):
        from bible.infrastructure.database.types import IndexBinding

        b = IndexBinding(
            domain_type="MEMORY",
            kb_index="kb1",
            tag="t",
            parser_script_source="x",
            parser_script_sha256="h",
            vector_model=None,
            search_profile_json={"a": 1},
            search_profile_sha256="s",
        )
        d = b.to_dict()
        assert d["domain_type"] == "MEMORY"
        assert d["kb_index"] == "kb1"
        assert d["vector_model"] is None

    def test_bulk_write_result_defaults(self):
        from bible.infrastructure.database.types import BulkWriteResult

        r = BulkWriteResult()
        assert r.success_count == 0
        assert r.fail_count == 0
        assert r.errors == []

    def test_bulk_write_result_accumulates(self):
        from bible.infrastructure.database.types import BulkWriteResult

        r = BulkWriteResult(success_count=3, fail_count=1, errors=[{"reason": "oops"}])
        assert r.success_count == 3
        assert len(r.errors) == 1

    def test_database_error_str_contains_code(self):
        from bible.infrastructure.database.types import DatabaseError

        err = DatabaseError(code="INDEX_BINDING_CONFLICT", message="duplicate")
        assert "INDEX_BINDING_CONFLICT" in str(err)
        assert "duplicate" in str(err)

    def test_database_error_is_runtime_error(self):
        from bible.infrastructure.database.types import DatabaseError

        err = DatabaseError(code="INTERNAL_ERROR", message="boom")  # type: ignore[arg-type]
        assert isinstance(err, RuntimeError)


# ===========================================================================
# §2 – OpenSearchWriter: get_binding_by_domain_index
# ===========================================================================


class TestOpenSearchWriterGetBindingByDomainIndex:
    @pytest.fixture(autouse=True)
    def patch_os(self):
        with patch.dict(sys.modules, _OS_MODULES):
            yield

    def test_returns_none_on_not_found(self):
        client = MagicMock()
        client.get.side_effect = _NotFoundError()
        writer = _make_writer(client)
        assert writer.get_binding_by_domain_index("MEMORY", "kb1") is None

    def test_returns_none_when_is_active_false(self):
        client = MagicMock()
        client.get.return_value = {"_source": _binding_source(is_active=False)}
        writer = _make_writer(client)
        assert writer.get_binding_by_domain_index("MEMORY", "kb_test") is None

    def test_returns_index_binding_on_hit(self):
        from bible.infrastructure.database.types import IndexBinding

        client = MagicMock()
        client.get.return_value = {"_source": _binding_source()}
        writer = _make_writer(client)
        result = writer.get_binding_by_domain_index("MEMORY", "kb_test")
        assert isinstance(result, IndexBinding)
        assert result.kb_index == "kb_test"
        assert result.is_active is True

    def test_uses_correct_doc_id(self):
        client = MagicMock()
        client.get.side_effect = _NotFoundError()
        writer = _make_writer(client)
        writer.get_binding_by_domain_index("MEMORY", "myidx")
        client.get.assert_called_once_with(index="test_bindings", id="MEMORY::myidx")

    def test_raises_database_error_on_transport_error(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        client.get.side_effect = _TransportError("network")
        writer = _make_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.get_binding_by_domain_index("MEMORY", "kb1")
        assert exc_info.value.code == "DATABASE_BACKEND_UNAVAILABLE"


# ===========================================================================
# §2 – OpenSearchWriter: get_binding_by_domain_tag
# ===========================================================================


class TestOpenSearchWriterGetBindingByDomainTag:
    @pytest.fixture(autouse=True)
    def patch_os(self):
        with patch.dict(sys.modules, _OS_MODULES):
            yield

    def test_returns_none_when_no_hits(self):
        client = MagicMock()
        client.search.return_value = {"hits": {"hits": []}}
        writer = _make_writer(client)
        assert writer.get_binding_by_domain_tag("MEMORY", "mem-tag") is None

    def test_returns_binding_on_single_hit(self):
        from bible.infrastructure.database.types import IndexBinding

        client = MagicMock()
        client.search.return_value = {"hits": {"hits": [{"_source": _binding_source()}]}}
        writer = _make_writer(client)
        result = writer.get_binding_by_domain_tag("MEMORY", "mem-tag")
        assert isinstance(result, IndexBinding)
        assert result.tag == "mem-tag"

    def test_returns_first_binding_on_multiple_hits(self):
        src1 = _binding_source(kb_index="kb1")
        src2 = _binding_source(kb_index="kb2")
        client = MagicMock()
        client.search.return_value = {
            "hits": {"hits": [{"_source": src1}, {"_source": src2}]}
        }
        writer = _make_writer(client)
        result = writer.get_binding_by_domain_tag("MEMORY", "mem-tag")
        assert result is not None
        assert result.kb_index == "kb1"

    def test_raises_database_error_on_transport_error(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        client.search.side_effect = _TransportError("timeout")
        writer = _make_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.get_binding_by_domain_tag("MEMORY", "mem-tag")
        assert exc_info.value.code == "DATABASE_BACKEND_UNAVAILABLE"


# ===========================================================================
# §2 – OpenSearchWriter: create_index_binding
# ===========================================================================


class TestOpenSearchWriterCreateIndexBinding:
    @pytest.fixture(autouse=True)
    def patch_os(self):
        with patch.dict(sys.modules, _OS_MODULES):
            yield

    def test_creates_with_op_type_create(self):
        client = MagicMock()
        client.index.return_value = {"_id": "MEMORY::kb_test", "result": "created"}
        writer = _make_writer(client)
        writer.create_index_binding(_binding_input())
        call_kwargs = client.index.call_args.kwargs
        assert call_kwargs["op_type"] == "create"

    def test_returns_created_true_and_id(self):
        client = MagicMock()
        client.index.return_value = {"_id": "MEMORY::kb_test", "result": "created"}
        writer = _make_writer(client)
        result = writer.create_index_binding(_binding_input())
        assert result["created"] is True
        assert result["_id"] == "MEMORY::kb_test"

    def test_raises_conflict_error_on_duplicate(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        client.index.side_effect = _ConflictError()
        writer = _make_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.create_index_binding(_binding_input())
        assert exc_info.value.code == "INDEX_BINDING_CONFLICT"

    def test_raises_error_when_required_field_missing(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        writer = _make_writer(client)
        bad_doc = {k: v for k, v in _binding_input().items() if k != "tag"}
        with pytest.raises(DatabaseError) as exc_info:
            writer.create_index_binding(bad_doc)
        assert exc_info.value.code == "DATABASE_INVALID_ARGUMENT"
        assert "tag" in exc_info.value.details.get("missing_fields", [])

    def test_raises_database_error_on_transport_error(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        client.index.side_effect = _TransportError("backend down")
        writer = _make_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.create_index_binding(_binding_input())
        assert exc_info.value.code == "DATABASE_BACKEND_UNAVAILABLE"


# ===========================================================================
# §2 – OpenSearchWriter: deactivate_binding
# ===========================================================================


class TestOpenSearchWriterDeactivateBinding:
    @pytest.fixture(autouse=True)
    def patch_os(self):
        with patch.dict(sys.modules, _OS_MODULES):
            yield

    def test_updates_correct_doc_id(self):
        client = MagicMock()
        client.update.return_value = {"_id": "MEMORY::kb_test", "result": "updated"}
        writer = _make_writer(client)
        writer.deactivate_binding("MEMORY", "kb_test")
        call_kwargs = client.update.call_args.kwargs
        assert call_kwargs["id"] == "MEMORY::kb_test"

    def test_returns_updated_true(self):
        client = MagicMock()
        client.update.return_value = {"_id": "MEMORY::kb_test", "result": "updated"}
        writer = _make_writer(client)
        result = writer.deactivate_binding("MEMORY", "kb_test")
        assert result["updated"] is True

    def test_raises_not_bound_on_not_found(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        client.update.side_effect = _NotFoundError()
        writer = _make_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.deactivate_binding("MEMORY", "kb_test")
        assert exc_info.value.code == "INDEX_NOT_BOUND"

    def test_script_sets_is_active_false(self):
        client = MagicMock()
        client.update.return_value = {"_id": "MEMORY::kb_test"}
        writer = _make_writer(client)
        writer.deactivate_binding("MEMORY", "kb_test")
        body = client.update.call_args.kwargs["body"]
        assert "is_active = false" in body["script"]["source"]


# ===========================================================================
# §3 – OpenSearchWriter: bulk_upsert_content_docs
# ===========================================================================


class TestOpenSearchWriterBulkUpsertContentDocs:
    @pytest.fixture(autouse=True)
    def patch_os(self):
        with patch.dict(sys.modules, _OS_MODULES):
            yield

    def test_empty_docs_returns_zero_counts(self):
        writer = _make_writer(MagicMock())
        result = writer.bulk_upsert_content_docs("my_index", [])
        assert result.success_count == 0
        assert result.fail_count == 0

    def test_success_count_matches_bulk_return(self):
        mods = _make_os_modules(bulk_return=(3, []))
        with patch.dict(sys.modules, mods):
            writer = _make_writer(MagicMock())
            docs = [{"_id": str(i), "text": "hello"} for i in range(3)]
            result = writer.bulk_upsert_content_docs("idx", docs)
        assert result.success_count == 3
        assert result.fail_count == 0

    def test_partial_failure_recorded(self):
        err = [{"index": {"error": {"reason": "bad"}}}]
        mods = _make_os_modules(bulk_return=(2, err))
        with patch.dict(sys.modules, mods):
            writer = _make_writer(MagicMock())
            docs = [{"_id": str(i), "text": "x"} for i in range(3)]
            result = writer.bulk_upsert_content_docs("idx", docs)
        assert result.success_count == 2
        assert result.fail_count == 1
        assert len(result.errors) == 1

    def test_doc_without_id_counted_as_failure(self):
        mods = _make_os_modules(bulk_return=(0, []))
        with patch.dict(sys.modules, mods):
            writer = _make_writer(MagicMock())
            result = writer.bulk_upsert_content_docs("idx", [{"text": "no id"}])
        assert result.fail_count == 1
        assert result.success_count == 0

    def test_raises_database_error_on_empty_index(self):
        from bible.infrastructure.database.types import DatabaseError

        with patch.dict(sys.modules, _OS_MODULES):
            writer = _make_writer(MagicMock())
            with pytest.raises(DatabaseError) as exc_info:
                writer.bulk_upsert_content_docs("", [{"_id": "x"}])
        assert exc_info.value.code == "DATABASE_INVALID_ARGUMENT"

    def test_uses_doc_as_upsert_true(self):
        actions_captured: list = []

        def capture_bulk(client, actions, **kwargs):
            actions_captured.extend(actions)
            return (len(actions), [])

        mods = _make_os_modules()
        mods["opensearchpy.helpers"].bulk = capture_bulk  # type: ignore[attr-defined]
        with patch.dict(sys.modules, mods):
            writer = _make_writer(MagicMock())
            writer.bulk_upsert_content_docs("idx", [{"_id": "1", "text": "hi"}])
        assert actions_captured[0]["doc_as_upsert"] is True
        assert actions_captured[0]["_op_type"] == "update"

    def test_creates_knn_index_for_content_vectors(self):
        mods = _make_os_modules(bulk_return=(1, []))
        client = MagicMock()
        client.indices.exists.return_value = False
        with patch.dict(sys.modules, mods):
            writer = _make_writer(client)
            writer.bulk_upsert_content_docs(
                "idx",
                [{"_id": "1", "content_vector": [0.1, 0.2, 0.3]}],
            )

        client.indices.create.assert_called_once()
        body = client.indices.create.call_args.kwargs["body"]
        assert body["settings"]["index"]["knn"] is True
        assert body["mappings"]["properties"]["content_vector"] == {
            "type": "knn_vector",
            "dimension": 3,
        }

    def test_creates_knn_index_with_num_candidates_setting(self):
        mods = _make_os_modules(bulk_return=(1, []))
        client = MagicMock()
        client.indices.exists.return_value = False
        with patch.dict(sys.modules, mods):
            writer = _make_writer(client)
            writer.bulk_upsert_content_docs(
                "idx",
                [{"_id": "1", "content_vector": [0.1, 0.2, 0.3]}],
                vector_options={"num_candidates": 123},
            )

        body = client.indices.create.call_args.kwargs["body"]
        assert body["settings"]["index"]["knn"] is True
        assert body["settings"]["index"]["knn.algo_param.ef_search"] == 123

    def test_adds_knn_mapping_when_existing_index_has_no_vector_field(self):
        mods = _make_os_modules(bulk_return=(1, []))
        client = MagicMock()
        client.indices.exists.return_value = True
        client.indices.get_mapping.return_value = {
            "idx": {"mappings": {"properties": {"title": {"type": "text"}}}}
        }
        with patch.dict(sys.modules, mods):
            writer = _make_writer(client)
            writer.bulk_upsert_content_docs(
                "idx",
                [{"_id": "1", "content_vector": [0.1, 0.2]}],
            )

        client.indices.put_mapping.assert_called_once_with(
            index="idx",
            body={
                "properties": {
                    "content_vector": {"type": "knn_vector", "dimension": 2}
                }
            },
            request_timeout=30,
        )

    def test_updates_num_candidates_for_existing_knn_index(self):
        mods = _make_os_modules(bulk_return=(1, []))
        client = MagicMock()
        client.indices.exists.return_value = True
        client.indices.get_mapping.return_value = {
            "idx": {
                "mappings": {
                    "properties": {
                        "content_vector": {"type": "knn_vector", "dimension": 2}
                    }
                }
            }
        }
        with patch.dict(sys.modules, mods):
            writer = _make_writer(client)
            writer.bulk_upsert_content_docs(
                "idx",
                [{"_id": "1", "content_vector": [0.1, 0.2]}],
                vector_options={"num_candidates": 77},
            )

        client.indices.put_settings.assert_called_once_with(
            index="idx",
            body={"index": {"knn.algo_param.ef_search": 77}},
            request_timeout=30,
        )

    def test_search_strips_num_candidates_for_opensearch(self):
        client = MagicMock()
        client.search.return_value = {"hits": {"total": 0, "hits": []}}
        writer = _make_writer(client)
        writer.search_content_docs(
            "idx",
            {
                "size": 5,
                "query": {
                    "knn": {
                        "content_vector": {
                            "vector": [0.1, 0.2],
                            "k": 5,
                            "num_candidates": 77,
                        }
                    }
                },
            },
        )

        body = client.search.call_args.kwargs["body"]
        knn = body["query"]["knn"]["content_vector"]
        assert knn == {"vector": [0.1, 0.2], "k": 5}


# ===========================================================================
# §3 – OpenSearchWriter: bulk_upsert_file_registry
# ===========================================================================


class TestOpenSearchWriterBulkUpsertFileRegistry:
    @pytest.fixture(autouse=True)
    def patch_os(self):
        with patch.dict(sys.modules, _OS_MODULES):
            yield

    def test_empty_records_returns_zero_counts(self):
        writer = _make_writer(MagicMock())
        result = writer.bulk_upsert_file_registry("my_index", [])
        assert result.success_count == 0 and result.fail_count == 0

    def test_success_count_matches_bulk_return(self):
        mods = _make_os_modules(bulk_return=(5, []))
        with patch.dict(sys.modules, mods):
            writer = _make_writer(MagicMock())
            records = [{"_id": str(i), "path": f"/f{i}.md"} for i in range(5)]
            result = writer.bulk_upsert_file_registry("file_idx", records)
        assert result.success_count == 5
        assert result.fail_count == 0

    def test_failure_counted_for_missing_id(self):
        mods = _make_os_modules(bulk_return=(0, []))
        with patch.dict(sys.modules, mods):
            writer = _make_writer(MagicMock())
            result = writer.bulk_upsert_file_registry("file_idx", [{"path": "/f.md"}])
        assert result.fail_count == 1


# ===========================================================================
# §4 – OpenSearchWriter: async task operations
# ===========================================================================


class TestOpenSearchWriterAsyncTask:
    @pytest.fixture(autouse=True)
    def patch_os(self):
        with patch.dict(sys.modules, _OS_MODULES):
            yield

    # -- create_async_task --

    def test_create_uses_op_type_create(self):
        client = MagicMock()
        client.index.return_value = {"_id": "task-1"}
        writer = _make_writer(client)
        writer.create_async_task({"task_id": "task-1", "task_type": "import", "status": "queued"})
        assert client.index.call_args.kwargs["op_type"] == "create"

    def test_create_raises_conflict_on_duplicate(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        client.index.side_effect = _ConflictError()
        writer = _make_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.create_async_task({"task_id": "task-1", "status": "queued"})
        assert exc_info.value.code == "INDEX_BINDING_CONFLICT"

    def test_create_raises_error_when_no_task_id(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        writer = _make_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.create_async_task({"task_type": "import"})
        assert exc_info.value.code == "DATABASE_INVALID_ARGUMENT"

    # -- get_async_task --

    def test_get_returns_source_on_hit(self):
        client = MagicMock()
        client.get.return_value = {"_source": {"task_id": "task-1", "status": "queued"}}
        writer = _make_writer(client)
        result = writer.get_async_task("task-1")
        assert result is not None
        assert result["task_id"] == "task-1"

    def test_get_returns_none_on_not_found(self):
        client = MagicMock()
        client.get.side_effect = _NotFoundError()
        writer = _make_writer(client)
        assert writer.get_async_task("missing") is None

    # -- find_async_task_by_idempotency --

    def test_find_returns_source_on_hit(self):
        src = {"task_id": "task-1", "idempotency_key": "key-x"}
        client = MagicMock()
        client.search.return_value = {"hits": {"hits": [{"_source": src}]}}
        writer = _make_writer(client)
        result = writer.find_async_task_by_idempotency("import", "key-x")
        assert result is not None
        assert result["task_id"] == "task-1"

    def test_find_returns_none_when_no_hits(self):
        client = MagicMock()
        client.search.return_value = {"hits": {"hits": []}}
        writer = _make_writer(client)
        assert writer.find_async_task_by_idempotency("import", "key-x") is None

    # -- update_async_task --

    def test_update_returns_true_on_success(self):
        existing = {"task_id": "task-1", "status": "queued"}
        client = MagicMock()
        client.get.return_value = {"_source": existing}
        client.update.return_value = {"_id": "task-1"}
        writer = _make_writer(client)
        assert writer.update_async_task("task-1", {"status": "running"}) is True

    def test_update_returns_false_when_task_not_found(self):
        # Without expected_statuses, the writer does not pre-check existence;
        # it calls client.update() directly and catches NotFoundError from OpenSearch.
        client = MagicMock()
        client.update.side_effect = _NotFoundError()
        writer = _make_writer(client)
        assert writer.update_async_task("missing", {"status": "running"}) is False

    def test_update_returns_false_when_status_not_in_expected(self):
        existing = {"task_id": "task-1", "status": "completed"}
        client = MagicMock()
        client.get.return_value = {"_source": existing}
        writer = _make_writer(client)
        result = writer.update_async_task(
            "task-1", {"status": "running"}, expected_statuses=["queued"]
        )
        assert result is False
        client.update.assert_not_called()

    def test_update_proceeds_when_status_matches_expected(self):
        existing = {"task_id": "task-1", "status": "queued"}
        client = MagicMock()
        client.get.return_value = {"_source": existing}
        client.update.return_value = {"_id": "task-1"}
        writer = _make_writer(client)
        result = writer.update_async_task(
            "task-1", {"status": "running"}, expected_statuses=["queued"]
        )
        assert result is True
        client.update.assert_called_once()


# ===========================================================================
# §5 – DatabaseFactory: routing, caching, reset, unsupported backend
# ===========================================================================


def _make_db_cfg(backend: str = "opensearch"):
    from bible.config.configure import BibleAtlasConfig, DatabaseConfig, OpenSearchDatabaseConfig

    return BibleAtlasConfig(
        database=DatabaseConfig(
            backend=backend,
            opensearch=OpenSearchDatabaseConfig(hosts=["localhost:9200"]),
        )
    )


class TestDatabaseFactory:
    def _make_mock_provider(self) -> MagicMock:
        provider = MagicMock()
        provider.get_client.return_value = MagicMock()
        return provider

    def _os_modules_with_provider(self, mock_provider_cls: MagicMock) -> dict:
        """sys.modules patch that injects mock_provider_cls as OpenSearchClientProvider."""
        fake_client_mod = types.ModuleType("bible.infrastructure.database.opensearch.client")
        fake_client_mod.OpenSearchClientProvider = mock_provider_cls  # type: ignore[attr-defined]
        return {
            **_OS_MODULES,
            "bible.infrastructure.database.opensearch.client": fake_client_mod,
        }

    # ---- backend routing ----

    def test_opensearch_backend_returns_opensearch_writer(self):
        from bible.infrastructure.database.factory import DatabaseFactory
        from bible.infrastructure.database.opensearch.writer import OpenSearchWriter

        factory = DatabaseFactory(_make_db_cfg("opensearch"))
        mock_provider_cls = MagicMock(return_value=self._make_mock_provider())

        with patch.dict(sys.modules, self._os_modules_with_provider(mock_provider_cls)):
            writer = factory.get_writer("MEMORY")
        assert isinstance(writer, OpenSearchWriter)

    def test_unsupported_backend_raises_database_error(self):
        from bible.infrastructure.database.factory import DatabaseFactory
        from bible.infrastructure.database.types import DatabaseError

        factory = DatabaseFactory(_make_db_cfg("hdfs"))
        with pytest.raises(DatabaseError) as exc_info:
            factory.get_writer("MEMORY")
        assert exc_info.value.code == "DATABASE_INVALID_ARGUMENT"
        assert "hdfs" in exc_info.value.message

    # ---- caching ----

    def test_get_writer_returns_same_instance_on_repeated_calls(self):
        from bible.infrastructure.database.factory import DatabaseFactory

        factory = DatabaseFactory(_make_db_cfg("opensearch"))
        mock_provider_cls = MagicMock(return_value=self._make_mock_provider())

        with patch.dict(sys.modules, self._os_modules_with_provider(mock_provider_cls)):
            w1 = factory.get_writer("MEMORY")
            w2 = factory.get_writer("KNOWLEDGE_BASE")  # domain ignored; same backend
        assert w1 is w2

    def test_get_writer_creates_provider_only_once(self):
        from bible.infrastructure.database.factory import DatabaseFactory

        factory = DatabaseFactory(_make_db_cfg("opensearch"))
        mock_provider_cls = MagicMock(return_value=self._make_mock_provider())

        with patch.dict(sys.modules, self._os_modules_with_provider(mock_provider_cls)):
            factory.get_writer("MEMORY")
            factory.get_writer("MEMORY")
        assert mock_provider_cls.call_count == 1

    # ---- reset ----

    def test_reset_clears_cache_and_new_instance_is_different(self):
        from bible.infrastructure.database.factory import DatabaseFactory

        factory = DatabaseFactory(_make_db_cfg("opensearch"))
        mock_provider_cls = MagicMock(return_value=self._make_mock_provider())

        with patch.dict(sys.modules, self._os_modules_with_provider(mock_provider_cls)):
            w1 = factory.get_writer("MEMORY")
            factory.reset()
            w2 = factory.get_writer("MEMORY")
        assert w1 is not w2

    def test_reset_calls_close_on_provider(self):
        from bible.infrastructure.database.factory import DatabaseFactory

        factory = DatabaseFactory(_make_db_cfg("opensearch"))
        mock_provider = self._make_mock_provider()
        mock_provider_cls = MagicMock(return_value=mock_provider)

        with patch.dict(sys.modules, self._os_modules_with_provider(mock_provider_cls)):
            factory.get_writer("MEMORY")
            factory.reset()
        mock_provider.close.assert_called_once()

    # ---- get_async_task_writer ----

    def test_get_async_task_writer_returns_same_as_get_writer(self):
        from bible.infrastructure.database.factory import DatabaseFactory

        factory = DatabaseFactory(_make_db_cfg("opensearch"))
        mock_provider_cls = MagicMock(return_value=self._make_mock_provider())

        with patch.dict(sys.modules, self._os_modules_with_provider(mock_provider_cls)):
            w1 = factory.get_writer("KNOWLEDGE_BASE")
            w2 = factory.get_async_task_writer()
        assert w1 is w2

    # ---- postgres not installed ----

    def test_postgres_backend_raises_when_psycopg_missing(self):
        from bible.infrastructure.database.factory import DatabaseFactory
        from bible.infrastructure.database.types import DatabaseError

        from bible.config.configure import (
            BibleAtlasConfig,
            DatabaseConfig,
            PostgresDatabaseConfig,
        )

        cfg = BibleAtlasConfig(
            database=DatabaseConfig(
                backend="postgres",
                postgres=PostgresDatabaseConfig(dsn="postgresql://u:p@localhost/db"),
            )
        )
        factory = DatabaseFactory(cfg)

        with patch.dict(sys.modules, {"psycopg_pool": None}):
            with pytest.raises((DatabaseError, ImportError)):
                factory.get_writer("MEMORY")


# ===========================================================================
# §6 – DatabaseFactory: concurrent get_writer initialises provider once
# ===========================================================================


class TestDatabaseFactoryConcurrency:
    def test_concurrent_get_writer_creates_provider_only_once(self):
        import time

        from bible.infrastructure.database.factory import DatabaseFactory

        factory = DatabaseFactory(_make_db_cfg("opensearch"))

        create_count = 0
        create_lock = threading.Lock()

        def slow_provider_factory(_cfg):
            nonlocal create_count
            time.sleep(0.01)
            with create_lock:
                create_count += 1
            p = MagicMock()
            p.get_client.return_value = MagicMock()
            return p

        mock_provider_cls = MagicMock(side_effect=slow_provider_factory)
        fake_client_mod = types.ModuleType("bible.infrastructure.database.opensearch.client")
        fake_client_mod.OpenSearchClientProvider = mock_provider_cls  # type: ignore[attr-defined]

        results: list = []
        results_lock = threading.Lock()

        def get_and_append():
            w = factory.get_writer("MEMORY")
            with results_lock:
                results.append(w)

        # Patch once at the outer level so all threads share the same context
        with patch.dict(
            sys.modules,
            {**_OS_MODULES, "bible.infrastructure.database.opensearch.client": fake_client_mod},
        ):
            threads = [threading.Thread(target=get_and_append) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert create_count == 1
        assert all(r is results[0] for r in results)


# ===========================================================================
# Elasticsearch fake modules & helpers
# ===========================================================================


def _make_es_modules(bulk_return: tuple[int, list] = (0, [])) -> dict:
    """Build a fresh set of fake elasticsearch sys.modules entries."""
    exc_mod = types.ModuleType("elasticsearch.exceptions")
    exc_mod.NotFoundError = _NotFoundError  # type: ignore[attr-defined]
    exc_mod.ConflictError = _ConflictError  # type: ignore[attr-defined]
    exc_mod.TransportError = _TransportError  # type: ignore[attr-defined]

    helpers_mod = types.ModuleType("elasticsearch.helpers")
    helpers_mod.bulk = MagicMock(return_value=bulk_return)  # type: ignore[attr-defined]

    es_mod = types.ModuleType("elasticsearch")
    es_mod.Elasticsearch = MagicMock  # type: ignore[attr-defined]
    es_mod.exceptions = exc_mod  # type: ignore[attr-defined]

    return {
        "elasticsearch": es_mod,
        "elasticsearch.exceptions": exc_mod,
        "elasticsearch.helpers": helpers_mod,
    }


_ES_MODULES = _make_es_modules()


def _make_es_cfg():
    from bible.config.configure import (
        BibleAtlasConfig,
        DatabaseConfig,
        ElasticsearchDatabaseConfig,
    )

    return BibleAtlasConfig(
        database=DatabaseConfig(
            backend="elasticsearch",
            elasticsearch=ElasticsearchDatabaseConfig(
                hosts=["localhost:9200"],
                binding_index="test_bindings",
                async_task_index="test_async_tasks",
                refresh_policy="false",
                bulk_chunk_size=500,
                request_timeout_seconds=30,
            ),
        )
    )


def _make_es_writer(mock_client: MagicMock, cfg=None):
    from bible.infrastructure.database.elasticsearch.writer import ElasticsearchWriter

    return ElasticsearchWriter(mock_client, cfg or _make_es_cfg())


# ===========================================================================
# §7 – ElasticsearchWriter: get_binding_by_domain_index
# ===========================================================================


class TestElasticsearchWriterGetBindingByDomainIndex:
    @pytest.fixture(autouse=True)
    def patch_es(self):
        with patch.dict(sys.modules, _ES_MODULES):
            yield

    def test_returns_none_on_not_found(self):
        client = MagicMock()
        client.get.side_effect = _NotFoundError()
        writer = _make_es_writer(client)
        assert writer.get_binding_by_domain_index("MEMORY", "kb1") is None

    def test_returns_none_when_is_active_false(self):
        client = MagicMock()
        client.get.return_value = {"_source": _binding_source(is_active=False)}
        writer = _make_es_writer(client)
        assert writer.get_binding_by_domain_index("MEMORY", "kb_test") is None

    def test_returns_index_binding_on_hit(self):
        from bible.infrastructure.database.types import IndexBinding

        client = MagicMock()
        client.get.return_value = {"_source": _binding_source()}
        writer = _make_es_writer(client)
        result = writer.get_binding_by_domain_index("MEMORY", "kb_test")
        assert isinstance(result, IndexBinding)
        assert result.kb_index == "kb_test"
        assert result.is_active is True

    def test_uses_correct_doc_id(self):
        client = MagicMock()
        client.get.side_effect = _NotFoundError()
        writer = _make_es_writer(client)
        writer.get_binding_by_domain_index("MEMORY", "myidx")
        client.get.assert_called_once_with(index="test_bindings", id="MEMORY::myidx")

    def test_raises_database_error_on_transport_error(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        client.get.side_effect = _TransportError("network")
        writer = _make_es_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.get_binding_by_domain_index("MEMORY", "kb1")
        assert exc_info.value.code == "DATABASE_BACKEND_UNAVAILABLE"


# ===========================================================================
# §7 – ElasticsearchWriter: get_binding_by_domain_tag
# ===========================================================================


class TestElasticsearchWriterGetBindingByDomainTag:
    @pytest.fixture(autouse=True)
    def patch_es(self):
        with patch.dict(sys.modules, _ES_MODULES):
            yield

    def test_returns_none_when_no_hits(self):
        client = MagicMock()
        client.search.return_value = {"hits": {"hits": []}}
        writer = _make_es_writer(client)
        assert writer.get_binding_by_domain_tag("MEMORY", "mem-tag") is None

    def test_returns_binding_on_single_hit(self):
        from bible.infrastructure.database.types import IndexBinding

        client = MagicMock()
        client.search.return_value = {"hits": {"hits": [{"_source": _binding_source()}]}}
        writer = _make_es_writer(client)
        result = writer.get_binding_by_domain_tag("MEMORY", "mem-tag")
        assert isinstance(result, IndexBinding)
        assert result.tag == "mem-tag"

    def test_returns_first_binding_on_multiple_hits(self):
        src1 = _binding_source(kb_index="kb1")
        src2 = _binding_source(kb_index="kb2")
        client = MagicMock()
        client.search.return_value = {
            "hits": {"hits": [{"_source": src1}, {"_source": src2}]}
        }
        writer = _make_es_writer(client)
        result = writer.get_binding_by_domain_tag("MEMORY", "mem-tag")
        assert result is not None
        assert result.kb_index == "kb1"

    def test_raises_database_error_on_transport_error(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        client.search.side_effect = _TransportError("timeout")
        writer = _make_es_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.get_binding_by_domain_tag("MEMORY", "mem-tag")
        assert exc_info.value.code == "DATABASE_BACKEND_UNAVAILABLE"


# ===========================================================================
# §7 – ElasticsearchWriter: create_index_binding
# ===========================================================================


class TestElasticsearchWriterCreateIndexBinding:
    @pytest.fixture(autouse=True)
    def patch_es(self):
        with patch.dict(sys.modules, _ES_MODULES):
            yield

    def test_creates_with_op_type_create(self):
        client = MagicMock()
        client.index.return_value = {"_id": "MEMORY::kb_test", "result": "created"}
        writer = _make_es_writer(client)
        writer.create_index_binding(_binding_input())
        call_kwargs = client.index.call_args.kwargs
        assert call_kwargs["op_type"] == "create"

    def test_returns_created_true_and_id(self):
        client = MagicMock()
        client.index.return_value = {"_id": "MEMORY::kb_test", "result": "created"}
        writer = _make_es_writer(client)
        result = writer.create_index_binding(_binding_input())
        assert result["created"] is True
        assert result["_id"] == "MEMORY::kb_test"

    def test_raises_conflict_error_on_duplicate(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        client.index.side_effect = _ConflictError()
        writer = _make_es_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.create_index_binding(_binding_input())
        assert exc_info.value.code == "INDEX_BINDING_CONFLICT"

    def test_raises_error_when_required_field_missing(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        writer = _make_es_writer(client)
        bad_doc = {k: v for k, v in _binding_input().items() if k != "tag"}
        with pytest.raises(DatabaseError) as exc_info:
            writer.create_index_binding(bad_doc)
        assert exc_info.value.code == "DATABASE_INVALID_ARGUMENT"
        assert "tag" in exc_info.value.details.get("missing_fields", [])

    def test_raises_database_error_on_transport_error(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        client.index.side_effect = _TransportError("backend down")
        writer = _make_es_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.create_index_binding(_binding_input())
        assert exc_info.value.code == "DATABASE_BACKEND_UNAVAILABLE"


# ===========================================================================
# §7 – ElasticsearchWriter: deactivate_binding
# ===========================================================================


class TestElasticsearchWriterDeactivateBinding:
    @pytest.fixture(autouse=True)
    def patch_es(self):
        with patch.dict(sys.modules, _ES_MODULES):
            yield

    def test_updates_correct_doc_id(self):
        client = MagicMock()
        client.update.return_value = {"_id": "MEMORY::kb_test", "result": "updated"}
        writer = _make_es_writer(client)
        writer.deactivate_binding("MEMORY", "kb_test")
        call_kwargs = client.update.call_args.kwargs
        assert call_kwargs["id"] == "MEMORY::kb_test"

    def test_returns_updated_true(self):
        client = MagicMock()
        client.update.return_value = {"_id": "MEMORY::kb_test", "result": "updated"}
        writer = _make_es_writer(client)
        result = writer.deactivate_binding("MEMORY", "kb_test")
        assert result["updated"] is True

    def test_raises_not_bound_on_not_found(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        client.update.side_effect = _NotFoundError()
        writer = _make_es_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.deactivate_binding("MEMORY", "kb_test")
        assert exc_info.value.code == "INDEX_NOT_BOUND"

    def test_script_sets_is_active_false(self):
        client = MagicMock()
        client.update.return_value = {"_id": "MEMORY::kb_test"}
        writer = _make_es_writer(client)
        writer.deactivate_binding("MEMORY", "kb_test")
        body = client.update.call_args.kwargs["body"]
        assert "is_active = false" in body["script"]["source"]


# ===========================================================================
# §8 – ElasticsearchWriter: bulk_upsert_content_docs
# ===========================================================================


class TestElasticsearchWriterBulkUpsertContentDocs:
    @pytest.fixture(autouse=True)
    def patch_es(self):
        with patch.dict(sys.modules, _ES_MODULES):
            yield

    def test_empty_docs_returns_zero_counts(self):
        writer = _make_es_writer(MagicMock())
        result = writer.bulk_upsert_content_docs("my_index", [])
        assert result.success_count == 0
        assert result.fail_count == 0

    def test_success_count_matches_bulk_return(self):
        mods = _make_es_modules(bulk_return=(3, []))
        with patch.dict(sys.modules, mods):
            writer = _make_es_writer(MagicMock())
            docs = [{"_id": str(i), "text": "hello"} for i in range(3)]
            result = writer.bulk_upsert_content_docs("idx", docs)
        assert result.success_count == 3
        assert result.fail_count == 0

    def test_partial_failure_recorded(self):
        err = [{"index": {"error": {"reason": "bad"}}}]
        mods = _make_es_modules(bulk_return=(2, err))
        with patch.dict(sys.modules, mods):
            writer = _make_es_writer(MagicMock())
            docs = [{"_id": str(i), "text": "x"} for i in range(3)]
            result = writer.bulk_upsert_content_docs("idx", docs)
        assert result.success_count == 2
        assert result.fail_count == 1
        assert len(result.errors) == 1

    def test_doc_without_id_counted_as_failure(self):
        mods = _make_es_modules(bulk_return=(0, []))
        with patch.dict(sys.modules, mods):
            writer = _make_es_writer(MagicMock())
            result = writer.bulk_upsert_content_docs("idx", [{"text": "no id"}])
        assert result.fail_count == 1
        assert result.success_count == 0

    def test_raises_database_error_on_empty_index(self):
        from bible.infrastructure.database.types import DatabaseError

        with patch.dict(sys.modules, _ES_MODULES):
            writer = _make_es_writer(MagicMock())
            with pytest.raises(DatabaseError) as exc_info:
                writer.bulk_upsert_content_docs("", [{"_id": "x"}])
        assert exc_info.value.code == "DATABASE_INVALID_ARGUMENT"

    def test_uses_doc_as_upsert_true(self):
        actions_captured: list = []

        def capture_bulk(client, actions, **kwargs):
            actions_captured.extend(actions)
            return (len(actions), [])

        mods = _make_es_modules()
        mods["elasticsearch.helpers"].bulk = capture_bulk  # type: ignore[attr-defined]
        with patch.dict(sys.modules, mods):
            writer = _make_es_writer(MagicMock())
            writer.bulk_upsert_content_docs("idx", [{"_id": "1", "text": "hi"}])
        assert actions_captured[0]["doc_as_upsert"] is True
        assert actions_captured[0]["_op_type"] == "update"

    def test_creates_dense_vector_index_for_content_vectors(self):
        mods = _make_es_modules(bulk_return=(1, []))
        client = MagicMock()
        client.indices.exists.return_value = False
        with patch.dict(sys.modules, mods):
            writer = _make_es_writer(client)
            writer.bulk_upsert_content_docs(
                "idx",
                [{"_id": "1", "content_vector": [0.1, 0.2, 0.3]}],
            )

        client.indices.create.assert_called_once()
        body = client.indices.create.call_args.kwargs["body"]
        assert body["mappings"]["properties"]["content_vector"] == {
            "type": "dense_vector",
            "dims": 3,
            "index": True,
            "similarity": "cosine",
        }

    def test_adds_dense_vector_mapping_when_existing_index_has_no_vector_field(self):
        mods = _make_es_modules(bulk_return=(1, []))
        client = MagicMock()
        client.indices.exists.return_value = True
        client.indices.get_mapping.return_value = {
            "idx": {"mappings": {"properties": {"title": {"type": "text"}}}}
        }
        with patch.dict(sys.modules, mods):
            writer = _make_es_writer(client)
            writer.bulk_upsert_content_docs(
                "idx",
                [{"_id": "1", "content_vector": [0.1, 0.2]}],
            )

        client.indices.put_mapping.assert_called_once_with(
            index="idx",
            body={
                "properties": {
                    "content_vector": {
                        "type": "dense_vector",
                        "dims": 2,
                        "index": True,
                        "similarity": "cosine",
                    }
                }
            },
            request_timeout=30,
        )

    def test_search_converts_vector_knn_to_elasticsearch_top_level_knn(self):
        client = MagicMock()
        client.search.return_value = {"hits": {"total": 0, "hits": []}}
        writer = _make_es_writer(client)
        writer.search_content_docs(
            "idx",
            {
                "size": 5,
                "query": {
                    "knn": {
                        "content_vector": {
                            "vector": [0.1, 0.2],
                            "k": 5,
                            "num_candidates": 77,
                        }
                    }
                },
            },
        )

        body = client.search.call_args.kwargs["body"]
        assert "query" not in body
        assert body["knn"] == {
            "field": "content_vector",
            "query_vector": [0.1, 0.2],
            "k": 5,
            "num_candidates": 77,
        }

    def test_search_converts_nested_knn_to_elasticsearch_query_knn(self):
        client = MagicMock()
        client.search.return_value = {"hits": {"total": 0, "hits": []}}
        writer = _make_es_writer(client)
        writer.search_content_docs(
            "idx",
            {
                "size": 5,
                "query": {
                    "bool": {
                        "should": [
                            {
                                "function_score": {
                                    "query": {
                                        "knn": {
                                            "content_vector": {
                                                "vector": [0.1, 0.2],
                                                "k": 5,
                                                "num_candidates": 77,
                                            }
                                        }
                                    },
                                    "weight": 0.6,
                                }
                            }
                        ]
                    }
                },
            },
        )

        knn = (
            client.search.call_args.kwargs["body"]["query"]["bool"]["should"][0]
            ["function_score"]["query"]["knn"]
        )
        assert knn == {
            "field": "content_vector",
            "query_vector": [0.1, 0.2],
            "num_candidates": 77,
        }


# ===========================================================================
# §8 – ElasticsearchWriter: bulk_upsert_file_registry
# ===========================================================================


class TestElasticsearchWriterBulkUpsertFileRegistry:
    @pytest.fixture(autouse=True)
    def patch_es(self):
        with patch.dict(sys.modules, _ES_MODULES):
            yield

    def test_empty_records_returns_zero_counts(self):
        writer = _make_es_writer(MagicMock())
        result = writer.bulk_upsert_file_registry("my_index", [])
        assert result.success_count == 0 and result.fail_count == 0

    def test_success_count_matches_bulk_return(self):
        mods = _make_es_modules(bulk_return=(5, []))
        with patch.dict(sys.modules, mods):
            writer = _make_es_writer(MagicMock())
            records = [{"_id": str(i), "path": f"/f{i}.md"} for i in range(5)]
            result = writer.bulk_upsert_file_registry("file_idx", records)
        assert result.success_count == 5
        assert result.fail_count == 0

    def test_failure_counted_for_missing_id(self):
        mods = _make_es_modules(bulk_return=(0, []))
        with patch.dict(sys.modules, mods):
            writer = _make_es_writer(MagicMock())
            result = writer.bulk_upsert_file_registry("file_idx", [{"path": "/f.md"}])
        assert result.fail_count == 1


# ===========================================================================
# §9 – ElasticsearchWriter: async task operations
# ===========================================================================


class TestElasticsearchWriterAsyncTask:
    @pytest.fixture(autouse=True)
    def patch_es(self):
        with patch.dict(sys.modules, _ES_MODULES):
            yield

    # -- create_async_task --

    def test_create_uses_op_type_create(self):
        client = MagicMock()
        client.index.return_value = {"_id": "task-1"}
        writer = _make_es_writer(client)
        writer.create_async_task({"task_id": "task-1", "task_type": "import", "status": "queued"})
        assert client.index.call_args.kwargs["op_type"] == "create"

    def test_create_raises_conflict_on_duplicate(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        client.index.side_effect = _ConflictError()
        writer = _make_es_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.create_async_task({"task_id": "task-1", "status": "queued"})
        assert exc_info.value.code == "INDEX_BINDING_CONFLICT"

    def test_create_raises_error_when_no_task_id(self):
        from bible.infrastructure.database.types import DatabaseError

        client = MagicMock()
        writer = _make_es_writer(client)
        with pytest.raises(DatabaseError) as exc_info:
            writer.create_async_task({"task_type": "import"})
        assert exc_info.value.code == "DATABASE_INVALID_ARGUMENT"

    # -- get_async_task --

    def test_get_returns_source_on_hit(self):
        client = MagicMock()
        client.get.return_value = {"_source": {"task_id": "task-1", "status": "queued"}}
        writer = _make_es_writer(client)
        result = writer.get_async_task("task-1")
        assert result is not None
        assert result["task_id"] == "task-1"

    def test_get_returns_none_on_not_found(self):
        client = MagicMock()
        client.get.side_effect = _NotFoundError()
        writer = _make_es_writer(client)
        assert writer.get_async_task("missing") is None

    # -- find_async_task_by_idempotency --

    def test_find_returns_source_on_hit(self):
        src = {"task_id": "task-1", "idempotency_key": "key-x"}
        client = MagicMock()
        client.search.return_value = {"hits": {"hits": [{"_source": src}]}}
        writer = _make_es_writer(client)
        result = writer.find_async_task_by_idempotency("import", "key-x")
        assert result is not None
        assert result["task_id"] == "task-1"

    def test_find_returns_none_when_no_hits(self):
        client = MagicMock()
        client.search.return_value = {"hits": {"hits": []}}
        writer = _make_es_writer(client)
        assert writer.find_async_task_by_idempotency("import", "key-x") is None

    # -- update_async_task --

    def test_update_returns_true_on_success(self):
        existing = {"task_id": "task-1", "status": "queued"}
        client = MagicMock()
        client.get.return_value = {"_source": existing}
        client.update.return_value = {"_id": "task-1"}
        writer = _make_es_writer(client)
        assert writer.update_async_task("task-1", {"status": "running"}) is True

    def test_update_returns_false_when_task_not_found(self):
        client = MagicMock()
        client.update.side_effect = _NotFoundError()
        writer = _make_es_writer(client)
        assert writer.update_async_task("missing", {"status": "running"}) is False

    def test_update_returns_false_when_status_not_in_expected(self):
        existing = {"task_id": "task-1", "status": "completed"}
        client = MagicMock()
        client.get.return_value = {"_source": existing}
        writer = _make_es_writer(client)
        result = writer.update_async_task(
            "task-1", {"status": "running"}, expected_statuses=["queued"]
        )
        assert result is False
        client.update.assert_not_called()

    def test_update_proceeds_when_status_matches_expected(self):
        existing = {"task_id": "task-1", "status": "queued"}
        client = MagicMock()
        client.get.return_value = {"_source": existing}
        client.update.return_value = {"_id": "task-1"}
        writer = _make_es_writer(client)
        result = writer.update_async_task(
            "task-1", {"status": "running"}, expected_statuses=["queued"]
        )
        assert result is True
        client.update.assert_called_once()


# ===========================================================================
# §10 – DatabaseFactory: elasticsearch backend routing & caching
# ===========================================================================


def _make_db_es_cfg(backend: str = "elasticsearch"):
    from bible.config.configure import (
        BibleAtlasConfig,
        DatabaseConfig,
        ElasticsearchDatabaseConfig,
    )

    return BibleAtlasConfig(
        database=DatabaseConfig(
            backend=backend,
            elasticsearch=ElasticsearchDatabaseConfig(hosts=["localhost:9200"]),
        )
    )


class TestDatabaseFactoryElasticsearch:
    def _make_mock_provider(self) -> MagicMock:
        provider = MagicMock()
        provider.get_client.return_value = MagicMock()
        return provider

    def _es_modules_with_provider(self, mock_provider_cls: MagicMock) -> dict:
        """sys.modules patch that injects mock_provider_cls as ElasticsearchClientProvider."""
        fake_client_mod = types.ModuleType(
            "bible.infrastructure.database.elasticsearch.client"
        )
        fake_client_mod.ElasticsearchClientProvider = mock_provider_cls  # type: ignore[attr-defined]
        return {
            **_ES_MODULES,
            "bible.infrastructure.database.elasticsearch.client": fake_client_mod,
        }

    def test_elasticsearch_backend_returns_elasticsearch_writer(self):
        from bible.infrastructure.database.elasticsearch.writer import ElasticsearchWriter
        from bible.infrastructure.database.factory import DatabaseFactory

        factory = DatabaseFactory(_make_db_es_cfg("elasticsearch"))
        mock_provider_cls = MagicMock(return_value=self._make_mock_provider())

        with patch.dict(sys.modules, self._es_modules_with_provider(mock_provider_cls)):
            writer = factory.get_writer("MEMORY")
        assert isinstance(writer, ElasticsearchWriter)

    def test_elasticsearch_get_writer_returns_same_instance_on_repeated_calls(self):
        from bible.infrastructure.database.factory import DatabaseFactory

        factory = DatabaseFactory(_make_db_es_cfg("elasticsearch"))
        mock_provider_cls = MagicMock(return_value=self._make_mock_provider())

        with patch.dict(sys.modules, self._es_modules_with_provider(mock_provider_cls)):
            w1 = factory.get_writer("MEMORY")
            w2 = factory.get_writer("KNOWLEDGE_BASE")
        assert w1 is w2

    def test_elasticsearch_get_writer_creates_provider_only_once(self):
        from bible.infrastructure.database.factory import DatabaseFactory

        factory = DatabaseFactory(_make_db_es_cfg("elasticsearch"))
        mock_provider_cls = MagicMock(return_value=self._make_mock_provider())

        with patch.dict(sys.modules, self._es_modules_with_provider(mock_provider_cls)):
            factory.get_writer("MEMORY")
            factory.get_writer("MEMORY")
        assert mock_provider_cls.call_count == 1

    def test_elasticsearch_reset_clears_cache_and_new_instance_is_different(self):
        from bible.infrastructure.database.factory import DatabaseFactory

        factory = DatabaseFactory(_make_db_es_cfg("elasticsearch"))
        mock_provider_cls = MagicMock(return_value=self._make_mock_provider())

        with patch.dict(sys.modules, self._es_modules_with_provider(mock_provider_cls)):
            w1 = factory.get_writer("MEMORY")
            factory.reset()
            w2 = factory.get_writer("MEMORY")
        assert w1 is not w2

    def test_elasticsearch_reset_calls_close_on_provider(self):
        from bible.infrastructure.database.factory import DatabaseFactory

        factory = DatabaseFactory(_make_db_es_cfg("elasticsearch"))
        mock_provider = self._make_mock_provider()
        mock_provider_cls = MagicMock(return_value=mock_provider)

        with patch.dict(sys.modules, self._es_modules_with_provider(mock_provider_cls)):
            factory.get_writer("MEMORY")
            factory.reset()
        mock_provider.close.assert_called_once()
