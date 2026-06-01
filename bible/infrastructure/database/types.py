from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from bible.common.errors import DomainError, ErrorCode

DomainType = Literal["KNOWLEDGE_BASE", "SKILL", "MEMORY"]


@dataclass(slots=True)
class IndexBinding:
    domain_type: DomainType
    kb_index: str
    tag: str
    parser_script_source: str
    parser_script_sha256: str
    vector_model: str | None
    search_profile_json: dict[str, Any]
    search_profile_sha256: str
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None
    deleted_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BulkWriteResult:
    success_count: int = 0
    fail_count: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


class DatabaseError(DomainError):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(code, message, details=details, retryable=retryable)
