from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import ConflictError, NotFoundError, TransportError
from opensearchpy.helpers import bulk

from bible.common.errors import ErrorCode
from bible.common.logger import get_logger
from bible.infrastructure.database.base import IDatabaseWriter
from bible.infrastructure.database.types import (
    BulkWriteResult,
    DatabaseError,
    DomainType,
    IndexBinding,
)

if TYPE_CHECKING:
    from bible.config.configure import BibleAtlasConfig


class OpenSearchWriter(IDatabaseWriter):
    def __init__(self, client: OpenSearch, cfg: "BibleAtlasConfig") -> None:
        self._client = client
        self._cfg = cfg
        self._config = cfg.database.opensearch
        self._binding_index = self._config.binding_index
        self._async_task_index = self._config.async_task_index
        self._refresh_policy = self._config.refresh_policy
        self._bulk_chunk_size = self._config.bulk_chunk_size
        self._request_timeout = self._config.request_timeout_seconds
        self._logger = get_logger(__name__)

    def get_binding_by_domain_index(self, domain: DomainType, kb_index: str) -> IndexBinding | None:
        doc_id = self._binding_doc_id(domain, kb_index)
        try:
            resp = self._client.get(index=self._binding_index, id=doc_id)
        except NotFoundError:
            return None
        except TransportError as exc:
            raise DatabaseError(
                ErrorCode.DATABASE_BACKEND_UNAVAILABLE,
                "Failed to query index binding by domain/index.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc

        source = resp.get("_source") or {}
        if not source.get("is_active", True):
            return None
        return self._to_binding(source)

    def get_binding_by_domain_tag(self, domain: DomainType, tag: str) -> IndexBinding | None:
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
                ErrorCode.DATABASE_BACKEND_UNAVAILABLE,
                "Failed to query index binding by domain/tag.",
                details={"domain_type": domain, "tag": tag},
            ) from exc

        hits = ((resp.get("hits") or {}).get("hits")) or []
        if not hits:
            return None
        if len(hits) > 1:
            self._logger.error(
                "Duplicated active bindings found for same domain/tag",
                extra={"domain_type": domain, "tag": tag, "count": len(hits)},
            )
        return self._to_binding(hits[0].get("_source") or {})

    def create_index_binding(self, binding_doc: dict[str, Any]) -> dict[str, Any]:
        required = {
            "domain_type",
            "kb_index",
            "tag",
            "parser_script_source",
            "parser_script_sha256",
            "search_profile_json",
            "search_profile_sha256",
        }
        missing = [key for key in sorted(required) if key not in binding_doc]
        if missing:
            raise DatabaseError(
                ErrorCode.DATABASE_INVALID_ARGUMENT,
                "create_index_binding requires complete binding_doc.",
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
                ErrorCode.INDEX_BINDING_CONFLICT,
                f"Index binding already exists for {domain}::{kb_index}.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc
        except TransportError as exc:
            raise DatabaseError(
                ErrorCode.DATABASE_BACKEND_UNAVAILABLE,
                "Failed to create index binding.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc

        return {"created": True, "_id": resp.get("_id", doc_id)}

    def deactivate_binding(self, domain: DomainType, kb_index: str) -> dict[str, Any]:
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
                ErrorCode.INDEX_NOT_BOUND,
                f"Binding not found for {domain}::{kb_index}.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc
        except TransportError as exc:
            raise DatabaseError(
                ErrorCode.DATABASE_BACKEND_UNAVAILABLE,
                "Failed to deactivate index binding.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc
        return {"updated": True, "_id": resp.get("_id", doc_id)}

    def bulk_upsert_content_docs(self, index: str, docs: list[dict[str, Any]]) -> BulkWriteResult:
        return self._bulk(index=index, docs=docs)

    def bulk_upsert_file_registry(
        self,
        index: str,
        file_records: list[dict[str, Any]],
    ) -> BulkWriteResult:
        return self._bulk(index=index, docs=file_records)

    def get_file_registry_by_storage_path(
        self,
        index: str,
        storage_path: str,
    ) -> dict[str, Any] | None:
        records = self.get_file_registry_by_storage_paths(index, [storage_path])
        return records[0] if records else None

    def get_file_registry_by_storage_paths(
        self,
        index: str,
        storage_paths: list[str],
    ) -> list[dict[str, Any]]:
        if not storage_paths:
            return []
        body = {
            "size": len(storage_paths),
            "query": {"bool": {"filter": [{"terms": {"storage_path.keyword": storage_paths}}]}},
        }
        try:
            resp = self._client.search(index=index, body=body, request_timeout=self._request_timeout)
        except TransportError as exc:
            raise DatabaseError(
                ErrorCode.DATABASE_BACKEND_UNAVAILABLE,
                "Failed to query file registry.",
                details={"index": index, "storage_path_count": len(storage_paths)},
            ) from exc

        hits = ((resp.get("hits") or {}).get("hits")) or []
        return [hit.get("_source") or {} for hit in hits]

    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        if not index:
            raise DatabaseError(ErrorCode.DATABASE_INVALID_ARGUMENT, "search requires index.")
        try:
            return self._client.search(index=index, body=body, request_timeout=self._request_timeout)
        except TransportError as exc:
            raise DatabaseError(
                ErrorCode.DATABASE_BACKEND_UNAVAILABLE,
                "Database search failed.",
                details={"index": index},
            ) from exc

    def create_async_task(self, task_doc: dict[str, Any]) -> None:
        task_id = str(task_doc.get("task_id") or "").strip()
        if not task_id:
            raise DatabaseError(ErrorCode.DATABASE_INVALID_ARGUMENT, "create_async_task requires task_id.")
        now = self._now_iso()
        payload = {
            **task_doc,
            "status": task_doc.get("status", "queued"),
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
                ErrorCode.CONFLICT,
                f"Async task already exists: {task_id}.",
                details={"task_id": task_id},
            ) from exc
        except TransportError as exc:
            raise DatabaseError(
                ErrorCode.DATABASE_BACKEND_UNAVAILABLE,
                "Failed to create async task.",
                details={"task_id": task_id},
            ) from exc

    def get_async_task(self, task_id: str) -> dict[str, Any] | None:
        try:
            resp = self._client.get(index=self._async_task_index, id=task_id)
        except NotFoundError:
            return None
        except TransportError as exc:
            raise DatabaseError(
                ErrorCode.DATABASE_BACKEND_UNAVAILABLE,
                "Failed to get async task.",
                details={"task_id": task_id},
            ) from exc
        return resp.get("_source") or None

    def find_async_task_by_idempotency(
        self,
        task_type: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        body = {
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
            resp = self._client.search(index=self._async_task_index, body=body)
        except TransportError as exc:
            raise DatabaseError(
                ErrorCode.DATABASE_BACKEND_UNAVAILABLE,
                "Failed to find async task by idempotency.",
                details={"task_type": task_type},
            ) from exc
        hits = ((resp.get("hits") or {}).get("hits")) or []
        if not hits:
            return None
        return hits[0].get("_source") or None

    def update_async_task(
        self,
        task_id: str,
        patch_doc: dict[str, Any],
        expected_statuses: list[str] | None = None,
    ) -> bool:
        if expected_statuses is not None:
            current = self.get_async_task(task_id)
            if current is None or current.get("status") not in expected_statuses:
                return False

        payload = {**patch_doc, "updated_at": self._now_iso()}
        try:
            self._client.update(
                index=self._async_task_index,
                id=task_id,
                body={"doc": payload},
                refresh=self._refresh_policy,
                request_timeout=self._request_timeout,
            )
        except NotFoundError:
            return False
        except TransportError as exc:
            raise DatabaseError(
                ErrorCode.DATABASE_BACKEND_UNAVAILABLE,
                "Failed to update async task.",
                details={"task_id": task_id},
            ) from exc
        return True

    def _bulk(self, index: str, docs: list[dict[str, Any]]) -> BulkWriteResult:
        if not index:
            raise DatabaseError(ErrorCode.DATABASE_INVALID_ARGUMENT, "bulk upsert requires index.")
        if not docs:
            return BulkWriteResult()

        result = BulkWriteResult()
        for chunk in self._chunked(docs, self._bulk_chunk_size):
            actions: list[dict[str, Any]] = []
            for doc in chunk:
                doc_id = str(doc.get("_id") or doc.get("doc_id") or doc.get("storage_path") or "").strip()
                if not doc_id:
                    result.fail_count += 1
                    result.errors.append({"reason": "missing _id/doc_id/storage_path", "keys": list(doc)[:10]})
                    continue
                payload = {key: value for key, value in doc.items() if key != "_id"}
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
                    ErrorCode.DATABASE_BACKEND_UNAVAILABLE,
                    "Bulk upsert failed due to backend transport error.",
                    details={"index": index, "batch_size": len(actions)},
                ) from exc
            result.success_count += int(success_count)
            if errors:
                result.fail_count += len(errors)
                result.errors.extend(errors)

        if result.fail_count:
            self._logger.warning(
                "Bulk upsert partial failed",
                extra={
                    "operation": "bulk_upsert",
                    "index": index,
                    "success_count": result.success_count,
                    "fail_count": result.fail_count,
                },
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
        chunk_size = max(1, size)
        for idx in range(0, len(docs), chunk_size):
            yield docs[idx : idx + chunk_size]

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
