from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterable

from bible.common.logger import get_logger

from ..base import IDatabaseWriter
from ..types import BulkWriteResult, DatabaseError, DomainType, IndexBinding

if TYPE_CHECKING:
    from bible.config.configure import BibleAtlasConfig
    from opensearchpy import OpenSearch


class OpenSearchWriter(IDatabaseWriter):
    def __init__(self, client: "OpenSearch", cfg: "BibleAtlasConfig") -> None:
        self._client = client
        os_cfg = cfg.database.opensearch
        self._binding_index = os_cfg.binding_index
        self._async_task_index = os_cfg.async_task_index
        self._refresh_policy = os_cfg.refresh_policy
        self._bulk_chunk_size = os_cfg.bulk_chunk_size
        self._request_timeout = os_cfg.request_timeout_seconds
        self._logger = get_logger(__name__)

    # ------------------------------------------------------------------
    # Index binding operations
    # ------------------------------------------------------------------

    def get_binding_by_domain_index(self, domain: DomainType, kb_index: str) -> IndexBinding | None:
        from opensearchpy.exceptions import NotFoundError, TransportError

        doc_id = self._binding_doc_id(domain, kb_index)
        self._logger.info(
            "OpenSearch binding lookup by index started domain=%s kb_index=%s binding_index=%s",
            domain,
            kb_index,
            self._binding_index,
        )
        try:
            resp = self._client.get(index=self._binding_index, id=doc_id)
        except NotFoundError:
            self._logger.info("OpenSearch binding lookup by index miss domain=%s kb_index=%s", domain, kb_index)
            return None
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to query index binding by domain/index.",
                details={"domain": domain, "kb_index": kb_index},
            ) from exc

        source = resp.get("_source", {})
        if not source.get("is_active", True):
            self._logger.info(
                "OpenSearch binding lookup by index found inactive binding domain=%s kb_index=%s",
                domain,
                kb_index,
            )
            return None
        self._logger.info("OpenSearch binding lookup by index hit domain=%s kb_index=%s", domain, kb_index)
        return self._to_binding(source)

    def get_binding_by_domain_tag(self, domain: DomainType, tag: str) -> IndexBinding | None:
        from opensearchpy.exceptions import TransportError

        self._logger.info(
            "OpenSearch binding lookup by tag started domain=%s tag=%s binding_index=%s",
            domain,
            tag,
            self._binding_index,
        )
        query = {
            "size": 2,
            "sort": [{"created_at": {"order": "desc"}}],
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
            self._logger.info("OpenSearch binding lookup by tag miss domain=%s tag=%s", domain, tag)
            return None
        if len(hits) > 1:
            self._logger.warning(
                "Duplicated active bindings found for same domain/tag: domain=%s tag=%s count=%d",
                domain, tag, len(hits),
            )
        selected = hits[0].get("_source", {})
        self._logger.info(
            "OpenSearch binding lookup by tag hit domain=%s tag=%s selected_kb_index=%s count=%d",
            domain,
            tag,
            selected.get("kb_index"),
            len(hits),
        )
        return self._to_binding(selected)

    def create_index_binding(self, binding_doc: dict[str, Any]) -> dict[str, Any]:
        from opensearchpy.exceptions import ConflictError, TransportError

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
        from opensearchpy.exceptions import NotFoundError, TransportError

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

    def upgrade_binding_vector_model(
        self,
        domain: DomainType,
        kb_index: str,
        vector_model: str,
    ) -> dict[str, Any]:
        """Set vector_model on a binding that was created without one.

        Uses a Painless script update (single atomic operation) rather than
        deactivate + re-create, which would fail with ConflictError because the
        physical document is still present after deactivation.
        """
        from opensearchpy.exceptions import NotFoundError, TransportError

        doc_id = self._binding_doc_id(domain, kb_index)
        now = self._now_iso()
        script = {
            "source": (
                "ctx._source.vector_model = params.vector_model; "
                "ctx._source.updated_at = params.now;"
            ),
            "lang": "painless",
            "params": {"vector_model": vector_model, "now": now},
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
                message="Failed to upgrade binding vector_model.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc
        return {"updated": True, "_id": resp.get("_id", doc_id)}

    def update_binding(
        self,
        domain: DomainType,
        kb_index: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically update arbitrary fields on an existing binding document."""
        from opensearchpy.exceptions import NotFoundError, TransportError

        doc_id = self._binding_doc_id(domain, kb_index)
        now = self._now_iso()
        patch_with_ts = {**patch, "updated_at": now}
        set_clauses = " ".join(
            f"ctx._source.{k} = params.{k};" for k in patch_with_ts
        )
        script = {
            "source": set_clauses,
            "lang": "painless",
            "params": patch_with_ts,
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
                message="Failed to update index binding.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc
        return {"updated": True, "_id": resp.get("_id", doc_id)}

    # ------------------------------------------------------------------
    # Bulk content / file-registry operations
    # ------------------------------------------------------------------

    def bulk_upsert_content_docs(
        self,
        index: str,
        docs: list[dict[str, Any]],
        *,
        vector_options: dict[str, Any] | None = None,
    ) -> BulkWriteResult:
        self._ensure_vector_index_mapping(index, docs, vector_options=vector_options)
        return self._bulk(index=index, docs=docs)

    def bulk_upsert_file_registry(
        self,
        index: str,
        file_records: list[dict[str, Any]],
    ) -> BulkWriteResult:
        return self._bulk(index=index, docs=file_records)

    def search_content_docs(
        self,
        index: str,
        dsl: dict[str, Any],
    ) -> dict[str, Any]:
        from opensearchpy.exceptions import TransportError

        size = dsl.get("size") if isinstance(dsl, dict) else None
        self._logger.info(
            "OpenSearch content search started index=%s size=%s",
            index,
            size if size is not None else "<unspecified>",
        )
        dsl = self._prepare_search_dsl(dsl)
        try:
            response = self._client.search(
                index=index,
                body=dsl,
                request_timeout=self._request_timeout,
            )
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to search content documents.",
                details={"index": index},
            ) from exc

        hits_obj = response.get("hits") or {}
        total = hits_obj.get("total", 0)
        total_value = int(total.get("value", 0)) if isinstance(total, dict) else int(total)
        hits = hits_obj.get("hits") or []
        self._logger.info(
            "OpenSearch content search completed index=%s total=%d hits=%d",
            index,
            total_value,
            len(hits),
        )
        return {
            "total": total_value,
            "hits": hits,
        }

    # ------------------------------------------------------------------
    # Async task operations
    # ------------------------------------------------------------------

    def create_async_task(self, task_doc: dict[str, Any]) -> None:
        from opensearchpy.exceptions import ConflictError, TransportError

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
        from opensearchpy.exceptions import NotFoundError, TransportError

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
        from opensearchpy.exceptions import TransportError

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
        from opensearchpy.exceptions import ConflictError, NotFoundError, TransportError

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
        from opensearchpy.exceptions import TransportError
        from opensearchpy.helpers import bulk

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

    def _ensure_vector_index_mapping(
        self,
        index: str,
        docs: list[dict[str, Any]],
        *,
        vector_options: dict[str, Any] | None = None,
    ) -> None:
        from opensearchpy.exceptions import TransportError

        vector_dims = self._first_content_vector_dims(docs)
        if vector_dims is None:
            return

        vector_mapping = {
            "type": "knn_vector",
            "dimension": vector_dims,
        }
        num_candidates = self._num_candidates_from_options(vector_options)
        index_settings: dict[str, Any] = {"knn": True}
        if num_candidates is not None:
            index_settings["knn.algo_param.ef_search"] = num_candidates
        try:
            if not self._client.indices.exists(index=index):
                self._logger.info(
                    "Creating OpenSearch vector index index=%s dims=%d num_candidates=%s",
                    index,
                    vector_dims,
                    num_candidates if num_candidates is not None else "<default>",
                )
                self._client.indices.create(
                    index=index,
                    body={
                        "settings": {"index": index_settings},
                        "mappings": {"properties": {"content_vector": vector_mapping}},
                    },
                    request_timeout=self._request_timeout,
                )
                return

            mapping_response = self._client.indices.get_mapping(index=index)
            properties = self._mapping_properties(mapping_response, index)
            existing = properties.get("content_vector")
            if existing is None:
                self._logger.info(
                    "Adding OpenSearch vector field mapping index=%s dims=%d",
                    index,
                    vector_dims,
                )
                self._client.indices.put_mapping(
                    index=index,
                    body={"properties": {"content_vector": vector_mapping}},
                    request_timeout=self._request_timeout,
                )
            elif existing.get("type") != "knn_vector":
                self._logger.warning(
                    "OpenSearch index %s has non-vector content_vector mapping: %s",
                    index,
                    existing,
                )
                return

            if num_candidates is not None:
                self._logger.info(
                    "Updating OpenSearch vector num_candidates index=%s num_candidates=%d",
                    index,
                    num_candidates,
                )
                self._client.indices.put_settings(
                    index=index,
                    body={"index": {"knn.algo_param.ef_search": num_candidates}},
                    request_timeout=self._request_timeout,
                )
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to prepare vector index mapping.",
                details={
                    "index": index,
                    "vector_dims": vector_dims,
                    "num_candidates": num_candidates,
                },
            ) from exc

    @staticmethod
    def _first_content_vector_dims(docs: list[dict[str, Any]]) -> int | None:
        for doc in docs:
            vector = doc.get("content_vector")
            if isinstance(vector, list) and vector:
                return len(vector)
        return None

    @staticmethod
    def _mapping_properties(mapping_response: Any, index: str) -> dict[str, Any]:
        if not isinstance(mapping_response, dict):
            return {}
        index_mapping = mapping_response.get(index)
        if not isinstance(index_mapping, dict):
            return {}
        mappings = index_mapping.get("mappings")
        if not isinstance(mappings, dict):
            return {}
        properties = mappings.get("properties")
        return properties if isinstance(properties, dict) else {}

    @staticmethod
    def _num_candidates_from_options(vector_options: dict[str, Any] | None) -> int | None:
        if not vector_options:
            return None
        num_candidates = vector_options.get("num_candidates")
        if type(num_candidates) is int and num_candidates > 0:
            return num_candidates
        return None

    def _prepare_search_dsl(self, dsl: dict[str, Any]) -> dict[str, Any]:
        """Translate backend-neutral kNN options to OpenSearch query DSL.

        ``num_candidates`` is the unified profile key.  OpenSearch 2.11 does
        not accept it in the query body; the equivalent search width is
        configured on the index via ``index.knn.algo_param.ef_search``.
        """
        prepared = deepcopy(dsl)
        self._strip_num_candidates_from_knn(prepared)
        return prepared

    def _strip_num_candidates_from_knn(self, node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "knn" and isinstance(value, dict):
                    for knn_body in value.values():
                        if isinstance(knn_body, dict):
                            knn_body.pop("num_candidates", None)
                self._strip_num_candidates_from_knn(value)
        elif isinstance(node, list):
            for item in node:
                self._strip_num_candidates_from_knn(item)

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
