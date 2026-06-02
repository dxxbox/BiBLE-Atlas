from __future__ import annotations

from typing import Any, Protocol

from .types import BulkWriteResult, DomainType, IndexBinding


class IDatabaseWriter(Protocol):
    def get_binding_by_domain_index(self, domain: DomainType, kb_index: str) -> IndexBinding | None:
        ...

    def get_binding_by_domain_tag(self, domain: DomainType, tag: str) -> IndexBinding | None:
        ...

    def create_index_binding(self, binding_doc: dict[str, Any]) -> dict[str, Any]:
        ...

    def deactivate_binding(self, domain: DomainType, kb_index: str) -> dict[str, Any]:
        ...

    def bulk_upsert_content_docs(self, index: str, docs: list[dict[str, Any]]) -> BulkWriteResult:
        ...

    def bulk_upsert_file_registry(self, index: str, file_records: list[dict[str, Any]]) -> BulkWriteResult:
        ...

    def create_async_task(self, task_doc: dict[str, Any]) -> None:
        ...

    def get_async_task(self, task_id: str) -> dict[str, Any] | None:
        ...

    def find_async_task_by_idempotency(self, task_type: str, idempotency_key: str) -> dict[str, Any] | None:
        ...

    def update_async_task(
        self,
        task_id: str,
        patch_doc: dict[str, Any],
        expected_statuses: list[str] | None = None,
    ) -> bool:
        ...

    def search_content_docs(
        self,
        index: str,
        dsl: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a search DSL against *index*.

        Returns a dict with keys:
          ``total`` (int) — total matched docs,
          ``hits``  (list[dict]) — each item has ``_score`` (float) and ``_source`` (dict).
        """
        ...
