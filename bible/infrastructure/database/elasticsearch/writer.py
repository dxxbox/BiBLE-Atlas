from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterable

from bible.common.logger import get_logger

from ..base import IDatabaseWriter
from ..types import BulkWriteResult, DatabaseError, DomainType, IndexBinding

if TYPE_CHECKING:
    from bible.config.configure import BibleAtlasConfig
    from elasticsearch import Elasticsearch


class ElasticsearchWriter(IDatabaseWriter):
    def __init__(self, client: "Elasticsearch", cfg: "BibleAtlasConfig") -> None:
        self._client = client
        es_cfg = cfg.database.elasticsearch
        self._binding_index = es_cfg.binding_index
        self._async_task_index = es_cfg.async_task_index
        self._refresh_policy = es_cfg.refresh_policy
        self._bulk_chunk_size = es_cfg.bulk_chunk_size
        self._request_timeout = es_cfg.request_timeout_seconds
        self._logger = get_logger(__name__)

    # ------------------------------------------------------------------
    # Index binding operations
    # ------------------------------------------------------------------

    def get_binding_by_domain_index(self, domain: DomainType, kb_index: str) -> IndexBinding | None:
        from elasticsearch.exceptions import NotFoundError, TransportError

        doc_id = self._binding_doc_id(domain, kb_index)
        try:
            resp = self._client.get(index=self._binding_index, id=doc_id)
        except NotFoundError:
            return None
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to query index binding by domain/index.",
                details={"domain": domain, "kb_index": kb_index},
            ) from exc

        source = resp.get("_source", {})
        if not source.get("is_active", True):
            return None
        return self._to_binding(source)

    def get_binding_by_domain_tag(self, domain: DomainType, tag: str) -> IndexBinding | None:
        from elasticsearch.exceptions import TransportError

        query = {
            "size": 2,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"domain_type.keyword": domain}},
                        {"term": {"tag.keyword": tag}},
                        {"term": {"is_active": True}},
                    ]
                }
            },
        }
        try:
            resp = self._client.search(index=self._binding_index, body=query)
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to query index binding by domain/tag.",
                details={"domain": domain, "tag": tag},
            ) from exc

        hits = (resp.get("hits") or {}).get("hits") or []
        if not hits:
            return None
        if len(hits) > 1:
            self._logger.error(
                "Duplicated active bindings found for same domain/tag: domain=%s tag=%s count=%d",
                domain, tag, len(hits),
            )
        return self._to_binding(hits[0].get("_source", {}))

    def create_index_binding(self, binding_doc: dict[str, Any]) -> dict[str, Any]:
        from elasticsearch.exceptions import ConflictError, TransportError

        required = {
            "domain_type",
            "kb_index",
            "tag",
            "parser_script_source",
            "parser_script_sha256",
            "search_profile_json",
            "search_profile_sha256",
        }
        missing = [key for key in required if key not in binding_doc]
        if missing:
            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message="create_index_binding requires complete binding_doc.",
                details={"missing_fields": missing},
            )

        domain = binding_doc["domain_type"]
        kb_index = binding_doc["kb_index"]
        doc_id = self._binding_doc_id(domain, kb_index)
        now = self._now_iso()
        payload = {
            **binding_doc,
            "is_active": bool(binding_doc.get("is_active", True)),
            "created_at": binding_doc.get("created_at", now),
            "updated_at": now,
            "deleted_at": None,
        }
        try:
            resp = self._client.index(
                index=self._binding_index,
                id=doc_id,
                body=payload,
                op_type="create",
                refresh=self._refresh_policy,
                request_timeout=self._request_timeout,
            )
        except ConflictError as exc:
            raise DatabaseError(
                code="INDEX_BINDING_CONFLICT",
                message=f"Index binding already exists for {domain}::{kb_index}.",
            ) from exc
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to create index binding.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc

        return {"created": True, "_id": resp.get("_id", doc_id)}

    def deactivate_binding(self, domain: DomainType, kb_index: str) -> dict[str, Any]:
        from elasticsearch.exceptions import NotFoundError, TransportError

        doc_id = self._binding_doc_id(domain, kb_index)
        now = self._now_iso()
        script = {
            "source": (
                "ctx._source.is_active = false; "
                "ctx._source.deleted_at = params.now; "
                "ctx._source.updated_at = params.now;"
            ),
            "lang": "painless",
            "params": {"now": now},
        }
        try:
            resp = self._client.update(
                index=self._binding_index,
                id=doc_id,
                body={"script": script},
                refresh=self._refresh_policy,
                request_timeout=self._request_timeout,
            )
        except NotFoundError as exc:
            raise DatabaseError(
                code="INDEX_NOT_BOUND",
                message=f"Binding not found for {domain}::{kb_index}.",
            ) from exc
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to deactivate index binding.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc
        return {"updated": True, "_id": resp.get("_id", doc_id)}

    # ------------------------------------------------------------------
    # Bulk content / file-registry operations
    # ------------------------------------------------------------------

    def bulk_upsert_content_docs(self, index: str, docs: list[dict[str, Any]]) -> BulkWriteResult:
        return self._bulk(index=index, docs=docs)

    def bulk_upsert_file_registry(
        self,
        index: str,
        file_records: list[dict[str, Any]],
    ) -> BulkWriteResult:
        return self._bulk(index=index, docs=file_records)

    # ------------------------------------------------------------------
    # Async task operations
    # ------------------------------------------------------------------

    def create_async_task(self, task_doc: dict[str, Any]) -> None:
        from elasticsearch.exceptions import ConflictError, TransportError

        task_id = str(task_doc.get("task_id") or "").strip()
        if not task_id:
            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message="create_async_task requires task_doc with task_id.",
            )
        now = self._now_iso()
        payload = {
            **task_doc,
            "created_at": task_doc.get("created_at", now),
            "updated_at": now,
        }
        try:
            self._client.index(
                index=self._async_task_index,
                id=task_id,
                body=payload,
                op_type="create",
                refresh=self._refresh_policy,
                request_timeout=self._request_timeout,
            )
        except ConflictError as exc:
            raise DatabaseError(
                code="INDEX_BINDING_CONFLICT",
                message=f"Async task already exists: {task_id}.",
            ) from exc
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to create async task.",
                details={"task_id": task_id},
            ) from exc

    def get_async_task(self, task_id: str) -> dict[str, Any] | None:
        from elasticsearch.exceptions import NotFoundError, TransportError

        try:
            resp = self._client.get(index=self._async_task_index, id=task_id)
        except NotFoundError:
            return None
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to get async task.",
                details={"task_id": task_id},
            ) from exc
        return resp.get("_source")

    def find_async_task_by_idempotency(
        self, task_type: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        from elasticsearch.exceptions import TransportError

        query = {
            "size": 1,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"task_type.keyword": task_type}},
                        {"term": {"idempotency_key.keyword": idempotency_key}},
                    ]
                }
            },
        }
        try:
            resp = self._client.search(index=self._async_task_index, body=query)
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to find async task by idempotency key.",
                details={"task_type": task_type, "idempotency_key": idempotency_key},
            ) from exc

        hits = (resp.get("hits") or {}).get("hits") or []
        if not hits:
            return None
        return hits[0].get("_source")

    def update_async_task(
        self,
        task_id: str,
        patch_doc: dict[str, Any],
        expected_statuses: list[str] | None = None,
    ) -> bool:
        from elasticsearch.exceptions import ConflictError, NotFoundError, TransportError

        if expected_statuses:
            existing = self.get_async_task(task_id)
            if existing is None:
                return False
            if existing.get("status") not in expected_statuses:
                return False

        now = self._now_iso()
        updates = {**patch_doc, "updated_at": now}
        script_parts = "; ".join(
            f"ctx._source['{k}'] = params['{k}']" for k in updates
        )
        script = {
            "source": script_parts,
            "lang": "painless",
            "params": updates,
        }
        try:
            self._client.update(
                index=self._async_task_index,
                id=task_id,
                body={"script": script},
                refresh=self._refresh_policy,
                request_timeout=self._request_timeout,
            )
        except (NotFoundError, ConflictError):
            return False
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to update async task.",
                details={"task_id": task_id},
            ) from exc
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _bulk(self, index: str, docs: list[dict[str, Any]]) -> BulkWriteResult:
        from elasticsearch.exceptions import TransportError
        from elasticsearch.helpers import bulk

        if not index:
            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message="bulk upsert requires index.",
            )
        if not docs:
            return BulkWriteResult()

        result = BulkWriteResult()
        for chunk in self._chunked(docs, self._bulk_chunk_size):
            actions: list[dict[str, Any]] = []
            for doc in chunk:
                doc_id = str(
                    doc.get("_id") or doc.get("doc_id") or doc.get("chunk_id") or ""
                ).strip()
                if not doc_id:
                    result.fail_count += 1
                    result.errors.append(
                        {"reason": "missing _id/doc_id/chunk_id", "doc_preview": list(doc.keys())[:10]}
                    )
                    continue

                payload = {k: v for k, v in doc.items() if k != "_id"}
                actions.append(
                    {
                        "_op_type": "update",
                        "_index": index,
                        "_id": doc_id,
                        "doc": payload,
                        "doc_as_upsert": True,
                    }
                )

            if not actions:
                continue

            try:
                success_count, errors = bulk(
                    self._client,
                    actions,
                    refresh=self._refresh_policy,
                    raise_on_error=False,
                    raise_on_exception=False,
                    request_timeout=self._request_timeout,
                )
            except TransportError as exc:
                raise DatabaseError(
                    code="DATABASE_BACKEND_UNAVAILABLE",
                    message="Bulk upsert failed due to backend transport error.",
                    details={"index": index, "batch_size": len(actions)},
                ) from exc

            result.success_count += int(success_count)
            if errors:
                result.fail_count += len(errors)
                result.errors.extend(errors)

        if result.fail_count > 0:
            self._logger.warning(
                "Bulk upsert partial failed: index=%s success=%d fail=%d errors=%s",
                index,
                result.success_count,
                result.fail_count,
                result.errors[:5],
            )
        return result

    def _binding_doc_id(self, domain: DomainType, kb_index: str) -> str:
        return f"{domain}::{kb_index}"

    def _to_binding(self, source: dict[str, Any]) -> IndexBinding:
        return IndexBinding(
            domain_type=source["domain_type"],
            kb_index=source["kb_index"],
            tag=source["tag"],
            parser_script_source=source["parser_script_source"],
            parser_script_sha256=source["parser_script_sha256"],
            vector_model=source.get("vector_model"),
            search_profile_json=source["search_profile_json"],
            search_profile_sha256=source["search_profile_sha256"],
            is_active=bool(source.get("is_active", True)),
            created_at=source.get("created_at"),
            updated_at=source.get("updated_at"),
            deleted_at=source.get("deleted_at"),
        )

    def _chunked(self, docs: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
        for idx in range(0, len(docs), size):
            yield docs[idx : idx + size]

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
