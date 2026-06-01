from __future__ import annotations

from typing import Any

from bible.common.errors import DomainError, ErrorCode
from bible.config.configure import SearchConfig
from bible.infrastructure.database import DatabaseFactory
from bible.infrastructure.database.types import DomainType


class InfrastructureSearchService:
    def __init__(
        self,
        *,
        domain: DomainType,
        database_factory: DatabaseFactory,
        search_config: SearchConfig,
    ) -> None:
        self._domain = domain
        self._database_factory = database_factory
        self._search_config = search_config

    def search(
        self,
        *,
        query: str,
        tag: str,
        search_type: str | None = None,
        top_k: int | None = None,
        vector_model: str | None = None,
        vector_weight: float | None = None,
    ) -> dict[str, Any]:
        writer = self._database_factory.get_writer(self._domain)
        binding = writer.get_binding_by_domain_tag(self._domain, tag)
        if binding is None:
            raise DomainError(
                ErrorCode.INDEX_NOT_BOUND,
                f"No active binding found for domain={self._domain}, tag={tag}.",
                details={"domain_type": self._domain, "tag": tag},
                retryable=False,
            )
        if vector_model and binding.vector_model and vector_model != binding.vector_model:
            raise DomainError(
                ErrorCode.CONFLICT,
                "Requested vector_model does not match the bound index vector_model.",
                details={"requested": vector_model, "bound": binding.vector_model},
                retryable=False,
            )

        body = self._build_search_body(
            query=query,
            top_k=top_k or self._search_config.default_top_k,
            search_type=search_type or "text",
            vector_weight=vector_weight,
            search_profile=binding.search_profile_json,
        )
        raw = writer.search(binding.kb_index, body)
        hits = ((raw.get("hits") or {}).get("hits")) or []
        return {
            "success": True,
            "domain": self._domain,
            "kb_index": binding.kb_index,
            "tag": tag,
            "total": self._extract_total(raw),
            "results": [self._format_hit(hit) for hit in hits],
        }

    def _build_search_body(
        self,
        *,
        query: str,
        top_k: int,
        search_type: str,
        vector_weight: float | None,
        search_profile: dict[str, Any],
    ) -> dict[str, Any]:
        del vector_weight
        fields = search_profile.get("fields") or ["title^2", "content", "description"]
        if search_type in {"keyword", "title"}:
            fields = search_profile.get("keyword_fields") or ["name^3", "title^2", "content"]
        return {
            "size": top_k,
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": fields,
                }
            },
        }

    def _extract_total(self, raw: dict[str, Any]) -> int:
        total = (raw.get("hits") or {}).get("total", 0)
        if isinstance(total, dict):
            return int(total.get("value") or 0)
        return int(total or 0)

    def _format_hit(self, hit: dict[str, Any]) -> dict[str, Any]:
        source = hit.get("_source") or {}
        return {
            **source,
            "score": hit.get("_score"),
        }
