from __future__ import annotations

from typing import Any

import pytest

from bible.common.errors import ErrorCode
from bible.config.configure import BibleAtlasConfig
from bible.infrastructure.database.factory import DatabaseFactory
from bible.infrastructure.database.opensearch.writer import OpenSearchWriter
from bible.infrastructure.database.types import DatabaseError


class FakeOpenSearch:
    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict[str, Any]] = {}
        self.index_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []

    def get(self, index: str, id: str) -> dict[str, Any]:
        from opensearchpy.exceptions import NotFoundError

        key = (index, id)
        if key not in self.docs:
            raise NotFoundError(404, "not found", {})
        return {"_id": id, "_source": self.docs[key]}

    def index(self, **kwargs):
        from opensearchpy.exceptions import ConflictError

        self.index_calls.append(kwargs)
        key = (kwargs["index"], kwargs["id"])
        if kwargs.get("op_type") == "create" and key in self.docs:
            raise ConflictError(409, "conflict", {})
        self.docs[key] = kwargs["body"]
        return {"_id": kwargs["id"]}

    def update(self, **kwargs):
        from opensearchpy.exceptions import NotFoundError

        self.update_calls.append(kwargs)
        key = (kwargs["index"], kwargs["id"])
        if key not in self.docs:
            raise NotFoundError(404, "not found", {})
        body = kwargs["body"]
        if "doc" in body:
            self.docs[key].update(body["doc"])
        else:
            self.docs[key].update({"is_active": False, "deleted_at": "now", "updated_at": "now"})
        return {"_id": kwargs["id"]}

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        index = kwargs["index"]
        body = kwargs.get("body") or {}
        if "terms" in str(body):
            paths = body["query"]["bool"]["filter"][0]["terms"]["storage_path.keyword"]
            hits = [
                {"_source": doc}
                for (doc_index, _), doc in self.docs.items()
                if doc_index == index and doc.get("storage_path") in paths
            ]
        elif index == "v4_index_binding":
            filters = body["query"]["bool"]["filter"]
            domain = filters[0]["term"]["domain_type.keyword"]
            tag = filters[1]["term"]["tag.keyword"]
            hits = [
                {"_source": doc}
                for (doc_index, _), doc in self.docs.items()
                if doc_index == index
                and doc.get("domain_type") == domain
                and doc.get("tag") == tag
                and doc.get("is_active") is True
            ]
        else:
            hits = [{"_source": {"content": "matched"}, "_score": 1.0}]
        return {"hits": {"total": {"value": len(hits)}, "hits": hits}}


def _binding_doc() -> dict[str, Any]:
    return {
        "domain_type": "MEMORY",
        "kb_index": "kb_memory",
        "tag": "memory",
        "parser_script_source": "def parse(): pass",
        "parser_script_sha256": "abc",
        "vector_model": None,
        "search_profile_json": {"fields": ["content"]},
        "search_profile_sha256": "def",
    }


def test_opensearch_writer_binding_lifecycle():
    client = FakeOpenSearch()
    writer = OpenSearchWriter(client, BibleAtlasConfig())

    created = writer.create_index_binding(_binding_doc())
    assert created["created"] is True
    assert client.index_calls[0]["op_type"] == "create"

    by_index = writer.get_binding_by_domain_index("MEMORY", "kb_memory")
    by_tag = writer.get_binding_by_domain_tag("MEMORY", "memory")
    assert by_index is not None
    assert by_index.kb_index == "kb_memory"
    assert by_tag is not None
    assert by_tag.tag == "memory"

    with pytest.raises(DatabaseError) as exc_info:
        writer.create_index_binding(_binding_doc())
    assert exc_info.value.code == ErrorCode.INDEX_BINDING_CONFLICT

    writer.deactivate_binding("MEMORY", "kb_memory")
    assert writer.get_binding_by_domain_index("MEMORY", "kb_memory") is None


def test_opensearch_writer_bulk_and_file_registry(monkeypatch):
    import bible.infrastructure.database.opensearch.writer as writer_module

    client = FakeOpenSearch()
    writer = OpenSearchWriter(client, BibleAtlasConfig())

    def fake_bulk(client_arg, actions, **kwargs):
        assert client_arg is client
        assert kwargs["raise_on_error"] is False
        return len(actions), []

    monkeypatch.setattr(writer_module, "bulk", fake_bulk)

    result = writer.bulk_upsert_content_docs("content_index", [{"doc_id": "doc1"}, {"content": "bad"}])
    assert result.success_count == 1
    assert result.fail_count == 1

    client.docs[("registry_index", "path1")] = {"storage_path": "path1", "kb_index": "kb_memory"}
    assert writer.get_file_registry_by_storage_path("registry_index", "path1") == {
        "storage_path": "path1",
        "kb_index": "kb_memory",
    }


def test_database_factory_reuses_provider_and_writer(monkeypatch):
    import bible.infrastructure.database.factory as factory_module

    class FakeProvider:
        closed = False

        def __init__(self, cfg):
            self.cfg = cfg

        def get_client(self):
            return FakeOpenSearch()

        def close(self):
            self.closed = True

    monkeypatch.setattr(factory_module, "OpenSearchClientProvider", FakeProvider)
    factory = DatabaseFactory(BibleAtlasConfig())

    first = factory.get_writer("MEMORY")
    second = factory.get_writer("KNOWLEDGE_BASE")
    assert first is second

    factory.reset()
    assert factory.get_writer("MEMORY") is not first
